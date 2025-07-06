# Файл: database.py (Версия для PostgreSQL)
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import datetime

# Адрес базы данных берется из переменных окружения, которые мы настроим на Render
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_connection():
    """Устанавливает соединение с базой данных PostgreSQL."""
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """Инициализирует таблицы в базе данных PostgreSQL, если они не существуют."""
    conn = get_connection()
    # 'with' автоматически закроет курсор и закоммитит изменения
    with conn.cursor() as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                full_name TEXT,
                role TEXT,
                manager_id_1 BIGINT,
                manager_id_2 BIGINT,
                time_bank_seconds INTEGER DEFAULT 0
            )''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS work_sessions (
                user_id BIGINT PRIMARY KEY,
                state_json JSONB
            )''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS requests (
                request_id SERIAL PRIMARY KEY,
                requester_id BIGINT,
                request_type TEXT,
                request_data JSONB,
                status TEXT DEFAULT 'pending',
                manager_1_message_id BIGINT,
                manager_2_message_id BIGINT
            )''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS work_log (
                log_id SERIAL PRIMARY KEY,
                user_id BIGINT,
                start_time TIMESTAMPTZ,
                end_time TIMESTAMPTZ,
                total_work_seconds INTEGER,
                total_break_seconds INTEGER,
                work_type TEXT DEFAULT 'office'
            )''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS work_debt (
                debt_id SERIAL PRIMARY KEY,
                user_id BIGINT,
                debt_seconds INTEGER,
                date_incurred DATE,
                status TEXT DEFAULT 'pending'
            )''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS debt_log (
                log_id SERIAL PRIMARY KEY,
                user_id BIGINT,
                start_time TIMESTAMPTZ,
                end_time TIMESTAMPTZ,
                cleared_seconds INTEGER
            )''')
            
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS absences (
                absence_id SERIAL PRIMARY KEY,
                user_id BIGINT,
                absence_type TEXT,
                start_date DATE,
                end_date DATE
            )''')
    conn.commit()
    conn.close()

def set_session_state(user_id, state_data):
    conn = get_connection()
    with conn.cursor() as cursor:
        state_data_serializable = json.dumps(state_data, default=str)
        cursor.execute(
            "INSERT INTO work_sessions (user_id, state_json) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET state_json = EXCLUDED.state_json",
            (user_id, state_data_serializable)
        )
    conn.commit()
    conn.close()

def get_session_state(user_id):
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT state_json FROM work_sessions WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()
    conn.close()
    if row and row['state_json']:
        state_data = row['state_json']
        if state_data.get('start_time'): state_data['start_time'] = datetime.datetime.fromisoformat(state_data['start_time'])
        if state_data.get('break_start_time'): state_data['break_start_time'] = datetime.datetime.fromisoformat(state_data['break_start_time'])
        if state_data.get('debt_start_time'): state_data['debt_start_time'] = datetime.datetime.fromisoformat(state_data['debt_start_time'])
        if state_data.get('break_end_time'): state_data['break_end_time'] = datetime.datetime.fromisoformat(state_data['break_end_time'])
        return state_data
    return None

def delete_session_state(user_id):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM work_sessions WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()

