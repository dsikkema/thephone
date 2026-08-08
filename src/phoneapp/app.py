import re
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


CLEAR='\033[2J'
HOME='\033[H'

ser = serial.Serial('/dev/serial0', 115200)
ser.flushInput()
ser.write('ATE0\r\n'.encode())
sleep(0.1)
ser.write('AT+CMGF=1\r\n'.encode())
sleep(0.1)
# TOODO: uncomment to load unread at start
ser.write(b'AT+CMGL="REC UNREAD"\r\n')


# req = (func, args, kwargs) tuple
req = None
resp = None

def handle_command(cmd, log, storage):
    pass

def _debug_server():
    rec_buff = ''
    while True:
        sleep(0.05)
        if ser.inWaiting():
            rec_buff = ser.read(ser.inWaiting()).decode()

line_buffer = []
rec_buff = ''
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
                rec_buff += ser.read(ser.inWaiting()).decode()
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
    conn = sqlite3.connect('phone.db', autocommit=True)
    storage = Storage(conn)
    datetime_patt = r'"(\d\d/\d\d/\d\d,\d\d:\d\d:\d\d)([-\+]+\d+)"'
    try:
        while True:
            sleep(0.2)
            # read loop
            cl = readline_at()
            if cl is not None:
                if cl.startswith("+CMTI"):
                    match  = re.match(r'\+CMTI: "[^"]*",(\d+).*', cl)
                    _idx = match.groups()[0]
                    ser.write(f"AT+CMGR={_idx}\r\n".encode())
                    sleep(0.05)
                elif cl.startswith("+CMGR"):
                    match  = re.match(r'\+CMGR: "[^"]+","\+(\d+)","[^"]*",' + datetime_patt, cl)
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
                    while cl != 'OK':
                        msg += ('\n' + cl)
                        cl = readline_at()
                    msg = msg.strip()
                    storage.save_recv_message(sender, sender, msg, recv_at)
                elif cl.startswith("+CMGL"):
                    while cl != 'OK':
                        match  = re.match(r'\+CMGL: \d+,"[^"]+","\+(\d+)","[^"]*",' + datetime_patt, cl)
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

    except BaseException as e:
        print(e)
        sys.stdout.flush()
        raise

def send_msg_at(rec, msg):
    ser.write(f"AT+CMGS=\"{rec}\"\r\n".encode())
    sleep(0.05)
    ser.write(msg.encode() + b'\x1a')
    sleep(0.05)


def readline(_stdin):
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


def print_send(_stdin, storage):
    print(''.join((CLEAR, HOME)), end='')
    print("Recipient (blank for self): ")
    rec = readline(_stdin)
    print("Message: ")
    msg = readline(_stdin)

    if rec == '':
        rec = os.environ.get('MYNO')
        if not rec:
            raise RuntimeError('must supply MYNO var or enter number')
    #at_test()
    send_message(rec, msg, storage)
    print('Done! Press enter to continue.')
    readline(_stdin)

def at_test():
    ser.write('AT\r\n'.encode())


def send_message(rec, msg, storage):
    (conversation_id, _id) = storage.save_new_sent_message(rec, msg)
    send_msg_at(rec, msg)
    storage.mark_successful_send(_id)

def print_list(_stdin, storage):
    print(''.join((CLEAR, HOME)), end='')
    print('\n'.join(
        f"Conversation ID: {row[0]}\nParticipants: {row[1]}\nPreview: {row[2]}" for row in
        storage.list_conversations()
        ))
    print('Press enter to continue.')
    readline(_stdin)
    
def _exit(*args):
    print('Goodbye!')
    return True

menu = [
    ('Send Message',  print_send),
    ('List Conversations', print_list),
    ('Exit', _exit)
]


def print_menu(init_cursor):
    sz = os.get_terminal_size()
    rows = sz.lines
    cols = sz.columns

    PREFIX='( ) '

    n_opts = len(menu)
    width = max(len(i[0]) for i in menu) + len(PREFIX)

    vpad_n = ((rows- n_opts) // 2)
    lpad_n = ((cols  - width) // 2)
    vpad = vpad_n * '\n'
    lpad = lpad_n * ' ' 

    page = ''.join((
        CLEAR,
        HOME,
        vpad,
        '\n'.join(
            ''.join((lpad, PREFIX, r[0])) for r in menu
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
    current_opt = 0
    n_opts, start_row, cursor_col = print_menu(current_opt)
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    new = termios.tcgetattr(fd)
    new[3] = new[3] & ~(termios.ICANON | termios.ECHO)
    termios.tcsetattr(fd, termios.TCSADRAIN, new)
    try:
        with sqlite3.connect('phone.db', autocommit=True) as conn:
            storage = Storage(conn)
            with os.fdopen(fd, 'rb', buffering=False) as _stdin:
                try:
                    while True:
                        k = _stdin.read(1).decode()
                        if k == '\n':
                            do_exit = menu[current_opt][1](_stdin, storage)
                            if do_exit:
                                break
                            n_opts, start_row, cursor_col = print_menu(current_opt)
                        elif k == 'j' and  current_opt < n_opts:
                            current_opt += 1
                            highlight_row(current_opt, start_row, cursor_col)
                        elif k == 'k' and current_opt > 0:
                            current_opt -= 1
                            highlight_row(current_opt, start_row, cursor_col)
                finally:
                    termios.tcsetattr(fd, termios.TCSANOW, old)
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSANOW, old)
        except:
            pass

def main():
    threading.Thread(target=server).start()
    app()
