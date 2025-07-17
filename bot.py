# =================================================================
#          КОД BOT.PY - ФИНАЛЬНАЯ ВЕРСИЯ
# =================================================================
import datetime
import json
import re
import os
import pytz
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters
)
import database as db

# --- ЗАГРУЗКА СЕКРЕТНЫХ ДАННЫХ И НАСТРОЙКИ ---
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
LOCAL_TZ = pytz.timezone('Asia/Barnaul')

ADMIN_IDS = [384630608] 
DAILY_BREAK_LIMIT_SECONDS = 3600
MIN_WORK_SECONDS = 8 * 3600

# Состояния для диалогов
GET_DATES_TEXT, GET_REPORT_DATES = range(2)

absence_type_map = {
    'absence_sick': 'Больничный', 'absence_vacation': 'Отпуск',
    'absence_trip': 'Командировка', 'request_remote_work': 'Удаленная работа',
    'request_day_off': 'Отгул'
}

# --- Вспомогательные функции ---
def get_now():
    return datetime.datetime.now(LOCAL_TZ)

def seconds_to_str(seconds):
    if not isinstance(seconds, (int, float)) or seconds < 0: seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours} ч {minutes} мин"

async def end_workday_logic(update, context: ContextTypes.DEFAULT_TYPE, user_id, is_early_leave=False, forgive_debt=False, used_bank_time=0):
    session_state = db.get_session_state(user_id)
    if not session_state: return
    start_time = session_state['start_time']
    end_time = get_now()
    total_break_seconds = session_state.get('total_break_seconds', 0)
    work_duration_seconds = (end_time - start_time).total_seconds() - total_break_seconds
    work_type = "remote" if session_state.get('is_remote') else "office"
    db.add_work_log(user_id, start_time, end_time, int(work_duration_seconds), total_break_seconds, work_type)
    
    if not is_early_leave and session_state.get('status') == 'working':
        unused_break_time = DAILY_BREAK_LIMIT_SECONDS - total_break_seconds
        if unused_break_time > 0:
            db.update_time_bank(user_id, unused_break_time)

    db.delete_session_state(user_id)
    
    work_time_str = seconds_to_str(work_duration_seconds)
    message_text = f"Рабочий день ({'удаленно' if work_type == 'remote' else 'в офисе'}) завершен. Вы отработали: {work_time_str}."

    if used_bank_time > 0:
        message_text += f"\nИз банка времени списано: {seconds_to_str(int(used_bank_time))}."
    elif is_early_leave and not forgive_debt:
        debt_seconds = MIN_WORK_SECONDS - work_duration_seconds
        if debt_seconds > 0:
            db.add_work_debt(user_id, int(debt_seconds))
            debt_str = seconds_to_str(debt_seconds)
            message_text += f"\n\nВам начислена отработка: **{debt_str}**."
    
    main_menu_markup = await get_main_menu(update, context, user_id)
    if main_menu_markup:
        await context.bot.send_message(user_id, message_text, reply_markup=main_menu_markup, parse_mode='Markdown')
    else:
        await context.bot.send_message(user_id, message_text, parse_mode='Markdown')

