import os
import termios
import serial
import sys
from time import sleep
import threading
from .storage import Storage
import sqlite3


CLEAR='\033[2J'
HOME='\033[H'

ser = serial.Serial('/dev/serial0', 115200)
ser.flushInput()


ser_lock = threading.Lock()
ser_callback = None

def handle_command(cmd, log):
    log.write(f"{int(time.time())}:{cmd}\n")
    if cmd == 'OK' or cmd == 'ERROR':
        if ser_callback is not None:
            ser_callback(cmd == 'OK')
        else:
            log.write(f"{int(time.time())} error:{cmd} received with no callback\n")


def server():
    rec_buff = ''
    try:
        with open('at_response.log', 'w') as log:
            while True:
                sleep(0.05)
                if ser.inWaiting():
                    print('b')
                    sys.stdout.flush()
                    _in = ser.read(ser.inWaiting())
                    print(_in)
                    sys.stdout.flush()
                    rec_buff += _in.decode()
                split = rec_buff.split('\n')
                cmds = split[:-1]
                rec_buff = split[-1]
                for cmd in cmds:
                    handle_command(cmd, log)
    except Error as e:
        print(e)
        sys.stdout.flush()
        raise




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
    with ser_lock:
        callback_done = threading.Event()
        success_flag = False
        def send_message_callback(success):
            global success_flag
            if success:
                success_flag = True 
                storage.mark_successful_send(_id)
            callback_done.set()
        ser_callback = send_message_callback

        # ser.write(f"AT+CMGS=\"{rec}\"\r\n".encode())
        # sleep(0.05)
        # ser.write(msg.encode() + b'\x1a')
        # sleep(0.05)
        ser.write(f"AT\r\n".encode())

        _id = storage.save_new_sent_message(rec, msg)

        # event returns False if timed_out, but we don't use that and just check the flag
        callback_done.wait(timeout=5)
        if not success_flag:
            print("Message failed to send.")
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
