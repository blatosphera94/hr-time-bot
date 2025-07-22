# Файл: config.py
import os
import pytz
from typing import List
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

class BotConfig:
    # --- Основные настройки ---
    TELEGRAM_BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN')
    ADMIN_IDS: List[int] = [384630608] # Замените на реальные ID администраторов

    # --- Настройки базы данных ---
    DATABASE_URL: str = os.getenv('DATABASE_URL')

    # --- Настройки времени и работы ---
    TIMEZONE: str = 'Asia/Barnaul'
    DAILY_BREAK_LIMIT_SECONDS: int = 3600  # 1 час
    MIN_WORK_SECONDS: int = 8 * 3600    # 8 часов

    # --- Настройки геолокации офиса ---
    OFFICE_LATITUDE: float = 53.3479
    OFFICE_LONGITUDE: float = 83.7796
    OFFICE_RADIUS_METERS: int = 200 # Радиус в метрах, в котором можно начать рабочий день

    # --- Настройки логирования ---
    LOG_LEVEL: str = 'INFO'
    # Используем полный путь для надежности при запуске из systemd
    LOG_FILE_PATH: str = '/root/hr-time-bot/bot.log'

    # --- Словари для маппинга ---
    ABSENCE_TYPE_MAP: dict = {
        'absence_sick': 'Больничный',
        'absence_vacation': 'Отпуск',
        'absence_trip': 'Командировка',
        'request_remote_work': 'Удаленная работа',
        'request_day_off': 'Отгул'
    }

# Создаем единственный экземпляр конфигурации для импорта
CONFIG = BotConfig()
# Создаем объект таймзоны для использования в других модулях
LOCAL_TZ = pytz.timezone(CONFIG.TIMEZONE)