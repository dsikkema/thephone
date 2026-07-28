import serial
import sys
from time import sleep
import threading

ser = serial.Serial('/dev/serial0', 115200)
ser.flushInput()

def server():
    rec_buff = ''
    while True:
        sleep(0.05)
        if ser.inWaiting():
            rec_buff = ser.read(ser.inWaiting()).decode()
            print(rec_buff)

def app():
    while True:
        sleep(3.0)
        ser.write(f"AT\r\n".encode())
threading.Thread(target=server).start()
app()
