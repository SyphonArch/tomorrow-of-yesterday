import task_manager as tm
import database


def format_duration(duration_minutes):
    """Format integer minutes as the compact duration prefix used in task strings."""
    assert isinstance(duration_minutes, int), 'duration_minutes must be an integer'
    assert duration_minutes > 0, 'duration_minutes must be positive'
    hours = duration_minutes // 60
    minutes = duration_minutes % 60
    if hours > 0 and minutes > 0:
        return f'{hours}h{minutes}m'
    if hours > 0:
        return f'{hours}h'
    return f'{minutes}m'


def get_task_string(task_id):
    """Return the string representation of the task with the given ID."""
    task = tm.get_task(task_id)
    if task is None:
        return f'[#{task_id}: Task not found]'
    duration = task['duration'] if 'duration' in task.keys() else None
    if duration:
        return f'[#{task_id}: {format_duration(duration)} | {task["description"]}]'
    return f'[#{task_id}: {task["description"]}]'


def get_day_string(today, date):
    """Return the name of the day with the given offset from today."""
    day_offset = (date - today).days
    iso = date.isoformat()
    if day_offset == -2:
        name = "day before yesterday"
    elif day_offset == -1:
        name = "yesterday"
    elif day_offset == 0:
        name = "today"
    elif day_offset == 1:
        name = "tomorrow"
    elif day_offset == 2:
        name = "day after tomorrow"
    elif 3 <= day_offset <= 6:
        name = f"{date.strftime('%A')}"
    elif -6 <= day_offset <= -3:
        name = f"{-day_offset} days ago"
    else:
        return iso
    return f'{name} ({iso})'


def get_task_identifier_prefix(day_offset):
    """Return the task identifier prefix for the given day offset.
    For today, no prefix is returned. For tomorrow, 'a' is returned. For the day after tomorrow, 'b' is returned.
    For the day before today, '-a' is returned. For the day before yesterday, '-b' is returned.

    For other days, the trend continues, and after 'z', the alphabet repeats with 'aa', 'ab', 'ac', and so on.
    """

    def num_to_alpha(n):
        assert n >= 0, 'n must be non-negative'
        # 'a', 'b', 'c', 'd', 'e', 'f', 'g'... 'z', 'aa', 'ab', 'ac', 'ad', 'ae', 'af', 'ag'...
        alpha = 'abcdefghijklmnopqrstuvwxyz'
        """Convert a number to a base-26 alphabetic string."""
        if n < 26:
            return alpha[n]
        else:
            return num_to_alpha(n // 26 - 1) + alpha[n % 26]

    if day_offset == 0:
        return ''
    else:
        sign = '-' if day_offset < 0 else ''
        return sign + num_to_alpha(abs(day_offset) - 1)
