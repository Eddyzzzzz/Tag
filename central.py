import time
import board
import busio
from digitalio import DigitalInOut
import neopixel
import adafruit_connection_manager
from adafruit_esp32spi import adafruit_esp32spi
import adafruit_minimqtt.adafruit_minimqtt as MQTT
import displayio
import terminalio
from adafruit_display_text import label
import adafruit_touchscreen
from adafruit_display_shapes.rect import Rect

MQTT_BROKER = "broker.hivemq.com"
MQTT_TOPIC = "taggame"
CIRCUITPY_WIFI_SSID = "tufts_eecs"
CIRCUITPY_WIFI_PASSWORD = "foundedin1883"

# PyPortal setup
esp32_cs = DigitalInOut(board.ESP_CS)
esp32_ready = DigitalInOut(board.ESP_BUSY)
esp32_reset = DigitalInOut(board.ESP_RESET)

spi = busio.SPI(board.SCK, board.MOSI, board.MISO)
esp = adafruit_esp32spi.ESP_SPIcontrol(spi, esp32_cs, esp32_ready, esp32_reset)

status_light = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2)

# Touchscreen setup
display = board.DISPLAY
ts = adafruit_touchscreen.Touchscreen(
    board.TOUCH_XL, board.TOUCH_XR,
    board.TOUCH_YD, board.TOUCH_YU,
    calibration=((5200, 59000), (5800, 57000)),
    size=(320, 240))

# Game state
num_runners = 1
num_taggers = 1
num_beacons = 0
game_duration = 300  # 5 minutes default
game_active = False
recognized_devices = set()

# MQTT callbacks
def connected(client, userdata, flags, rc):
    print("Connected to MQTT broker!")

def disconnected(client, userdata, rc):
    print("Disconnected from MQTT broker!")
    
def subscribe(client, userdata, topic, granted_qos):
    # This method is called when the client subscribes to a new feed.
    print("Subscribed to {0} with QOS level {1}".format(topic, granted_qos))

def publish(client, userdata, topic, pid):
    # This method is called when the client publishes data to a feed.
    print("Published to {0} with PID {1}".format(topic, pid))


def message(client, topic, message):
    """Method callled when a client's subscribed feed has a new
    value.
    :param str topic: The topic of the feed with a new value.
    :param str message: The new value
    """
    print(f"New message on topic '{topic}': '{message}'")
    if topic == MQTT_TOPIC + "/recognize":
        device_id = message
        recognized_devices.add(device_id)
        print(f"Recognized device: {device_id}")
        print(f"Total recognized devices: {len(recognized_devices)}")
    else:
        print(f"Unhandled topic: {topic}")

# Connect to WiFi and MQTT
print("Connecting to WiFi...")
esp.connect_AP(CIRCUITPY_WIFI_SSID, CIRCUITPY_WIFI_PASSWORD)
print("Connected!")

pool = adafruit_connection_manager.get_radio_socketpool(esp)
ssl_context = adafruit_connection_manager.get_radio_ssl_context(esp)

client = MQTT.MQTT(
    broker=MQTT_BROKER,
    port=1883,
    socket_pool=pool,
    ssl_context=ssl_context,
    socket_timeout=0.1,  # Reduce socket timeout
    keep_alive=60
)

client.on_connect = connected
client.on_disconnect = disconnected
client.on_subscribe = subscribe
client.on_publish = publish
client.on_message = message

print("Connecting to MQTT broker...")
client.connect()
client.subscribe(MQTT_TOPIC + '/recognize')
print("subscribed")
time.sleep(0.5)

