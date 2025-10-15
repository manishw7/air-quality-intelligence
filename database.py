
import mysql.connector
from mysql.connector import errorcode
import os

DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_USER = os.environ.get('DB_USER', 'root')
DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
DB_NAME = 'aqi_app'

def get_db_connection():
    """Establishes a connection to the MySQL database."""
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        return conn
    except mysql.connector.Error as err:
        if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
            print("Something is wrong with your user name or password")
        elif err.errno == errorcode.ER_BAD_DB_ERROR:
            print(f"Database '{DB_NAME}' does not exist")
        else:
            print(err)
        return None

def init_db():
    """Initializes the database by creating tables from the schema.sql file."""
    conn = get_db_connection()
    if conn is None:
        print("Could not connect to the database. Aborting initialization.")
        return
        
    cursor = conn.cursor()
    
    with open('schema.sql') as f:
        sql_commands = f.read().split(';')
        for command in sql_commands:
            if command.strip():
                try:
                    cursor.execute(command)
                except mysql.connector.Error as err:
                    print(f"Failed executing command: {command.strip()}")
                    print(f"MySQL Error: {err}")

    conn.commit()
    cursor.close()
    conn.close()
    print("Database initialized successfully.")

if __name__ == '__main__':
    init_db()