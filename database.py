import sqlite3


def get_connection():
    """Return a connection to the database."""
    conn = sqlite3.connect('task_db.db')
    conn.row_factory = sqlite3.Row
    return conn


def setup_database():
    """Set up the database if it doesn't exist."""
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        description TEXT,
        created_date TEXT,
        status TEXT, -- 'scheduled', 'completed', 'irrelevant', 'buffered'
        scheduled_date TEXT,
        latest_event_id INTEGER,
        FOREIGN KEY (latest_event_id) REFERENCES task_events (event_id)
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS task_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER,
        event_type TEXT,
        event_date TEXT,
        scheduled_date TEXT,
        FOREIGN KEY (task_id) REFERENCES tasks (id)
    )
    ''')

    conn.commit()
    conn.close()
