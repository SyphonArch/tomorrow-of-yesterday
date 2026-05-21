import cmd
import task_manager as tm
import database
import sys
import datetime
import json
import re
import unicodedata
from decimal import Decimal
import helpers
import termcolor

try:
    import readline

    # Make auto-completion work on Mac OS X.
    if 'libedit' in readline.__doc__:
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")
except ImportError:
    print("No readline support; Autocomplete disabled.", file=sys.stderr)


class ToYCLI(cmd.Cmd):
    prompt = '##############################################\nToY> '

    no_shortcuts = ['setup', 'EOF', 'remove']  # Commands that should not have shortcuts

    def __init__(self):
        super().__init__()
        self.shortcuts = self.generate_shortcuts()
        self.bindings = {}
        database.setup_database()  # Create the database if it doesn't exist
        self.intro = self.build_intro()
        with open('config.json', 'r') as f:
            self.config = json.load(f)

    def build_intro(self):
        welcome_message = database.get_setting('welcome_message')
        lines = welcome_message.splitlines()
        width = max(46, *(display_width(line) for line in lines))
        border = '#' * width
        centered_lines = [center_display(line, width) for line in lines]
        return '\n'.join([border, *centered_lines, border]) + '\n'

    def cmdloop(self, intro=None):
        """Override the cmdloop method to list tasks at startup.
        This is necessary so that the intro message is printed before the list of tasks."""
        if intro is None:
            intro = self.intro
        print(intro)

        self.do_list('')  # List tasks

        try:
            super().cmdloop(intro='')
        except KeyboardInterrupt:
            self.do_quit('')

    def generate_shortcuts(self):
        """Generate shortcuts for all commands."""
        commands = [name[3:] for name in dir(self) if name.startswith('do_')]
        shortcuts = {}
        for command in commands:
            if command in self.no_shortcuts:
                continue
            if command[0] in shortcuts:
                raise ValueError(f"Command '{command}' has the same shortcut as '{shortcuts[command[0]]}'.")
            shortcuts[command[0]] = command
        return shortcuts

    def get_task_id(self, arg):
        """Get the task ID from the argument."""
        if not arg:
            return None
        if arg[0] == '#':
            return int(arg[1:])
        else:
            if arg in self.bindings:
                return self.bindings[arg]
            else:
                return None

    def precmd(self, line):
        self.clean_bindings()  # Remove any bindings that are no longer valid
        # Split the line into command and argument
        parts = line.split()
        if parts:
            # If the command is in the shortcuts dictionary, replace it with the full command
            if parts[0] in self.shortcuts:
                parts[0] = self.shortcuts[parts[0]]
                line = ' '.join(parts)
        return line

    def do_list(self, arg):
        """List tasks: list <offset_start> <optional:offset_end>, list w, or simply list"""
        if arg:
            args = arg.split()
            if args == ['w']:
                offset_start, offset_end = -6, 0
            elif len(args) not in (1, 2):
                print('Usage: list <offset_start> <optional:offset_end> or list w')
                return
            else:
                try:
                    if len(args) == 1:
                        offset_start = int(args[0])
                        offset_end = offset_start
                    else:
                        offset_start, offset_end = map(int, args)
                except ValueError:
                    print('Usage: list <offset_start> <optional:offset_end> or list w')
                    return
        else:
            offset_start, offset_end = self.config['default_day_offset_start'], self.config['default_day_offset_end']
        if offset_start > offset_end:
            print('offset_start must be less than or equal to offset_end')
            return

        bindings = {}

        def priority_stars(task) -> str:
            priority = task['priority'] if 'priority' in task.keys() else 0
            if priority <= 0:
                return ''
            return "⭐" * int(priority)

        # --- tiny, non-memoized helpers ---
        def scheduled_dates(task_id: int):
            """All scheduled dates for this task, as date objects (may be empty)."""
            evts = tm.get_schedule_events(task_id)
            return [datetime.date.fromisoformat(e['scheduled_date']) for e in evts]

        def latest_scheduled_date(task_id: int):
            """Most recent scheduled date by event id, or None if the task was never scheduled."""
            evts = tm.get_schedule_events(task_id)
            if not evts:
                return None
            latest = max(evts, key=lambda e: e['event_id'])
            return datetime.date.fromisoformat(latest['scheduled_date'])

        def resched_marker(task_id: int) -> str:
            """Dark-grey '(resched N, age Xd)' only if rescheduled >= 1, age from earliest scheduled date."""
            ds = scheduled_dates(task_id)
            resched = max(0, len(ds) - 1)
            if resched == 0:
                return ""
            earliest = min(ds)
            age_days = (datetime.date.today() - earliest).days
            txt = f"(resched {resched}" + (f", age {age_days}d)" if age_days > 0 else ")")
            return termcolor.colored(txt, 'dark_grey')

        def priority_and_resched(task, task_id: int) -> str:
            stars = priority_stars(task)
            marker = resched_marker(task_id)
            if stars and marker:
                return f' {stars} {marker}'
            if stars:
                return f' {stars}'
            if marker:
                return f' {marker}'
            return ''

        def duration_string(duration: int) -> str:
            if duration == 0:
                return '0m'
            return helpers.format_duration(duration)

        def day_duration_marker(tasks) -> str:
            active_tasks = [task for task in tasks if task['status'] != 'irrelevant']
            if not active_tasks:
                return ''
            completed_duration = sum(task['duration'] or 0 for task in active_tasks if task['status'] == 'completed')
            scheduled_duration = sum(task['duration'] or 0 for task in active_tasks)
            completed_count = sum(1 for task in active_tasks if task['status'] == 'completed')
            if completed_count == 0:
                return termcolor.colored(f'[{duration_string(scheduled_duration)}]', 'magenta')
            if completed_count == len(active_tasks):
                return termcolor.colored(f'[{duration_string(scheduled_duration)}]', 'green')
            return termcolor.colored(
                f'[{duration_string(completed_duration)}/{duration_string(scheduled_duration)}]',
                'magenta',
            )
        # -----------------------------------

        today = datetime.date.today()

        # Check for overdue tasks and tasks that are too far in the future
        cutoff_date_start = today + datetime.timedelta(days=offset_start)
        cutoff_date_end = today + datetime.timedelta(days=offset_end)
        unfinished_tasks = tm.get_unfinished_tasks()
        overdue_tasks = []
        unlisted_tasks = []
        for task in unfinished_tasks:
            scheduled_date = datetime.date.fromisoformat(task['scheduled_date'])
            if scheduled_date < cutoff_date_start:
                overdue_tasks.append(task)
            elif scheduled_date > cutoff_date_end:
                unlisted_tasks.append(task)

        # Sort by scheduled date, then priority (desc), then id for stability
        overdue_tasks = sorted(
            overdue_tasks,
            key=lambda x: (x['scheduled_date'], -x['priority'], x['id'])
        )
        unlisted_tasks = sorted(
            unlisted_tasks,
            key=lambda x: (x['scheduled_date'], -x['priority'], x['id'])
        )

        # Print overdue tasks
        if overdue_tasks:
            print(termcolor.colored('>> Unfinished tasks from previous days <<', 'light_red'))
            for i, task in enumerate(overdue_tasks):
                task_id = task['id']
                base = helpers.get_task_string(task_id)
                task_identifier = f'!{i}'
                bindings[task_identifier] = task_id
                scheduled_date = datetime.date.fromisoformat(task['scheduled_date'])
                task_string_colored = termcolor.colored(base, 'light_red') + priority_and_resched(task, task_id)
                print(f'{task_identifier}. {task_string_colored} | '
                      f'{helpers.get_day_string(today, scheduled_date)}')
            print()

        # Print tasks for each day in the list
        for day_offset in range(offset_start, offset_end + 1):
            date = today + datetime.timedelta(days=day_offset)
            day_string = helpers.get_day_string(today, date)
            tasks = tm.get_tasks_for_date(date)
            marker = day_duration_marker(tasks)
            marker_suffix = f' {marker}' if marker else ''
            print(f'// {day_string}{marker_suffix} //')
            print('-' * 40)

            if not tasks:
                print('Nothing to do!\n')
            else:
                # Sort: scheduled → irrelevant → completed (your original order)
                tasks = sorted(
                    tasks,
                    key=lambda x: (
                        0 if x['status'] == 'scheduled' else 1 if x['status'] == 'irrelevant' else 2,
                        -x['priority'],
                        x['id']
                    )
                )

                remaining_scheduled_task_count = 0

                for i, task in enumerate(tasks):
                    task_id = task['id']
                    base = helpers.get_task_string(task_id)
                    task_identifier = helpers.get_task_identifier_prefix(day_offset) + str(i)
                    bindings[task_identifier] = task_id
                    status = f'[{task["status"]}]' if task['status'] != 'scheduled' else ''
                    if task['status'] == 'scheduled':
                        remaining_scheduled_task_count += 1
                        colored = termcolor.colored(base, 'magenta') + priority_and_resched(task, task_id)
                    elif task['status'] == 'completed':
                        colored = termcolor.colored(base, 'green') + priority_and_resched(task, task_id)
                    else:
                        assert task['status'] == 'irrelevant'
                        colored = termcolor.colored(base, 'blue') + priority_and_resched(task, task_id)
                    status_suffix = f' {status}' if status else ''
                    print(f'{task_identifier}. {colored}{status_suffix}')
                if remaining_scheduled_task_count == 0:
                    print(termcolor.colored('~ You have completed the day! Yay! >.< ~', 'green', 'on_black'))

            # --- Rescheduled tasks footer for this day ---
            # Tasks that ever had a scheduled event on this date (dedup by id)
            ever_on_date_ids = {t['id'] for t in tm.get_all_tasks_ever_scheduled_to_date(date)}

            # Show only when the task currently sits after a day it was previously scheduled for.
            rescheduled_tasks = []
            for tid in ever_on_date_ids:
                task = tm.get_task(tid)
                if task['scheduled_date'] is None:
                    effective_scheduled_date = latest_scheduled_date(tid)
                    should_show = effective_scheduled_date is not None and effective_scheduled_date >= date
                else:
                    effective_scheduled_date = datetime.date.fromisoformat(task['scheduled_date'])
                    should_show = effective_scheduled_date > date
                if should_show:
                    rescheduled_tasks.append(task)

            if rescheduled_tasks:
                print(termcolor.colored('-- Rescheduled tasks --', 'dark_grey'))
                for i, task in enumerate(
                    sorted(
                        rescheduled_tasks,
                        key=lambda x: (
                            latest_scheduled_date(x['id']).isoformat(),
                            -x['priority'],
                            x['id'],
                        )
                    )
                ):
                    task_id = task['id']
                    base = helpers.get_task_string(task_id)
                    if task['status'] in ('scheduled', 'completed'):
                        date_string_or_buffered = f"{task['status']} {task['scheduled_date']}"
                    else:
                        date_string_or_buffered = task['status']
                    line_left = termcolor.colored(base, 'dark_grey')
                    line_right = termcolor.colored(f' | {date_string_or_buffered}', 'dark_grey')
                    print(line_left + line_right)
            print()

        # Print unlisted tasks
        if unlisted_tasks:
            print(termcolor.colored('>> Tasks further in the future <<', 'cyan'))
            for i, task in enumerate(unlisted_tasks):
                task_id = task['id']
                base = helpers.get_task_string(task_id)
                task_identifier = f'+{i}'
                bindings[task_identifier] = task_id
                scheduled_date = datetime.date.fromisoformat(task['scheduled_date'])
                task_string_colored = termcolor.colored(base, 'cyan') + priority_and_resched(task, task_id)
                print(f'{task_identifier}. {task_string_colored} | '
                      f'{helpers.get_day_string(today, scheduled_date)}')
            print()

        # Print buffered tasks
        buffered_tasks = tm.get_buffered_tasks()
        if buffered_tasks:
            print(termcolor.colored('))) Buffered tasks (((', 'yellow'))
            for i, task in enumerate(buffered_tasks):
                task_id = task['id']
                base = helpers.get_task_string(task_id)
                task_identifier = f'*{i}'
                bindings[task_identifier] = task_id
                task_string_colored = termcolor.colored(base, 'yellow') + priority_and_resched(task, task_id)
                print(f'{task_identifier}. {task_string_colored}')
            print()

        self.bindings = bindings

    def do_add(self, arg):
        """Add a new task. Usage: add <task_description>"""
        if arg == '':
            print('Usage: add <task_description>\n')
            return

        while True:
            schedule_choice = safe_input("Enter the date to schedule the task (h for hints): ")
            if schedule_choice is None:
                return
            schedule_choice = schedule_choice.strip()
            if schedule_choice.lower() == 'h':
                print_date_format_hints()
                continue
            date_or_buffer = parse_date_or_buffer(schedule_choice)
            if date_or_buffer is not None:
                break
            else:
                print('Invalid date format. Please try again or enter "h" for hints.')

        while True:
            duration_input = safe_input("Duration [optional, h]: ")
            if duration_input is None:
                return
            duration_input = duration_input.strip()
            if duration_input == '':
                duration = None
                break
            if duration_input.lower() == 'h':
                print_duration_format_hints('blank_no_duration')
                continue
            duration = parse_duration(duration_input)
            if duration is not None:
                break
            else:
                print('Invalid duration. Use h for hints.')

        task_description = f'{helpers.format_duration(duration)} | {arg}' if duration else arg

        # Confirm the date or buffer before creating the task
        if date_or_buffer == 'buffer':
            print(f'Add task "{task_description}" to buffer?')
        else:
            date = date_or_buffer
            print(f'Schedule task "{task_description}" to '
                  f'{helpers.get_day_string(datetime.date.today(), date)}?')

        confirmation = safe_input('Press <enter> to confirm or Ctrl-C to abort.')
        if confirmation is None:
            return

        # Only create the task after a valid date or buffer is confirmed
        task_id = tm.create_task(arg, duration=duration)

        if date_or_buffer == 'buffer':
            print(f'Task {helpers.get_task_string(task_id)} left in buffer.')
        else:
            tm.schedule_task(task_id, date)
            print(f'Task {helpers.get_task_string(task_id)} scheduled to '
                  f'{helpers.get_day_string(datetime.date.today(), date)}.')

    def do_priority(self, arg):
        """Set priority for a task: priority <task_identifier> <priority>"""
        args = arg.split()
        if len(args) != 2:
            print('Usage: priority <task_identifier> <priority>\n')
            return

        task_id = self.get_task_id(args[0])
        if task_id is None:
            print(f"Invalid task identifier '{args[0]}'\n")
            return

        try:
            priority = int(args[1])
            if priority < 0:
                raise ValueError
        except ValueError:
            print('Priority must be a non-negative integer.\n')
            return

        tm.set_priority(task_id, priority)
        stars = '⭐' * priority
        print(f'Priority for {helpers.get_task_string(task_id)} set to {stars if stars else "no stars"}.\n')

    def do_duration(self, arg):
        """Set duration for a task: duration <task_identifier> <duration|clear>"""
        args = arg.split(maxsplit=1)
        if len(args) != 2:
            print('Usage: duration <task_identifier> <duration|clear>\n')
            return

        task_id = self.get_task_id(args[0])
        if task_id is None:
            print(f"Invalid task identifier '{args[0]}'\n")
            return

        duration_input = args[1].strip()
        if duration_input.lower() in ('clear', 'none'):
            duration = None
        else:
            duration = parse_duration(duration_input)
            if duration is None:
                print('Invalid duration. Examples: 4.5, 30m, 1h30m.\n')
                return

        tm.set_duration(task_id, duration)
        if duration is None:
            print(f'Duration cleared for {helpers.get_task_string(task_id)}.\n')
        else:
            print(f'Duration for {helpers.get_task_string(task_id)} set to {helpers.format_duration(duration)}.\n')

    def do_completed(self, arg):
        """Mark task as completed: completed <task_identifier>"""
        task_id = self.get_task_id(arg)
        if task_id is None:
            print(f"Invalid task identifier '{arg}'\n")
            return

        # Check if the task is scheduled
        task = tm.get_task(task_id)
        if task['status'] != 'scheduled':
            print(f'Task {helpers.get_task_string(task_id)} needs to be scheduled to be marked as done.\n')
            return

        confirmation = safe_input(f'Mark {helpers.get_task_string(task_id)} done? [enter/Ctrl-C] ')
        if confirmation is None:
            return

        tm.mark_task_completed(task_id)
        print(f'Task {helpers.get_task_string(task_id)} marked as done.\n')

    def do_irrelevant(self, arg):
        """Mark task as irrelevant: irrelevant <task_identifier>"""
        task_id = self.get_task_id(arg)
        if task_id is None:
            print(f"Invalid task identifier '{arg}'\n")
            return

        # Check if the task is already irrelevant
        task = tm.get_task(task_id)
        if task['status'] == 'irrelevant':
            print(f'Task {helpers.get_task_string(task_id)} already marked as irrelevant.\n')
            return

        confirmation = safe_input(f'Mark {helpers.get_task_string(task_id)} as irrelevant?'
                                       '\nPress <enter> to continue or Ctrl-C to abort.')
        if confirmation is None:
            return

        tm.mark_task_irrelevant(task_id)
        print(f'Task {helpers.get_task_string(task_id)} marked as irrelevant.\n')

    def do_buffer(self, arg):
        """Move task to buffer: buffer <task_identifier>"""
        task_id = self.get_task_id(arg)
        if task_id is None:
            print(f"Invalid task identifier '{arg}'\n")
            return

        # Check if the task is already in the buffer
        task = tm.get_task(task_id)
        if task['status'] == 'buffered':
            print(f'Task {helpers.get_task_string(task_id)} already in buffer.\n')
            return

        # Confirm
        print(f'Move task {helpers.get_task_string(task_id)} to buffer?')
        confirmation = safe_input('Press <enter> to continue or Ctrl-C to abort.')
        if confirmation is None:
            return

        tm.buffer_task(task_id)
        print(f'Task {helpers.get_task_string(task_id)} moved to buffer.\n')

    def do_remove(self, arg):
        """Remove a task: remove <task_identifier>"""
        task_id = self.get_task_id(arg)
        if task_id is None:
            print(f"Invalid task identifier '{arg}'\n")
            return
        task_string = helpers.get_task_string(task_id)  # Get the task string before removing the task

        # Confirm the task removal
        print('Warning: This action cannot be undone! Only remove a task if it was added by mistake.')
        print('If you want to remove a task that is no longer relevant, mark it as irrelevant instead.')
        print(f'Remove task {task_string}?')
        confirmation = safe_input('Press <enter> to continue or Ctrl-C to abort.')
        if confirmation is None:
            return

        tm.remove_task(task_id)
        print(f'Task {task_string} removed.\n')

    def do_schedule(self, arg):
        """Schedule a task: schedule <task_identifier>"""
        task_id = self.get_task_id(arg)
        if task_id is None:
            print(f"Invalid task identifier '{arg}'\n")
            return

        while True:
            date_input = safe_input("Enter the date to reschedule the task (h for hints): ")
            if date_input is None:
                return
            date_input = date_input.strip()
            if date_input.lower() == 'h':
                print_date_format_hints()
                continue
            date_or_buffer = parse_date_or_buffer(date_input)
            if date_or_buffer is not None:
                break
            else:
                print('Invalid date format. Please try again or enter "h" for hints.')

        # Check original scheduled_date
        task = tm.get_task(task_id)
        original_date = datetime.date.fromisoformat(task['scheduled_date']) \
            if task['scheduled_date'] is not None else None

        if date_or_buffer == 'buffer':
            print(f'Move task {helpers.get_task_string(task_id)} to buffer?')
        else:
            date = date_or_buffer
            if date == original_date and task['status'] == 'scheduled':
                print(f'Task {helpers.get_task_string(task_id)} is already scheduled to '
                      f'{helpers.get_day_string(datetime.date.today(), date)}.\n')
                return
            print(f'Schedule task {helpers.get_task_string(task_id)} to '
                  f'{helpers.get_day_string(datetime.date.today(), date)}?')

        confirmation = safe_input('Press <enter> to confirm or Ctrl-C to abort.')
        if confirmation is None:
            return

        if date_or_buffer == 'buffer':
            tm.buffer_task(task_id)
            print(f'Task {helpers.get_task_string(task_id)} moved to buffer.\n')
        else:
            tm.schedule_task(task_id, date)
            print(f'Task {helpers.get_task_string(task_id)} scheduled to '
                  f'{helpers.get_day_string(datetime.date.today(), date)}.\n')

    def do_evaluate(self, arg):
        """Evaluate how well I did in the given interval: evaluate <offset_start> <offset_end> or evaluate w"""
        args = arg.split()
        if args == ['w']:
            offset_start, offset_end = -6, 0
        elif len(args) != 2:
            print('Usage: evaluate <offset_start> <offset_end> or evaluate w\n')
            return
        else:
            try:
                offset_start, offset_end = map(int, args)
            except ValueError:
                print('Usage: evaluate <offset_start> <offset_end> or evaluate w\n')
                return
        if offset_start > offset_end:
            print('offset_start must be less than or equal to offset_end')
            return

        today = datetime.date.today()

        scheduled_count = 0
        completed_that_day_count = 0
        completed_next_day_count = 0
        completed_another_day_count = 0
        made_irrelevant_count = 0
        made_buffered_count = 0
        incomplete_count = 0
        scheduled_duration = 0
        completed_that_day_duration = 0
        completed_next_day_duration = 0
        completed_another_day_duration = 0
        made_irrelevant_duration = 0
        made_buffered_duration = 0
        incomplete_duration = 0

        all_tasks = {}

        # Collect all tasks that were ever scheduled to the given interval
        # Don't count the same task multiple times
        for day_offset in range(offset_start, offset_end + 1):
            date = today + datetime.timedelta(days=day_offset)
            tasks = tm.get_all_tasks_ever_scheduled_to_date(date)
            for task in tasks:
                if task['id'] not in all_tasks:
                    all_tasks[task['id']] = task

        # Evaluate the tasks
        for task_id, task in all_tasks.items():
            scheduled_count += 1
            duration = task['duration'] or 0
            scheduled_duration += duration
            if task['status'] == 'irrelevant':
                made_irrelevant_count += 1
                made_irrelevant_duration += duration
            elif task['status'] == 'buffered':
                made_buffered_count += 1
                made_buffered_duration += duration
            elif task['status'] == 'scheduled':
                incomplete_count += 1
                incomplete_duration += duration
            else:
                assert task['status'] == 'completed', f"Task {task['id']} has invalid status {task['status']}"
                # Get the first scheduled date
                task_schedule_events = tm.get_schedule_events(task_id)
                task_schedule_events.sort(key=lambda x: x['scheduled_date'])
                first_scheduled_date = datetime.date.fromisoformat(task_schedule_events[0]['scheduled_date'])
                # Check when the final scheduled date was
                scheduled_date = datetime.date.fromisoformat(task['scheduled_date'])
                diff = scheduled_date - first_scheduled_date
                if diff.days == 0:
                    completed_that_day_count += 1
                    completed_that_day_duration += duration
                elif diff.days == 1:
                    completed_next_day_count += 1
                    completed_next_day_duration += duration
                else:
                    completed_another_day_count += 1
                    completed_another_day_duration += duration

        print(f'Evaluation for the interval {offset_start} to {offset_end} days from today:')
        print()
        print(f'Total number of tasks scheduled: {scheduled_count:>6}')

        if scheduled_count == 0:
            print("No tasks scheduled in the interval.")
        else:
            completed_count = completed_that_day_count + completed_next_day_count + completed_another_day_count
            completed_duration = (
                completed_that_day_duration
                + completed_next_day_duration
                + completed_another_day_duration
            )

            print()
            print(f'Completed total:                 {completed_count:>6} '
                  f'({(completed_count / scheduled_count * 100):.0f}%)')
            print(f'Completed on first day:          {completed_that_day_count:>6} '
                  f'({(completed_that_day_count / scheduled_count * 100):.0f}%)')
            print(f'Completed on next day:           {completed_next_day_count:>6} '
                  f'({(completed_next_day_count / scheduled_count * 100):.0f}%)')
            print(f'Completed on another day:        {completed_another_day_count:>6} '
                  f'({(completed_another_day_count / scheduled_count * 100):.0f}%)')
            print(f'Made irrelevant:                 {made_irrelevant_count:>6} '
                  f'({(made_irrelevant_count / scheduled_count * 100):.0f}%)')
            print(f'Buffered:                        {made_buffered_count:>6} '
                  f'({(made_buffered_count / scheduled_count * 100):.0f}%)')
            print(f'Incomplete:                      {incomplete_count:>6} '
                  f'({(incomplete_count / scheduled_count * 100):.0f}%)')
            print()

            def format_duration_or_zero(duration: int) -> str:
                if duration == 0:
                    return '0m'
                return helpers.format_duration(duration)

            def duration_percent(duration: int) -> str:
                if scheduled_duration == 0:
                    return 'n/a'
                return f'{(duration / scheduled_duration * 100):.0f}%'

            print(f'Total duration scheduled:        {format_duration_or_zero(scheduled_duration):>6}')
            print()
            print(f'Completed total:                 {format_duration_or_zero(completed_duration):>6} '
                  f'({duration_percent(completed_duration)})')
            print(f'Completed on first day:          {format_duration_or_zero(completed_that_day_duration):>6} '
                  f'({duration_percent(completed_that_day_duration)})')
            print(f'Completed on next day:           {format_duration_or_zero(completed_next_day_duration):>6} '
                  f'({duration_percent(completed_next_day_duration)})')
            print(f'Completed on another day:        {format_duration_or_zero(completed_another_day_duration):>6} '
                  f'({duration_percent(completed_another_day_duration)})')
            print(f'Made irrelevant:                 {format_duration_or_zero(made_irrelevant_duration):>6} '
                  f'({duration_percent(made_irrelevant_duration)})')
            print(f'Buffered:                        {format_duration_or_zero(made_buffered_duration):>6} '
                  f'({duration_percent(made_buffered_duration)})')
            print(f'Incomplete:                      {format_duration_or_zero(incomplete_duration):>6} '
                  f'({duration_percent(incomplete_duration)})')

    def do_task(self, arg):
        """Get information about a task: task <task_identifier>"""
        if arg == '':
            print('Usage: task <task_identifier>\n')
            return

        task_id = self.get_task_id(arg)

        if task_id is None:
            print(f"Invalid task identifier '{arg}'\n")
            return

        task = tm.get_task(task_id)
        assert task is not None, f"Task {task_id} not found"
        task_string = helpers.get_task_string(task_id)

        print(f'Evaluating task {task_string}')
        print(f'    Created on: {task["created_date"]:>20}')
        print(f'    Status: {task["status"]:>24}')
        print(f'    Priority: {task["priority"]:>22}')
        duration = task['duration'] if 'duration' in task.keys() else None
        duration_string = helpers.format_duration(duration) if duration else 'none'
        print(f'    Duration: {duration_string:>22}')
        if task['status'] != 'buffered':
            print(f'    Scheduled for: {task["scheduled_date"]:>17}')

        print()
        scheduling_events = tm.get_schedule_events(task_id)
        print(f'    Total times scheduled: {len(scheduling_events)}')
        for i, event in enumerate(scheduling_events):
            date = datetime.date.fromisoformat(event['scheduled_date'])
            print(f'        {i + 1}. {helpers.get_day_string(datetime.date.today(), date)}')

        print()

    def do_welcome(self, arg):
        """View or set the welcome message: welcome <message>"""
        message = arg.strip()
        if not message:
            print(f'Welcome message: {database.get_setting("welcome_message")}\n')
            return

        database.set_setting('welcome_message', message)
        self.intro = self.build_intro()
        print(f'Welcome message set to: {message}\n')

    def do_modify_description(self, arg):
        """Modify a task's description and duration: modify <task_identifier>"""
        task_identifier = arg

        task_id = self.get_task_id(task_identifier)
        if task_id is None:
            print(f"Invalid task identifier '{task_identifier}'\n")
            return

        print(f'Modifying task {helpers.get_task_string(task_id)}...')
        new_description = safe_input('Description [keep]: ')
        if new_description is None:
            return
        new_description = new_description.strip()

        while True:
            new_duration = safe_input('Duration [keep/clear/h]: ')
            if new_duration is None:
                return
            new_duration = new_duration.strip()
            if new_duration == '':
                duration = tm.get_task(task_id)['duration']
                break
            if new_duration.lower() == 'h':
                print_duration_format_hints('blank_keep')
                continue
            if new_duration.lower() in ('clear', 'none'):
                duration = None
                break
            duration = parse_duration(new_duration)
            if duration is not None:
                break
            print('Invalid duration. Use h for hints.')

        if new_description:
            tm.modify_description(task_id, new_description)
        tm.set_duration(task_id, duration)
        print(f'Task modified to {helpers.get_task_string(task_id)}.\n')

    def clean_bindings(self):
        """Remove bindings that are no longer valid."""
        # Use double loop to avoid modifying the dictionary while iterating over it
        to_remove = []
        for task_identifier, task_id in self.bindings.items():
            if tm.get_task(task_id) is None:
                to_remove.append(task_identifier)
        for task_identifier in to_remove:
            del self.bindings[task_identifier]

    def do_quit(self, arg):
        """Quit the task manager"""
        return self.terminate()

    def do_EOF(self, arg):
        """Quit the task manager"""
        return self.terminate()

    def terminate(self):
        """Terminate the task manager"""
        print('\nTill Tomorrow!')
        return True


