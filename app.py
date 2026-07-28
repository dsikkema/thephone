import os
import termios
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

def print_menu(init_cursor):
    sz = os.get_terminal_size()
    rows = sz.lines
    cols = sz.columns

    menu = [
        'Send Message',
        'List Received Messages'
    ]
    CLEAR='\033[2J'
    HOME='\033[H'
    PREFIX='( ) '

    n_opts = len(menu)
    width = max(len(i) for i in menu) + len(PREFIX)

    vpad_n = ((rows- n_opts) // 2)
    lpad_n = ((cols  - width) // 2)
    vpad = vpad_n * '\n'
    lpad = lpad_n * ' ' 

    page = ''.join((
        CLEAR,
        HOME,
        vpad,
        '\n'.join(
            ''.join((lpad, PREFIX, r)) for r in menu
        ),
        vpad
    ))
    print(page, end='')
    start_row = vpad_n + 1
    cursor_col = lpad_n + 2
    highlight_row(init_cursor, start_row, cursor_col)
    return n_opts, start_row, cursor_col

def highlight_row(n, start_row, cursor_col):
    print(f"\033[{start_row + n};{cursor_col}H", end='')

def app():
    current_row = 0
    n_opts, start_row, cursor_col = print_menu(current_row)
    while True:
        sleep(1)
threading.Thread(target=server).start()
app()
