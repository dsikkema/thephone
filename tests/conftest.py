import pytest
import sqlite3

@pytest.fixture
def conn():
    pass
    with open('init.sql', 'r') as f:
        init_script = f.read()
    conn = sqlite3.connect(':memory:')
    conn.executescript(init_script)
    return conn
