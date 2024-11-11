from database import get_connection
import datetime


def create_task(description):
    """Create a new task with the given description.
    Task is added to the buffer by default."""
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
    INSERT INTO tasks (description, created_date, status)
    VALUES (?, DATE('now'), 'created')
    ''', (description,))
    task_id = c.lastrowid

    conn.commit()
    conn.close()

    # Buffer the task
    event_id = buffer_task(task_id)

    conn = get_connection()
    c = conn.cursor()

    c.execute('''
    UPDATE tasks
    SET latest_event_id = ?
    WHERE id = ?
    ''', (event_id, task_id))

    conn.commit()
    conn.close()

    return task_id


def mark_task_completed(task_id):
    """Mark the task with the given ID as done."""
    conn = get_connection()
    c = conn.cursor()

    # Check if the task is scheduled
    c.execute('''
    SELECT status
    FROM tasks
    WHERE id = ?
    ''', (task_id,))
    status = c.fetchone()
    assert status[0] == 'scheduled', 'You can only mark a task as completed if it is scheduled'

    c.execute('''
    INSERT INTO task_events (task_id, event_type, event_date)
    VALUES (?, 'completed', DATE('now'))
    ''', (task_id,))
    event_id = c.lastrowid

    c.execute('''
    UPDATE tasks
    SET latest_event_id = ?, status = 'completed'
    WHERE id = ?
    ''', (event_id, task_id))

    conn.commit()
    conn.close()


def mark_task_irrelevant(task_id):
    """Mark the task with the given ID as irrelevant."""
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
    INSERT INTO task_events (task_id, event_type, event_date)
    VALUES (?, 'irrelevant', DATE('now'))
    ''', (task_id,))
    event_id = c.lastrowid

    c.execute('''
    UPDATE tasks
    SET latest_event_id = ?, status = 'irrelevant'
    WHERE id = ?
    ''', (event_id, task_id))

    conn.commit()
    conn.close()


def buffer_task(task_id):
    """Move the task with the given ID to the buffer."""
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
    INSERT INTO task_events (task_id, event_type, event_date)
    VALUES (?, 'buffered', DATE('now'))
    ''', (task_id,))
    event_id = c.lastrowid

    c.execute('''
    UPDATE tasks
    SET latest_event_id = ?, status = 'buffered', scheduled_date = NULL
    WHERE id = ?
    ''', (event_id, task_id))

    conn.commit()
    conn.close()

    return event_id


def remove_task(task_id):
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
    DELETE FROM tasks WHERE id = ?
    ''', (task_id,))
    c.execute('''
    DELETE FROM task_events WHERE task_id = ?
    ''', (task_id,))

    conn.commit()
    conn.close()


def schedule_task(task_id, scheduled_date):
    """Schedule the task with the given ID to the new date."""
    assert isinstance(scheduled_date, datetime.date), 'new_date must be a datetime.date object'
    scheduled_date = scheduled_date.isoformat()  # YYYY-MM-DD
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
    INSERT INTO task_events (task_id, event_type, event_date, scheduled_date)
    VALUES (?, 'scheduled', DATE('now'), ?)
    ''', (task_id, scheduled_date))
    event_id = c.lastrowid

    c.execute('''
    UPDATE tasks
    SET latest_event_id = ?, status = 'scheduled', scheduled_date = ?
    WHERE id = ?
    ''', (event_id, scheduled_date, task_id))

    conn.commit()
    conn.close()


def get_task(task_id):
    """Return the task with the given ID."""
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
    SELECT *
    FROM tasks
    WHERE id = ?
    ''', (task_id,))
    task = c.fetchone()

    conn.close()

    return task


def get_unfinished_tasks():
    """Return all tasks that are not marked as done or irrelevant."""
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
    SELECT *
    FROM tasks
    WHERE status = 'scheduled'
    ORDER BY id
    ''')
    tasks = c.fetchall()

    conn.close()

    return tasks


def get_tasks_for_date(date):
    """Return all tasks scheduled for the given date."""
    assert isinstance(date, datetime.date), 'date must be a datetime.date object'
    date = date.isoformat()

    conn = get_connection()
    c = conn.cursor()

    c.execute('''
    SELECT *
    FROM tasks
    WHERE scheduled_date = ?
    ORDER BY id
    ''', (date,))
    tasks = c.fetchall()

    conn.close()

    return tasks


def get_buffered_tasks():
    """Return all tasks in the buffer."""
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
    SELECT *
    FROM tasks
    WHERE status = 'buffered'
    ORDER BY id
    ''')
    tasks = c.fetchall()

    conn.close()

    return tasks


def get_all_tasks_ever_scheduled_to_date(date):
    """Return all tasks that were ever scheduled to the given date."""
    assert isinstance(date, datetime.date), 'date must be a datetime.date object'
    date = date.isoformat()

    conn = get_connection()
    c = conn.cursor()

    c.execute('''
    SELECT task_id
    FROM task_events
    WHERE scheduled_date = ?
    ORDER BY task_id
    ''', (date,))
    task_ids = c.fetchall()

    conn.close()

    return [get_task(task_id[0]) for task_id in task_ids]


def get_schedule_events(task_id, after_date=None):
    """Return all scheduling events for the task with the given ID."""
    if after_date is None:
        after_date = datetime.date(1, 1, 1)  # A date before the beginning of time

    assert isinstance(after_date, datetime.date), 'after_date must be a datetime.date object'
    after_date = after_date.isoformat()

    conn = get_connection()
    c = conn.cursor()

    c.execute('''
    SELECT *
    FROM task_events
    WHERE task_id = ?
    AND scheduled_date > ?
    ORDER BY scheduled_date
    ''', (task_id, after_date))
    task_events = c.fetchall()

    conn.close()

    return task_events


def modify_description(task_id, description):
    """Modify the description of the task with the given ID."""
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
    UPDATE tasks
    SET description = ?
    WHERE id = ?
    ORDER BY id
    ''', (description, task_id))

    conn.commit()
    conn.close()
