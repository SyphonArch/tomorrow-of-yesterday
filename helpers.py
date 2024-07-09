import task_manager as tm
import database


def get_task_string(task_id):
    """Return the string representation of the task with the given ID."""
    task = tm.get_task(task_id)
    if task is None:
        return f'[#{task_id}: Task not found]'
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
