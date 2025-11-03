from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime
from database import get_db_connection

app = Flask(__name__)
app.secret_key = "todo-secret-key"


@app.route('/')
def index():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM tasks ORDER BY date ASC, time ASC")
    tasks = cursor.fetchall()
    conn.close()
    return render_template('index.html', tasks=tasks)


@app.route('/add', methods=['POST'])
def add():
    title = request.form['title']
    date_input = request.form['date']
    time_input = request.form['time']
    frequency = request.form['frequency']

    if not title or not date_input or not time_input:
        flash("Title, date, and time are required!")
        return redirect(url_for('index'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO tasks (title, date, time, frequency, completed)
        VALUES (%s, %s, %s, %s, %s)
    """, (title, date_input, time_input, frequency, 0))
    conn.commit()
    conn.close()
    flash("Task added successfully!")
    return redirect(url_for('index'))


@app.route('/complete/<int:task_id>')
def complete(task_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
    conn.commit()
    conn.close()
    flash("Task marked as completed and deleted.")
    return redirect(url_for('index'))


@app.route('/reminder-data')
def reminder_data():
    """Send all active reminders to frontend"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, title, date, time FROM tasks WHERE completed = 0")
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
            # MySQL TIME returned as timedelta → convert manually
            total_seconds = int(time_val.total_seconds())
            hours = (total_seconds // 3600) % 24
            minutes = (total_seconds % 3600) // 60
            t['time'] = f"{hours:02d}:{minutes:02d}"

        fixed_tasks.append(t)

    return jsonify(fixed_tasks)


if __name__ == '__main__':
    app.run(debug=True)
