# Файл: config.py
import os
import pytz
from typing import List
from dotenv import load_dotenv

load_dotenv()

class BotConfig:
    # --- Основные настройки ---
    TELEGRAM_BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN')
    ADMIN_IDS: List[int] = [384630608]

    # --- Настройки базы данных ---
    DATABASE_URL: str = os.getenv('DATABASE_URL')

    # --- Настройки времени и работы ---
    TIMEZONE: str = 'Asia/Barnaul'
    DAILY_BREAK_LIMIT_SECONDS: int = 3600  # 1 час
    MIN_WORK_SECONDS: int = 8 * 3600    # 8 часов

    # --- Настройки геолокации офиса ---
    OFFICE_LATITUDE: float = 53.356422
    OFFICE_LONGITUDE: float = 83.771422
    OFFICE_RADIUS_METERS: int = 200

    # --- Настройки логирования ---
    LOG_LEVEL: str = 'INFO'
    LOG_FILE_PATH: str = 'bot.log'

    # --- Словари для маппинга ---
    ABSENCE_TYPE_MAP: dict = {
        'absence_sick': 'Больничный',
        'absence_vacation': 'Отпуск',
        'absence_trip': 'Командировка',
        'request_remote_work': 'Удаленная работа',
        'request_day_off': 'Отгул'
    }

CONFIG = BotConfig()
LOCAL_TZ = pytz.timezone(CONFIG.TIMEZONE)