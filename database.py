# Файл: database.py
# Этот модуль содержит все функции для взаимодействия с базой данных PostgreSQL.

import psycopg2
from psycopg2.extras import RealDictCursor
import json
import datetime
import logging
from contextlib import contextmanager
from typing import Dict, Any, List, Optional
from config import CONFIG, LOCAL_TZ

logger = logging.getLogger(__name__)

@contextmanager
def db_connection():
    """Контекстный менеджер для безопасных транзакций с базой данных."""
    conn = None
    try:
        conn = psycopg2.connect(CONFIG.DATABASE_URL)
        yield conn
        conn.commit()
    except psycopg2.Error as e:
        if conn: conn.rollback()
        logger.error(f"Ошибка транзакции с БД: {e}")
        raise
    finally:
        if conn: conn.close()

def init_db(drop_existing=False):
    """Инициализирует базу данных, создавая таблицы, если их нет."""
    tables = ['users', 'work_sessions', 'requests', 'work_log', 'work_debt', 'debt_log', 'absences']
    with db_connection() as conn:
        with conn.cursor() as cursor:
            if drop_existing:
                for table in reversed(tables):
                    logger.warning(f"Удаление таблицы {table}...")
                    cursor.execute(f'DROP TABLE IF EXISTS {table} CASCADE')

            logger.info("Создание таблиц...")
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    role TEXT DEFAULT 'employee',
                    manager_id_1 BIGINT,
                    manager_id_2 BIGINT,
                    time_bank_seconds INTEGER DEFAULT 0,
                    office_latitude REAL,
                    office_longitude REAL,
                    office_radius_meters INTEGER
                )''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS work_sessions (
                    user_id BIGINT PRIMARY KEY,
                    state_json JSONB,
                    CONSTRAINT fk_user FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS requests (
                    request_id SERIAL PRIMARY KEY, requester_id BIGINT, request_type TEXT, 
                    request_data JSONB, status TEXT DEFAULT 'pending', 
                    manager_1_message_id BIGINT, manager_2_message_id BIGINT,
                    CONSTRAINT fk_requester FOREIGN KEY(requester_id) REFERENCES users(user_id) ON DELETE CASCADE
                )''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS work_log (
                    log_id SERIAL PRIMARY KEY, user_id BIGINT, start_time TIMESTAMPTZ, 
                    end_time TIMESTAMPTZ, total_work_seconds INTEGER, 
                    total_break_seconds INTEGER, work_type TEXT DEFAULT 'office',
                    CONSTRAINT fk_user FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )''')
                
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS work_debt (
                    debt_id SERIAL PRIMARY KEY, user_id BIGINT, debt_seconds INTEGER, 
                    date_incurred DATE, status TEXT DEFAULT 'pending',
                    CONSTRAINT fk_user FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS debt_log (
                    log_id SERIAL PRIMARY KEY, user_id BIGINT, start_time TIMESTAMPTZ, 
                    end_time TIMESTAMPTZ, cleared_seconds INTEGER,
                    CONSTRAINT fk_user FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS absences (
                    absence_id SERIAL PRIMARY KEY, user_id BIGINT, absence_type TEXT, 
                    start_date DATE, end_date DATE,
                    CONSTRAINT fk_user FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )''')
    logger.info("База данных успешно инициализирована.")

def get_absences_for_user(user_id: int, check_date: datetime.date) -> List[Dict]:
    """Находит активные отсутствия для пользователя на КОНКРЕТНУЮ ДАТУ."""
    with db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT * FROM absences WHERE user_id = %s AND start_date <= %s AND end_date >= %s",
                (user_id, check_date, check_date)
            )
            return cursor.fetchall()

def get_absences_for_user_in_period(user_id: int, start_date: datetime.date, end_date: datetime.date) -> List[Dict]:
    """
    Находит все отсутствия, которые пересекаются с заданным ДИАПАЗОНОМ ДАТ.
    Это нужно для отчетов руководителя.
    """
    with db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Логика запроса: найти все записи, где (начало_отсутствия <= конец_периода) И (конец_отсутствия >= начало_периода)
            cursor.execute(
                "SELECT * FROM absences WHERE user_id = %s AND start_date <= %s AND end_date >= %s",
                (user_id, end_date, start_date)
            )
            return cursor.fetchall()