# Display functions
def create_text_box(text, x, y, width, height, color):
    box = displayio.Group()
    background = Rect(x, y, width, height, fill=color)
    box.append(background)
    text_area = label.Label(terminalio.FONT, text=text, color=0xFFFFFF, x=x+5, y=y+height//2)
    box.append(text_area)
    return box

def update_display(main_text, option1, option2):
    display.root_group = None
    main_group = displayio.Group()
    main_group.append(create_text_box(main_text, 10, 10, 300, 50, 0x0000FF))
    main_group.append(create_text_box(option1, 10, 70, 145, 50, 0x00FF00))
    main_group.append(create_text_box(option2, 165, 70, 145, 50, 0xFF0000))
    display.root_group = main_group

def set_rules():
    global num_runners, num_taggers, num_beacons, game_duration
    rules = [num_runners, num_taggers, num_beacons, game_duration // 60]
    rule_names = ["Runners", "Taggers", "Beacons", "Duration (min)"]
    
    for i, rule in enumerate(rules):
        update_display(f"Set {rule_names[i]}", str(rule), "Confirm")
        while True:
            p = ts.touch_point
            if p:
                if p[0] < 160:  # Left side
                    if i < 2:  # Runners and Taggers
                        rules[i] = (rules[i] % 8) + 1
                    elif i == 2:  # Beacons
                        rules[i] = (rules[i] + 1) % 9  # Allow 0 to 8 beacons
                    else:  # Duration
                        rules[i] = (rules[i] % 10) + 1
                    update_display(f"Set {rule_names[i]}", str(rules[i]), "Confirm")
                else:  # Right side (Confirm)
                    time.sleep(0.5)
                    break
            time.sleep(0.1)
    
    num_runners, num_taggers, num_beacons, game_duration = rules[0], rules[1], rules[2], rules[3] * 60
    
def start_game():
    global game_active
    game_active = True
    roles = ["Runner"] * num_runners + ["Tagger"] * num_taggers
    if num_beacons > 0:
        roles += ["Beacon"] * num_beacons
    devices = list(recognized_devices)[:len(roles)]
    for device, role in zip(devices, roles):
        client.publish(MQTT_TOPIC + "/assign", f"{device},{role}")
        time.sleep(0.1)
    client.publish(MQTT_TOPIC + "/game", "start")
    update_display("Game Started", "", "End Game")

def end_game():
    global game_active
    game_active = False
    client.publish(MQTT_TOPIC + "/game", "end")
    update_display("Game Ended", "New Game", "")



while True:
    update_display("Waiting for devices", f"Recognized: {len(recognized_devices)}", "Start Setup")
    print(f"Current recognized devices: {recognized_devices}")
    last_mqtt_check = time.monotonic()
    reconnect_delay = 5  # Start with a 5 second delay between reconnection attempts
    max_reconnect_delay = 60  # Maximum delay of 1 minute

    while True:
        p = ts.touch_point
        if p and p[0] > 160:
            break
        
        # Check MQTT messages every 100ms
        if time.monotonic() - last_mqtt_check >= 0.1:
            try:
                client.loop(timeout=0.2)  # Increased timeout
                last_mqtt_check = time.monotonic()
                reconnect_delay = 5  # Reset delay on successful loop
            except MQTT.MMQTTException as e:
                print(f"MQTT Error: {e}")
                # Attempt to reconnect
                try:
                    print(f"Attempting to reconnect in {reconnect_delay} seconds...")
                    time.sleep(reconnect_delay)
                    client.reconnect()
                    print("Reconnected successfully")
                    reconnect_delay = 5  # Reset delay on successful reconnection
                except Exception as reconnect_error:
                    print(f"Failed to reconnect: {reconnect_error}")
                    reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)  # Exponential backoff
        
        time.sleep(0.1)
        update_display("Waiting for devices", f"Recognized: {len(recognized_devices)}", "Start Setup")
    
    set_rules()
    update_display("Ready to Start", "Start Game", "")
    
    start_time = None
    while True:
        p = ts.touch_point
        if p:
            if not game_active and p[0] < 160:  # Start Game
                start_game()
                start_time = time.monotonic()
            elif game_active and p[0] > 160:  # End Game
                end_game()
                break
        
        if game_active:
            elapsed_time = time.monotonic() - start_time
            if elapsed_time >= game_duration:
                end_game()
                break
            update_display(f"Game in progress", f"Time left: {game_duration - int(elapsed_time)}s", "End Game")
        
        # Check MQTT messages every 100ms
        if time.monotonic() - last_mqtt_check >= 0.1:
            try:
                client.loop(timeout=0.01)
                last_mqtt_check = time.monotonic()
            except MQTT.MMQTTException as e:
#                 print(f"MQTT Error: {e}")
                # Attempt to reconnect
                try:
                    client.reconnect()
                except Exception as reconnect_error:
#                     print(f"Failed to reconnect: {reconnect_error}")
                    pass
        
        time.sleep(0.01)

    time.sleep(0.5)  # Debounce
    recognized_devices.clear()