def add_or_update_user(user_id, full_name, role='employee', manager_id_1=None, manager_id_2=None):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO users (user_id, full_name, role, manager_id_1, manager_id_2, time_bank_seconds) 
            VALUES (%s, %s, %s, %s, %s, 0) 
            ON CONFLICT (user_id) DO UPDATE SET 
            full_name = EXCLUDED.full_name, 
            role = EXCLUDED.role, 
            manager_id_1 = EXCLUDED.manager_id_1, 
            manager_id_2 = EXCLUDED.manager_id_2
            """,
            (user_id, full_name, role, manager_id_1, manager_id_2)
        )
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
    conn.close()
    return user

def get_all_users():
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT user_id, full_name, role FROM users ORDER BY full_name")
        users = cursor.fetchall()
    conn.close()
    return users
    
def get_managed_users(manager_id):
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT user_id, full_name FROM users WHERE manager_id_1 = %s OR manager_id_2 = %s", (manager_id, manager_id))
        users = cursor.fetchall()
    conn.close()
    return users

def delete_user(user_id):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM work_sessions WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM work_debt WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM work_log WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM debt_log WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM absences WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()

def create_request(requester_id, request_type, request_data, msg_id_1=None, msg_id_2=None):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO requests (requester_id, request_type, request_data, manager_1_message_id, manager_2_message_id) VALUES (%s, %s, %s, %s, %s) RETURNING request_id",
            (requester_id, request_type, json.dumps(request_data), msg_id_1, msg_id_2)
        )
        request_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return request_id

def get_request(request_id):
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT * FROM requests WHERE request_id = %s", (request_id,))
        request = cursor.fetchone()
    conn.close()
    return request

def update_request_status(request_id, status):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("UPDATE requests SET status = %s WHERE request_id = %s", (status, request_id))
    conn.commit()
    conn.close()
    
def add_work_log(user_id, start_time, end_time, total_work_seconds, total_break_seconds, work_type):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO work_log (user_id, start_time, end_time, total_work_seconds, total_break_seconds, work_type) VALUES (%s, %s, %s, %s, %s, %s)",
            (user_id, start_time, end_time, total_work_seconds, total_break_seconds, work_type)
        )
    conn.commit()
    conn.close()

def get_work_logs_for_user(user_id, start_date, end_date):
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT * FROM work_log WHERE user_id = %s AND start_time >= %s AND start_time < %s", (user_id, start_date, end_date))
        logs = cursor.fetchall()
    conn.close()
    return logs

def add_work_debt(user_id, debt_seconds):
    conn = get_connection()
    with conn.cursor() as cursor:
        today_date = datetime.date.today()
        cursor.execute("INSERT INTO work_debt (user_id, debt_seconds, date_incurred) VALUES (%s, %s, %s)", (user_id, debt_seconds, today_date))
    conn.commit()
    conn.close()

def get_total_debt(user_id):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT SUM(debt_seconds) FROM work_debt WHERE user_id = %s AND status = 'pending'", (user_id,))
        result = cursor.fetchone()[0]
    conn.close()
    return result if result else 0

def update_time_bank(user_id, seconds_to_add):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("UPDATE users SET time_bank_seconds = time_bank_seconds + %s WHERE user_id = %s", (seconds_to_add, user_id))
    conn.commit()
    conn.close()
    
def clear_work_debt(user_id, seconds_to_clear):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT debt_id, debt_seconds FROM work_debt WHERE user_id = %s AND status = 'pending' ORDER BY date_incurred ASC", (user_id,))
        debts = cursor.fetchall()
        cleared_amount = seconds_to_clear
        for debt_id, debt_seconds in debts:
            if cleared_amount >= debt_seconds:
                cursor.execute("UPDATE work_debt SET status = 'cleared', debt_seconds = 0 WHERE debt_id = %s", (debt_id,))
                cleared_amount -= debt_seconds
            else:
                new_debt = debt_seconds - cleared_amount
                cursor.execute("UPDATE work_debt SET debt_seconds = %s WHERE debt_id = %s", (new_debt, debt_id))
                cleared_amount = 0
            if cleared_amount <= 0:
                break
    conn.commit()
    conn.close()

def add_debt_log(user_id, start_time, end_time, cleared_seconds):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO debt_log (user_id, start_time, end_time, cleared_seconds) VALUES (%s, %s, %s, %s)", (user_id, start_time, end_time, cleared_seconds))
    conn.commit()
    conn.close()

def get_debt_logs_for_user(user_id, start_date, end_date):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT SUM(cleared_seconds) FROM debt_log WHERE user_id = %s AND start_time >= %s AND start_time < %s", (user_id, start_date, end_date))
        result = cursor.fetchone()[0]
    conn.close()
    return result if result else 0
    
def add_absence(user_id, absence_type, start_date, end_date):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO absences (user_id, absence_type, start_date, end_date) VALUES (%s, %s, %s, %s)", (user_id, absence_type, start_date, end_date))
    conn.commit()
    conn.close()

def get_approved_request(user_id, request_type, date_str):
    conn = get_connection()
    with conn.cursor() as cursor:
        query = f"SELECT request_id FROM requests WHERE requester_id = %s AND request_type = %s AND status = 'approved' AND request_data->>'date' = %s"
        cursor.execute(query, (user_id, request_type, date_str))
        row = cursor.fetchone()
    conn.close()
    return row is not None