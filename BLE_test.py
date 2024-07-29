import network
from mqtt import MQTTClient
import bluetooth
import time
import struct
import utime
import machine
from neopixel import NeoPixel
from machine import Pin, PWM
import urandom
import ubinascii

pin = Pin(21, Pin.OUT)   # set GPIO0 to output to drive NeoPixels
np = NeoPixel(pin, 1)   # create NeoPixel driver on GPIO0 for 1 pixel

NAME_FLAG = 0x09
SCAN_RESULT = 5
SCAN_DONE = 6

rss = 0

class Listen:   
    def __init__(self): 
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._ble.irq(self.callback)
        self.scanning = False
        self.caught_count = 0
        self.last_tagger_rssi = 0
        self.save_count = 0

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
            global rss
            addr_type, addr, adv_type, rssi, adv_data = data
            name = self.find_name(adv_data)

            if "Beacon" in name:
#                 print("name: %s, rssi: %d"%(name, rssi))
                rss = rssi
                
            
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

# Setup
ble = Listen()

rssi_distance = [
    (-80, 10),  # (RSSI, distance in meters)
    (-70, 6),
    (-60, 3),
    (-50, 1),
    (-35, 0)
]

def map_rssi_to_frequency(rssi):
    # Define the frequency range (in Hz)
    min_freq = 0.5  # 0.5 Hz = blink every 2 seconds (for far distances)
    max_freq = 5    # 5 Hz = blink 5 times per second (for close distances)

    # Find the two nearest RSSI values in our data
    for i, (r1, d1) in enumerate(rssi_distance):
        if rssi >= r1 or i == len(rssi_distance) - 1:
            if i == 0:
                return min_freq
            r2, d2 = rssi_distance[i-1]
            break

    # Interpolate between the two points
    if r1 == r2:
        ratio = 1
    else:
        ratio = (rssi - r1) / (r2 - r1)
    
    distance = d1 + ratio * (d2 - d1)

    # Map distance to frequency (inverse relationship)
    freq = min_freq + (max_freq - min_freq) * (10 - min(distance, 10)) / 10

    return freq

# Main loop
while True:
    ble.scan(0)
    
    if rss > -100:  # Only change if a beacon was detected
        frequency = map_rssi_to_frequency(rss)
        delay_ms = int(1000 / (2 * frequency))  # Convert frequency to delay
    else:
        delay_ms = 1000  # Default to 1 second if no beacon detected
    
    # Blink yellow
    np[0] = (255, 255, 0)  # Yellow
    np.write()
    utime.sleep_ms(100)  # Fixed 'on' time
    
    np[0] = (0, 0, 0)  # Off
    np.write()
    utime.sleep_ms(delay_ms - 100)  # Variable 'off' time
    
    print(f"Beacon RSSI: {rss}, Blink Frequency: {frequency:.2f} Hz")
