import serial
import time
import sys

assert len(sys.argv) == 3
recipient=sys.argv[1]
msg = sys.argv[2]
print(recipient, msg)
ser = None
try:
	ser = serial.Serial('/dev/serial0',115200)
	ser.flushInput()
	ser.write((f"AT+CMGS=\"{recipient}\"\r\n").encode())
	time.sleep(0.1)
	ser.write(msg.encode())
	ser.write(b'\x1A')
	time.sleep(0.1)
	rec_buff=''
	if ser.inWaiting():
	  time.sleep(0.1)
	  rec_buff=ser.read(ser.inWaiting())
	if rec_buff != '':
	  print(rec_buff.decode())
	  rec_buff=''

except Exception as e:
	print(f"error: {e}")
	if ser:
		ser.close()
