import network
from mqtt import MQTTClient
import bluetooth
import time
import struct
import utime
import machine
from machine import Pin
import ubinascii
import urandom
from neopixel import NeoPixel

# Configuration
WIFI_SSID = "tufts_eecs"
WIFI_PASSWORD = "foundedin1883"
MQTT_BROKER = "test.mosquitto.org"
MQTT_TOPIC = "game/status"
GAME_DURATION = 300  # 5 minutes in seconds

pin = Pin(16, Pin.OUT)   # set GPIO0 to output to drive NeoPixels
np = NeoPixel(pin, 1)   # create NeoPixel driver on GPIO0 for 8 pixels

NAME_FLAG = 0x09

BEACON_ID = ubinascii.hexlify(machine.unique_id()).decode()
caught_runners = set()

class Yell:
    def __init__(self):
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        
    def advertise(self, name = 'Beacon', interval_us=100000):
        short = name[:8]
        payload = struct.pack("BB", len(short) + 1, NAME_FLAG) + short.encode()
        self._ble.gap_advertise(interval_us, adv_data=payload)
        
    def stop_advertising(self):
        self._ble.gap_advertise(None)
# Setup
ble = Yell()

# Setup
# led = Pin(15, Pin.OUT)  # Green when active, Red when cooling down, Blue when game ends
button = Pin(8, Pin.IN, Pin.PULL_UP)

# Game state
game_active = False
cooldown_active = False
cooldown_time = 5  # 5 seconds cooldown

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    while not wlan.isconnected():
        pass
    print('WiFi connected')

def mqtt_connect():
    client = MQTTClient("beacon", MQTT_BROKER)
    client.connect()
    print('Connected to MQTT Broker')
    return client

def start_game():
    global start_time, game_active
    game_active = True
    start_time = utime.time()
    np[0] = (0, 255, 0) # set the first pixel to green
    np.write()              # write data to all pixels
    
    print("Game started")

def end_game():
    global game_active
    np[0] = (0, 0, 255) # set the first pixel to blue
    np.write()              # write data to all pixels
    game_active = False
    print("Game ended")

def button_pressed():
    global game_active
    if not game_active:
        mqtt_client.publish(MQTT_TOPIC, "game_start")
    else:
        mqtt_client.publish(MQTT_TOPIC, "game_end")

# Setup interrupt for button press
# button.irq(trigger=Pin.IRQ_FALLING, handler=button_pressed)

def mqtt_callback(topic, msg):
    global game_active
    if topic == MQTT_TOPIC.encode():
        if msg == b"game_start":
            start_game()
            
        elif msg == b"game_end":
            end_game()
            
        else:
            pass
    elif topic == (MQTT_TOPIC + "/caught").encode():
        if game_active:
            caught_runner = msg.decode()
            caught_runners.add(caught_runner)
            print(f"Runner {caught_runner} caught")
    elif topic == (MQTT_TOPIC + "/save").encode():
        if game_active and caught_runners:
            runner_to_save = urandom.choice(list(caught_runners))
            caught_runners.remove(runner_to_save)
            mqtt_client.publish(MQTT_TOPIC + "/save_" + runner_to_save, "you_are_saved")
            print(f"Saving runner {runner_to_save}")
    
# Main loop
connect_wifi()

mqtt_client = mqtt_connect()
mqtt_client.set_callback(mqtt_callback)
mqtt_client.subscribe(MQTT_TOPIC)
mqtt_client.subscribe(MQTT_TOPIC + "/caught")
mqtt_client.subscribe(MQTT_TOPIC + "/save")

while True:
    if button.value() == 0:
        button_pressed()
        time.sleep(0.2)
    if game_active:
        current_time = utime.time()
        if current_time - start_time >= GAME_DURATION:
            end_game()
        elif not cooldown_active:
            ble.advertise("Beacon")
            # print("Advertising as Beacon") 
    mqtt_client.check_msg()
    utime.sleep(0.1)

