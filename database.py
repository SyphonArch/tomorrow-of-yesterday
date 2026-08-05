import sqlite3

DEFAULT_SETTINGS = {
    'welcome_message': "Welcome to ToY, your personal task scheduler!\nType 'help' for a list of commands.",
}


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
        status TEXT, -- 'scheduled', 'completed', 'missed', 'irrelevant', 'buffered'
        priority INTEGER NOT NULL DEFAULT 0,
        duration INTEGER,
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

    c.execute('PRAGMA table_info(tasks)')
    task_columns = {row['name'] for row in c.fetchall()}
    if 'duration' not in task_columns:
        c.execute('ALTER TABLE tasks ADD COLUMN duration INTEGER')

    c.execute('''
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    ''')

    for key, value in DEFAULT_SETTINGS.items():
        c.execute('''
        INSERT OR IGNORE INTO app_settings (key, value)
        VALUES (?, ?)
        ''', (key, value))

    conn.commit()
    conn.close()


def get_setting(key):
    assert key in DEFAULT_SETTINGS, f'unknown setting {key}'

    conn = get_connection()
    c = conn.cursor()

    c.execute('''
    SELECT value
    FROM app_settings
    WHERE key = ?
    ''', (key,))
    row = c.fetchone()

    conn.close()

    if row is None:
        return DEFAULT_SETTINGS[key]
    return row['value']


def set_setting(key, value):
    assert key in DEFAULT_SETTINGS, f'unknown setting {key}'
    assert isinstance(value, str), 'value must be a string'
    assert value.strip() != '', 'value must not be blank'

    conn = get_connection()
    c = conn.cursor()

    c.execute('''
    INSERT INTO app_settings (key, value)
    VALUES (?, ?)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value
    ''', (key, value))

    conn.commit()
    conn.close()
