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

MQTT_BROKER = "test.mosquitto.org"
MQTT_TOPIC = "game/status"
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
game_type = 0  # 0: Tag Game, 1: Other Game
num_runners = 6
num_taggers = 2
num_beacons = 1
random_roles = True
game_active = False

devices = ["device1", "device2", "device3", "device4", "device5", "device6", "device7", "device8", "device9"]

# MQTT callbacks
def connected(client, userdata, flags, rc):
    print("Connected to MQTT broker!")

def disconnected(client, userdata, rc):
    print("Disconnected from MQTT broker!")

def message(client, topic, message):
    print("New message on topic {0}: {1}".format(topic, message))

# Connect to WiFi and MQTT
print("Connecting to WiFi...")
esp.connect_AP(CIRCUITPY_WIFI_SSID, CIRCUITPY_WIFI_PASSWORD)
print("Connected!")

pool = adafruit_connection_manager.get_radio_socketpool(esp)
ssl_context = adafruit_connection_manager.get_radio_ssl_context(esp)

mqtt_client = MQTT.MQTT(
    broker=MQTT_BROKER,
    socket_pool=pool,
    ssl_context=ssl_context,
    socket_timeout=1,
    keep_alive=60
)

mqtt_client.on_connect = connected
mqtt_client.on_disconnect = disconnected
mqtt_client.on_message = message

print("Connecting to MQTT broker...")
mqtt_client.connect()

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
    

def select_game():
    global game_type
    update_display("Select Game", "Tag Game", "Other Game")
    while True:
        p = ts.touch_point
        if p:
            if p[0] > 160:  # Right side
                game_type = 1
            else:  # Left side
                game_type = 0
            time.sleep(0.5)
            return

def set_rules():
    global num_runners, num_taggers, num_beacons, random_roles
    rules = [num_runners, num_taggers, num_beacons, int(random_roles)]
    rule_names = ["Runners", "Taggers", "Beacons", "Random Roles"]
    
    for i, rule in enumerate(rules):
        update_display(f"Set {rule_names[i]}", str(rule), "Confirm")
        while True:
            p = ts.touch_point
            if p:
                if p[0] < 160:  # Left side
                    if i < 3:
                        rules[i] = (rules[i] % 7) + 1
                    else:
                        rules[i] = 1 - rules[i]
                    update_display(f"Set {rule_names[i]}", str(rules[i]), "Confirm")
                else:  # Right side (Confirm)
                    time.sleep(0.5)
                    break
            time.sleep(0.1)
    
    num_runners, num_taggers, num_beacons, random_roles = rules[0], rules[1], rules[2], bool(rules[3])

def start_game():
    global game_active
    game_active = True
    roles = ["Runner"] * num_runners + ["Tagger"] * num_taggers + ["Beacon"] * num_beacons
#     if random_roles:
#         roles = [roles[i] for i in range(len(roles))]  # Simplified shuffle
    for device, role in zip(devices, roles):
        mqtt_client.publish(MQTT_TOPIC + "/assign", f"{role},start")
        time.sleep(0.1)
    update_display("Game Started", "", "End Game")

def end_game():
    global game_active
    game_active = False
    for device in devices:
        mqtt_client.publish(MQTT_TOPIC + "/assign", "None,end")
    update_display("Game Ended", "New Game", "")

# Main game loop
while True:
    select_game()
    set_rules()
    update_display("Ready to Start", "Start Game", "")
    
    last_mqtt_check = time.monotonic()
    while True:
        p = ts.touch_point
        if p:
            if not game_active and p[0] < 160:  # Start Game
                start_game()
            elif game_active and p[0] > 160:  # End Game
                end_game()
                break
        
        # Check MQTT messages every second
        if time.monotonic() - last_mqtt_check >= 1:
            try:
                mqtt_client.loop(timeout=0.1)
                last_mqtt_check = time.monotonic()
            except MQTT.MMQTTException as e:
#                 print(f"MQTT Error: {e}")
                # Attempt to reconnect
                try:
                    mqtt_client.reconnect()
                except Exception as reconnect_error:
#                     print(f"Failed to reconnect: {reconnect_error}")
                    pass
        
        time.sleep(0.1)

    time.sleep(0.5)  # Debounce
