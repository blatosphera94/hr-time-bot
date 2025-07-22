# Файл: utils.py
import datetime
import time
import logging
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from config import CONFIG, LOCAL_TZ
import database as db

logger = logging.getLogger(__name__)

# --- Общие утилиты ---
def get_now() -> datetime.datetime:
    """Возвращает текущее время с учетом таймзоны из конфига."""
    return datetime.datetime.now(LOCAL_TZ)

def seconds_to_str(seconds: int) -> str:
    """Конвертирует секунды в читаемый формат 'X ч Y мин'."""
    if not isinstance(seconds, (int, float)) or seconds < 0:
        seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours} ч {minutes} мин"

# --- Декораторы ---
def admin_only(func):
    """Декоратор, ограничивающий доступ к функции только для администраторов."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in CONFIG.ADMIN_IDS:
            logger.warning(f"Несанкционированная попытка доступа от {user_id} к {func.__name__}")
            if update.message:
                await update.message.reply_text("У вас нет доступа к этой команде.")
            elif update.callback_query:
                await update.callback_query.answer("У вас нет доступа к этой команде.", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

async def end_workday_logic(context: ContextTypes.DEFAULT_TYPE, user_id: int, is_early_leave: bool = False, forgive_debt: bool = False, used_bank_time: int = 0):
    """Универсальная логика завершения рабочего дня."""
    # Локальный импорт для избежания циклов зависимостей
    from menu_generator import MenuGenerator
    
    session_state = db.get_session_state(user_id)
    if not session_state or session_state.get('status') != 'working':
        logger.warning(f"Попытка завершить день для user_id {user_id} без активной сессии 'working'.")
        return

    start_time = session_state['start_time']
    end_time = get_now()
    total_break_seconds = session_state.get('total_break_seconds', 0)
    work_duration_seconds = (end_time - start_time).total_seconds() - total_break_seconds
    work_type = "remote" if session_state.get('is_remote') else "office"
    
    db.add_work_log(user_id, start_time, end_time, int(work_duration_seconds), total_break_seconds, work_type)
    
    # Начисление в банк времени за неиспользованные перерывы
    if not is_early_leave:
        unused_break_time = CONFIG.DAILY_BREAK_LIMIT_SECONDS - total_break_seconds
        if unused_break_time > 0:
            db.update_time_bank(user_id, unused_break_time)

    db.delete_session_state(user_id)
    
    work_time_str = seconds_to_str(work_duration_seconds)
    message_text = f"Рабочий день ({'удаленно' if work_type == 'remote' else 'в офисе'}) завершен. Вы отработали: {work_time_str}."

    # Логика обработки долга при раннем уходе
    if used_bank_time > 0:
        message_text += f"\nИз банка времени списано: {seconds_to_str(int(used_bank_time))}."
    elif is_early_leave and not forgive_debt:
        debt_seconds = CONFIG.MIN_WORK_SECONDS - work_duration_seconds
        if debt_seconds > 0:
            db.add_work_debt(user_id, int(debt_seconds))
            debt_str = seconds_to_str(debt_seconds)
            message_text += f"\n\nВам начислена отработка: **{debt_str}**."
    
    main_menu_markup = await MenuGenerator.get_main_menu(user_id)
    await context.bot.send_message(user_id, message_text, reply_markup=main_menu_markup, parse_mode='Markdown')
