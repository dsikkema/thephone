import re
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
# lol
# ser.write(b'AT+CMGL="ALL"\r\n')


# req = (func, args, kwargs) tuple
req = None
resp = None
tasks = []

def handle_command(cmd, log, storage):
    pass

def _debug_server():
    rec_buff = ''
    while True:
        sleep(0.05)
        if ser.inWaiting():
            rec_buff = ser.read(ser.inWaiting()).decode()
def server():
    conn = sqlite3.connect('phone.db', autocommit=True)
    storage = Storage(conn)
    rec_buff = ''
    sep = '\r\n'
    try:
        with open('at_response.log', 'w') as log:
            while True:
                sleep(0.05)
                if ser.inWaiting():
                    sys.stdout.flush()
                    _in = ser.read(ser.inWaiting())
                    sys.stdout.flush()
                    rec_buff += _in.decode()
                split = rec_buff.split(sep)
                # eliminate empty values, but don't eliminate last one even if empty
                split = [s for s in split[:-1] if s] + [split[-1]]
                cmds = split[:-1]
                rec_buff = split[-1]
                for cmd in cmds:
                    # handle_command should append the correct task to task queue
                    handle_command(cmd, log, storage)
                
                if req:
                    tasks.append(req)
                    req = None
                for t in tasks:
                    t[0](*t[1], **t[2])
    except BaseException as e:
        print(e)
        sys.stdout.flush()
        raise

def send_msg_at(rec, msg):
    """
    Leaving off: need to keep all serial reading in the same loop - other notifications may come in that
    would get read by this loop if this loop read from the wire. 

    Requests are serial, therefore could register a single request listener _to_ the read loop though, with
    a callback - handled in-server

    This func creates a function and a regex pattern to look for (OR|ERROR|etc), assigns it to req_callback 
    and req_callback.pattern)- read loop's handle_command checks cmds against the req_callback.pattern

    callback simply sets response val (Note: client must unset resp as soon as read it)

    """
    ser.write(f"AT+CMGS=\"{rec}\"\r\n".encode())
    sleep(0.05)
    ser.write(msg.encode() + b'\x1a')
    sleep(0.05)
    def send_message_callback(cmd, st):
        if cmd == 'OK':
            ser_callback.result = True 
            st.mark_successful_send(_id)
        callback_done.set()



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
    # ser_lock guards: ser write, callback creation
    global ser_callback
    with ser_lock:
        callback_done = threading.Event()
        (conversation_id, _id) = storage.save_new_sent_message(rec, msg)
        
        # register a pattern to be handled by this (takes priority)
        send_message_callback.pattern = 'OK|ERROR|\\+CMS ERROR: .*' 
        ser_callback = send_message_callback
        ser_callback.result = None

        # ser.write(f"AT\r\n".encode())

        # event returns False if timed_out, but we don't use that and just check the flag
        callback_done.wait(timeout=5)
        if not ser_callback.result:
            print("Message failed to send.")
        else:
            print("Sent successfully!")
        ser_callback = None

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
