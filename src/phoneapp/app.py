import re
import json
from cryptography.fernet import Fernet
import functools
import math
import datetime
import os
import termios
import serial
import sys
from time import sleep
import time
import threading
from .storage import Storage
import sqlite3

# remember: must run with PYTHONUNBUFFERED=1 to disable output (or input, can't remember) buffering


CLEAR='\033[2J'
HOME='\033[H'

ser = serial.Serial('/dev/serial0', 115200)
ser.flushInput()
ser.write('ATE0\r\n'.encode())
sleep(0.05)
ser.write('AT+CMGF=1\r\n'.encode())
sleep(0.05)
ser.write(b'AT+CMGL="REC UNREAD"\r\n')
sleep(0.05)
# ser.write(b'AT+CMGD=,1\r\n')
# enable gps
# TOODO: maybe need to do this *right* before getting coords
ser.write(b'AT+CGPS=1,1\r\n')
sleep(0.05)
ser.write(b'AT+HTTPTERM\r\n')
sleep(0.05)
ser.write(b'AT+HTTPINIT\r\n')
sleep(0.05)

line_buffer = []
rec_buff = ''
gps_coord = None
gps_ready = threading.Event()
http_resp = None
http_ready = threading.Event()
hang_up = None
def readline_at():
    global line_buffer
    global rec_buff
    sep = '\r\n'
    # always do a single read to prime the line buffer
    if ser.inWaiting():
        rec_buff += ser.read(ser.inWaiting()).decode()
        split = rec_buff.split(sep)
        line_buffer += split[:-1]
        rec_buff = split[-1]
    # anything to return? then do so
    if line_buffer:
        c = line_buffer.pop(0)
        print(c.encode())
        return c
    else:
        # while nothing to return and partial line, wait&read
        while rec_buff and not line_buffer:
            sleep(0.05)
            if ser.inWaiting():
                _read = ser.read(ser.inWaiting())
                sys.stdout.flush()
                rec_buff += _read.decode()
                split = rec_buff.split(sep)
                line_buffer += split[:-1]
                rec_buff = split[-1]
        # either above loop read something into line_buffer (return pop buffer)
        # or else it never entered (return None)
        c = line_buffer.pop(0) if line_buffer else None
        if c:
            print(c.encode())
        return c

