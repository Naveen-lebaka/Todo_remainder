import mysql.connector


def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",          # change if needed
        password="root123",
        database="todo_db"
    )