def print_date_format_hints():
    """Prints the supported date formats."""
    print("Supported date formats:")
    print(" - 'buffer' or 'b' to leave in buffer")
    print(" - [T]oday or to[M]orrow")
    print(" - Integer offset from today (e.g., '3' or '-1')")
    print(" - Date in 'YYYY-MM-DD' format")
    print(" - Date in 'MM-DD' format (next occurrence, including today)")
    print(" - Day of the week (first three letters, e.g., 'mon', 'tue')")


def print_duration_format_hints(blank_behavior):
    """Prints the supported duration formats."""
    assert blank_behavior in ('blank_keep', 'blank_no_duration'), 'invalid blank behavior'
    print("Supported duration formats:")
    if blank_behavior == 'blank_keep':
        print(" - Leave blank to keep the current duration")
        print(" - Enter 'clear' to remove duration")
    else:
        print(" - Leave blank for no duration")
    print(" - Bare numbers are hours: '4' or '4.5'")
    print(" - Minutes: '30m' or '100m'")
    print(" - Hours: '1h', '1.5h', or '2h'")
    print(" - Hours and minutes: '1h30m' or '2h5m'")


def display_width(text):
    """Approximate terminal display width for centered intro text."""
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ('F', 'W') else 1
    return width


def center_display(text, width):
    """Center text using display-cell width instead of Python character count."""
    padding = max(0, width - display_width(text))
    left_padding = padding // 2
    right_padding = padding - left_padding
    return (' ' * left_padding) + text + (' ' * right_padding)


