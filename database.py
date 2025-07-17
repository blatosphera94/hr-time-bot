# Файл: database.py (Полная и правильная версия для PostgreSQL)
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import datetime
import pytz

DATABASE_URL = os.environ.get('DATABASE_URL')
LOCAL_TZ_STR = 'Asia/Barnaul'

def get_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY, full_name TEXT, role TEXT, 
                manager_id_1 BIGINT, manager_id_2 BIGINT, time_bank_seconds INTEGER DEFAULT 0
            )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS work_sessions (user_id BIGINT PRIMARY KEY, state_json JSONB)''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS requests (
                request_id SERIAL PRIMARY KEY, requester_id BIGINT, request_type TEXT, 
                request_data JSONB, status TEXT DEFAULT 'pending', 
                manager_1_message_id BIGINT, manager_2_message_id BIGINT
            )''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS work_log (
                log_id SERIAL PRIMARY KEY, user_id BIGINT, start_time TIMESTAMPTZ, 
                end_time TIMESTAMPTZ, total_work_seconds INTEGER, 
                total_break_seconds INTEGER, work_type TEXT DEFAULT 'office'
            )''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS work_debt (
                debt_id SERIAL PRIMARY KEY, user_id BIGINT, debt_seconds INTEGER, 
                date_incurred DATE, status TEXT DEFAULT 'pending'
            )''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS debt_log (
                log_id SERIAL PRIMARY KEY, user_id BIGINT, start_time TIMESTAMPTZ, 
                end_time TIMESTAMPTZ, cleared_seconds INTEGER
            )''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS absences (
                absence_id SERIAL PRIMARY KEY, user_id BIGINT, absence_type TEXT, 
                start_date DATE, end_date DATE
            )''')
    conn.commit()
    conn.close()

def get_absences_for_user(user_id, check_date):
    """Возвращает отсутствия пользователя на конкретную дату."""
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            "SELECT * FROM absences WHERE user_id = %s AND start_date <= %s AND end_date >= %s",
            (user_id, check_date, check_date)
        )
        absences = cursor.fetchall()
    conn.close()
    return absences

def get_todays_work_log_for_user(user_id):
    """Проверяет, есть ли у пользователя завершенная сессия за сегодня."""
    conn = get_connection()
    local_tz = pytz.timezone(LOCAL_TZ_STR)
    today_start = datetime.datetime.now(local_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT * FROM work_log WHERE user_id = %s AND start_time >= %s ORDER BY end_time DESC LIMIT 1", (user_id, today_start))
        log = cursor.fetchone()
    conn.close()
    return log

def update_request_messages(request_id, msg1_id=None, msg2_id=None):
    conn = get_connection()
    with conn.cursor() as cursor:
        if msg1_id:
            cursor.execute("UPDATE requests SET manager_1_message_id = %s WHERE request_id = %s", (msg1_id, request_id))
        if msg2_id:
            cursor.execute("UPDATE requests SET manager_2_message_id = %s WHERE request_id = %s", (msg2_id, request_id))
    conn.commit()
    conn.close()

def set_session_state(user_id, state_data):
    conn = get_connection()
    with conn.cursor() as cursor:
        state_copy = state_data.copy()
        for key, value in state_copy.items():
            if isinstance(value, datetime.datetime):
                state_copy[key] = value.isoformat()
        state_data_serializable = json.dumps(state_copy)
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
        local_tz = pytz.timezone(LOCAL_TZ_STR)
        for key, value in state_data.items():
            if 'time' in key and isinstance(value, str):
                try:
                    dt_object = datetime.datetime.fromisoformat(value)
                    if dt_object.tzinfo is None:
                         state_data[key] = local_tz.localize(dt_object)
                    else:
                         state_data[key] = dt_object.astimezone(local_tz)
                except ValueError: pass 
        return state_data
    return None

def add_or_update_user(user_id, full_name, role='employee', manager_id_1=None, manager_id_2=None):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT time_bank_seconds FROM users WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()
        current_bank = row[0] if row else 0
        cursor.execute("""
            INSERT INTO users (user_id, full_name, role, manager_id_1, manager_id_2, time_bank_seconds) 
            VALUES (%s, %s, %s, %s, %s, %s) 
            ON CONFLICT (user_id) DO UPDATE SET 
            full_name = EXCLUDED.full_name, role = EXCLUDED.role, 
            manager_id_1 = EXCLUDED.manager_id_1, manager_id_2 = EXCLUDED.manager_id_2;
            """, (user_id, full_name, role, manager_id_1, manager_id_2, current_bank))
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
        tables = ['absences', 'debt_log', 'work_debt', 'work_log', 'requests', 'work_sessions', 'users']
        for table in tables:
            cursor.execute(f"DELETE FROM {table} WHERE user_id = %s", (user_id,))
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
        today = datetime.date.today()
        first_day_of_month = today.replace(day=1)
        cursor.execute("SELECT SUM(debt_seconds) FROM work_debt WHERE user_id = %s AND status = 'pending' AND date_incurred >= %s", (user_id, first_day_of_month))
        result = cursor.fetchone()
    conn.close()
    return result[0] if result and result[0] else 0

def update_time_bank(user_id, seconds_to_add):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("UPDATE users SET time_bank_seconds = time_bank_seconds + %s WHERE user_id = %s", (seconds_to_add, user_id))
    conn.commit()
    conn.close()
    
def clear_work_debt(user_id, seconds_to_clear):
    conn = get_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute("SELECT debt_id, debt_seconds FROM work_debt WHERE user_id = %s AND status = 'pending' ORDER BY date_incurred ASC", (user_id,))
        debts = cursor.fetchall()
        cleared_amount = seconds_to_clear
        for debt in debts:
            if cleared_amount >= debt['debt_seconds']:
                cursor.execute("UPDATE work_debt SET status = 'cleared', debt_seconds = 0 WHERE debt_id = %s", (debt['debt_id'],))
                cleared_amount -= debt['debt_seconds']
            else:
                new_debt = debt['debt_seconds'] - cleared_amount
                cursor.execute("UPDATE work_debt SET debt_seconds = %s WHERE debt_id = %s", (new_debt, debt['debt_id']))
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
        result = cursor.fetchone()
    conn.close()
    return result[0] if result and result[0] else 0
    
def add_absence(user_id, absence_type, start_date, end_date):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO absences (user_id, absence_type, start_date, end_date) VALUES (%s, %s, %s, %s)", (user_id, absence_type, start_date, end_date))
    conn.commit()
    conn.close()

def get_approved_request(user_id, request_type, date_str):
    conn = get_connection()
    with conn.cursor() as cursor:
        query = "SELECT request_id FROM requests WHERE requester_id = %s AND request_type = %s AND status = 'approved' AND request_data->>'date' = %s"
        cursor.execute(query, (user_id, request_type, date_str))
        row = cursor.fetchone()
    conn.close()
    return row is not None

def delete_session_state(user_id):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM work_sessions WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()