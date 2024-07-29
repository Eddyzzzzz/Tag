import network
from mqtt import MQTTClient
import bluetooth
import time
import struct
import utime
import machine
from machine import Pin
from neopixel import NeoPixel
import urandom
import ubinascii

# Configuration
WIFI_SSID = "tufts_eecs"
WIFI_PASSWORD = "foundedin1883"
MQTT_BROKER = "test.mosquitto.org"
MQTT_TOPIC = "taggame"
DEVICE_ID = ubinascii.hexlify(machine.unique_id()).decode()

# Constants
SAFE_DISTANCE = -50
CAUGHT_DISTANCE = -40
NAME_FLAG = 0x09
SCAN_RESULT = 5
SCAN_DONE = 6

# Hardware setup
led = NeoPixel(Pin(28), 1)  # NeoPixel on GPIO 28
button = Pin(20, Pin.IN, Pin.PULL_UP)

# Game state
role = None
active = False
caught = False
cooldown_active = False
cooldown_start = 0

class BLE:
    def __init__(self): 
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.irq(self.callback)
        self.scanning = False
        self._connections = set()
        self.name = "Player_" + DEVICE_ID[:4]
        self._ble.config(gap_name=self.name)
        self._scan_callback = None
        self._adv_payload = None

    def callback(self, event, data):
        if event == SCAN_RESULT:
            self.read_scan(data)

        elif event == SCAN_DONE:
            if self.scanning:
                self.stop_scan()
                
    def find_name(self, payload):
        start = 0
        name = None
        while (len(payload) - start) > 1:
            size = payload[start]
            end =  start + size + 1
            if payload[start+1] == NAME_FLAG:
                name = payload[start + 2:end]
                break
            start = end
        return str(name, "utf-8") if name else ""

    def read_scan(self, data):
        global caught, cooldown_active, cooldown_start
        addr_type, addr, adv_type, rssi, adv_data = data
        name = self.find_name(adv_data)
        if name:
            print("name: %s, rssi: %d"%(name, rssi))
        if role == "Runner" and not caught:
            if name and "Tagger" in name and rssi > CAUGHT_DISTANCE:
                caught = True
                mqtt_client.publish(MQTT_TOPIC + "/caught", DEVICE_ID)
            elif name and "Beacon" in name and rssi > SAFE_DISTANCE and not cooldown_active:
                mqtt_client.publish(MQTT_TOPIC + "/save", "save_runner")
                cooldown_active = True
                cooldown_start = time.time()
        elif role == "Beacon" and not caught:
            if name and "Tagger" in name and rssi > CAUGHT_DISTANCE:
                caught = True
                mqtt_client.publish(MQTT_TOPIC + "/caught", DEVICE_ID)
            
    def scan(self, duration = 2000):
        self.scanning = True
        return self._ble.gap_scan(duration, 30000, 30000)

    def wait_for_scan(self):
        while self.scanning:
            #print('.',end='')
            time.sleep(0.1)
        
    def stop_scan(self):
        self.scanning = False
        self._ble.gap_scan(None)

ble = BLE()

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    while not wlan.isconnected():
        time.sleep(1)
    print('WiFi connected')

def mqtt_connect():
    client = MQTTClient(DEVICE_ID, MQTT_BROKER, keepalive=60)
    client.connect()
    print('Connected to MQTT Broker')
    return client

def set_led_color(r, g, b):
    led[0] = (r, g, b)
    led.write()

def mqtt_callback(topic, msg):
    global role, active, caught
    print(f"Received message on topic {topic}: {msg}")
    if topic == (MQTT_TOPIC + "/assign").encode():
        device, assigned_role = msg.decode().split(',')
        if device == DEVICE_ID:
            role = assigned_role
            active = True
            caught = False
            
    elif topic == (MQTT_TOPIC + "/game").encode():
        if msg == b"start":
            active = True
        elif msg == b"end":
            active = False
    elif topic == (MQTT_TOPIC + "/save").encode():
        if role == "Runner" and caught:
            if urandom.getrandbits(1):  # 50% chance of being saved
                caught = False
                mqtt_client.publish(MQTT_TOPIC + "/saved", DEVICE_ID)

# Setup
connect_wifi()
mqtt_client = mqtt_connect()
mqtt_client.set_callback(mqtt_callback)
mqtt_client.subscribe(MQTT_TOPIC + "/assign")
mqtt_client.subscribe(MQTT_TOPIC + "/game")
mqtt_client.subscribe(MQTT_TOPIC + "/save")

# Recognize device
mqtt_client.publish(MQTT_TOPIC + "/recognize", DEVICE_ID)

# Main loop
while True:                
    if active:
        if role == "Runner":
            if not caught:
                set_led_color(0, 255, 0)  # Green
                ble.scan(0)
            else:
                set_led_color(0, 0, 255) # Blue
        elif role == "Tagger":
            set_led_color(255, 0, 0)  # Red
            ble.advertise("Tagger")
        elif role == "Beacon":
            if cooldown_active:
                set_led_color(0, 0, 0) # Turn Off
                if time.time() - cooldown_start > 5: 
                    cooldown_active = False
            elif not caught:
                set_led_color(255, 255, 0)  # Yellow
                ble.advertise("Beacon")
            else:
                set_led_color(0, 0, 255)  # Blue
    else:
        ble.stop_scan()
        set_led_color(0, 0, 0)
    
    mqtt_client.check_msg()
    time.sleep(0.1)