def server():
    global gps_coord
    global hang_up
    global http_resp
    with sqlite3.connect('phone.db', autocommit=True) as conn:
        storage = Storage(conn)
        datetime_patt = r'"(\d\d/\d\d/\d\d,\d\d:\d\d:\d\d)([-\+]+\d+)"'
        tasks = []
        try:
            while True:
                sleep(0.2)
                # read loop
                cl = readline_at()
                if cl is not None:
                    if cl.startswith("+CMTI"):
                        match  = re.match(r'\+CMTI: "[^"]*",(\d+).*', cl)
                        _idx = match.groups()[0]
                        # TOODO: make CMGR write a task
                        ser.write(f"AT+CMGR={_idx}\r\n".encode())
                        sleep(0.05)
                    elif cl.startswith("+CMGR"):
                        match  = re.match(r'\+CMGR: "[^"]+","\+?(\d+)","[^"]*",' + datetime_patt, cl)
                        if not match:
                            raise ValueError(f"bad match: {cl}")
                        sender = match.groups()[0]
                        offset_num = int(match.groups()[2]) # positive or negative quarters of an hour offset from utc
                        offset_delta = datetime.timedelta(minutes=offset_num*15)
                        recv_at = datetime.datetime.strptime(match.groups()[1], '%y/%m/%d,%H:%M:%S').replace(
                                tzinfo=datetime.timezone(offset_delta)
                            )
                        msg = ''
                        cl = readline_at()
                        while cl != 'OK':
                            msg += ('\n' + cl)
                            cl = readline_at()
                        msg = msg.strip()
                        storage.save_recv_message(sender, sender, msg, recv_at)
                    elif cl.startswith("+CMGL"):
                        while cl != 'OK':
                            match  = re.match(r'\+CMGL: \d+,"[^"]+","\+?(\d+)","[^"]*",' + datetime_patt, cl)
                            if not match:
                                print('bad match')
                            sender = match.groups()[0]
                            offset_num = int(match.groups()[2]) # positive or negative quarters of an hour offset from utc
                            offset_delta = datetime.timedelta(minutes=offset_num*15)
                            recv_at = datetime.datetime.strptime(match.groups()[1], '%y/%m/%d,%H:%M:%S').replace(
                                tzinfo=datetime.timezone(offset_delta)
                            )
                            msg = ''
                            cl = readline_at()
                            while cl != 'OK' and not cl.startswith('+CMGL'):
                                msg += ('\n' + cl)
                                cl = readline_at()
                            if cl == 'OK':
                                msg = msg.rstrip()
                            storage.save_recv_message(sender, sender, msg, recv_at)
                    elif cl.startswith("+CGPSINFO"):
                        # +CGPSINFO: 3025.118530,N,09742.830097,W,110826,054234.0,232.2,0.0,317.7
                        match = re.match(r'\+CGPSINFO: (\d{2})(\d{2}\.\d{6}),(N|S),(\d{3})(\d{2}\.\d{6}),(E|W).*', cl)
                        if not match:
                            raise ValueError(f"bad match: {cl}")
                        g = match.groups()
                        lat_deg = g[0]
                        lat_minutes = g[1]
                        north_south = g[2]
                        longitude_deg = g[3]
                        longitude_minutes = g[4]
                        east_west = g[5]

                        lat_decimal_degree = coord_to_degrees(lat_deg, lat_minutes, north_south)
                        long_decimal_degree = coord_to_degrees(longitude_deg, longitude_minutes, east_west)
                        gps_coord = (lat_decimal_degree, long_decimal_degree)
                        gps_ready.set()
                    elif cl.startswith('+HTTPACTION'):
                        match = re.match(r'\+HTTPACTION: \d+,(\d+),(\d+)', cl)
                        if not match:
                            raise ValueError(f"bad match: {cl}")
                        g = match.groups()
                        status_code = g[0]
                        resp_bytes = g[1]
                        print('read cmd')
                        ser.write(f"AT+HTTPREAD={resp_bytes}\r\n".encode())
                        sleep(0.5)
                        cl = readline_at()

                        # success format:

                        # OK
                        # +HTTPREAD: DATA,<data_len>
                        # <data>
                        # [+HTTPREAD: DATA,<data_len>
                        # <data>
                        # ...]
                        # +HTTPREAD: 0

                        # go until '+HTTPREAD: 0' end while skipping everything but data lines
                        body = ''
                        while cl != "+HTTPREAD:0" and cl != "+HTTPREAD: 0": # docs and reality disagree about the space - reality is no space
                            if cl == 'ERROR':
                                raise ValueError('oh no')
                            if cl != "OK" and not cl.startswith("+HTTPREAD: "):
                                body += cl
                            cl = readline_at()
                        http_resp = (status_code, body)
                        http_ready.set()
                        sleep(0.1)
                    elif cl.startswith("VOICE CALL: END"):
                        hang_up = True
            while tasks:
                tasks.pop(0)()

        except BaseException as e:
            print(e)
            sys.stdout.flush()
            raise

def coord_to_degrees(degrees, minutes, direction):
    """
    transform a (single) coordinate value from N/S/E/W degrees and minutes
    into positive or negative decimal degrees
    """
    res = float(degrees) + float(minutes)/60
    if direction in ('W', 'S'):
        res *= -1
    return res

# TOODO: make this a task on server that handles write
def send_msg_at(rec, msg):
    ser.write(f"AT+CMGS=\"{rec}\"\r\n".encode())
    sleep(0.05)
    ser.write(msg.encode() + b'\x1a')
    sleep(0.05)


def readline():
    """
    Omit trailing newline. Turn echo and canonical mode back on temporarily
    """
    fd = _stdin.fileno()
    old = termios.tcgetattr(fd)
    new = termios.tcgetattr(fd)
    new[3] = new[3] | termios.ICANON | termios.ECHO
    termios.tcsetattr(fd, termios.TCSADRAIN, new)
    try:
        return _stdin.readline()[:-1].decode()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def print_send(rec=None):
    print(''.join((CLEAR, HOME)), end='')
    print('Ctrl+C to exit')
    try:
        if rec is None:
            print("Recipient (blank for self)")
            rec = readline()
        print("Message: ")
        msg = readline()

        if rec == '':
            rec = os.environ.get('MYNO')
            if not rec:
                raise RuntimeError('must supply MYNO var or enter number')
        #at_test()
        send_message(rec, msg)
        print('Done! Press enter to continue.')
        readline()
    except KeyboardInterrupt:
        pass

