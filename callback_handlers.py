# Файл: callback_handlers.py
# Этот модуль содержит всю логику для обработки нажатий на inline-кнопки.

import datetime
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

import database as db
from config import CONFIG
from menu_generator import MenuGenerator
from report_generator import ReportGenerator
from utils import get_now, end_workday_logic, seconds_to_str

logger = logging.getLogger(__name__)

class CallbackHandlerManager:
    """
    Класс-менеджер, который обрабатывает все callback-запросы от inline-клавиатур.
    Каждая кнопка в боте в итоге вызывает один из методов этого класса.
    """

    async def main_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Главный маршрутизатор для всех callback-запросов.
        Он получает callback_data от кнопки и вызывает соответствующий метод этого класса.
        """
        query = update.callback_query
        # Немедленно отвечаем на callback, чтобы пользователь не видел "часики" у кнопки.
        await query.answer()
        
        user_id = query.from_user.id
        command = query.data

        # Словарь-маршрутизатор для статичных команд (без параметров в callback_data)
        routes = {
            'show_status': self.show_status,
            'show_time_bank': self.show_time_bank,
            'absence_menu': self.absence_menu,
            'back_to_main_menu': self.back_to_main_menu,
            'back_to_working_menu': self.back_to_working_menu,
            'back_to_manager_menu': self.back_to_manager_menu,
            'start_work_remote': self.start_work_remote,
            'end_work': self.end_work,
            'start_break': self.start_break,
            'end_break': self.end_break,
            'end_work_use_bank': self.end_work_use_bank,
            'end_work_ask_manager': self.end_work_ask_manager,
            'additional_work_menu': self.additional_work_menu,
            'start_debt_work': self.start_debt_work,
            'start_banking_work': self.start_banking_work,
            'end_debt_work': self.end_debt_work,
            'end_banking_work': self.end_banking_work,
            'request_report': self.request_report,
            'manager_report_button': self.request_report,
            'team_status_button': self.team_status_button,
            'help_button': self.help_button,
            'show_all_users': self.show_all_users,
            'cancel_action': self.cancel_action,
        }
        
        handler_method = routes.get(command)

        if handler_method:
            await handler_method(update, context)
        # Обработка динамических callback'ов (с ID или другими параметрами)
        elif command.startswith(('approve_', 'deny_', 'approve_no_debt_', 'ack_request_')):
            await self.process_manager_decision(update, context)
        elif command.startswith('user_details_'):
            await self.user_details(update, context)
        elif command.startswith('confirm_delete_'):
            await self.confirm_delete(update, context)
        elif command.startswith('report_today_') or command.startswith('report_this_month_'):
            await self.generate_period_report(update, context)
        else:
            logger.warning(f"Получен неизвестный callback от user_id {user_id}: {command}")

    # --- МЕТОДЫ-ОБРАБОТЧИКИ ---

    async def show_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает всплывающее уведомление с текущим статусом пользователя."""
        query = update.callback_query
        user_id = query.from_user.id
        session_state = db.get_session_state(user_id)
        status_text = "Вы не в активной сессии."
        if session_state and session_state.get('status'):
            status = session_state['status']
            start_time = session_state['start_time']
            if status == 'working':
                work_duration = (get_now() - start_time).total_seconds()
                break_duration = session_state.get('total_break_seconds', 0)
                remaining_break = CONFIG.DAILY_BREAK_LIMIT_SECONDS - break_duration
                status_text = (f"Статус: Работаете\n"
                               f"Отработано сегодня: {seconds_to_str(work_duration - break_duration)}\n"
                               f"Осталось перерыва: {seconds_to_str(remaining_break)}")
            elif status == 'on_break':
                break_start_time = session_state['break_start_time']
                elapsed_break = (get_now() - break_start_time).total_seconds()
                status_text = f"Статус: На перерыве\nДлительность: {seconds_to_str(elapsed_break)}"
            elif status in ['clearing_debt', 'banking_time']:
                elapsed_extra = (get_now() - start_time).total_seconds()
                work_type_text = "Отработка долга" if status == 'clearing_debt' else "Работа в банк времени"
                status_text = f"Статус: {work_type_text}\nПрошло времени: {seconds_to_str(elapsed_extra)}"
        await query.answer(text=status_text, show_alert=True)

    async def show_time_bank(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает всплывающее уведомление с состоянием банка времени."""
        query = update.callback_query
        user_id = query.from_user.id
        user_info = db.get_user(user_id)
        banked_seconds = user_info.get('time_bank_seconds', 0) if user_info else 0
        await query.answer(f"🏦 В вашем банке времени накоплено: {seconds_to_str(banked_seconds)}", show_alert=True)

    # --- Логика рабочего дня ---

    async def start_work_remote(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начинает удаленный рабочий день."""
        await self.start_work(update, update.callback_query.from_user.id, is_remote=True)
        
    async def start_work(self, update: Update, user_id: int, is_remote: bool):
        """Универсальная функция для начала работы (удаленно или после проверки геолокации)."""
        if db.get_session_state(user_id):
            await update.effective_message.reply_text("Вы не можете начать новый день, пока не завершите текущую сессию.")
            return

        new_state = {'status': 'working', 'start_time': get_now(), 'total_break_seconds': 0, 'is_remote': is_remote}
        db.set_session_state(user_id, new_state)
        
        message_text = f"Рабочий день начат в {new_state['start_time'].strftime('%H:%M:%S')}."
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(text=message_text, reply_markup=MenuGenerator.get_working_menu())
        else: # Этот блок сработает после проверки геолокации, где нет callback_query
            await update.effective_message.reply_text(text=message_text, reply_markup=MenuGenerator.get_working_menu())

    async def end_work(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Завершает рабочий день или предлагает варианты, если время не выработано."""
        query = update.callback_query
        user_id = query.from_user.id
        session_state = db.get_session_state(user_id)
        if not session_state: return

        work_duration = (get_now() - session_state['start_time']).total_seconds()
        if work_duration < CONFIG.MIN_WORK_SECONDS:
            await query.edit_message_text("Вы хотите уйти раньше. Как поступим?", reply_markup=MenuGenerator.get_early_leave_menu())
        else:
            await query.edit_message_text("Завершение рабочего дня...")
            await end_workday_logic(context, user_id)

    async def start_break(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает начало перерыва."""
        query = update.callback_query
        user_id = query.from_user.id
        session_state = db.get_session_state(user_id)
        
        if not session_state or session_state.get('status') != 'working':
            await query.answer("Нельзя уйти на перерыв, не начав рабочий день.", show_alert=True)
            return

        remaining_break_seconds = CONFIG.DAILY_BREAK_LIMIT_SECONDS - session_state.get('total_break_seconds', 0)
        if remaining_break_seconds <= 0:
            await query.answer("У вас не осталось времени на перерыв.", show_alert=True)
            return
            
        session_state['status'] = 'on_break'
        session_state['break_start_time'] = get_now()
        db.set_session_state(user_id, session_state)
        
        await query.edit_message_text(
            text=f"Вы ушли на перерыв. У вас осталось {seconds_to_str(remaining_break_seconds)}.",
            reply_markup=MenuGenerator.get_break_menu()
        )

    async def end_break(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Завершает перерыв и возвращает в рабочий режим."""
        query = update.callback_query
        user_id = query.from_user.id
        session_state = db.get_session_state(user_id)
        if not session_state or session_state.get('status') != 'on_break': return

        break_duration = (get_now() - session_state['break_start_time']).total_seconds()
        session_state['total_break_seconds'] = session_state.get('total_break_seconds', 0) + int(break_duration)
        session_state['status'] = 'working'
        del session_state['break_start_time']
        db.set_session_state(user_id, session_state)
        remaining_break_str = seconds_to_str(CONFIG.DAILY_BREAK_LIMIT_SECONDS - session_state['total_break_seconds'])
        await query.edit_message_text(text=f"Вы вернулись к работе. У вас осталось {remaining_break_str} перерыва.", reply_markup=MenuGenerator.get_working_menu())

    async def end_work_use_bank(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Завершает рабочий день, списывая недостающее время из банка времени."""
        query = update.callback_query
        user_id = query.from_user.id
        user_info = db.get_user(user_id)
        session_state = db.get_session_state(user_id)
        if not session_state or not user_info: return

        work_duration = (get_now() - session_state['start_time']).total_seconds() - session_state.get('total_break_seconds', 0)
        shortfall_seconds = CONFIG.MIN_WORK_SECONDS - work_duration
        banked_seconds = user_info.get('time_bank_seconds', 0)
        
        if banked_seconds >= shortfall_seconds:
            db.update_time_bank(user_id, -int(shortfall_seconds))
            await query.edit_message_text("Завершение рабочего дня за счет банка времени...")
            await end_workday_logic(context, user_id, is_early_leave=True, used_bank_time=shortfall_seconds)
        else:
            needed_str = seconds_to_str(shortfall_seconds - banked_seconds)
            await query.answer(f"Недостаточно времени в банке. Нужно еще: {needed_str}", show_alert=True)
            
    async def end_work_ask_manager(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отправляет запрос руководителю на раннее завершение дня."""
        query = update.callback_query
        user_id = query.from_user.id
        user_info = db.get_user(user_id)
        if not user_info: return
        
        manager_1, manager_2 = user_info.get('manager_id_1'), user_info.get('manager_id_2')
        if not manager_1 and not manager_2:
            await query.edit_message_text("Ошибка: за вами не закреплен руководитель для согласования.", reply_markup=MenuGenerator.get_working_menu())
            return
        
        await query.edit_message_text("Отправляем запрос на согласование руководителю...")
        request_id = db.create_request(user_id, 'early_leave', {})
        keyboard = [
            [InlineKeyboardButton("✅ Одобрить", callback_data=f'approve_{request_id}'), InlineKeyboardButton("❌ Отклонить", callback_data=f'deny_{request_id}')],
            [InlineKeyboardButton("🎉 Одобрить без отработки", callback_data=f'approve_no_debt_{request_id}')]
        ]
        text_for_manager = f"Сотрудник {user_info['full_name']} запрашивает раннее завершение рабочего дня."
        msg_ids = {}
        if manager_1:
            msg = await context.bot.send_message(manager_1, text_for_manager, reply_markup=InlineKeyboardMarkup(keyboard))
            msg_ids['msg1_id'] = msg.message_id
        if manager_2 and manager_2 != manager_1:
            msg = await context.bot.send_message(manager_2, text_for_manager, reply_markup=InlineKeyboardMarkup(keyboard))
            msg_ids['msg2_id'] = msg.message_id
        db.update_request_messages(request_id, **msg_ids)

    # --- Навигация по меню ---
    
    async def absence_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.edit_message_text("Выберите тип отсутствия:", reply_markup=MenuGenerator.get_absence_menu())
    
    async def back_to_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        markup = await MenuGenerator.get_main_menu(query.from_user.id)
        await query.edit_message_text("Выберите действие:", reply_markup=markup)

    async def back_to_working_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.edit_message_text("Вы работаете.", reply_markup=MenuGenerator.get_working_menu())

    async def back_to_manager_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.edit_message_text("Меню руководителя:", reply_markup=MenuGenerator.get_manager_menu())
    
    async def cancel_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.edit_message_text("Действие отменено.")

    # --- Отчеты и помощь ---
    
    async def request_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        user_info = db.get_user(user_id)
        if not user_info: return
        
        session_state = db.get_session_state(user_id)
        is_manager = user_info['role'] in ['manager', 'admin']
        await query.edit_message_text("Выберите период для отчета:", reply_markup=MenuGenerator.get_report_period_menu(is_manager=is_manager, in_session=bool(session_state)))
        
    async def team_status_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        report_text = await ReportGenerator.get_team_status_text(user_id)
        await context.bot.send_message(user_id, report_text, parse_mode='Markdown')

    async def help_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        from command_handlers import CommandHandlerManager
        await CommandHandlerManager.help_command(update, context)

    # --- Логика администратора/менеджера ---
    
    async def process_manager_decision(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        user_info = db.get_user(user_id)
        if not user_info or user_info.get('role') not in ['manager', 'admin']:
            await query.answer("У вас нет прав для этого действия.", show_alert=True)
            return

        parts = query.data.split('_')
        action = "_".join(parts[:-1])
        request_id = int(parts[-1])
        
        request_info = db.get_request(request_id)
        if not request_info or request_info['status'] != 'pending':
            await query.edit_message_text("Этот запрос уже был обработан.")
            return

        requester_info = db.get_user(request_info['requester_id'])
        if not requester_info:
            await query.edit_message_text("Ошибка: не удалось найти сотрудника.")
            return

        if action == 'ack_request':
            db.update_request_status(request_id, 'acknowledged')
            await query.edit_message_text(f"✅ Принято к сведению (уведомление от {requester_info['full_name']}).")
        else:
            new_status = 'approved' if action.startswith('approve') else 'denied'
            db.update_request_status(request_id, new_status)
            
            response_text = f"Вы {'одобрили' if new_status == 'approved' else 'отклонили'} запрос от {requester_info['full_name']}"
            if action == 'approve_no_debt': response_text += " (без начисления отработки)."
            await query.edit_message_text(response_text)
            
            text_to_employee = f"Ваш запрос ('{request_info.get('request_type', 'Неизвестно')}') был {'одобрен' if new_status == 'approved' else 'отклонен'}."
            
            if request_info['request_type'] == 'early_leave' and new_status == 'approved':
                forgive_debt = (action == 'approve_no_debt')
                await end_workday_logic(context, requester_info['user_id'], is_early_leave=True, forgive_debt=forgive_debt)
            
            await context.bot.send_message(requester_info['user_id'], text_to_employee)

    async def user_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        target_user_id = int(query.data.split('_')[-1])
        info = db.get_user(target_user_id)
        if not info:
            await query.edit_message_text("Пользователь не найден."); return
            
        text = (f"**Инфо о пользователе:**\nИмя: {info['full_name']}\nID: `{info['user_id']}`\nРоль: {info['role']}\n"
                f"Банк времени: {seconds_to_str(info.get('time_bank_seconds',0))}\n"
                f"ID Рук. 1: {info.get('manager_id_1', 'Н/Д')}\nID Рук. 2: {info.get('manager_id_2', 'Н/Д')}")
        keyboard = [
            # Заменили прямое удаление на вызов команды /deluser для безопасности
            [InlineKeyboardButton("« Назад к списку", callback_data="show_all_users")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        
    async def show_all_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        from command_handlers import CommandHandlerManager
        await CommandHandlerManager.list_users(update, context)

    async def confirm_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        target_user_id = int(query.data.split('_')[-1])
        info = db.get_user(target_user_id)
        if not info:
            await query.edit_message_text("Пользователь уже удален."); return
        
        db.delete_user(target_user_id)
        await query.edit_message_text(f"Пользователь {info['full_name']} удален.")
        
    async def generate_period_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        command = query.data
        
        report_type = command.split('_')[-1]
        today = get_now().date()
        
        if 'today' in command:
            start_date, end_date = today, today
        else: # this_month
            start_date = today.replace(day=1)
            next_month = start_date.replace(day=28) + datetime.timedelta(days=4)
            end_date = next_month - datetime.timedelta(days=next_month.day)
        
        await query.delete_message()
        if report_type == 'manager':
            report_text = await ReportGenerator.get_manager_report_text(user_id, start_date, end_date)
            reply_markup = MenuGenerator.get_manager_menu()
        else:
            report_text = await ReportGenerator.get_employee_report_text(user_id, start_date, end_date)
            is_in_session = bool(db.get_session_state(user_id))
            reply_markup = MenuGenerator.get_working_menu() if is_in_session else await MenuGenerator.get_main_menu(user_id)
            
        await context.bot.send_message(user_id, report_text, parse_mode='Markdown', reply_markup=reply_markup)
        
    # --- Дополнительная работа ---
    
    async def additional_work_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.edit_message_text("Выберите тип дополнительной работы:", reply_markup=MenuGenerator.get_additional_work_menu(query.from_user.id))

    async def start_debt_work(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._start_extra_work(update, 'clearing_debt')

    async def start_banking_work(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._start_extra_work(update, 'banking_time', notify_manager=True, bot=context.bot)

    async def end_debt_work(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._end_extra_work(update, context)

    async def end_banking_work(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._end_extra_work(update, context)

    async def _start_extra_work(self, update: Update, status: str, notify_manager: bool = False, bot=None):
        query = update.callback_query
        user_id = query.from_user.id
        start_time = get_now()
        db.set_session_state(user_id, {'status': status, 'start_time': start_time})
        text, markup = MenuGenerator.get_extra_work_active_menu(status, start_time)
        await query.edit_message_text(text, reply_markup=markup)

        if notify_manager:
            user_info = db.get_user(user_id)
            if not user_info or (not user_info.get('manager_id_1') and not user_info.get('manager_id_2')): return
            text_for_manager = f"Сотрудник {user_info['full_name']} начал работать в банк времени."
            request_id = db.create_request(user_id, 'banking_work', {})
            keyboard = [[InlineKeyboardButton("✅ Принято", callback_data=f'ack_request_{request_id}')]]
            msg_ids = {}
            if user_info.get('manager_id_1'):
                msg = await bot.send_message(user_info['manager_id_1'], text_for_manager, reply_markup=InlineKeyboardMarkup(keyboard))
                msg_ids['msg1_id'] = msg.message_id
            if user_info.get('manager_id_2') and user_info.get('manager_id_2') != user_info.get('manager_id_1'):
                msg = await bot.send_message(user_info['manager_id_2'], text_for_manager, reply_markup=InlineKeyboardMarkup(keyboard))
                msg_ids['msg2_id'] = msg.message_id
            db.update_request_messages(request_id, **msg_ids)

    async def _end_extra_work(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        session_state = db.get_session_state(user_id)
        if not session_state: return

        start_time = session_state['start_time']
        status = session_state['status']
        worked_seconds = (get_now() - start_time).total_seconds()
        
        if status == 'clearing_debt':
            db.clear_work_debt(user_id, int(worked_seconds))
            db.add_debt_log(user_id, start_time, get_now(), int(worked_seconds))
            text = f"Зачтено в счет отработки: {seconds_to_str(worked_seconds)}."
        elif status == 'banking_time':
            db.update_time_bank(user_id, int(worked_seconds))
            db.add_work_log(user_id, start_time, get_now(), int(worked_seconds), 0, 'banking')
            text = f"Работа в банк времени завершена. Вы накопили: {seconds_to_str(worked_seconds)}."
        else:
            return

        db.delete_session_state(user_id)
        await query.edit_message_text(text, reply_markup=await MenuGenerator.get_main_menu(user_id))

# Создаем единственный экземпляр класса для импорта в bot.py
callback_manager = CallbackHandlerManager()
