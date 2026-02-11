# ToY - Tomorrow of Yesterday

A simple task management application to "reclaim the tomorrow of yesterday".

Built for personal use, to augment due date-based task management with a more task allocation-based approach.

## Features
- Set tasks for a certain date
- Mark tasks as done
- Mark tasks as irrelevant
- Move tasks into a buffer for unscheduled tasks
- Assign priority to tasks
- Delete tasks
- Reschedule tasks
- Retain task history
- Evaluate task completion rate

## Setup
1. Ensure you have Python installed.
2. Install the required packages:
   ```sh
   pip install -r requirements.txt
   ```
3. Run the application:
   ```sh
   python main.py
   ```

## One-time migration (existing databases)
If you already have a `task_db.db` created before priorities were added, run:
```sh
python migrate_add_priority.py
```
