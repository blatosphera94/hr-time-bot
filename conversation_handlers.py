# Файл: conversation_handlers.py (Финальная версия с исправлением логики радиуса)
import re
import datetime
import logging
from math import radians, sin, cos, sqrt, atan2
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes, 
    ConversationHandler, 
    MessageHandler, 
    CallbackQueryHandler, 
    filters,
    CommandHandler
)

import database as db
from config import CONFIG
from menu_generator import MenuGenerator
from report_generator import ReportGenerator

logger = logging.getLogger(__name__)

# Состояния
GET_DATES_TEXT, GET_REPORT_DATES, GET_LOCATION = range(3)

# --- Диалог оформления отсутствий ---
async def ask_for_dates_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    absence_type_key = query.data
    context.user_data['absence_type'] = absence_type_key
    absence_name = CONFIG.ABSENCE_TYPE_MAP.get(absence_type_key, "отсутствие").lower()
    
    prompt_text = f"Введите даты для '{absence_name}', например: 01.08.2025 - 15.08.2025"
    if absence_type_key in ['request_remote_work', 'request_day_off']:
        prompt_text = f"Введите дату для '{absence_name}', например: 15.08.2025"
        
    await query.edit_message_text(f"{prompt_text}\n\nДля отмены введите /cancel")
    return GET_DATES_TEXT

