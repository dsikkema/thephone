import re
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
ser.write(b'AT+CMGD=,1\r\n')

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
        # print(c.encode())
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
    with sqlite3.connect('phone.db', autocommit=True) as conn:
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
    ]


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
