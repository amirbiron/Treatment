from datetime import datetime
from typing import Dict

from telegram import Update
from telegram.ext import ContextTypes

from config import config
from database import DatabaseManager
from utils.keyboards import (
	get_main_menu_keyboard,
	get_appointments_menu_keyboard,
	get_calendar_keyboard,
	get_time_selection_keyboard,
	get_appointment_reminder_keyboard,
)
from scheduler import medicine_scheduler


class AppointmentsHandler:
	"""Handle appointment creation flow"""
	def __init__(self):
		self.valid_types = {
			"doctor": "רופא",
			"blood": "בדיקת דם",
			"treatment": "טיפול",
			"checkup": "בדיקה",
			"custom": "אחר",
		}

	async def show_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		await update.message.reply_text(
			f"{config.EMOJIS['calendar']} קביעת תור\n\n{config.APPOINTMENTS_HELP}",
			reply_markup=get_appointments_menu_keyboard()
		)

	async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		query = update.callback_query
		await query.answer()
		data = query.data
		ud: Dict = context.user_data.setdefault('appt_state', {})

		if data == 'appt_cancel':
			context.user_data.pop('appt_state', None)
			await query.edit_message_text("בוטל", reply_markup=get_main_menu_keyboard())
			return

		if data.startswith('appt_type_'):
			appt_type = data.split('_', 2)[2]
			ud.clear()
			ud['type'] = appt_type
			ud['step'] = 'details'
			prompt = {
				'doctor': "הקלידו את שם הרופא",
				'blood': "הקלידו את סוג בדיקת הדם",
				'treatment': "הקלידו את סוג הטיפול",
				'checkup': "הקלידו את סוג הבדיקה",
				'custom': "הקלידו את נושא התור",
			}.get(appt_type, "הקלידו פרטי תור")
			await query.edit_message_text(prompt)
			return

		if data.startswith('appt_cal_nav_'):
			parts = data.split('_')
			year = int(parts[3])
			month = int(parts[4])
			dirn = parts[5]
			if dirn == 'prev':
				month -= 1
				if month == 0:
					month = 12
					year -= 1
			else:
				month += 1
				if month == 13:
					month = 1
					year += 1
			await query.edit_message_text(
				"בחרו תאריך:",
				reply_markup=get_calendar_keyboard(year, month)
			)
			return

		if data.startswith('appt_date_'):
			_, _, y, m, d = data.split('_')
			year, month, day = int(y), int(m), int(d)
			ud['date'] = f"{year:04d}-{month:02d}-{day:02d}"
			ud['step'] = 'time'
			await query.edit_message_text(
				"בחרו שעה לְתור או הזינו בפורמט HH:MM:",
				reply_markup=get_time_selection_keyboard()
			)
			return

		if data == 'time_custom':
			ud['awaiting_time_text'] = True
			await query.edit_message_text("הקלידו שעה בפורמט HH:MM (למשל 09:30)")
			return

		if data.startswith('time_'):
			parts = data.split('_')
			if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
				hour = int(parts[1])
				minute = int(parts[2])
				ud['time'] = f"{hour:02d}:{minute:02d}"
				ud['step'] = 'reminders'
				rem1 = config.APPOINTMENT_REMIND_DAY_BEFORE
				rem3 = config.APPOINTMENT_REMIND_3_DAYS_BEFORE
				ud['rem1'] = rem1
				ud['rem3'] = rem3
				await query.edit_message_text(
					"בחירת תזכורות:",
					reply_markup=get_appointment_reminder_keyboard(rem1, rem3)
				)
				return

		if data == 'appt_rem1_toggle':
			ud['rem1'] = not bool(ud.get('rem1', False))
			await query.edit_message_reply_markup(
				reply_markup=get_appointment_reminder_keyboard(ud.get('rem1', False), ud.get('rem3', False))
			)
			return

		if data == 'appt_rem3_toggle':
			ud['rem3'] = not bool(ud.get('rem3', False))
			await query.edit_message_reply_markup(
				reply_markup=get_appointment_reminder_keyboard(ud.get('rem1', False), ud.get('rem3', False))
			)
			return

		if data == 'appt_back':
			# Go back to time selection
			ud['step'] = 'time'
			await query.edit_message_text(
				"בחרו שעה לְתור או הזינו בפורמט HH:MM:",
				reply_markup=get_time_selection_keyboard()
			)
			return

		if data == 'appt_save':
			# Validate and save
			user = await DatabaseManager.get_user_by_telegram_id(query.from_user.id)
			if not user:
				await query.edit_message_text("נדרש /start קודם")
				return
			try:
				appt_type = ud.get('type', 'custom')
				title = ud.get('title', 'תור')
				date_str = ud.get('date')
				time_str = ud.get('time', '09:00')
				rem1 = bool(ud.get('rem1', False))
				rem3 = bool(ud.get('rem3', False))
				if not date_str or not time_str:
					await query.edit_message_text("אנא בחרו תאריך ושעה")
					return
				when = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
				appt = await DatabaseManager.create_appointment(
					user_id=user.id,
					category=appt_type,
					title=title,
					when_at=when,
					remind_day_before=rem1,
					remind_3days_before=rem3,
				)
				# Schedule reminders
				await medicine_scheduler.schedule_appointment_reminders(user.id, appt.id, when, rem1, rem3, user.timezone or config.DEFAULT_TIMEZONE)
				context.user_data.pop('appt_state', None)
				await query.edit_message_text(f"{config.EMOJIS['success']} התור נשמר!", reply_markup=get_main_menu_keyboard())
				return
			except Exception:
				await query.edit_message_text(config.ERROR_MESSAGES['general'])
				return

		# Default: ignore
		await query.edit_message_text(config.ERROR_MESSAGES['general'])

	async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		text = (update.message.text or "").strip()
		ud: Dict = context.user_data.setdefault('appt_state', {})
		if ud.get('step') == 'details':
			ud['title'] = text
			ud['step'] = 'date'
			# Show calendar starting current month
			now = datetime.utcnow()
			await update.message.reply_text(
				"בחרו תאריך:",
				reply_markup=get_calendar_keyboard(now.year, now.month)
			)
			return
		if ud.get('awaiting_time_text'):
			ud.pop('awaiting_time_text', None)
			# Validate HH:MM
			try:
				h, m = text.split(':')
				hour = int(h)
				minute = int(m)
				if not (0 <= hour <= 23 and 0 <= minute <= 59):
					raise ValueError()
				ud['time'] = f"{hour:02d}:{minute:02d}"
				ud['step'] = 'reminders'
				rem1 = config.APPOINTMENT_REMIND_DAY_BEFORE
				rem3 = config.APPOINTMENT_REMIND_3_DAYS_BEFORE
				ud['rem1'] = rem1
				ud['rem3'] = rem3
				await update.message.reply_text(
					"בחירת תזכורות:",
					reply_markup=get_appointment_reminder_keyboard(rem1, rem3)
				)
				return
			except Exception:
				await update.message.reply_text("פורמט שגוי. הזינו שעה כמו 09:30")
				return


appointments_handler = AppointmentsHandler()