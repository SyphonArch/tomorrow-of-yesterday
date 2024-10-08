import cmd
import task_manager as tm
import database
import sys
import datetime
import json
import helpers
import termcolor
import signal

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
    intro = """##############################################
Welcome to ToY, your personal task scheduler!
Type 'help' for a list of commands.
##############################################
"""
    prompt = '==============================================\nToY> '

    no_shortcuts = ['setup', 'EOF', 'remove']  # Commands that should not have shortcuts

    def __init__(self):
        super().__init__()
        self.shortcuts = self.generate_shortcuts()
        self.bindings = {}
        database.setup_database()  # Create the database if it doesn't exist
        with open('config.json', 'r') as f:
            self.config = json.load(f)

    def cmdloop(self, intro=None):
        """Override the cmdloop method to list tasks at startup.
        This is necessary so that the intro message is printed before the list of tasks."""
        if intro is None:
            intro = self.intro
        print(intro)

        self.do_list('')  # List tasks

        ret_val = super().cmdloop(intro='')
        return ret_val

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
        """List tasks: list <offset_start> <optional:offset_end> or simply list"""
        if arg:
            args = arg.split()
            if len(args) not in (1, 2):
                print('Usage: list <offset_start> <optional:offset_end>')
                return
            try:
                if len(args) == 1:
                    offset_start = int(args[0])
                    offset_end = offset_start
                else:
                    offset_start, offset_end = map(int, args)
            except ValueError:
                print('Usage: list <offset_start> <optional:offset_end>')
                return
        else:
            offset_start, offset_end = self.config['default_day_offset_start'], self.config['default_day_offset_end']
        if offset_start > offset_end:
            print('offset_start must be less than or equal to offset_end')
            return

        bindings = {}

        today = datetime.date.today()

        # Check for overdue tasks and tasks that are too far in the future
        cuttoff_date_start = today + datetime.timedelta(days=offset_start)
        cuttoff_date_end = today + datetime.timedelta(days=offset_end)
        unfinished_tasks = tm.get_unfinished_tasks()
        overdue_tasks = []
        unlisted_tasks = []
        for task in unfinished_tasks:
            scheduled_date = datetime.date.fromisoformat(task['scheduled_date'])
            if scheduled_date < cuttoff_date_start:
                overdue_tasks.append(task)
            elif scheduled_date > cuttoff_date_end:
                unlisted_tasks.append(task)

        # Sort the tasks by scheduled date
        overdue_tasks = sorted(overdue_tasks, key=lambda x: x['scheduled_date'])
        unlisted_tasks = sorted(unlisted_tasks, key=lambda x: x['scheduled_date'])

        # Print overdue tasks
        if overdue_tasks:
            print(termcolor.colored('>> Unfinished tasks from previous days <<', 'light_red'))
            for i, task in enumerate(overdue_tasks):
                task_id = task['id']
                task_string = helpers.get_task_string(task_id)
                task_identifier = f'!{i}'
                bindings[task_identifier] = task_id
                scheduled_date = datetime.date.fromisoformat(task['scheduled_date'])
                task_string = termcolor.colored(task_string, 'light_red')
                print(f'{task_identifier}. {task_string} | {helpers.get_day_string(today, scheduled_date)}')
            print()

        # Print tasks for each day in the list
        for day_offset in range(offset_start, offset_end + 1):
            date = today + datetime.timedelta(days=day_offset)
            day_string = helpers.get_day_string(today, date)
            print(f'// {day_string} //')
            print('-' * 40)

            tasks = tm.get_tasks_for_date(date)
            if not tasks:
                print('Nothing to do!\n')
                continue

            # sort the tasks so that 'scheduled' tasks are before 'irrelevant' tasks, and 'completed' tasks are last
            tasks = sorted(tasks,
                           key=lambda x: 0 if x['status'] == 'scheduled' else 1 if x['status'] == 'irrelevant' else 2)

            remaining_scheduled_task_count = 0

            for i, task in enumerate(tasks):
                task_id = task['id']
                task_string = helpers.get_task_string(task_id)
                task_identifier = helpers.get_task_identifier_prefix(day_offset) + str(i)
                bindings[task_identifier] = task_id
                status = f'[{task["status"]}]' if task['status'] != 'scheduled' else ''
                # Color the task string based on the status
                if task['status'] == 'scheduled':
                    remaining_scheduled_task_count += 1
                    task_string = termcolor.colored(task_string, 'magenta')
                elif task['status'] == 'completed':
                    task_string = termcolor.colored(task_string, 'green')
                else:
                    assert task['status'] == 'irrelevant'
                    task_string = termcolor.colored(task_string, 'cyan')

                    task_string = termcolor.colored(task_string, 'yellow')
                print(f'{task_identifier}. {task_string} {status}')
            if remaining_scheduled_task_count == 0:
                print(termcolor.colored('~ You have completed the day! Yay! >.< ~', 'green', 'on_black'))

            potentially_rescheduled_tasks = tm.get_all_tasks_ever_scheduled_to_date(date)
            rescheduled_tasks = [task for task in potentially_rescheduled_tasks if
                                 task['scheduled_date'] != date.isoformat()]

            # Print rescheduled tasks
            if rescheduled_tasks:
                print(termcolor.colored('-- Rescheduled tasks --', 'dark_grey'))
                for i, task in enumerate(rescheduled_tasks):
                    task_id = task['id']
                    task_string = helpers.get_task_string(task_id)
                    if task['status'] in ('scheduled', 'completed'):
                        date_string_or_buffered = f"{task['status']} {task['scheduled_date']}"
                    else:
                        date_string_or_buffered = task['status']
                    print(termcolor.colored(f'{task_string} | {date_string_or_buffered}',
                                            'dark_grey'))
            print()

        # Print unlisted tasks
        if unlisted_tasks:
            print(termcolor.colored('>> Tasks further in the future <<', 'blue'))
            for i, task in enumerate(unlisted_tasks):
                task_id = task['id']
                task_string = helpers.get_task_string(task_id)
                task_identifier = f'+{i}'
                bindings[task_identifier] = task_id
                scheduled_date = datetime.date.fromisoformat(task['scheduled_date'])
                task_string = termcolor.colored(task_string, 'blue')
                print(f'{task_identifier}. {task_string} | {helpers.get_day_string(today, scheduled_date)}')
            print()

        # Print buffered tasks
        buffered_tasks = tm.get_buffered_tasks()
        if buffered_tasks:
            print(termcolor.colored('))) Buffered tasks (((', 'yellow'))
            for i, task in enumerate(buffered_tasks):
                task_id = task['id']
                task_string = helpers.get_task_string(task_id)
                task_identifier = f'*{i}'
                bindings[task_identifier] = task_id
                task_string = termcolor.colored(task_string, 'yellow')
                print(f'{task_identifier}. {task_string}')
            print()

        self.bindings = bindings

    def do_add(self, arg):
        """Add a new task. Usage: add <task_description>"""
        if arg == '':
            print('Usage: add <task_description>\n')
            return

        while True:
            schedule_choice = input(f'Schedule task to [T]oday, to[M]orrow, leave in [B]uffer, '
                                    f'specify a [D]ate or an [O]ffset from today?'
                                    f'\nYour choice: ').lower()
            if len(schedule_choice) == 1 and schedule_choice[0] in ('t', 'm', 'b', 'd', 'o'):
                break
            print('Invalid choice. Please try again.')

        if schedule_choice == 't':
            task_id = tm.create_task(arg)
            tm.schedule_task(task_id, datetime.date.today())
            print(f'Task {helpers.get_task_string(task_id)} scheduled to today.')
        elif schedule_choice == 'm':
            task_id = tm.create_task(arg)
            tm.schedule_task(task_id, datetime.date.today() + datetime.timedelta(days=1))
            print(f'Task {helpers.get_task_string(task_id)} scheduled to tomorrow.')
        elif schedule_choice == 'b':
            task_id = tm.create_task(arg)
            print(f'Task {helpers.get_task_string(task_id)} left in buffer.')
        elif schedule_choice == 'd':
            while True:
                try:
                    new_date = input('Enter the date (YYMMDD): ')
                    date = datetime.datetime.strptime(new_date, '%y%m%d').date()
                    task_id = tm.create_task(arg)
                    tm.schedule_task(task_id, date)
                    print(f'Task {helpers.get_task_string(task_id)} scheduled to {new_date}.')
                    break
                except ValueError:
                    print('Invalid date. Please try again.')
        elif schedule_choice == 'o':
            while True:
                try:
                    offset = int(input('Enter the offset from today: '))
                    date = datetime.date.today() + datetime.timedelta(days=offset)
                    task_id = tm.create_task(arg)
                    tm.schedule_task(task_id, date)
                    print(f'Task {helpers.get_task_string(task_id)} scheduled to '
                          f'{helpers.get_day_string(datetime.date.today(), date)}.')
                    break
                except ValueError:
                    print('Invalid offset. Please try again.')
        else:
            raise RuntimeError('This code should be unreachable.')
        print()

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

        input(f'Mark {helpers.get_task_string(task_id)} as done?'
              '\nPress <enter> to continue or Ctrl-C to abort.')
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

        input(f'Mark {helpers.get_task_string(task_id)} as irrelevant?'
              '\nPress <enter> to continue or Ctrl-C to abort.')

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
        input('Press <enter> to continue or Ctrl-C to abort.')

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
        input('Press <enter> to continue or Ctrl-C to abort.')

        tm.remove_task(task_id)
        print(f'Task {task_string} removed.\n')

    def do_schedule(self, arg):
        """Schedule a task: schedule <task_identifier> <new_date>"""
        parts = arg.split()
        if len(parts) != 2:
            print('Usage: schedule <task_identifier> <days_offset or new_date: YYYY-MM-DD>\n')
            return
        task_identifier, days_offset_or_date = parts
        today = datetime.date.today()
        if days_offset_or_date.isdigit() or days_offset_or_date[0] == '-' and days_offset_or_date[1:].isdigit():
            days_offset = int(days_offset_or_date)
            date = today + datetime.timedelta(days=days_offset)
        else:
            date = datetime.date.fromisoformat(days_offset_or_date)

        task_id = self.get_task_id(task_identifier)
        if task_id is None:
            print(f"Invalid task identifier '{task_identifier}'\n")
            return

        # Check original scheduled_date
        task = tm.get_task(task_id)
        original_date = datetime.date.fromisoformat(task['scheduled_date']) \
            if task['scheduled_date'] is not None else None

        if date == original_date and task['status'] == 'scheduled':
            print(f'Task {helpers.get_task_string(task_id)} already scheduled to '
                  f'{helpers.get_day_string(today, date)}.\n')
            return

        # Confirm the task scheduling
        print(f'Schedule task {helpers.get_task_string(task_id)} to {helpers.get_day_string(today, date)}?')
        input('Press <enter> to continue or Ctrl-C to abort.')

        # Schedule the task
        tm.schedule_task(task_id, date)
        print(f'Task {helpers.get_task_string(task_id)} scheduled to '
              f'{helpers.get_day_string(today, date)}.\n')

    def do_evaluate(self, arg):
        """Evaluate how well I did in the given interval: evaluate <offset_start> <offset_end>"""
        args = arg.split()
        if len(args) != 2:
            print('Usage: evaluate <offset_start> <offset_end>\n')
            return
        try:
            offset_start, offset_end = map(int, args)
        except ValueError:
            print('Usage: evaluate <offset_start> <offset_end>\n')
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
            if task['status'] == 'irrelevant':
                made_irrelevant_count += 1
            elif task['status'] == 'buffered':
                made_buffered_count += 1
            elif task['status'] == 'scheduled':
                incomplete_count += 1
            else:
                assert task['status'] == 'completed', f"Task {task['id']} has invalid status {task['status']}"
                # Get the first scheduled date
                task_schedule_events = tm.get_schedule_events(task_id)
                task_schedule_events.sort(key=lambda x: x['scheduled_date'])
                first_scheduled_date = datetime.date.fromisoformat(task_schedule_events[0]['scheduled_date'])
                # check when the final scheduled date was
                scheduled_date = datetime.date.fromisoformat(task['scheduled_date'])
                diff = scheduled_date - first_scheduled_date
                if diff.days == 0:
                    completed_that_day_count += 1
                elif diff.days == 1:
                    completed_next_day_count += 1
                else:
                    completed_another_day_count += 1

        print(f'Evaluation for the interval {offset_start} to {offset_end} days from today:')
        print()
        print(f'Total number of tasks scheduled: {scheduled_count:>6}')
        print(f'Completed on first day:          {completed_that_day_count:>6} '
              f'({completed_that_day_count / scheduled_count:.0%})')
        print(f'Completed on next day:           {completed_next_day_count:>6} '
                f'({completed_next_day_count / scheduled_count:.0%})')
        print(f'Completed on another day:        {completed_another_day_count:>6} '
              f'({completed_another_day_count / scheduled_count:.0%})')
        print(f'Made irrelevant:                 {made_irrelevant_count:>6} '
              f'({made_irrelevant_count / scheduled_count:.0%})')
        print(f'Buffered:                        {made_buffered_count:>6} '
              f'({made_buffered_count / scheduled_count:.0%})')
        print(f'Incomplete:                      {incomplete_count:>6} '
              f'({incomplete_count / scheduled_count:.0%})')

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
        if task['status'] != 'buffered':
            print(f'    Scheduled for: {task["scheduled_date"]:>17}')

        print()
        scheduling_events = tm.get_schedule_events(task_id)
        print(f'    Total times scheduled: {len(scheduling_events)}')
        for i, event in enumerate(scheduling_events):
            date = datetime.date.fromisoformat(event['scheduled_date'])
            print(f'        {i + 1}. {helpers.get_day_string(datetime.date.today(), date)}')

        print()

    def do_modify_description(self, arg):
        """Modify a task's description: modify <task_identifier> <new_description>"""
        task_identifier = arg

        task_id = self.get_task_id(task_identifier)
        if task_id is None:
            print(f"Invalid task identifier '{task_identifier}'\n")
            return

        print(f'Modifying task {helpers.get_task_string(task_id)}...')
        new_description = input('Enter the new description: ')

        tm.modify_description(task_id, new_description)
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


if __name__ == '__main__':
    app = ToYCLI()


    def sigint_handler(*_):  # Handle Ctrl+C
        app.terminate()
        sys.exit(0)


    signal.signal(signal.SIGINT, sigint_handler)
    sys.exit(app.cmdloop())
