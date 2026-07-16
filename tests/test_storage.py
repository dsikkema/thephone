# pytest
from phoneapp.storage import Storage
from datetime import datetime, timezone, timedelta
import pytest

@pytest.fixture
def storage(conn):
    return Storage(conn)

p1 = '1234567890'
p2 = '7777777777'

def onerow(conn, sql):
    cur = conn.execute(sql)
    return cur.fetchone()

def test_the_test(conn):
    assert 'ok' == 'ok'
    conn.execute("""insert into conversations 
    (id, participants)
    values
    (1, '1234567890')
    """)

    cur = conn.execute("""
    select id, participants from conversations""")
    res = cur.fetchall()
    assert res == [(1, '1234567890')]

def test_get_or_create_conversation(conn, storage):
    id1 = storage.get_or_create_conversation(p1)
    id2 = storage.get_or_create_conversation(p2)

    assert isinstance(id1, int)
    assert isinstance(id2, int)
    assert id2 > id1
    assert id1 == storage.get_or_create_conversation(p1)
    assert id2 == storage.get_or_create_conversation(p2)
    res = onerow(conn, 'select count(*) from conversations')
    assert res == (2,)

def test_save_recv_mesage(conn, storage):
    m = 'hey'
    ts = datetime.now(timezone.utc) - timedelta(seconds=2)
    storage.save_recv_message(p1, p1, m, ts)
    (_id, conv_id, sender, content, recv_at, created_at) = onerow(conn, 'select * from recv_messages where id=1')
    
    assert isinstance(_id, int)
    assert isinstance(conv_id, int)
    assert sender == p1
    assert content == m
    assert recv_at == int(ts.timestamp())
    assert isinstance(created_at, int) 

    # next message, same conversation
    m2 = 'hey again'
    ts2 = datetime.now(timezone.utc) - timedelta(seconds=1)

    storage.save_recv_message(p1, p1, m2, ts2)
    (_id2, conv_id2, sender, content, recv_at, created_at) = onerow(conn, 'select id, conversation_id, sender, content, recv_at, created_at from recv_messages where id=2')
    
    assert isinstance(_id2, int)
    assert _id2 > _id
    assert conv_id == conv_id2
    assert sender == p1
    assert content == m2
    assert recv_at == int(ts2.timestamp())
    assert isinstance(created_at, int) 

    # next message in different conversation
    m3 = 'hey third'
    ts3 = datetime.now(timezone.utc)
    storage.save_recv_message(p2, p2, m3, ts3)
    (_id3, conv_id3, sender, content, recv_at, created_at) = onerow(conn, 'select id, conversation_id, sender, content, recv_at, created_at from recv_messages where id=3')

    c=conn.execute('select * from conversations')
    r=c.fetchall()
    print(r)
    assert isinstance(_id3, int)
    assert _id3 > _id2
    assert isinstance(conv_id3, int)
    assert conv_id3 > conv_id
    assert sender == p2
    assert content == m3
    assert recv_at == int(ts3.timestamp())
    assert isinstance(created_at, int) 

def test_save_new_sent_message(conn, storage):

    # Message 1 Conv 1
    m1='hey'
    inserted_id = storage.save_new_sent_message(p1, m1)
    (_, cid1, success1, content1, sent_at1) = onerow(
        conn,
        f"select * from sent_messages where id={inserted_id}"
    )

    assert cid1 == 1
    assert success1 == 0
    assert content1 == m1
    assert isinstance(sent_at1, int)

    # Message 2 Conv 1
    m2="hey again"
    inserted_id = storage.save_new_sent_message(p1, m2)
    (_, cid2, success2, content2, sent_at2) = onerow(
        conn,
        f"select * from sent_messages where id={inserted_id}"
    )

    assert cid2 == 1
    assert success2 == 0
    assert content2 == m2
    assert isinstance(sent_at2, int)

    # Message 1 Conv 2
    m3="hey again three"
    inserted_id = storage.save_new_sent_message(p2, m3)
    (_, cid3, success3, content3, sent_at3) = onerow(
        conn,
        f"select * from sent_messages where id={inserted_id}"
    )

    assert cid3 == 2
    assert success3 == 0
    assert content3 == m3
    assert isinstance(sent_at3, int)

def test_mark_successful_send(conn, storage):
    inserted_id = storage.save_new_sent_message(p1, "hey")
    storage.mark_successful_send(inserted_id)
    (_, cid1, success1, content1, sent_at1) = onerow(
        conn,
        f"select * from sent_messages where id={inserted_id}"
    )
    assert success1 == 1

def test_list_conversations(conn, storage):
    _1s = timedelta(seconds=1)
    start = datetime.now(timezone.utc) - timedelta(seconds=30)
    
    p3 = '3333333333'
    p4 = '4444444444'
    p5 = '5555555555'
    p6 = '6666666666'

    # conv 1
    storage.save_new_sent_message(p2, 'hey', start)
    storage.save_recv_message(p2, p2, 'hey back atcha', start + _1s)
    storage.save_recv_message(p2, p2, 'what is up?', start + _1s*2)

    # conv 2
    storage.save_recv_message(p3, p3, 'please help me', start + _1s*3)
    storage.save_new_sent_message(p3, 'ok i will help you', start+_1s*4)
    storage.save_recv_message(p3, p3, 'nevermind it got fixed', start+_1s*5)

    # conv 3 - started first, ended last of the 5
    storage.save_recv_message(p4, p4, 'guess what', start - _1s*10)
    storage.save_new_sent_message(p4, 'lol no', start+_1s*10)
    storage.save_recv_message(p4, p4, 'they invented words, this is going to be so cool', start+_1s*29)

    # conv 4
    storage.save_recv_message(p5, p5, 'ok', start + _1s*20)

    # conv 5
    storage.save_recv_message(p1, p1, 'ok', start + _1s*25)

    # conv 6 - too old, excluded
    storage.save_recv_message(p6, p6, 'ok', start - _1s*100000)

    res = storage.list_conversations(n=5)
    assert res == [
        # conv 3
        (3, p4, 'they invented words, this is g'),
        # conv 5
        (5, p1, 'ok'),
        # conv 4
        (4, p5, 'ok'),
        # conv 2
        (2, p3, 'nevermind it got fixed'),
        # conv 1
        (1, p2, 'what is up?')
    ]


