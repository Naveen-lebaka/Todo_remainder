from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime
import mysql.connector
from database import get_db_connection

app = Flask(__name__)
app.secret_key = "todo-secret-key"


@app.route('/')
def index():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM tasks ORDER BY time ASC")
    tasks = cursor.fetchall()
    conn.close()
    return render_template('index.html', tasks=tasks)


@app.route('/add', methods=['POST'])
def add():
    title = request.form['title']
    time_input = request.form['time']
    frequency = request.form['frequency']

    if not title or not time_input:
        flash("Title and time are required!")
        return redirect(url_for('index'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO tasks (title, time, frequency, completed) VALUES (%s, %s, %s, %s)",
                   (title, time_input, frequency, 0))
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
    cursor.execute("SELECT id, title, time FROM tasks WHERE completed = 0")
    tasks = cursor.fetchall()
    conn.close()
    return jsonify(tasks)


if __name__ == '__main__':
    app.run(debug=True)