async def process_dates_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_input = update.message.text
    absence_type_key = context.user_data.get('absence_type')
    absence_name = CONFIG.ABSENCE_TYPE_MAP.get(absence_type_key, "Отсутствие")

    try:
        found_dates = re.findall(r'\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b', user_input)
        if not found_dates:
            await update.message.reply_text("Не могу найти ни одной даты. Попробуйте формат: ДД.ММ.ГГГГ или введите /cancel.")
            return GET_DATES_TEXT

        parsed_dates = [datetime.date(int(y if len(y)==4 else f"20{y}"), int(m), int(d)) for d, m, y in found_dates]
        start_date, end_date = min(parsed_dates), max(parsed_dates)
        
        user_info = db.get_user(user.id)
        if not user_info:
            await update.message.reply_text("Ошибка: не удалось найти ваш профиль.")
            return ConversationHandler.END

        if absence_type_key in ['request_remote_work', 'request_day_off']:
            if not user_info.get('manager_id_1') and not user_info.get('manager_id_2'):
                await update.message.reply_text("Ошибка: за вами не закреплен руководитель для согласования.", reply_markup=await MenuGenerator.get_main_menu(user.id))
                return ConversationHandler.END

            text_for_manager = f"Сотрудник {user_info['full_name']} запрашивает '{absence_name}' на {start_date.strftime('%d.%m.%Y')}."
            request_type_for_db = 'Удаленная работа' if absence_type_key == 'request_remote_work' else 'Отгул'
            request_id = db.create_request(user.id, request_type_for_db, {'date': str(start_date)})
            
            keyboard = [[InlineKeyboardButton("✅ Одобрить", callback_data=f'approve_{request_id}'), InlineKeyboardButton("❌ Отклонить", callback_data=f'deny_{request_id}')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            msg_ids = {}
            if user_info.get('manager_id_1'):
                msg = await context.bot.send_message(user_info['manager_id_1'], text_for_manager, reply_markup=reply_markup)
                msg_ids['msg1_id'] = msg.message_id
            if user_info.get('manager_id_2') and user_info.get('manager_id_2') != user_info.get('manager_id_1'):
                msg = await context.bot.send_message(user_info['manager_id_2'], text_for_manager, reply_markup=reply_markup)
                msg_ids['msg2_id'] = msg.message_id
            db.update_request_messages(request_id, **msg_ids)
            await update.message.reply_text(f"Ваш запрос на '{absence_name}' отправлен на согласование.", reply_markup=await MenuGenerator.get_main_menu(user.id))
        else:
            db.add_absence(user.id, absence_name, start_date, end_date)
            await update.message.reply_text(f"{absence_name} с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')} успешно зарегистрирован.", reply_markup=await MenuGenerator.get_main_menu(user.id))
            
            text_for_manager = f"FYI: Сотрудник {user_info['full_name']} оформил '{absence_name}' с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')}."
            if user_info.get('manager_id_1'): await context.bot.send_message(user_info['manager_id_1'], text_for_manager)
            if user_info.get('manager_id_2') and user_info.get('manager_id_2') != user_info.get('manager_id_1'): await context.bot.send_message(user_info['manager_id_2'], text_for_manager)

        context.user_data.clear()
        return ConversationHandler.END

    except (ValueError, TypeError) as e:
        logger.error(f"Ошибка парсинга даты: {e}")
        await update.message.reply_text("Неверный формат даты. Попробуйте еще раз (ДД.ММ.ГГГГ) или введите /cancel.")
        return GET_DATES_TEXT

async def ask_for_report_dates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    report_type = query.data.split('_')[-1]
    context.user_data['report_type'] = report_type
    await query.edit_message_text("Введите период для отчета в формате: ДД.ММ.ГГГГ - ДД.ММ.ГГГГ\n\nДля отмены введите /cancel")
    return GET_REPORT_DATES

async def process_report_dates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    report_type = context.user_data.get('report_type')
    try:
        found_dates = re.findall(r'\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b', update.message.text)
        if not found_dates:
            await update.message.reply_text("Не могу найти дат. Попробуйте формат: ДД.ММ.ГГГГ - ДД.ММ.ГГГГ или /cancel")
            return GET_REPORT_DATES

        parsed_dates = [datetime.date(int(y if len(y)==4 else f"20{y}"), int(m), int(d)) for d, m, y in found_dates]
        start_date, end_date = min(parsed_dates), max(parsed_dates)
        
        await update.message.delete()
        
        if report_type == 'manager':
            report_text = await ReportGenerator.get_manager_report_text(user_id, start_date, end_date)
            reply_markup = MenuGenerator.get_manager_menu()
        else:
            report_text = await ReportGenerator.get_employee_report_text(user_id, start_date, end_date)
            is_in_session = bool(db.get_session_state(user_id))
            reply_markup = MenuGenerator.get_working_menu() if is_in_session else await MenuGenerator.get_main_menu(user_id)
        
        await context.bot.send_message(user_id, report_text, parse_mode='Markdown', reply_markup=reply_markup)
        return ConversationHandler.END

    except (ValueError, TypeError):
        await update.message.reply_text("Неверный формат. Попробуйте еще раз или введите /cancel")
        return GET_REPORT_DATES

# В файле conversation_handlers.py

async def ask_for_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Запрашивает геолокацию с подробной инструкцией для ПК."""
    query = update.callback_query
    await query.answer()
    
    keyboard = [[KeyboardButton("📍 Отправить мою геолокацию", request_location=True)]]
    
    message_text = (
        "Для начала работы в офисе, пожалуйста, подтвердите ваше местоположение.\n\n"
        "📱 **На телефоне:**\n"
        "Просто нажмите на кнопку ниже.\n\n"
        "💻 **На компьютере (Windows/Mac/Linux):**\n"
        "1. Нажмите на значок скрепки (📎).\n"
        "2. Выберите 'Геолокация' (Location).\n"
        "3. В открывшемся окне с картой нажмите 'ОТПРАВИТЬ ЭТУ ГЕОПОЗИЦИЮ'."
    )
    
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=message_text,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True),
        parse_mode='Markdown'
    )
    await query.delete_message()
    return GET_LOCATION

async def process_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_location = update.message.location
    await update.message.reply_text("Проверяем вашу геолокацию...", reply_markup=ReplyKeyboardRemove())

    user_info = db.get_user(user.id)
    if not user_info:
        await update.message.reply_text("Ошибка: Ваш профиль не найден. Пожалуйста, добавьте себя через /adduser.")
        return ConversationHandler.END

    office_lat = CONFIG.OFFICE_LATITUDE
    office_lon = CONFIG.OFFICE_LONGITUDE
    user_lat = user_location.latitude
    user_lon = user_location.longitude

    logger.info(f"Проверка геолокации для user_id {user.id}:")
    logger.info(f"Координаты офиса (из config.py): Широта={office_lat}, Долгота={office_lon}")
    logger.info(f"Координаты пользователя: Широта={user_lat}, Долгота={user_lon}")

    R = 6371.0
    lat1_rad, lon1_rad = radians(office_lat), radians(office_lon)
    lat2_rad, lon2_rad = radians(user_lat), radians(user_lon)
    
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    
    a = sin(dlat / 2)*2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)*2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    
    distance_km = R * c
    distance_m = distance_km * 1000
    
    logger.info(f"Рассчитанное расстояние: {distance_m:.2f} метров. Разрешенный радиус: {CONFIG.OFFICE_RADIUS_METERS} м.")

    if distance_m <= CONFIG.OFFICE_RADIUS_METERS:
       python
    from utils import start_work_logic
    await start_work_logic(update, context, user.id, is_remote=False)
    else:
        await update.message.reply_text(
            f"Вы находитесь слишком далеко от офиса ({int(distance_m)} м). Пожалуйста, подойдите ближе.",
            reply_markup=await MenuGenerator.get_main_menu(user.id)
        )
    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = "Действие отменено."

    if update.callback_query:
        await update.callback_query.answer()
        user_info = db.get_user(user_id)
        session_state = db.get_session_state(user_id)
        if user_info and user_info.get('role') in ['admin', 'manager']:
            reply_markup = MenuGenerator.get_manager_menu()
        elif session_state:
            reply_markup = MenuGenerator.get_working_menu()
        else:
            reply_markup = await MenuGenerator.get_main_menu(user_id)
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=await MenuGenerator.get_main_menu(user_id))

    context.user_data.clear()
    return ConversationHandler.END

absence_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(ask_for_dates_text, pattern='^(request_remote_work|absence_sick|absence_vacation|absence_trip|request_day_off|absence_sick_child)$')],
    states={GET_DATES_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_dates_text)]},
    fallbacks=[CommandHandler('cancel', cancel_conversation)],
    per_message=False
)
report_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(ask_for_report_dates, pattern='^report_custom_period_')],
    states={GET_REPORT_DATES: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_report_dates)]},
    fallbacks=[CommandHandler('cancel', cancel_conversation)],
    per_message=False
)
location_conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(ask_for_location, pattern='^start_work_office_location$')],
    states={GET_LOCATION: [MessageHandler(filters.LOCATION, process_location)]},
    fallbacks=[CallbackQueryHandler(cancel_conversation, pattern='^cancel_action$'), CommandHandler('cancel', cancel_conversation)],
    per_message=False
)