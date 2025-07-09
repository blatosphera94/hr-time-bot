# =================================================================
#          КОД BOT.PY - ФИНАЛЬНАЯ ИСПРАВЛЕННАЯ ВЕРСИЯ
# =================================================================
import datetime
import json
import re
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters
)
import database as db

# --- ЗАГРУЗКА СЕКРЕТНЫХ ДАННЫХ ---
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("7439821992:AAFl9-sBqA580zrCJB1ooMYFPQi7vs2JbMk")

# --- ГЛОБАЛЬНЫЕ НАСТРОЙКИ ---
ADMIN_IDS = [384630608] # !!! ЗАМЕНИТЕ НА СВОЙ ID АДМИНИСТРАТОРА !!!
DAILY_BREAK_LIMIT_SECONDS = 3600
MIN_WORK_SECONDS = 8 * 3600

# Состояния для диалогов
(
    GET_ABSENCE_DATES, GET_REPORT_DATES
) = range(2)

absence_type_map = {
    'absence_sick': 'Больничный',
    'absence_vacation': 'Отпуск',
    'absence_trip': 'Командировка',
    'request_remote_work': 'Удаленная работа'
}

# --- Вспомогательные функции ---
def seconds_to_str(seconds):
    if not isinstance(seconds, (int, float)) or seconds < 0: seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours} ч {minutes} мин"

async def end_workday_logic(user_id, context: ContextTypes.DEFAULT_TYPE, is_early_leave=False, used_bank_time=0):
    session_state = db.get_session_state(user_id)
    if not session_state: return
    start_time = session_state['start_time']
    end_time = datetime.datetime.now()
    total_break_seconds = session_state.get('total_break_seconds', 0)
    work_duration_seconds = (end_time - start_time).total_seconds() - total_break_seconds
    work_type = "remote" if session_state.get('is_remote') else "office"
    db.add_work_log(user_id, str(start_time), str(end_time), int(work_duration_seconds), total_break_seconds, work_type)
    
    if not is_early_leave:
        unused_break_time = DAILY_BREAK_LIMIT_SECONDS - total_break_seconds
        if unused_break_time > 0:
            db.update_time_bank(user_id, unused_break_time)

    db.delete_session_state(user_id)
    
    work_time_str = seconds_to_str(work_duration_seconds)
    message_text = f"Рабочий день ({'удаленно' if work_type == 'remote' else 'в офисе'}) завершен. Вы отработали: {work_time_str}."

    if used_bank_time > 0:
        message_text += f"\nИз банка времени списано: {seconds_to_str(int(used_bank_time))}."
    elif is_early_leave:
        debt_seconds = MIN_WORK_SECONDS - work_duration_seconds
        if debt_seconds > 0:
            db.add_work_debt(user_id, int(debt_seconds))
            debt_str = seconds_to_str(debt_seconds)
            message_text += f"\n\nВам начислена отработка: **{debt_str}**."
    
    user_info = db.get_user(user_id)
    if user_info and user_info['role'] in ['manager', 'admin']:
        main_menu_markup = get_manager_menu()
    else:
        main_menu_markup = await get_main_menu(user_id)
    
    await context.bot.send_message(user_id, message_text, reply_markup=main_menu_markup, parse_mode='Markdown')

# --- Функции для создания меню ---
async def get_main_menu(user_id):
    today_str = str(datetime.date.today())
    approved_remote_work = db.get_approved_request(user_id, 'Удаленная работа', today_str)
    keyboard = []
    if approved_remote_work:
        keyboard.append([InlineKeyboardButton("☀️ Начать работу (удаленно)", callback_data='start_work_remote')])
    else:
        keyboard.append([InlineKeyboardButton("☀️ Начать рабочий день", callback_data='start_work_office')])
    keyboard.extend([
        [InlineKeyboardButton("🏦 Банк времени", callback_data='show_time_bank')],
        [InlineKeyboardButton("🛠️ Отработка", callback_data='debt_menu')],
        [InlineKeyboardButton("📝 Оформить отсутствие", callback_data='absence_menu')],
        [InlineKeyboardButton("📊 Запросить отчет", callback_data='request_report')]
    ])
    return InlineKeyboardMarkup(keyboard)

