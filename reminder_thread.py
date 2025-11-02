import time
from datetime import datetime, timedelta
from database import get_db_connection


def reminder_worker():
    print("Reminder thread started...")
    while True:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM tasks WHERE completed = 0")
        tasks = cursor.fetchall()

        current_time = datetime.now().replace(second=0, microsecond=0)
        for task in tasks:
            task_time = datetime.strptime(task['time'], "%Y-%m-%dT%H:%M")
            if current_time >= task_time:
                print(f"🔔 Reminder: {task['title']} is due now!")

                # If daily/monthly/yearly, reschedule
                if task['frequency'] == 'daily':
                    new_time = task_time + timedelta(days=1)
                elif task['frequency'] == 'monthly':
                    new_time = task_time + timedelta(days=30)
                elif task['frequency'] == 'yearly':
                    new_time = task_time + timedelta(days=365)
                else:
                    new_time = None

                if new_time:
                    cursor.execute("UPDATE tasks SET time = %s WHERE id = %s",
                                   (new_time.strftime("%Y-%m-%dT%H:%M"), task['id']))
                else:
                    # one-time task reminder -> keep reminding every 5 min
                    print(
                        f"⏰ Will remind '{task['title']}' again in 5 min until marked as read.")
        conn.commit()
        conn.close()
        time.sleep(300)  # check every 5 minutes
