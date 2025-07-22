# Файл: report_generator.py
import datetime
from typing import List
import database as db
from utils import seconds_to_str, get_now

class ReportGenerator:
    """
    Класс, отвечающий за генерацию текстов для отчетов.
    Разделение логики: этот модуль не отправляет сообщения, а только готовит текст.
    """

    @staticmethod
    async def get_team_status_text(manager_id: int) -> str:
        """Генерирует текст статуса команды для руководителя."""
        team_members = db.get_managed_users(manager_id)
        if not team_members:
            return "За вами не закреплено ни одного сотрудника."
        
        status_lines = [f"**Статус команды на {get_now().strftime('%d.%m.%Y %H:%M')}**\n"]
        today = get_now().date()
        
        for member in team_members:
            member_id = member['user_id']
            member_name = member['full_name']
            session = db.get_session_state(member_id)
            
            if session and session.get('status'):
                status = session['status']
                start_time = session['start_time']
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
                        # Убедимся, что end_time имеет правильную таймзону
                        end_time_local = last_log['end_time'].astimezone(get_now().tzinfo)
                        status_lines.append(f"⚪️ {member_name}: Закончил работу в {end_time_local.strftime('%H:%M')}")
                    else:
                        status_lines.append(f"⚪️ {member_name}: Не в сети")
        
        return "\n".join(status_lines)

    @staticmethod
    async def get_employee_report_text(user_id: int, start_date: datetime.date, end_date: datetime.date) -> str:
        """Генерирует текстовое содержимое отчета для сотрудника."""
        work_logs = db.get_work_logs_for_user(user_id, str(start_date), str(end_date + datetime.timedelta(days=1)))
        total_work_seconds = sum(log.get('total_work_seconds', 0) for log in work_logs)
        total_break_seconds = sum(log.get('total_break_seconds', 0) for log in work_logs)
        
        report_text = f"**Отчет для вас за период с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')}**\n\n"
        report_text += f"**Чистое рабочее время:** {seconds_to_str(total_work_seconds)}\n"
        report_text += f"**Время на перерывах:** {seconds_to_str(total_break_seconds)}\n\n"
        
        cleared_debt = db.get_debt_logs_for_user(user_id, str(start_date), str(end_date + datetime.timedelta(days=1)))
        total_current_debt = db.get_total_debt(user_id)
        if cleared_debt > 0 or total_current_debt > 0:
            report_text += f"**Отработка:**\n"
            report_text += f"Закрыто долга за период: {seconds_to_str(cleared_debt)}\n"
            report_text += f"Общий текущий долг: {seconds_to_str(total_current_debt)}"
            
        return report_text

    @staticmethod
    async def get_manager_report_text(manager_id: int, start_date: datetime.date, end_date: datetime.date) -> str:
        """Генерирует текстовое содержимое отчета для руководителя."""
        team_members = db.get_managed_users(manager_id)
        if not team_members:
            return "За вами не закреплено ни одного сотрудника."
            
        report_lines = [f"**Отчет по команде за период с {start_date.strftime('%d.%m.%Y')} по {end_date.strftime('%d.%m.%Y')}**\n"]
        
        end_date_for_query = end_date + datetime.timedelta(days=1)
        
        for member in team_members:
            member_id = member['user_id']
            member_name = member['full_name']
            
            logs = db.get_work_logs_for_user(member_id, str(start_date), str(end_date_for_query))
            # Для отсутствий нужно проверять пересечение периодов, а не только начальную дату
            absences_list = db.get_absences_for_user(member_id, start_date) 
            
            employee_line = f"👤 **{member_name}**:"
            
            if logs:
                total_work = sum(log.get('total_work_seconds', 0) for log in logs)
                total_break = sum(log.get('total_break_seconds', 0) for log in logs)
                employee_line += f" отработано {seconds_to_str(total_work)} (перерывы: {seconds_to_str(total_break)})."
            
            if absences_list:
                details = []
                for a in absences_list:
                    # Убедимся, что типы - datetime.date
                    absence_start = a['start_date']
                    absence_end = a['end_date']
                    if isinstance(absence_start, str):
                        absence_start = datetime.datetime.fromisoformat(absence_start).date()
                    if isinstance(absence_end, str):
                        absence_end = datetime.datetime.fromisoformat(absence_end).date()

                    # Проверяем, что отсутствие пересекается с периодом отчета
                    if max(start_date, absence_start) <= min(end_date, absence_end):
                        details.append(f"{a['absence_type']} ({absence_start.strftime('%d.%m')}-{absence_end.strftime('%d.%m')})")

                if details:
                    employee_line += f"\n  - *Отсутствия:* {', '.join(details)}" if logs else f" *{', '.join(details)}.*"
            
            if not logs and not (absences_list and details):
                employee_line += " нет данных за период."
                
            report_lines.append(employee_line)

        return "\n".join(report_lines)