# --- Функции для создания меню ---
async def get_main_menu(update, context, user_id):
    today = get_now().date()
    
    absences = db.get_absences_for_user(user_id, today)
    if absences:
        absence = absences[0]
        absence_type = absence['absence_type'].lower()
        end_date_str = absence['end_date'].strftime('%d.%m.%Y')
        messages = {
            'отпуск': f"Вы в отпуске до {end_date_str}. Хорошего отдыха!",
            'больничный': f"Вы на больничном до {end_date_str}. Скорейшего выздоровления!",
            'командировка': f"Вы в командировке до {end_date_str}. Успешной поездки!"
        }
        text = messages.get(absence_type, f"У вас оформлено отсутствие до {end_date_str}.")
        
        if update and hasattr(update, 'message') and update.message:
            await update.message.reply_text(text)
        elif update and hasattr(update, 'callback_query') and update.callback_query:
             await update.callback_query.edit_message_text(text)
        elif context:
            await context.bot.send_message(user_id, text)
        return None

    is_weekend = today.weekday() >= 5
    today_logs = db.get_todays_work_log_for_user(user_id)
    if today_logs and not is_weekend:
        is_weekend = True

    if is_weekend:
        keyboard = [
            [InlineKeyboardButton("🛠️ Доп. работа", callback_data='additional_work_menu')],
            [InlineKeyboardButton("❓ Помощь", callback_data='help_button')]
        ]
    else:
        today_str = str(today)
        approved_remote_work = db.get_approved_request(user_id, 'Удаленная работа', today_str)
        keyboard = []
        if approved_remote_work:
            keyboard.append([InlineKeyboardButton("☀️ Начать работу (удаленно)", callback_data='start_work_remote')])
        else:
            keyboard.append([InlineKeyboardButton("☀️ Начать рабочий день", callback_data='start_work_office')])
        keyboard.extend([
            [InlineKeyboardButton("🏦 Банк времени", callback_data='show_time_bank')],
            [InlineKeyboardButton("🛠️ Доп. работа", callback_data='additional_work_menu')],
            [InlineKeyboardButton("📝 Оформить отсутствие", callback_data='absence_menu')],
            [InlineKeyboardButton("📊 Запросить отчет", callback_data='request_report')],
            [InlineKeyboardButton("❓ Помощь", callback_data='help_button')]
        ])
    return InlineKeyboardMarkup(keyboard)