def get_manager_menu():
    keyboard = [[InlineKeyboardButton("📊 Отчет по команде", callback_data='manager_report_button')]]
    return InlineKeyboardMarkup(keyboard)

def get_report_period_menu(is_manager=False):
    keyboard = [
        [InlineKeyboardButton("📊 Отчет за сегодня", callback_data='report_today')],
        [InlineKeyboardButton("🗓️ Отчет за текущий месяц", callback_data='report_this_month')],
        [InlineKeyboardButton("📅 Выбрать другой период", callback_data='report_custom_period')]
    ]
    if is_manager:
        keyboard.append([InlineKeyboardButton("« Назад", callback_data='back_to_manager_menu')])
    else:
        keyboard.append([InlineKeyboardButton("« Назад", callback_data='back_to_main_menu')])
    return InlineKeyboardMarkup(keyboard)

async def get_debt_menu(user_id):
    total_debt_seconds = db.get_total_debt(user_id)
    debt_str = seconds_to_str(total_debt_seconds)
    text = "У вас нет задолженностей по отработке. Отлично!"
    keyboard = [[InlineKeyboardButton("« Назад", callback_data='back_to_main_menu')]]
    if total_debt_seconds > 0:
        text = f"Ваша задолженность: **{debt_str}**."
        keyboard.insert(0, [InlineKeyboardButton("Начать отработку", callback_data='start_debt_work')])
    return text, InlineKeyboardMarkup(keyboard)

def get_debt_working_menu(total_debt_seconds):
    debt_str = seconds_to_str(total_debt_seconds)
    text = f"Идет отработка. Текущий долг: {debt_str}"
    keyboard = [[InlineKeyboardButton("Закончить отработку", callback_data='end_debt_work')]]
    return text, InlineKeyboardMarkup(keyboard)
def get_absence_menu():
    keyboard = [[InlineKeyboardButton("💻 Удаленная работа (запрос)", callback_data='request_remote_work')], [InlineKeyboardButton("🙋‍♂️ Попросить отгул", callback_data='request_day_off')], [InlineKeyboardButton("🤧 Больничный", callback_data='absence_sick')], [InlineKeyboardButton("🌴 Отпуск", callback_data='absence_vacation')], [InlineKeyboardButton("✈️ Командировка", callback_data='absence_trip')], [InlineKeyboardButton("« Назад", callback_data='back_to_main_menu')]]
    return InlineKeyboardMarkup(keyboard)
def get_working_menu():
    keyboard = [[InlineKeyboardButton("🌙 Закончить рабочий день", callback_data='end_work')], [InlineKeyboardButton("☕ Уйти на перерыв", callback_data='start_break_choice')], [InlineKeyboardButton("🏦 Банк времени", callback_data='show_time_bank')], [InlineKeyboardButton("📊 Запросить отчет", callback_data='request_report'), InlineKeyboardButton("⏱️ Мое время", callback_data='show_status')]]
    return InlineKeyboardMarkup(keyboard)