def safe_input(prompt):
    """Input method that handles interrupted or unavailable terminal input."""
    try:
        return input(prompt)
    except KeyboardInterrupt:
        print('\nOperation cancelled.\n')
        return None
    except (EOFError, OSError):
        print('\nInput stream closed; exiting.\n')
        raise SystemExit(0)


def parse_duration(duration_input):
    """Parse a duration input and return integer minutes."""
    duration_input = duration_input.strip().lower()
    decimal_hour_match = re.fullmatch(r'(\d+(?:\.\d+)?)(?:h)?', duration_input)
    if decimal_hour_match:
        hours = Decimal(decimal_hour_match.group(1))
        minutes = hours * Decimal(60)
        if minutes <= 0 or minutes != minutes.to_integral_value():
            return None
        return int(minutes)

    match = re.fullmatch(r'(?:(\d+)h)?(?:(\d+)m)?', duration_input)
    if not match:
        return None

    hours_text, minutes_text = match.groups()
    if hours_text is None and minutes_text is None:
        return None

    hours = int(hours_text) if hours_text is not None else 0
    minutes = int(minutes_text) if minutes_text is not None else 0
    total_minutes = hours * 60 + minutes
    if total_minutes <= 0:
        return None
    return total_minutes


def parse_date_or_buffer(date_input):
    """Parses a date input and returns a date object or 'buffer'.
    Returns None if the input is invalid.

    date_input can be:
    - 'buffer' or 'b' (case-insensitive) to indicate buffering
    - 't' or 'm' for today or tomorrow
    - An integer offset from today (e.g., '3' or '-1')
    - A date in 'YYYY-MM-DD' format
    - A date in 'MM-DD' format (assumed to be the next occurrence, including today)
    - A day of the week (first three letters, case-insensitive)
    """
    date_input = date_input.strip().lower()
    if date_input in ['buffer', 'b']:
        return 'buffer'
    else:
        return parse_date(date_input)