def get_manager_menu():
    keyboard = [
        [InlineKeyboardButton("👨‍💻 Статус команды", callback_data='team_status_button')],
        [InlineKeyboardButton("📊 Отчет по команде", callback_data='manager_report_button')],
        [InlineKeyboardButton("❓ Помощь", callback_data='help_button')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_report_period_menu(is_manager=False, in_session=False):
    base_callback = "manager" if is_manager else "employee"
    keyboard = [
        [InlineKeyboardButton("📊 Отчет за сегодня", callback_data=f'report_today_{base_callback}')],
        [InlineKeyboardButton("🗓️ Отчет за текущий месяц", callback_data=f'report_this_month_{base_callback}')],
        [InlineKeyboardButton("📅 Выбрать другой период", callback_data=f'report_custom_period_{base_callback}')]
    ]
    back_button_data = 'back_to_main_menu'
    if is_manager:
        back_button_data = 'back_to_manager_menu'
    elif in_session:
        back_button_data = 'back_to_working_menu'
    keyboard.append([InlineKeyboardButton("« Назад", callback_data=back_button_data)])
    return InlineKeyboardMarkup(keyboard)

def get_additional_work_menu(user_id):
    total_debt_seconds = db.get_total_debt(user_id)
    keyboard = [[InlineKeyboardButton("🏦 Начать работу в банк времени", callback_data='start_banking_work')]]
    if total_debt_seconds > 0:
        debt_str = seconds_to_str(total_debt_seconds)
        keyboard.insert(0, [InlineKeyboardButton(f"Погасить долг ({debt_str})", callback_data='start_debt_work')])
    
    keyboard.append([InlineKeyboardButton("« Назад", callback_data='back_to_main_menu')])
    return InlineKeyboardMarkup(keyboard)

def get_extra_work_active_menu(status, start_time):
    duration_str = seconds_to_str((get_now() - start_time).total_seconds())
    
    if status == 'clearing_debt':
        text = f"Идет отработка долга. Прошло: {duration_str}"
        button_text = "Закончить отработку"
        callback_data = "end_debt_work"
    else: # banking_time
        text = f"Идет работа в банк времени. Накоплено: {duration_str}"
        button_text = "Закончить работу в банк"
        callback_data = "end_banking_work"

    keyboard = [[InlineKeyboardButton(button_text, callback_data=callback_data)]]
    return text, InlineKeyboardMarkup(keyboard)

def get_absence_menu():
    keyboard = [[InlineKeyboardButton("💻 Удаленная работа (запрос)", callback_data='request_remote_work')], [InlineKeyboardButton("🙋‍♂️ Попросить отгул", callback_data='request_day_off')], [InlineKeyboardButton("🤧 Больничный", callback_data='absence_sick')], [InlineKeyboardButton("🌴 Отпуск", callback_data='absence_vacation')], [InlineKeyboardButton("✈️ Командировка", callback_data='absence_trip')], [InlineKeyboardButton("« Назад", callback_data='back_to_main_menu')]]
    return InlineKeyboardMarkup(keyboard)

def get_working_menu():
    keyboard = [[InlineKeyboardButton("🌙 Закончить рабочий день", callback_data='end_work')], [InlineKeyboardButton("☕ Уйти на перерыв", callback_data='start_break_choice')], [InlineKeyboardButton("🏦 Банк времени", callback_data='show_time_bank')], [InlineKeyboardButton("📊 Запросить отчет", callback_data='request_report'), InlineKeyboardButton("⏱️ Мое время", callback_data='show_status')], [InlineKeyboardButton("❓ Помощь", callback_data='help_button')]]
    return InlineKeyboardMarkup(keyboard)

def get_break_menu():
    keyboard = [[InlineKeyboardButton("▶️ Вернуться с перерыва", callback_data='end_break')], [InlineKeyboardButton("🏦 Банк времени", callback_data='show_time_bank')], [InlineKeyboardButton("📊 Запросить отчет", callback_data='request_report'), InlineKeyboardButton("⏱️ Мое время", callback_data='show_status')], [InlineKeyboardButton("❓ Помощь", callback_data='help_button')]]
    return InlineKeyboardMarkup(keyboard)

def get_early_leave_menu():
    keyboard = [
        [InlineKeyboardButton("Использовать банк времени", callback_data='end_work_use_bank')],
        [InlineKeyboardButton("Запросить согласование", callback_data='end_work_ask_manager')],
        [InlineKeyboardButton("« Отмена", callback_data='back_to_working_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Логика диалогов ---
async def ask_for_dates_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    absence_type = query.data
    context.user_data['absence_type'] = absence_type
    absence_name = absence_type_map.get(absence_type, "отсутствие").lower()
    prompt_text = f"Введите даты для '{absence_name}', например: 01.08.2025 - 15.08.2025"
    if absence_type in ['request_remote_work', 'request_day_off']:
        prompt_text = f"Введите дату для '{absence_name}', например: 15.08.2025"
    await query.edit_message_text(f"{prompt_text}\n\nДля отмены введите /cancel")
    return GET_DATES_TEXT

async def process_dates_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_input = update.message.text
    absence_type_key = context.user_data.get('absence_type')
    absence_name = absence_type_map.get(absence_type_key, "Отсутствие")
    try:
        found_dates = re.findall(r'\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b', user_input)
        if len(found_dates) < 1:
            await update.message.reply_text("Не могу найти ни одной даты. Попробуйте формат: ДД.ММ.ГГГГ или введите /cancel для отмены.")
            return GET_DATES_TEXT
        parsed_dates = []
        for day, month, year in found_dates:
            if len(year) == 2: year = f"20{year}"
            parsed_dates.append(datetime.date(int(year), int(month), int(day)))
        start_date = min(parsed_dates)
        end_date = max(parsed_dates) if len(parsed_dates) > 1 else start_date
        user_info = db.get_user(user.id)
        
        if absence_type_key in ['request_remote_work', 'request_day_off']:
            if not user_info or (not user_info.get('manager_id_1') and not user_info.get('manager_id_2')):
                await update.message.reply_text("Ошибка: за вами не закреплен руководитель.", reply_markup=await get_main_menu(update, context, user.id))
                return ConversationHandler.END
            text_for_manager = f"Сотрудник {user_info['full_name']} запрашивает '{absence_name}' на {start_date.strftime('%d.%m.%Y')}."
            request_type_for_db = 'Удаленная работа' if absence_type_key == 'request_remote_work' else 'Отгул'
            request_id = db.create_request(user.id, request_type_for_db, {'date': str(start_date)})
            keyboard = [[InlineKeyboardButton("✅ Одобрить", callback_data=f'approve_{request_id}'), InlineKeyboardButton("❌ Отклонить", callback_data=f'deny_{request_id}')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            msg_id_1, msg_id_2 = None, None
            if user_info.get('manager_id_1'):
                msg1 = await context.bot.send_message(user_info['manager_id_1'], text_for_manager, reply_markup=reply_markup)
                msg_id_1 = msg1.message_id
            if user_info.get('manager_id_2') and user_info.get('manager_id_2') != user_info.get('manager_id_1'):
                msg2 = await context.bot.send_message(user_info['manager_id_2'], text_for_manager, reply_markup=reply_markup)
                msg_id_2 = msg2.message_id
            db.update_request_messages(request_id, msg_id_1, msg_id_2)
            await update.message.reply_text(f"Ваш запрос на '{absence_name}' отправлен.", reply_markup=await get_main_menu(update, context, user.id))
        else:
            db.add_absence(user.id, absence_name, str(start_date), str(end_date))
            await update.message.reply_text(f"{absence_name} с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')} успешно зарегистрирован.", reply_markup=await get_main_menu(update, context, user.id))
            if user_info:
                text_for_manager = (f"FYI: Сотрудник {user_info['full_name']} оформил '{absence_name}' с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')}.")
                if user_info.get('manager_id_1'): await context.bot.send_message(user_info['manager_id_1'], text_for_manager)
                if user_info.get('manager_id_2') and user_info.get('manager_id_2') != user_info.get('manager_id_1'): await context.bot.send_message(user_info['manager_id_2'], text_for_manager)
        
        context.user_data.clear()
        return ConversationHandler.END
    except (ValueError, TypeError):
        await update.message.reply_text("Неверный формат даты. Попробуйте еще раз или введите /cancel для отмены.")
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
    user_info = db.get_user(user_id)
    report_type = context.user_data.get('report_type')
    try:
        found_dates = re.findall(r'\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b', update.message.text)
        if len(found_dates) < 1:
            await update.message.reply_text("Не могу найти дат. Попробуйте формат: ДД.ММ.ГГГГ - ДД.ММ.ГГГГ")
            return GET_REPORT_DATES
        parsed_dates = []
        for day, month, year in found_dates:
            if len(year) == 2: year = f"20{year}"
            parsed_dates.append(datetime.date(int(year), int(month), int(day)))
        start_date = min(parsed_dates)
        end_date = max(parsed_dates) if len(parsed_dates) > 1 else start_date
        
        await update.message.delete()
        
        if report_type == 'manager':
            await send_manager_report(user_id, context, start_date, end_date)
        else:
            await send_employee_report(user_id, context, start_date, end_date)
            
        return ConversationHandler.END
    except (ValueError, TypeError):
        await update.message.reply_text("Неверный формат. Попробуйте еще раз или введите /cancel")
        return GET_REPORT_DATES

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user_info = db.get_user(user_id)
    session_state = db.get_session_state(user_id)
    
    text = "Действие отменено."
    reply_markup = await get_main_menu(update, context, user_id)
    if reply_markup is None:
        return ConversationHandler.END
        
    if user_info and user_info['role'] in ['manager', 'admin']:
        reply_markup = get_manager_menu()
    elif session_state:
        reply_markup = get_working_menu()
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

    context.user_data.clear()
    return ConversationHandler.END

# --- Логика отчетов и статусов ---
async def send_employee_report(user_id, context: ContextTypes.DEFAULT_TYPE, start_date, end_date):
    work_logs = db.get_work_logs_for_user(user_id, str(start_date), str(end_date + datetime.timedelta(days=1)))
    total_work_seconds = sum(log['total_work_seconds'] for log in work_logs)
    total_break_seconds = sum(log['total_break_seconds'] for log in work_logs)
    report_text = f"**Отчет для вас за период с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')}**\n\n"
    report_text += f"**Чистое рабочее время:** {seconds_to_str(total_work_seconds)}\n"
    report_text += f"**Время на перерывах:** {seconds_to_str(total_break_seconds)}\n\n"
    
    cleared_debt = db.get_debt_logs_for_user(user_id, str(start_date), str(end_date + datetime.timedelta(days=1)))
    total_current_debt = db.get_total_debt(user_id)
    if cleared_debt > 0 or total_current_debt > 0:
        report_text += f"**Отработка:**\n"
        report_text += f"Закрыто долга за период: {seconds_to_str(cleared_debt)}\n"
        report_text += f"Общий текущий долг: {seconds_to_str(total_current_debt)}"

    session_state = db.get_session_state(user_id)
    back_callback = 'back_to_working_menu' if session_state else 'back_to_main_menu'
    keyboard = [[InlineKeyboardButton("« Назад", callback_data=back_callback)]]
    await context.bot.send_message(chat_id=user_id, text=report_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def send_manager_report(manager_id, context: ContextTypes.DEFAULT_TYPE, start_date, end_date):
    team_members = db.get_managed_users(manager_id)
    if not team_members:
        await context.bot.send_message(chat_id=manager_id, text="За вами не закреплено ни одного сотрудника.")
        return
        
    report_lines = [f"**Отчет по команде за период с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')}**\n"]
    
    for member in team_members:
        member_id = member['user_id']
        member_name = member['full_name']
        
        logs = db.get_work_logs_for_user(member_id, str(start_date), str(end_date + datetime.timedelta(days=1)))
        absences = db.get_absences_for_user(member_id, start_date, end_date)
        
        employee_line = f"👤 **{member_name}**:"
        
        if logs:
            total_work_seconds_member = sum(log['total_work_seconds'] for log in logs)
            total_break_seconds_member = sum(log['total_break_seconds'] for log in logs)
            employee_line += f" отработано {seconds_to_str(total_work_seconds_member)} (перерывы: {seconds_to_str(total_break_seconds_member)})."
        
        if absences:
            absence_details = []
            for a in absences:
                start_str = a['start_date'].strftime('%d.%m')
                end_str = a['end_date'].strftime('%d.%m')
                period = start_str if start_str == end_str else f"{start_str}-{end_str}"
                absence_details.append(f"{a['absence_type']} ({period})")
            
            if logs:
                employee_line += f"\n  - *Отсутствия:* {', '.join(absence_details)}"
            else:
                 employee_line += f" *{', '.join(absence_details)}.*"
        
        if not logs and not absences:
            employee_line += " нет данных за период."
            
        report_lines.append(employee_line)

    report_text = "\n".join(report_lines)
    keyboard = [[InlineKeyboardButton("« Назад", callback_data='back_to_manager_menu')]]
    await context.bot.send_message(chat_id=manager_id, text=report_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def get_team_status_logic(manager_id, context: ContextTypes.DEFAULT_TYPE):
    team_members = db.get_managed_users(manager_id)
    if not team_members:
        await context.bot.send_message(chat_id=manager_id, text="За вами не закреплено ни одного сотрудника.")
        return
    
    status_lines = [f"**Статус команды на {get_now().strftime('%d.%m.%Y %H:%M')}**\n"]
    today = get_now().date()
    
    for member in team_members:
        member_id = member['user_id']
        member_name = member['full_name']
        session = db.get_session_state(member_id)
        
        if session and session.get('status'):
            status = session.get('status')
            start_time = session.get('start_time')
            if status == 'working':
                status_lines.append(f"🟢 {member_name}: Работает с {start_time.strftime('%H:%M')}")
            elif status == 'on_break':
                break_start = session.get('break_start_time')
                status_lines.append(f"☕️ {member_name}: На перерыве с {break_start.strftime('%H:%M')}")
            else:
                status_lines.append(f"⚙️ {member_name}: Доп. работа с {start_time.strftime('%H:%M')}")
        else:
            absences = db.get_absences_for_user(member_id, today)
            if absences:
                status_lines.append(f"🏖️ {member_name}: {absences[0]['absence_type']}")
            else:
                last_log = db.get_todays_work_log_for_user(member_id)
                if last_log:
                    status_lines.append(f"⚪️ {member_name}: Закончил работу в {last_log['end_time'].astimezone(LOCAL_TZ).strftime('%H:%M')}")
                else:
                    status_lines.append(f"⚪️ {member_name}: Не в сети")

    await context.bot.send_message(chat_id=manager_id, text="\n".join(status_lines), parse_mode='Markdown')

# --- Стандартные команды ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_info = db.get_user(user.id)
    if not user_info:
        await update.message.reply_text("Ваш аккаунт не зарегистрирован. Обратитесь к администратору.")
        return
    
    main_menu_markup = await get_main_menu(update, context, user.id)
    if main_menu_markup is None:
        return

    if user_info['role'] in ['manager', 'admin']:
        await update.message.reply_text("Меню руководителя:", reply_markup=get_manager_menu())
        return
        
    session_state = db.get_session_state(user.id)
    if not session_state or not session_state.get('status'):
        await update.message.reply_text("Выберите действие:", reply_markup=main_menu_markup)
    else:
        status = session_state.get('status')
        if status == 'working': await update.message.reply_text("Вы работаете. Меню восстановлено:", reply_markup=get_working_menu())
        elif status == 'on_break': await update.message.reply_text("Вы на перерыве. Меню восстановлено:", reply_markup=get_break_menu())
        elif status in ['clearing_debt', 'banking_time']:
            text, markup = get_extra_work_active_menu(status, session_state['start_time'])
            await update.message.reply_text(text, reply_markup=markup)

async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Формат: /adduser ID \"Имя Фамилия\" [роль] [ID_рук_1] [ID_рук_2]")
            return
        
        user_id_str = args[0]
        match = re.search(r'"(.*?)"', " ".join(args[1:]))
        if not match:
            full_name = args[1]
            remaining_args = args[2:]
        else:
            full_name = match.group(1)
            remaining_args_str = " ".join(args[1:]).replace(f'"{full_name}"', '').strip()
            remaining_args = remaining_args_str.split()

        target_user_id = int(user_id_str)
        role = 'employee'
        manager_1 = None
        manager_2 = None
        
        if len(remaining_args) > 0: role = remaining_args[0]
        if len(remaining_args) > 1: manager_1 = int(remaining_args[1])
        if len(remaining_args) > 2: manager_2 = int(remaining_args[2])

        db.add_or_update_user(target_user_id, full_name, role, manager_1, manager_2)
        await update.message.reply_text(f"Пользователь {full_name} (ID: {target_user_id}) сохранен.")
    except (IndexError, ValueError) as e:
        await update.message.reply_text(f"Ошибка в аргументах: {e}. Проверьте формат.")

async def show_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS: return
    all_users = db.get_all_users()
    if not all_users:
        await update.message.reply_text("В базе данных пока нет пользователей.")
        return
    keyboard = [[InlineKeyboardButton(f"{user['full_name']} ({user['role']})", callback_data=f"user_details_{user['user_id']}")] for user in all_users]
    await update.message.reply_text("Список пользователей:", reply_markup=InlineKeyboardMarkup(keyboard))

async def deluser_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return
    try:
        target_user_id = int(context.args[0])
        user_info = db.get_user(target_user_id)
        if not user_info:
            await update.message.reply_text(f"Пользователь с ID {target_user_id} не найден.")
            return
            
        db.delete_user(target_user_id)
        await update.message.reply_text(f"Пользователь {user_info['full_name']} (ID: {target_user_id}) успешно удален.")
    except (IndexError, ValueError):
        await update.message.reply_text("Неверный формат. Используйте: /deluser <ID>")

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_info = db.get_user(update.effective_user.id)
    session_state = db.get_session_state(update.effective_user.id)
    is_manager = user_info and user_info['role'] in ['manager', 'admin']
    await update.message.reply_text("Выберите период для отчета:", reply_markup=get_report_period_menu(is_manager=is_manager, in_session=bool(session_state)))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_info = db.get_user(user_id)
    help_text = "Инструкция по использованию бота:\n\n"
    if user_info and user_info['role'] == 'admin':
        help_text += ("**Вы — Администратор.**\n\n"
                      "`/adduser ID \"Имя Фамилия\" [роль] [ID_рук]` - добавить/изменить пользователя.\n"
                      "`/users` - посмотреть список всех пользователей.\n"
                      "`/deluser ID` - удалить пользователя по ID.\n"
                      "`/report` - отчет по команде.\n"
                      "`/help` - эта справка.")
    elif user_info and user_info['role'] == 'manager':
        help_text += ("**Вы — Руководитель.**\n\n"
                      "Команда `/start` вызовет ваше меню с кнопкой отчета по команде.\n"
                      "Вы будете получать запросы на согласование отгулов, удаленной работы и раннего ухода от ваших сотрудников. Реагируйте на них кнопками.\n"
                      "`/help` - эта справка.")
    elif user_info and user_info['role'] == 'employee':
        help_text += ("**Вы — Сотрудник.**\n\n"
                      "- Начинайте и заканчивайте рабочий день кнопками.\n"
                      "- Фиксируйте перерывы.\n"
                      "- Запрашивайте отсутствия через меню 'Оформить отсутствие'.\n"
                      "- Проверяйте накопленное время в 'Банке времени'.\n"
                      "`/help` - эта справка.")
    else:
        help_text += "Ваш аккаунт не зарегистрирован. Пожалуйста, обратитесь к администратору."
    
    if update.callback_query:
        await context.bot.send_message(chat_id=user_id, text=help_text, parse_mode='Markdown')
    else:
        await update.message.reply_text(help_text, parse_mode='Markdown')

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"Произошла ошибка: {context.error}")

# --- Основной обработчик кнопок ---
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    command = query.data
    
    session_state = db.get_session_state(user_id)
    user_info = db.get_user(user_id)
    is_manager = user_info and user_info['role'] in ['manager', 'admin']
    
    # ... (код обработчика кнопок) ...

# --- Функция запуска бота ---
def main() -> None:
    db.init_db()
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("ОШИБКА: Токен не найден.")
        return

    application = Application.builder().token(token).build()
    
    application.add_error_handler(error_handler)
    
    # Регистрация всех хендлеров
    absence_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(ask_for_dates_text, pattern='^request_remote_work$'),
            CallbackQueryHandler(ask_for_dates_text, pattern='^absence_sick$'),
            CallbackQueryHandler(ask_for_dates_text, pattern='^absence_vacation$'),
            CallbackQueryHandler(ask_for_dates_text, pattern='^absence_trip$'),
            CallbackQueryHandler(ask_for_dates_text, pattern='^request_day_off$'),
        ],
        states={GET_DATES_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_dates_text)]},
        fallbacks=[CommandHandler('cancel', cancel_conversation)],
    )
    report_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_for_report_dates, pattern='^report_custom_period_')],
        states={GET_REPORT_DATES: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_report_dates)]},
        fallbacks=[CommandHandler('cancel', cancel_conversation)],
    )

    application.add_handler(absence_conv_handler)
    application.add_handler(report_conv_handler)
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("adduser", add_user))
    application.add_handler(CommandHandler("users", show_users))
    application.add_handler(CommandHandler("deluser", deluser_command))
    application.add_handler(CommandHandler("report", report_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    
    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()