def get_break_menu():
    keyboard = [[InlineKeyboardButton("▶️ Вернуться с перерыва", callback_data='end_break')], [InlineKeyboardButton("🏦 Банк времени", callback_data='show_time_bank')], [InlineKeyboardButton("📊 Запросить отчет", callback_data='request_report'), InlineKeyboardButton("⏱️ Мое время", callback_data='show_status')]]
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
    if absence_type == 'request_remote_work':
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
        # Для запросов на согласование
        if absence_type_key == 'request_remote_work':
            if not user_info or (not user_info.get('manager_id_1') and not user_info.get('manager_id_2')):
                await update.message.reply_text("Ошибка: за вами не закреплен руководитель.", reply_markup=await get_main_menu(user.id))
                return ConversationHandler.END
            text_for_manager = f"Сотрудник {user_info['full_name']} запрашивает '{absence_name}' на {start_date.strftime('%d.%m.%Y')}."
            manager_1 = user_info.get('manager_id_1')
            manager_2 = user_info.get('manager_id_2')
            msg_id_1, msg_id_2 = None, None
            if manager_1:
                msg1 = await context.bot.send_message(manager_1, text_for_manager)
                msg_id_1 = msg1.message_id
            if manager_2 and manager_2 != manager_1:
                msg2 = await context.bot.send_message(manager_2, text_for_manager)
                msg_id_2 = msg2.message_id
            request_id = db.create_request(user.id, 'remote_work', {'date': str(start_date)}, msg_id_1, msg_id_2)
            keyboard = [[InlineKeyboardButton("✅ Одобрить", callback_data=f'approve_{request_id}'), InlineKeyboardButton("❌ Отклонить", callback_data=f'deny_{request_id}')]]
            if msg_id_1: await context.bot.edit_message_reply_markup(chat_id=manager_1, message_id=msg_id_1, reply_markup=InlineKeyboardMarkup(keyboard))
            if msg_id_2: await context.bot.edit_message_reply_markup(chat_id=manager_2, message_id=msg_id_2, reply_markup=InlineKeyboardMarkup(keyboard))
            await update.message.reply_text(f"Ваш запрос на '{absence_name}' отправлен.", reply_markup=await get_main_menu(user.id))
        # Для обычных уведомлений
        else:
            db.add_absence(user.id, absence_name, str(start_date), str(end_date))
            await update.message.reply_text(f"{absence_name} с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')} успешно зарегистрирован.", reply_markup=await get_main_menu(user.id))
            if user_info:
                text_for_manager = (f"FYI: Сотрудник {user_info['full_name']} оформил '{absence_name}' с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')}.")
                if user_info.get('manager_id_1'): await context.bot.send_message(user_info['manager_id_1'], text_for_manager)
                if user_info.get('manager_id_2') and user_info['manager_id_2'] != user_info.get('manager_id_1'): await context.bot.send_message(user_info['manager_id_2'], text_for_manager)
        context.user_data.clear()
        return ConversationHandler.END
    except (ValueError, TypeError):
        await update.message.reply_text("Неверный формат даты. Попробуйте еще раз или введите /cancel для отмены.")
        return GET_ABSENCE_DATES
async def ask_for_report_dates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Введите период для отчета в формате: ДД.ММ.ГГГГ - ДД.ММ.ГГГГ\n\nДля отмены введите /cancel")
    return GET_REPORT_DATES
async def process_report_dates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user_info = db.get_user(user_id)
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
        
        if user_info and user_info['role'] in ['manager', 'admin']:
            await send_manager_report(user_id, context, start_date, end_date)
        else:
            await send_employee_report(user_id, context, start_date, end_date)
        
        if user_info and user_info['role'] in ['manager', 'admin']:
            await update.message.reply_text("Меню руководителя:", reply_markup=get_manager_menu())
        else:
            await update.message.reply_text("Выберите действие:", reply_markup=await get_main_menu(user_id))

        return ConversationHandler.END
    except (ValueError, TypeError):
        await update.message.reply_text("Неверный формат. Попробуйте еще раз или введите /cancel")
        return GET_REPORT_DATES
async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user_info = db.get_user(user_id)
    if user_info and user_info['role'] in ['manager', 'admin']:
        await update.message.reply_text("Действие отменено.", reply_markup=get_manager_menu())
    else:
        await update.message.reply_text("Действие отменено.", reply_markup=await get_main_menu(user_id))
    context.user_data.clear()
    return ConversationHandler.END