def at_test():
    ser.write('AT\r\n'.encode())


def send_message(rec, msg):
    (conversation_id, _id) = app_storage.save_new_sent_message(rec, msg)
    send_msg_at(rec, msg)
    app_storage.mark_successful_send(_id)

def render_conv(_id, participants):
    rerender = True
    while True:
        if rerender:
            sz = os.get_terminal_size()
            rows = sz.lines
            cols = sz.columns
            def _linewrap(m, length):
                return functools.reduce(lambda l1, l2: l1+l2, [[l[i*length:(i+1)*length] for i in range(math.ceil(len(l) / length))] or [''] for l in m.split('\n')])
            def _justify_conv_line(is_recv, line, width):
                return '  ' + line if is_recv else line.rjust(width-2, ' ')

            msgs = app_storage.get_most_recent_conversation_content(_id, 1_000_000)
            rendered_lines = []
            for msg in reversed(msgs):
                is_recv = not bool(msg[3])
                sender = msg[1] if is_recv else 'Me'
                timestamp = msg[0]
                wrapped_content = _linewrap(msg[2], int(0.8 * cols))
                rendered_lines.extend([_justify_conv_line(is_recv, str(l), cols) for l in [sender, timestamp, *wrapped_content]])
            #print(f"debug: {rows=} {cols=} {len(rendered_lines)=}, {rendered_lines=}")
            sys.stdout.flush()
            rendered_lines = (rows - len(rendered_lines)) * [''] + rendered_lines
            last_line_idx = len(rendered_lines) - 1
        rerender=False

        print(''.join((CLEAR, HOME)), end='')
        print('\n'.join(rendered_lines[last_line_idx - rows + 1:last_line_idx + 1]), end='')
        k = _stdin.read(1).decode()
        if k == 'j' and last_line_idx < len(rendered_lines) - 1:
            last_line_idx += 1
        elif k == 'k' and last_line_idx > rows:
            last_line_idx -= 1
        elif k == '\n':
            print_send(rec=participants)
            rerender=True
        elif k == '\033':
            break




def print_list():
    # sorry, doing this in sql is too annoying because you have to duplicate the whole subquery that gets
    # the message content to be able to get the index of the first newline
    def _conv_list():
        return [
            (f"{row[1]}: {row[2].split('\n')[0]}", functools.partial(render_conv, row[0], row[1]))
            for row in app_storage.list_conversations()
        ]
    nav_menu(_conv_list)
    
def main_menu():
    return [
        ('Send Message',  print_send),
        ('List Conversations', print_list),
        ('GPS', gps),
        ('Place Call', phone_call),
    ]

def phone_call():
    global hang_up
    hang_up = False
    print("Who do you want to call?")
    rec = readline()
    ser.write(f"ATD{rec};\r\n".encode())
    print("Call in progress. Press ESC to hang up.")
    try:
        os.set_blocking(_stdin.fileno(), False)
        while not hang_up:
            sleep(0.5)
            # print('check')
            k = _stdin.read(1)
            if k == b'\033':
                ser.write(b'AT+CHUP\r\n')
    finally:
        # re enable blocking
        os.set_blocking(_stdin.fileno(), True)
        

def encrypt(plain):
    # from env var
    key = os.environ('FERNET_KEY')
    if key is None:
        raise RuntimeError('need the key')

    fernet = Fernet(key.encode())
    return fernet.encrypt(s.encode())