def get_todays_work_log_for_user(user_id: int) -> Optional[Dict]:
    """Получает последний лог работы для пользователя за сегодня."""
    today_start = datetime.datetime.now(LOCAL_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    with db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM work_log WHERE user_id = %s AND start_time >= %s ORDER BY end_time DESC LIMIT 1", (user_id, today_start))
            return cursor.fetchone()

def update_request_messages(request_id: int, msg1_id: int = None, msg2_id: int = None):
    with db_connection() as conn:
        with conn.cursor() as cursor:
            if msg1_id:
                cursor.execute("UPDATE requests SET manager_1_message_id = %s WHERE request_id = %s", (msg1_id, request_id))
            if msg2_id:
                cursor.execute("UPDATE requests SET manager_2_message_id = %s WHERE request_id = %s", (msg2_id, request_id))

def set_session_state(user_id: int, state_data: Dict[str, Any]):
    with db_connection() as conn:
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

def get_session_state(user_id: int) -> Optional[Dict]:
    with db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT state_json FROM work_sessions WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
    if not row or not row['state_json']:
        return None
        
    state_data = row['state_json']
    for key, value in state_data.items():
        if 'time' in key and isinstance(value, str):
            try:
                dt_object = datetime.datetime.fromisoformat(value)
                state_data[key] = dt_object.astimezone(LOCAL_TZ)
            except (ValueError, TypeError): pass 
    return state_data

def add_or_update_user(user_id: int, full_name: str, role: str = 'employee', manager_id_1: int = None, manager_id_2: int = None):
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT time_bank_seconds FROM users WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            current_bank = row[0] if row else 0
            cursor.execute("""
                INSERT INTO users (user_id, full_name, role, manager_id_1, manager_id_2, time_bank_seconds, office_latitude, office_longitude, office_radius_meters) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) 
                ON CONFLICT (user_id) DO UPDATE SET 
                full_name = EXCLUDED.full_name, role = EXCLUDED.role, 
                manager_id_1 = EXCLUDED.manager_id_1, manager_id_2 = EXCLUDED.manager_id_2;
                """, (user_id, full_name, role, manager_id_1, manager_id_2, current_bank, CONFIG.OFFICE_LATITUDE, CONFIG.OFFICE_LONGITUDE, CONFIG.OFFICE_RADIUS_METERS))
    
def get_user(user_id: int) -> Optional[Dict]:
    with db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            return cursor.fetchone()

def get_all_users() -> List[Dict]:
    with db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT user_id, full_name, role FROM users ORDER BY full_name")
            return cursor.fetchall()
    
def get_managed_users(manager_id: int) -> List[Dict]:
    with db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT user_id, full_name FROM users WHERE manager_id_1 = %s OR manager_id_2 = %s", (manager_id, manager_id))
            return cursor.fetchall()

def delete_user(user_id: int):
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM work_sessions WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM requests WHERE requester_id = %s", (user_id,))
            cursor.execute("DELETE FROM work_log WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM work_debt WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM debt_log WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM absences WHERE user_id = %s", (user_id,))
            cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))

def create_request(requester_id: int, request_type: str, request_data: Dict, msg_id_1: int = None, msg_id_2: int = None) -> int:
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO requests (requester_id, request_type, request_data, manager_1_message_id, manager_2_message_id) VALUES (%s, %s, %s, %s, %s) RETURNING request_id",
                (requester_id, request_type, json.dumps(request_data), msg_id_1, msg_id_2)
            )
            return cursor.fetchone()[0]

def get_request(request_id: int) -> Optional[Dict]:
    with db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM requests WHERE request_id = %s", (request_id,))
            return cursor.fetchone()

def update_request_status(request_id: int, status: str):
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE requests SET status = %s WHERE request_id = %s", (status, request_id))
    
def add_work_log(user_id: int, start_time: datetime.datetime, end_time: datetime.datetime, total_work_seconds: int, total_break_seconds: int, work_type: str):
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO work_log (user_id, start_time, end_time, total_work_seconds, total_break_seconds, work_type) VALUES (%s, %s, %s, %s, %s, %s)",
                (user_id, start_time, end_time, total_work_seconds, total_break_seconds, work_type)
            )

def get_work_logs_for_user(user_id: int, start_date: str, end_date: str) -> List[Dict]:
    with db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT * FROM work_log WHERE user_id = %s AND start_time >= %s AND start_time < %s", (user_id, start_date, end_date))
            return cursor.fetchall()

def add_work_debt(user_id: int, debt_seconds: int):
    with db_connection() as conn:
        with conn.cursor() as cursor:
            today_date = datetime.date.today()
            cursor.execute("INSERT INTO work_debt (user_id, debt_seconds, date_incurred) VALUES (%s, %s, %s)", (user_id, debt_seconds, today_date))

def get_total_debt(user_id: int) -> int:
    with db_connection() as conn:
        with conn.cursor() as cursor:
            today = datetime.date.today()
            first_day_of_month = today.replace(day=1)
            cursor.execute("SELECT SUM(debt_seconds) FROM work_debt WHERE user_id = %s AND status = 'pending' AND date_incurred >= %s", (user_id, first_day_of_month))
            result = cursor.fetchone()
            return result[0] if result and result[0] else 0

def update_time_bank(user_id: int, seconds_to_add: int):
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE users SET time_bank_seconds = time_bank_seconds + %s WHERE user_id = %s", (seconds_to_add, user_id))
    
def clear_work_debt(user_id: int, seconds_to_clear: int):
    with db_connection() as conn:
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

def add_debt_log(user_id: int, start_time: datetime.datetime, end_time: datetime.datetime, cleared_seconds: int):
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO debt_log (user_id, start_time, end_time, cleared_seconds) VALUES (%s, %s, %s, %s)", (user_id, start_time, end_time, cleared_seconds))

def get_debt_logs_for_user(user_id: int, start_date: str, end_date: str) -> int:
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT SUM(cleared_seconds) FROM debt_log WHERE user_id = %s AND start_time >= %s AND start_time < %s", (user_id, start_date, end_date))
            result = cursor.fetchone()
            return result[0] if result and result[0] else 0
    
def add_absence(user_id: int, absence_type: str, start_date: datetime.date, end_date: datetime.date):
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO absences (user_id, absence_type, start_date, end_date) VALUES (%s, %s, %s, %s)", (user_id, absence_type, start_date, end_date))

def get_approved_request(user_id: int, request_type: str, date_str: str) -> bool:
    with db_connection() as conn:
        with conn.cursor() as cursor:
            query = "SELECT request_id FROM requests WHERE requester_id = %s AND request_type = %s AND status = 'approved' AND request_data->>'date' = %s"
            cursor.execute(query, (user_id, request_type, date_str))
            return cursor.fetchone() is not None

def delete_session_state(user_id: int):
    with db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM work_sessions WHERE user_id = %s", (user_id,))