# --- Логика отчетов ---
async def send_employee_report(user_id, context: ContextTypes.DEFAULT_TYPE, start_date, end_date):
    work_logs = db.get_work_logs_for_user(user_id, str(start_date), str(end_date + datetime.timedelta(days=1)))
    total_work_seconds = sum(log['total_work_seconds'] for log in work_logs)
    cleared_debt = db.get_debt_logs_for_user(user_id, str(start_date), str(end_date + datetime.timedelta(days=1)))
    total_current_debt = db.get_total_debt(user_id)
    report_text = f"**Отчет для вас за период с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')}**\n\n"
    report_text += f"**1. Рабочее время**\n"
    report_text += f"Отработано за период: {seconds_to_str(total_work_seconds)}\n\n"
    report_text += f"**2. Время отработки**\n"
    report_text += f"Закрыто долга за период: {seconds_to_str(cleared_debt)}\n"
    report_text += f"Общий текущий долг: {seconds_to_str(total_current_debt)}"
    await context.bot.send_message(chat_id=user_id, text=report_text, parse_mode='Markdown')
async def send_manager_report(manager_id, context: ContextTypes.DEFAULT_TYPE, start_date, end_date):
    team_members = db.get_managed_users(manager_id)
    if not team_members:
        await context.bot.send_message(chat_id=manager_id, text="За вами не закреплено ни одного сотрудника.")
        return
    report_text = f"**Отчет по команде за период с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')}**\n\n"
    total_team_hours = 0
    for member in team_members:
        member_id = member['user_id']
        member_name = member['full_name']
        logs = db.get_work_logs_for_user(member_id, str(start_date), str(end_date + datetime.timedelta(days=1)))
        if not logs:
            report_text += f"👤 **{member_name}**: нет данных за период.\n"
            continue
        total_work_seconds_member = sum(log['total_work_seconds'] for log in logs)
        total_team_hours += total_work_seconds_member / 3600
        report_text += f"👤 **{member_name}**: отработано {seconds_to_str(total_work_seconds_member)}.\n"
    report_text += f"\n**Всего по команде:** {total_team_hours:.1f} ч."
    await context.bot.send_message(chat_id=manager_id, text=report_text, parse_mode='Markdown')

# --- Стандартные команды ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_info = db.get_user(user.id)
    if not user_info:
        await update.message.reply_text("Ваш аккаунт не зарегистрирован. Обратитесь к администратору.")
        return
    if user_info['role'] in ['manager', 'admin']:
        await update.message.reply_text("Меню руководителя:", reply_markup=get_manager_menu())
        return
    session_state = db.get_session_state(user.id)
    main_menu_markup = await get_main_menu(user.id)
    if not session_state or not session_state.get('status'):
        await update.message.reply_text("Выберите действие:", reply_markup=main_menu_markup)
    else:
        status = session_state.get('status')
        if status == 'working': await update.message.reply_text("Вы работаете. Меню восстановлено:", reply_markup=get_working_menu())
        elif status == 'on_break': await update.message.reply_text("Вы на перерыве. Меню восстановлено:", reply_markup=get_break_menu())
        elif status == 'clearing_debt':
            total_debt = db.get_total_debt(user.id)
            text, markup = get_debt_working_menu(total_debt)
            await update.message.reply_text(text, reply_markup=markup)
        else: await update.message.reply_text("Выберите действие:", reply_markup=main_menu_markup)
async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_id = update.effective_user.id
    if admin_id not in ADMIN_IDS:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Формат: /adduser ID Имя [роль] [ID_рук_1] [ID_рук_2]")
            return
        target_user_id = int(args[0])
        full_name = args[1] 
        role = 'employee'
        manager_1 = None
        manager_2 = None
        if len(args) > 2: role = args[2]
        if len(args) > 3: manager_1 = int(args[3])
        if len(args) > 4: manager_2 = int(args[4])
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
async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_info = db.get_user(update.effective_user.id)
    is_manager = user_info and user_info['role'] in ['manager', 'admin']
    await update.message.reply_text("Выберите период для отчета:", reply_markup=get_report_period_menu(is_manager=is_manager))
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"Произошла ошибка: {context.error}")