def parse_date(date_input):
    """Parses a date input and returns a date object.
    Returns None if the input is invalid.

    date_input can be:
    - 't' or 'm' for today or tomorrow
    - An integer offset from today (e.g., '3' or '-1')
    - A date in 'YYYY-MM-DD' format
    - A date in 'MM-DD' format (assumed to be the next occurrence, including today)
    - A day of the week (first three letters, case-insensitive)
    """
    today = datetime.date.today()
    date_input = date_input.strip().lower()

    # Check for 'today' or 'tomorrow'
    if date_input in ['t']:
        return today
    if date_input in ['m']:
        return today + datetime.timedelta(days=1)

    # Check if date_input is an integer offset
    try:
        days_offset = int(date_input)
        return today + datetime.timedelta(days=days_offset)
    except ValueError:
        pass

    # Check if date_input is a day of the week (first three letters)
    weekdays = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    day_abbrev = date_input[:3].lower()
    if day_abbrev in weekdays:
        target_weekday = weekdays.index(day_abbrev)
        current_weekday = today.weekday()  # 0 = Monday, 6 = Sunday
        days_ahead = (target_weekday - current_weekday + 7) % 7
        if days_ahead == 0:
            days_ahead = 7  # Go to next week
        return today + datetime.timedelta(days=days_ahead)

    # Check if date_input is in MM-DD format
    try:
        parts = date_input.split('-')
        if len(parts) != 2:
            raise ValueError
        month, day = map(int, parts)
        year = today.year
        date_candidate = datetime.date(year, month, day)
        if date_candidate < today:
            date_candidate = datetime.date(year + 1, month, day)
        return date_candidate
    except ValueError:
        pass

    # Check if date_input is in YYYY-MM-DD format
    try:
        date_candidate = datetime.datetime.strptime(date_input, '%Y-%m-%d').date()
        return date_candidate
    except ValueError:
        pass

    # If none of the formats match, return None to indicate invalid date
    return None


if __name__ == '__main__':
    app = ToYCLI()
    sys.exit(app.cmdloop())