def gps():
    global gps_coord
    global http_resp
    gps_coord = None
    gps_ready.clear()
    print(''.join((CLEAR, HOME)), end='')
    print("Enter destination:")
    dest = readline()
    # get coord:
    ser.write(b'AT+CGPSINFO\r\n')
    sleep(0.1)
    gps_ready.wait()
    lat_decimal_degree, long_decimal_degree = gps_coord
    print(f"debug: coord = {lat_decimal_degree, long_decimal_degree}")
    sleep(0.5)

    # http for sever
    http_ready.clear()
    http_resp = None
    print('url')
    ser.write(b'AT+HTTPPARA="URL","http://postman-echo.com/post"\r\n')
    sleep(0.5)
    print('body')
    payload='{"val":123}'.encode()
    ser.write(f"AT+HTTPDATA={len(payload)},300\r\n".encode()) # <num bytes to send>, <num seconds to wait for input>
    sleep(0.5)
    # <then write data>
    ser.write(payload)
    sleep(0.5)
    print('action')
    payload='{"val":123}'.encode()
    ser.write(b'AT+HTTPACTION=1\r\n')
    sleep(0.5)
    print('wait')
    http_ready.wait()
    resp = http_resp
    print(f"Your response is: {resp}")
    print('Done! Press enter to continue.')
    readline()

    # search new coord
    # curl "https://api.mapbox.com/search/geocode/v6/forward?q=3500+Cookstown+Dr+Austin+Tx&access_token=$MAPBOX_TOKEN"

    # nav to coord
    # url encode: long/lat, %2C = ',', %3B = ';'
    # curl "https://api.mapbox.com/directions/v5/mapbox/driving/-74.150434%2C40.811716%3B-74.136459%2C40.794178?alternatives=true&geometries=geojson&language=en&overview=full&steps=true&access_token=<tok>"

    """
    # distances in meters
     $ jq '.routes[].legs[].steps[] | .maneuver.instruction, .distance' < instruction.json
        "Drive northeast on Havelock Drive."
        66.595
        "Turn right onto Gable Drive."
        164.972
        "Turn right onto Adelphi Lane."
        428.936
        "Turn right onto Waters Park Road."
        757.518
        "Bear right onto North Mopac Service Road."
        644.145
        "Turn left onto Duval Road/FM 1325. Continue on FM 1325."
        1282.02
        "Turn left onto Esperanza Crossing."
        103.685
        "Turn left."
        18.364
        "Turn right."
        10.525
        "Bear right."
        31.107
        "Your destination is on the right."
        0
    """

def print_menu(menu, init_cursor):
    sz = os.get_terminal_size()
    rows = sz.lines
    cols = sz.columns

    PREFIX='( ) '

    n_opts = len(menu)
    width = max(len(i[0]) for i in menu) if menu else 0 + len(PREFIX)

    vpad_n = ((rows- n_opts) // 2)
    lpad_n = ((cols  - width) // 2)
    vpad = vpad_n * '\n'
    lpad = lpad_n * ' ' 

    page = ''.join((
        CLEAR,
        HOME,
        vpad,
        '\n'.join(
            (''.join((lpad, PREFIX, r[0])) for r in menu) if menu else ['(No options)']
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

def nav_menu(menu):
    # menu is a function so it can get recalled incase values are dynamic
    current_opt = 0
    n_opts, start_row, cursor_col = print_menu(menu(), current_opt)

    # put terminal into 'raw' mode, disabling printing of user's keypresses
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    new = termios.tcgetattr(fd)
    new[3] = new[3] & ~(termios.ICANON | termios.ECHO)
    termios.tcsetattr(fd, termios.TCSADRAIN, new)
    try:
        while True:
            k = _stdin.read(1).decode()
            if k == '\n' and menu:
                menu()[current_opt][1]()
                # done with the option selection; print current menu again
                n_opts, start_row, cursor_col = print_menu(menu(), current_opt)
            elif k == 'j' and  current_opt < n_opts:
                current_opt += 1
                highlight_row(current_opt, start_row, cursor_col)
            elif k == 'k' and current_opt > 0:
                current_opt -= 1
                highlight_row(current_opt, start_row, cursor_col)
            elif k == '\033':
                print("Goodbye!")
                break
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, old)

app_storage = None
_stdin = None

def main():
    threading.Thread(target=server, daemon=True).start()
    global app_storage
    global _stdin
    with sqlite3.connect('phone.db', autocommit=True) as conn:
        app_storage = Storage(conn)
        fd = sys.stdin.fileno()
        with os.fdopen(fd, 'rb', buffering=False) as _stdin_ctx:
            _stdin = _stdin_ctx
            nav_menu(main_menu)
