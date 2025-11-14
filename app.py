from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime, date, time, timedelta
import calendar

from database import get_db_connection

app = Flask(__name__)
app.secret_key = "todo-secret-key"


# -----------------------
# Helpers: robust parsing and next occurrence
# -----------------------
def _timedelta_to_time(td: timedelta) -> time:
    """
    Convert a MySQL TIME returned as timedelta to a time object.
    Normalizes negative durations into the 0-24h range.
    """
    total_seconds = int(td.total_seconds()) % (24 * 3600)
    hours = (total_seconds // 3600) % 24
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return time(hour=hours, minute=minutes, second=seconds)


def parse_date_time_fields(db_date, db_time):
    """
    Robustly parse DB date/time fields into a single datetime.
    Accepts:
      - db_date: date or str 'YYYY-MM-DD'
      - db_time: str 'HH:MM' or 'HH:MM:SS' or 'HH:MM:SS.mmm',
                 datetime.time, or datetime.timedelta (MySQL TIME)
    Returns: datetime (naive, server local)
    """
    # --- date part ---
    if isinstance(db_date, str):
        try:
            d = datetime.strptime(db_date, "%Y-%m-%d").date()
        except ValueError:
            # fallback for isoformat or with time part
            d = datetime.fromisoformat(db_date).date()
    elif isinstance(db_date, date):
        d = db_date
    else:
        raise ValueError(
            f"Unsupported date field: {type(db_date)} -> {db_date!r}")

    # --- time part ---
    if isinstance(db_time, time):
        t = db_time

    elif isinstance(db_time, timedelta):
        t = _timedelta_to_time(db_time)

    elif isinstance(db_time, str):
        ts = db_time.strip()
        parsed = None
        for fmt in ("%H:%M", "%H:%M:%S", "%H:%M:%S.%f"):
            try:
                parsed = datetime.strptime(ts, fmt).time()
                break
            except ValueError:
                continue
        if parsed is None:
            parts = ts.split(":")
            if len(parts) >= 2:
                try:
                    hh = int(parts[0]) % 24
                    mm = int(parts[1]) % 60
                    ss = int(parts[2].split(".")[0]) if len(parts) >= 3 else 0
                    parsed = time(hh, mm, ss)
                except Exception:
                    parsed = None
        if parsed is None:
            raise ValueError(f"Unsupported time string format: {ts!r}")
        t = parsed

    elif isinstance(db_time, (bytes, bytearray)):
        return parse_date_time_fields(db_date, db_time.decode())

    else:
        raise ValueError(
            f"Unsupported time field: {type(db_time)} -> {db_time!r}")

    return datetime.combine(d, t)


def next_occurrence(dt: datetime, frequency: str) -> datetime:
    """
    Given a datetime dt (current scheduled occurrence) and frequency in ('daily','monthly','yearly')
    return the next scheduled datetime (one step forward).
    """
    frequency = (frequency or "").lower().strip()
    if frequency == "daily":
        return dt + timedelta(days=1)

    elif frequency == "monthly":
        year = dt.year
        month = dt.month + 1
        if month > 12:
            month = 1
            year += 1
        day = dt.day
        last_day = calendar.monthrange(year, month)[1]
        new_day = min(day, last_day)
        return datetime(year, month, new_day, dt.hour, dt.minute, dt.second)

    elif frequency == "yearly":
        year = dt.year + 1
        month = dt.month
        day = dt.day
        if month == 2 and day == 29 and not calendar.isleap(year):
            day = 28
        last_day = calendar.monthrange(year, month)[1]
        new_day = min(day, last_day)
        return datetime(year, month, new_day, dt.hour, dt.minute, dt.second)

    else:
        raise ValueError("Unsupported frequency")


# -----------------------
# Routes
# -----------------------
@app.route('/')
def index():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM tasks WHERE completed = 0 ORDER BY date ASC, time ASC")
    tasks = cursor.fetchall()
    conn.close()
    return render_template('index.html', tasks=tasks)


@app.route('/add', methods=['POST'])
def add():
    title = request.form['title']
    date_input = request.form['date']
    time_input = request.form['time']
    frequency = request.form.get('frequency', '')

    if not title or not date_input or not time_input:
        flash("Title, date, and time are required!")
        return redirect(url_for('index'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO tasks (title, date, time, frequency, completed)
        VALUES (%s, %s, %s, %s, %s)
    """, (title, date_input, time_input, frequency or None, 0))
    conn.commit()
    conn.close()
    flash("Task added successfully!")
    return redirect(url_for('index'))


@app.route('/complete/<int:task_id>')
def complete(task_id):
    """
    Mark the current scheduled occurrence as completed.
    For recurring tasks (daily/monthly/yearly), insert an entry into task_history
    and update tasks.date/time to the next occurrence (do not delete).
    For one-time tasks, mark completed = 1 (do not delete).
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
    task = cursor.fetchone()
    if not task:
        conn.close()
        flash("Task not found.")
        return redirect(url_for('index'))

    title = task['title']
    frequency = (task['frequency'] or '').lower().strip()

    # parse scheduled datetime (robust)
    try:
        scheduled_dt = parse_date_time_fields(task['date'], task['time'])
    except Exception as e:
        # fallback: if time is timedelta, coerce to string then parse
        if isinstance(task.get('time'), timedelta):
            total_seconds = int(task['time'].total_seconds()) % (24 * 3600)
            hh = (total_seconds // 3600) % 24
            mm = (total_seconds % 3600) // 60
            ss = total_seconds % 60
            task['time'] = f"{hh:02d}:{mm:02d}:{ss:02d}"
            scheduled_dt = parse_date_time_fields(task['date'], task['time'])
        else:
            conn.close()
            flash(f"Error parsing scheduled time: {e}")
            return redirect(url_for('index'))

    now = datetime.now()

    if not frequency:
        # one-time task: mark completed (do NOT delete)
        cursor.execute(
            "UPDATE tasks SET completed = 1 WHERE id = %s", (task_id,))
        # optional: insert into history if table exists
        try:
            cursor.execute("""
                INSERT INTO task_history (task_id, title, scheduled_datetime, completed_at, missed, notes)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                task_id,
                title,
                scheduled_dt.strftime("%Y-%m-%d %H:%M:%S"),
                now.strftime("%Y-%m-%d %H:%M:%S"),
                1 if (now - scheduled_dt) > timedelta(minutes=1) else 0,
                "one-time completed"
            ))
        except Exception:
            conn.rollback()
        conn.commit()
        conn.close()
        flash("Task marked as completed.")
        return redirect(url_for('index'))

    # recurring task: compute completed_occurrence and next occurrence(s)
    occurrence_dt = scheduled_dt
    if occurrence_dt > now:
        completed_occurrence = occurrence_dt
        missed = False
        missed_count = 0
    else:
        last_occurrence = occurrence_dt
        while True:
            nxt = next_occurrence(last_occurrence, frequency)
            if nxt <= now:
                last_occurrence = nxt
            else:
                break
        completed_occurrence = last_occurrence
        missed = (now - completed_occurrence) > timedelta(seconds=5)
        missed_count = 0
        cur = occurrence_dt
        while cur < last_occurrence:
            cur = next_occurrence(cur, frequency)
            missed_count += 1

    # log into history if available
    try:
        cursor.execute("""
            INSERT INTO task_history (task_id, title, scheduled_datetime, completed_at, missed, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            task_id,
            title,
            completed_occurrence.strftime("%Y-%m-%d %H:%M:%S"),
            now.strftime("%Y-%m-%d %H:%M:%S"),
            1 if missed else 0,
            f"missed_count={missed_count}"
        ))
        conn.commit()
    except Exception:
        conn.rollback()

    # compute next future occurrence (> now)
    next_dt = completed_occurrence
    while True:
        next_dt = next_occurrence(next_dt, frequency)
        if next_dt > now:
            break

    new_date = next_dt.date().strftime("%Y-%m-%d")
    new_time = next_dt.time().strftime("%H:%M:%S")

    cursor.execute("""
        UPDATE tasks SET date = %s, time = %s, completed = 0
        WHERE id = %s
    """, (new_date, new_time, task_id))
    conn.commit()
    conn.close()

    flash(
        f"Recurring task rescheduled to {new_date} {new_time}. Missed occurrences: {missed_count}")
    return redirect(url_for('index'))


@app.route('/delete/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    """
    Permanently delete a task and its history (if any).
    Uses POST to avoid accidental deletes via GET.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # delete history (if table exists)
        try:
            cursor.execute(
                "DELETE FROM task_history WHERE task_id = %s", (task_id,))
        except Exception:
            conn.rollback()

        # delete the task itself
        cursor.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
        conn.commit()
        flash("Task deleted successfully.")
    except Exception as e:
        conn.rollback()
        flash(f"Failed to delete task: {e}")
    finally:
        conn.close()

    return redirect(url_for('index'))


@app.route('/reminder-data')
def reminder_data():
    """Send all active reminders to frontend"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, title, date, time, frequency FROM tasks WHERE completed = 0")
    tasks = cursor.fetchall()
    conn.close()

    fixed_tasks = []
    for t in tasks:
        # Convert date
        if hasattr(t['date'], 'strftime'):
            t['date'] = t['date'].strftime("%Y-%m-%d")

        # Handle MySQL TIME as timedelta or time object
        time_val = t['time']
        if hasattr(time_val, 'strftime'):  # if it's a datetime.time object
            t['time'] = time_val.strftime("%H:%M")
        else:
            try:
                total_seconds = int(time_val.total_seconds())
                hours = (total_seconds // 3600) % 24
                minutes = (total_seconds % 3600) // 60
                t['time'] = f"{hours:02d}:{minutes:02d}"
            except Exception:
                t['time'] = str(time_val)[:5]

        fixed_tasks.append(t)

    return jsonify(fixed_tasks)


if __name__ == '__main__':
    app.run(debug=True)