# --- Основной обработчик кнопок ---
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    command = query.data
    
    await query.answer()

    session_state = db.get_session_state(user_id)
    user_info = db.get_user(user_id)
    is_manager = user_info and user_info['role'] in ['manager', 'admin']
    
    if command == 'show_status':
        status_text = "Вы не в активной сессии."
        if session_state:
            status = session_state.get('status')
            if status == 'working':
                start_time = session_state.get('start_time')
                total_break_seconds = session_state.get('total_break_seconds', 0)
                remaining_break_str = seconds_to_str(DAILY_BREAK_LIMIT_SECONDS - total_break_seconds)
                status_text = f"Статус: Работаете\nОсталось перерыва на сегодня: {remaining_break_str}"
            elif status == 'on_break':
                break_start_time = session_state.get('break_start_time')
                if break_start_time:
                    elapsed_break = seconds_to_str((datetime.datetime.now() - break_start_time).total_seconds())
                    status_text = f"Статус: На перерыве\nПрошло времени: {elapsed_break}"
                else: status_text = "Статус: На перерыве"
            elif status == 'clearing_debt':
                total_debt = db.get_total_debt(user_id)
                status_text = f"Статус: Отработка\nТекущий долг: {seconds_to_str(total_debt)}"
        await query.answer(text=status_text, show_alert=True)
    
    elif command.startswith('approve_') or command.startswith('deny_'):
        if not (is_admin or is_manager):
            await context.bot.send_message(user_id, "У вас нет прав для этого действия.")
            return
        action, request_id_str = command.split('_')
        request_id = int(request_id_str)
        request_info = db.get_request(request_id)
        if not request_info or request_info['status'] != 'pending':
            await query.edit_message_text(f"Запрос уже был обработан.")
            return
        requester_info = db.get_user(request_info['requester_id'])
        if not requester_info:
            await query.edit_message_text("Не удалось найти сотрудника, отправившего запрос.")
            return
        manager_1_id, manager_2_id = requester_info.get('manager_id_1'), requester_info.get('manager_id_2')
        new_status = 'approved' if action == 'approve' else 'denied'
        db.update_request_status(request_id, new_status)
        await query.edit_message_text(f"Вы {'одобрили' if new_status == 'approved' else 'отклонили'} запрос от {requester_info['full_name']}.")
        other_manager_id = manager_2_id if user_id == manager_1_id else manager_1_id
        if other_manager_id:
            other_message_id = request_info.get('manager_2_message_id') if other_manager_id == manager_2_id else request_info.get('manager_1_message_id')
            if other_message_id:
                try: await context.bot.edit_message_text(f"Запрос от {requester_info['full_name']} был обработан другим руководителем. Статус: {new_status}.", chat_id=other_manager_id, message_id=other_message_id)
                except Exception as e: print(f"Не удалось обновить сообщение у второго менеджера: {e}")
        text_to_employee = f"Ваш запрос ('{request_info.get('request_type', 'Неизвестно')}') был {'одобрен' if new_status == 'approved' else 'отклонен'} руководителем."
        if request_info['request_type'] == 'early_leave' and new_status == 'approved':
            await end_workday_logic(requester_info['user_id'], context, is_early_leave=True)
        else:
            await context.bot.send_message(requester_info['user_id'], text_to_employee)
    
    elif command.startswith('user_details_'):
        target_user_id = int(command.split('_')[-1])
        info = db.get_user(target_user_id)
        text = f"Инфо:\nИмя: {info['full_name']}\nID: {info['user_id']}\nРоль: {info['role']}\nID Рук. 1: {info.get('manager_id_1', 'Н/Н')}\nID Рук. 2: {info.get('manager_id_2', 'Н/Н')}"
        keyboard = [[InlineKeyboardButton(f"❌ Удалить {info['full_name']}", callback_data=f"delete_user_{target_user_id}")], [InlineKeyboardButton("« Назад к списку", callback_data="show_all_users")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif command == "show_all_users":
        all_users = db.get_all_users()
        keyboard = [[InlineKeyboardButton(f"{u['full_name']} ({u['role']})", callback_data=f"user_details_{u['user_id']}")] for u in all_users]
        await query.edit_message_text("Список пользователей:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif command.startswith('delete_user_'):
        target_user_id = int(command.split('_')[-1])
        info = db.get_user(target_user_id)
        text = f"Вы уверены, что хотите удалить пользователя {info['full_name']}? Это действие необратимо."
        keyboard = [[InlineKeyboardButton("ДА, УДАЛИТЬ", callback_data=f"confirm_delete_{target_user_id}")], [InlineKeyboardButton("Отмена", callback_data=f"user_details_{target_user_id}")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif command.startswith('confirm_delete_'):
        target_user_id = int(command.split('_')[-1])
        db.delete_user(target_user_id)
        await query.edit_message_text("Пользователь успешно удален.")
        all_users = db.get_all_users()
        keyboard = [[InlineKeyboardButton(f"{u['full_name']} ({u['role']})", callback_data=f"user_details_{u['user_id']}")] for u in all_users]
        await context.bot.send_message(user_id, "Обновленный список пользователей:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif command == 'absence_menu':
        await query.edit_message_text("Выберите тип отсутствия:", reply_markup=get_absence_menu())
    
    elif command == 'back_to_main_menu':
        await query.edit_message_text("Выберите действие:", reply_markup=await get_main_menu(user_id))
    
    elif command == 'manager_report_button':
        await query.edit_message_text("Выберите период для отчета по команде:", reply_markup=get_report_period_menu(is_manager=True))
    
    elif command == 'report_today':
        today = datetime.date.today()
        await query.delete_message()
        if is_manager:
            await send_manager_report(user_id, context, today, today)
        else:
            await send_employee_report(user_id, context, today, today)
    
    elif command == 'report_this_month':
        today = datetime.date.today()
        first_day = today.replace(day=1)
        next_month = first_day.replace(day=28) + datetime.timedelta(days=4)
        last_day = next_month - datetime.timedelta(days=next_month.day)
        await query.delete_message()
        if is_manager:
            await send_manager_report(user_id, context, first_day, last_day)
        else:
            await send_employee_report(user_id, context, first_day, last_day)
    
    elif command == 'back_to_manager_menu':
        await query.edit_message_text("Меню руководителя:", reply_markup=get_manager_menu())
    
    elif command == 'request_day_off':
        if not user_info or (not user_info.get('manager_id_1') and not user_info.get('manager_id_2')):
            await context.bot.send_message(user_id, "Ошибка: за вами не закреплен руководитель.")
            return
        manager_1, manager_2 = user_info.get('manager_id_1'), user_info.get('manager_id_2')
        text_for_manager = f"Сотрудник {user_info['full_name']} запрашивает отгул."
        msg_id_1, msg_id_2 = None, None
        if manager_1:
            msg1 = await context.bot.send_message(manager_1, text_for_manager)
            msg_id_1 = msg1.message_id
        if manager_2 and manager_2 != manager_1:
            msg2 = await context.bot.send_message(manager_2, text_for_manager)
            msg_id_2 = msg2.message_id
        request_id = db.create_request(user_id, 'day_off', {}, msg_id_1, msg_id_2)
        keyboard = [[InlineKeyboardButton("✅ Одобрить", callback_data=f'approve_{request_id}'), InlineKeyboardButton("❌ Отклонить", callback_data=f'deny_{request_id}')]]
        if msg_id_1: await context.bot.edit_message_reply_markup(chat_id=manager_1, message_id=msg_id_1, reply_markup=InlineKeyboardMarkup(keyboard))
        if msg_id_2: await context.bot.edit_message_reply_markup(chat_id=manager_2, message_id=msg_id_2, reply_markup=InlineKeyboardMarkup(keyboard))
        await query.edit_message_text("Ваш запрос на отгул отправлен руководителю.", reply_markup=await get_main_menu(user_id))
    
    elif command == 'request_report':
        await query.edit_message_text("Выберите период для отчета:", reply_markup=get_report_period_menu(is_manager=False))
    
    elif command == 'end_work':
        if not session_state: return
        work_duration_with_breaks = (datetime.datetime.now() - session_state['start_time']).total_seconds()
        if work_duration_with_breaks < MIN_WORK_SECONDS:
            await query.edit_message_text("Вы хотите уйти раньше. Как поступим?", reply_markup=get_early_leave_menu())
        else:
            await query.edit_message_text("Завершение рабочего дня...")
            await end_workday_logic(user_id, context, is_early_leave=False)
    
    elif command == 'end_work_use_bank':
        work_duration = (datetime.datetime.now() - session_state['start_time']).total_seconds() - session_state.get('total_break_seconds', 0)
        shortfall_seconds = MIN_WORK_SECONDS - work_duration
        banked_seconds = user_info.get('time_bank_seconds', 0)
        if banked_seconds >= shortfall_seconds:
            db.update_time_bank(user_id, -int(shortfall_seconds))
            await query.edit_message_text("Завершение рабочего дня за счет банка времени...")
            await end_workday_logic(user_id, context, is_early_leave=True, used_bank_time=shortfall_seconds)
        else:
            needed_str = seconds_to_str(shortfall_seconds - banked_seconds)
            await query.edit_message_text(f"Недостаточно времени в банке. Нужно отработать еще: {needed_str}", reply_markup=get_early_leave_menu())
    
    elif command == 'end_work_ask_manager':
        await query.edit_message_text("Отправляем запрос на согласование руководителю...")
        manager_1, manager_2 = user_info.get('manager_id_1'), user_info.get('manager_id_2')
        if not manager_1 and not manager_2:
            await context.bot.send_message(user_id, "Не удалось запросить ранний уход: не найдены руководители.")
            return
        text_for_manager = f"Сотрудник {user_info['full_name']} запрашивает раннее завершение рабочего дня."
        msg_id_1, msg_id_2 = None, None
        if manager_1:
            msg1 = await context.bot.send_message(manager_1, text_for_manager)
            msg_id_1 = msg1.message_id
        if manager_2 and manager_2 != manager_1:
            msg2 = await context.bot.send_message(manager_2, text_for_manager)
            msg_id_2 = msg2.message_id
        request_id = db.create_request(user_id, 'early_leave', {}, msg_id_1, msg_id_2)
        keyboard = [[InlineKeyboardButton("✅ Одобрить", callback_data=f'approve_{request_id}'), InlineKeyboardButton("❌ Отклонить", callback_data=f'deny_{request_id}')]]
        if msg_id_1: await context.bot.edit_message_reply_markup(chat_id=manager_1, message_id=msg_id_1, reply_markup=InlineKeyboardMarkup(keyboard))
        if msg_id_2: await context.bot.edit_message_reply_markup(chat_id=manager_2, message_id=msg_id_2, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif command == 'debt_menu':
        text, markup = await get_debt_menu(user_id)
        await query.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')
    
    elif command == 'start_debt_work':
        session_state = db.get_session_state(user_id) or {}
        session_state['status'] = 'clearing_debt'
        session_state['debt_start_time'] = datetime.datetime.now()
        db.set_session_state(user_id, session_state)
        total_debt = db.get_total_debt(user_id)
        text, markup = get_debt_working_menu(total_debt)
        await query.edit_message_text(text, reply_markup=markup)
    
    elif command == 'end_debt_work':
        if not session_state or session_state.get('status') != 'clearing_debt': return
        total_debt_before = db.get_total_debt(user_id)
        start_time = session_state['debt_start_time']
        end_time = datetime.datetime.now()
        cleared_seconds = (end_time - start_time).total_seconds()
        db.clear_work_debt(user_id, int(cleared_seconds))
        db.add_debt_log(user_id, str(start_time), str(end_time), int(cleared_seconds))
        del session_state['status'], session_state['debt_start_time']
        if not session_state:
            db.delete_session_state(user_id)
        else:
            db.set_session_state(user_id, session_state)
        cleared_str = seconds_to_str(int(cleared_seconds))
        initial_debt_str = seconds_to_str(total_debt_before)
        await query.edit_message_text(f"Зачтено в счет отработки: {cleared_str} из {initial_debt_str}.")
        text, markup = await get_debt_menu(user_id)
        await context.bot.send_message(user_id, text, reply_markup=markup, parse_mode='Markdown')
    
    elif command == 'start_work_office' or command == 'start_work_remote':
        if session_state:
            await query.edit_message_text(text="Вы не можете начать новый день, пока не завершите текущую сессию.", reply_markup=get_working_menu())
            return
        is_remote = (command == 'start_work_remote')
        new_state = {'status': 'working', 'start_time': datetime.datetime.now(), 'total_break_seconds': 0, 'is_remote': is_remote}
        db.set_session_state(user_id, new_state)
        start_time_str = new_state['start_time'].strftime("%H:%M:%S")
        await query.edit_message_text(text=f"Рабочий день начат в {start_time_str}.", reply_markup=get_working_menu())
    
    elif command == 'start_break_choice':
        if not session_state: return
        used_break_seconds = session_state.get('total_break_seconds', 0)
        remaining_break_seconds = DAILY_BREAK_LIMIT_SECONDS - used_break_seconds
        if remaining_break_seconds <= 0:
            await query.answer(text="У вас не осталось времени на перерыв.", show_alert=True)
            return
        session_state['status'] = 'on_break'
        session_state['break_start_time'] = datetime.datetime.now()
        db.set_session_state(user_id, session_state)
        remaining_time_str = seconds_to_str(remaining_break_seconds)
        await query.edit_message_text(text=f"У вас осталось {remaining_time_str} перерыва. Хорошего отдыха!", reply_markup=get_break_menu())
    
    elif command == 'end_break':
        if not session_state or session_state.get('status') != 'on_break': return
        break_duration = (datetime.datetime.now() - session_state['break_start_time']).total_seconds()
        total_break_seconds = session_state.get('total_break_seconds', 0) + int(break_duration)
        session_state['total_break_seconds'] = total_break_seconds
        session_state['status'] = 'working'
        db.set_session_state(user_id, session_state)
        remaining_break_time_str = seconds_to_str(DAILY_BREAK_LIMIT_SECONDS - total_break_seconds)
        await query.edit_message_text(text=f"Вы вернулись к работе. У вас осталось {remaining_break_time_str} перерыва.", reply_markup=get_working_menu())
    
    elif command == 'back_to_working_menu':
        await query.edit_message_text(text="Вы работаете.", reply_markup=get_working_menu())

# --- Функция запуска бота ---
def main() -> None:
    """Запуск бота."""
    db.init_db()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_error_handler(error_handler)
    
    # Диалоги
    absence_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(ask_for_dates_text, pattern='^absence_sick$'),
            CallbackQueryHandler(ask_for_dates_text, pattern='^absence_vacation$'),
            CallbackQueryHandler(ask_for_dates_text, pattern='^absence_trip$'),
            CallbackQueryHandler(ask_for_dates_text, pattern='^request_remote_work$'),
        ],
        states={GET_DATES_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_dates_text)]},
        fallbacks=[CommandHandler('cancel', cancel_conversation)],
    )
    report_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(ask_for_report_dates, pattern='^report_custom_period$')],
        states={GET_REPORT_DATES: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_report_dates)]},
        fallbacks=[CommandHandler('cancel', cancel_conversation)],
    )

    application.add_handler(absence_conv_handler)
    application.add_handler(report_conv_handler)
    
    # Команды и кнопки
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("adduser", add_user))
    application.add_handler(CommandHandler("users", show_users))
    application.add_handler(CommandHandler("report", report_command))
    application.add_handler(CallbackQueryHandler(button_callback_handler))
    
    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()