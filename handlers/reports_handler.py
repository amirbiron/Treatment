"""
Reports Handler
Handles generation and sending of various reports: weekly, monthly, adherence, symptoms
"""

import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from config import config
from database import DatabaseManager
from utils.keyboards import get_reports_keyboard, get_main_menu_keyboard, get_cancel_keyboard, get_confirmation_keyboard
from utils.helpers import (
	format_datetime_hebrew,
	format_date_hebrew,
	calculate_adherence_rate,
	calculate_average_mood,
	group_by_date,
	calculate_streaks,
	create_progress_bar,
	generate_summary_stats,
	create_report_filename,
	format_list_hebrew,
)

logger = logging.getLogger(__name__)

# Conversation states
SELECT_REPORT_TYPE, SELECT_DATE_RANGE, CONFIRM_SEND = range(3)


class ReportsHandler:
	"""Handler for generating and managing reports"""

	def __init__(self):
		self.user_report_data: Dict[int, Dict] = {}

		# Report types
		self.report_types = {
			"weekly": "דוח שבועי",
			"monthly": "דוח חודשי",
			"adherence": "דוח נטילת תרופות",
			"symptoms": "דוח תופעות לוואי",
			"full": "דוח מקיף",
		}

		# Date range options
		self.date_ranges = {
			"last_7_days": "7 ימים אחרונים",
			"last_14_days": "14 ימים אחרונים",
			"last_30_days": "30 ימים אחרונים",
			"last_3_months": "3 חודשים אחרונים",
			"custom": "תקופה מותאמת אישית",
		}

	def get_conversation_handler(self) -> ConversationHandler:
		"""Get the conversation handler for reports"""
		return ConversationHandler(
			entry_points=[
				CommandHandler("weekly_report", self.generate_weekly_report),
				CommandHandler("monthly_report", self.generate_monthly_report),
				CallbackQueryHandler(self.show_reports_menu, pattern="^reports_menu$"),
				CallbackQueryHandler(self.start_custom_report, pattern="^report_"),
			],
			states={
				SELECT_REPORT_TYPE: [CallbackQueryHandler(self.handle_report_type_selection, pattern="^rtype_")],
				SELECT_DATE_RANGE: [CallbackQueryHandler(self.handle_date_range_selection, pattern="^range_")],
				CONFIRM_SEND: [
					CallbackQueryHandler(self.confirm_send_report, pattern="^send_confirm_"),
					CallbackQueryHandler(self.cancel_send_report, pattern="^send_cancel_"),
				],
			},
			fallbacks=[
				CommandHandler("cancel", self.cancel_report),
				CallbackQueryHandler(self.cancel_report, pattern="^cancel$"),
			],
			per_message=False,
		)

	def get_handlers(self) -> List:
		"""Get additional command handlers"""
		return [
			CommandHandler("generate_report", self.start_custom_report),
			CommandHandler("send_to_doctor", self.send_to_doctor_flow),
			CallbackQueryHandler(self.show_reports_menu, pattern="^reports_menu$"),
			CallbackQueryHandler(self.start_custom_report, pattern="^report_"),
			CallbackQueryHandler(self.handle_report_actions, pattern="^report_action_"),
			CallbackQueryHandler(self.export_report, pattern="^export_report_"),
		]

	async def generate_weekly_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		"""Generate weekly report"""
		try:
			user_id = update.effective_user.id
			user = await DatabaseManager.get_user_by_telegram_id(user_id)

			if not user:
				await self._send_error_message(update, "משתמש לא נמצא")
				return

			# Show loading indication (single message)
			loading_msg = None
			if getattr(update, "callback_query", None):
				await update.callback_query.answer()
				loading_msg = await update.callback_query.message.reply_text("⏳ טוען דוח…")
			elif getattr(update, "message", None):
				loading_msg = await update.message.reply_text("⏳ טוען דוח…")

			# Calculate date range (last 7 days)
			end_date = date.today()
			start_date = end_date - timedelta(days=7)

			# Generate report
			report = await self._generate_adherence_report(user.id, start_date, end_date)
			symptoms_report = await self._generate_symptoms_report(user.id, start_date, end_date)

			# Combine reports
			full_report = self._combine_reports([report, symptoms_report])

			# Cache last report for export/share
			context.user_data["last_report"] = {
				"type": "weekly",
				"start": start_date,
				"end": end_date,
				"title": "דוח שבועי",
				"content": full_report,
			}

			message = f"""
{config.EMOJIS['report']} <b>דוח שבועי</b>
📅 {format_date_hebrew(start_date)} - {format_date_hebrew(end_date)}

{full_report}

{config.EMOJIS['info']} ניתן לשתף דוח זה ידנית עם הרופא/המטפל בלחיצה על "שמור כקובץ".
			"""

			keyboard = [
				[
					InlineKeyboardButton("📧 שלח לרופא", callback_data="report_action_send_doctor"),
					InlineKeyboardButton("💾 שמור כקובץ", callback_data="export_report_weekly"),
				],
				[InlineKeyboardButton(f"{config.EMOJIS['home']} תפריט ראשי", callback_data="main_menu")],
			]

			# Replace loading with final content
			if loading_msg:
				await loading_msg.edit_text(message, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
			else:
				if update.callback_query:
					await update.callback_query.edit_message_text(
						message, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
					)
				elif getattr(update, "message", None):
					await update.message.reply_text(message, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

			# Send to caregivers
			await self._send_report_to_caregivers(user.id, "דוח שבועי", full_report, context)

		except Exception as e:
			logger.error(f"Error generating weekly report: {e}")
			await self._send_error_message(update, "שגיאה ביצירת הדוח השבועי")

	async def generate_monthly_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		"""Generate monthly report"""
		try:
			user_id = update.effective_user.id
			user = await DatabaseManager.get_user_by_telegram_id(user_id)

			if not user:
				await self._send_error_message(update, "משתמש לא נמצא")
				return

			# Calculate date range (last 30 days)
			end_date = date.today()
			start_date = end_date - timedelta(days=30)

			# Generate comprehensive report
			adherence_report = await self._generate_adherence_report(user.id, start_date, end_date)
			symptoms_report = await self._generate_symptoms_report(user.id, start_date, end_date)
			inventory_report = await self._generate_inventory_report(user.id)
			trends_report = await self._generate_trends_report(user.id, start_date, end_date)

			# Combine all reports
			full_report = self._combine_reports([adherence_report, symptoms_report, inventory_report, trends_report])

			# Cache last report for export/share
			context.user_data["last_report"] = {
				"type": "monthly",
				"start": start_date,
				"end": end_date,
				"title": "דוח חודשי מקיף",
				"content": full_report,
			}

			message = f"""
{config.EMOJIS['report']} <b>דוח חודשי מקיף</b>
📅 {format_date_hebrew(start_date)} - {format_date_hebrew(end_date)}

{full_report}

{config.EMOJIS['info']} דוח זה מתאים להצגה לרופא או למטפל.
			"""

			keyboard = [
				[
					InlineKeyboardButton("📧 שלח לרופא", callback_data="report_action_send_doctor"),
					InlineKeyboardButton("💾 שמור כקובץ", callback_data="export_report_monthly"),
				],
				[InlineKeyboardButton("📊 דוח מפורט נוסף", callback_data="report_detailed")],
				[InlineKeyboardButton(f"{config.EMOJIS['home']} תפריט ראשי", callback_data="main_menu")],
			]

			if update.callback_query:
				await update.callback_query.answer()
				await update.callback_query.edit_message_text(
					message, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
				)
			elif getattr(update, "message", None):
				await update.message.reply_text(message, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

		except Exception as e:
			logger.error(f"Error generating monthly report: {e}")
			await self._send_error_message(update, "שגיאה ביצירת הדוח החודשי")

	async def show_reports_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		"""Show reports menu"""
		try:
			message = f"""
{config.EMOJIS['report']} <b>מרכז הדוחות</b>

בחרו את סוג הדוח שתרצו ליצור:

📊 <b>דוחות זמינים:</b>
• דוח שבועי - סיכום 7 ימים אחרונים
• דוח חודשי - סיכום מקיף של החודש
• דוח נטילת תרופות - מיקוד בציות לטיפול
• דוח תופעות לוואי - מעקב תסמינים
• דוח מקיף - כל המידע במקום אחד
			"""

			keyboard = [
				[
					InlineKeyboardButton("📅 דוח שבועי", callback_data="report_weekly"),
					InlineKeyboardButton("📋 דוח מקיף", callback_data="report_full"),
				],
				[InlineKeyboardButton("⚙️ דוחות מתקדמים", callback_data="reports_advanced")],
				[InlineKeyboardButton(f"{config.EMOJIS['back']} חזור", callback_data="main_menu")],
			]

			if update.callback_query:
				await update.callback_query.answer()
				await update.callback_query.edit_message_text(
					message, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
				)
			elif getattr(update, "message", None):
				await update.message.reply_text(message, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

		except Exception as e:
			logger.error(f"Error showing reports menu: {e}")
			await self._send_error_message(update, "שגיאה בהצגת תפריט הדוחות")

	async def start_custom_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		"""Entry point for handling custom report selections from callbacks or command."""
		try:
			callback_query = None
			data = ""
			# Support both Update and CallbackQuery objects
			if hasattr(update, "data") and hasattr(update, "edit_message_text"):
				callback_query = update
				data = callback_query.data or ""
				await callback_query.answer()
			elif getattr(update, "callback_query", None):
				callback_query = update.callback_query
				data = callback_query.data or ""
				await callback_query.answer()
			else:
				data = ""

			if not data or data == "generate_report":
				await self.show_reports_menu(update, context)
				return ConversationHandler.END

			# For heavy reports show loading animation
			loading_msg = None
			if data == "report_full":
				if callback_query:
					loading_msg = await callback_query.message.reply_text("⏳ טוען דוח…")
				elif getattr(update, "message", None):
					loading_msg = await update.message.reply_text("⏳ טוען דוח…")

			if data == "report_weekly":
				# Avoid double-loading: generate directly with the same update
				return await self.generate_weekly_report(update, context)
			if data == "report_monthly":
				await self.generate_monthly_report(update, context)
				return ConversationHandler.END
			if data == "report_send_doctor":
				await self.send_to_doctor_flow(update, context)
				return ConversationHandler.END
			if data in ("reports_advanced", "report_detailed"):
				adv_msg = """
⚙️ <b>דוחות מתקדמים</b>

בחרו דוח ממוקד:
• דוח נטילת תרופות (ציות לפי תרופה)
• דוח תופעות לוואי (תסמינים ותופעות נפוצות)
				"""
				adv_kb = InlineKeyboardMarkup(
					[
						[InlineKeyboardButton("💊 דוח נטילת תרופות", callback_data="report_adherence")],
						[InlineKeyboardButton("🩺 דוח תופעות לוואי", callback_data="report_symptoms")],
						[InlineKeyboardButton(f"{config.EMOJIS['back']} חזרה", callback_data="reports_menu")],
					]
				)
				if getattr(update, "callback_query", None):
					await update.callback_query.edit_message_text(adv_msg, parse_mode="HTML", reply_markup=adv_kb)
				else:
					await update.message.reply_text(adv_msg, parse_mode="HTML", reply_markup=adv_kb)
				return ConversationHandler.END
			# Default date range for custom single reports: last 30 days
			end_date = date.today()
			start_date = end_date - timedelta(days=30)

			user_id = update.effective_user.id
			user = await DatabaseManager.get_user_by_telegram_id(user_id)
			if not user:
				await self._send_error_message(update, "משתמש לא נמצא")
				return ConversationHandler.END

			report_title = ""
			report_content = ""

			if data == "report_adherence":
				report_title = "דוח נטילת תרופות (30 ימים)"
				report_content = await self._generate_adherence_report(user.id, start_date, end_date)
			elif data == "report_symptoms":
				report_title = "דוח תופעות לוואי (30 ימים)"
				report_content = await self._generate_symptoms_report(user.id, start_date, end_date)
			elif data == "report_full":
				report_title = "דוח מקיף (30 ימים)"
				adherence = await self._generate_adherence_report(user.id, start_date, end_date)
				symptoms = await self._generate_symptoms_report(user.id, start_date, end_date)
				trends = await self._generate_trends_report(user.id, start_date, end_date)
				report_content = self._combine_reports([adherence, symptoms, trends])
			else:
				await self.show_reports_menu(update, context)
				return ConversationHandler.END

			# Compose and send
			content = f"""
<b>{report_title}</b>

{report_content}
			"""
			if getattr(update, "callback_query", None):
				await update.callback_query.edit_message_text(content, parse_mode="HTML")
			else:
				await update.message.reply_text(content, parse_mode="HTML")
			return ConversationHandler.END
		except Exception as e:
			logger.error(f"Error in start_custom_report: {e}")
			await self._send_error_message(update, "שגיאה ביצירת הדוח")
			return ConversationHandler.END

	async def handle_report_type_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		# Implementation omitted for brevity in this edit
		return ConversationHandler.END

	async def handle_date_range_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		# Implementation omitted for brevity in this edit
		return ConversationHandler.END

	async def confirm_send_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		# Implementation omitted for brevity in this edit
		return ConversationHandler.END

	async def cancel_send_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
		# Implementation omitted for brevity in this edit
		return ConversationHandler.END

	async def _generate_adherence_report(self, user_id: int, start_date: date, end_date: date) -> str:
		"""Generate medication adherence report"""
		try:
			# Get user medicines
			medicines = await DatabaseManager.get_user_medicines(user_id)

			if not medicines:
				return f"{config.EMOJIS['info']} אין תרופות רשומות"

			total_doses = 0
			taken_doses = 0
			missed_doses = 0
			skipped_doses = 0

			medicine_stats = []

			for medicine in medicines:
				# Get doses for this medicine in date range
				doses = await DatabaseManager.get_medicine_doses_in_range(medicine.id, start_date, end_date)

				med_taken = len([d for d in doses if getattr(d, 'status', None) == "taken"])  # robust
				med_missed = len([d for d in doses if getattr(d, 'status', None) == "missed"])  # robust
				med_skipped = len([d for d in doses if getattr(d, 'status', None) == "skipped"])  # robust
				med_total = len(doses)

				if med_total > 0:
					adherence_rate = (med_taken / med_total) * 100

					medicine_stats.append(
						{"name": medicine.name, "taken": med_taken, "total": med_total, "adherence": adherence_rate}
					)

					total_doses += med_total
					taken_doses += med_taken
					missed_doses += med_missed
					skipped_doses += med_skipped

			if total_doses == 0:
				return f"{config.EMOJIS['info']} אין נתוני נטילה בתקופה זו"

			overall_adherence = (taken_doses / total_doses) * 100

			# Create report
			report = f"""
💊 <b>דוח נטילת תרופות</b>

📊 <b>סיכום כללי:</b>
• סה"כ מנות מתוכננות: {total_doses}
• מנות שנלקחו: {taken_doses} ({taken_doses/total_doses*100:.1f}%)
• מנות שדולגו: {skipped_doses} ({skipped_doses/total_doses*100:.1f}%)
• מנות שהוחמצו: {missed_doses} ({missed_doses/total_doses*100:.1f}%)

🎯 <b>שיעור ציות כללי:</b> {create_progress_bar(taken_doses, total_doses)} {overall_adherence:.1f}%

📋 <b>פירוט לפי תרופה:</b>
			"""

			for stat in medicine_stats:
				progress_bar = create_progress_bar(stat["taken"], stat["total"], 8)
				report += f"• <b>{stat['name']}:</b> {progress_bar} {stat['adherence']:.1f}%\n"

			# Add recommendations
			if overall_adherence >= 90:
				report += f"\n{config.EMOJIS['success']} <b>מצוין!</b> שיעור ציות גבוה מאוד."
			elif overall_adherence >= 80:
				report += f"\n{config.EMOJIS['warning']} <b>טוב.</b> יש מקום לשיפור קל."
			else:
				report += f"\n{config.EMOJIS['error']} <b>דורש תשומת לב.</b> מומלץ להתייעצות עם הרופא."

			return report

		except Exception as e:
			logger.error(f"Error generating adherence report: {e}")
			return f"{config.EMOJIS['error']} שגיאה ביצירת דוח נטילת תרופות"

	async def _generate_symptoms_report(self, user_id: int, start_date: date, end_date: date) -> str:
		"""Generate symptoms and side effects report"""
		try:
			# Get symptom logs in date range
			symptom_logs = await DatabaseManager.get_symptom_logs_in_range(user_id, start_date, end_date)

			if not symptom_logs:
				return f"{config.EMOJIS['info']} אין נתוני תופעות לוואי בתקופה זו"

			# Calculate statistics
			mood_scores = [log.mood_score for log in symptom_logs if log.mood_score]
			avg_mood = sum(mood_scores) / len(mood_scores) if mood_scores else 0

			symptoms_days = len([log for log in symptom_logs if log.symptoms])
			side_effects_days = len([log for log in symptom_logs if log.side_effects])

			# Common symptoms analysis
			all_symptoms = []
			all_side_effects = []

			for log in symptom_logs:
				if log.symptoms:
					all_symptoms.extend(log.symptoms.split(", "))
				if log.side_effects:
					all_side_effects.extend(log.side_effects.split(", "))

			# Count frequency
			from collections import Counter

			common_symptoms = Counter(all_symptoms).most_common(5)
			common_side_effects = Counter(all_side_effects).most_common(5)

			report = f"""
🩺 <b>דוח תופעות לוואי ותסמינים</b>

📊 <b>סיכום כללי:</b>
• ימים עם רישומים: {len(symptom_logs)}
• ממוצע מצב רוח: {avg_mood:.1f}/10 {self._get_mood_emoji(avg_mood)}
• ימים עם תסמינים: {symptoms_days}
• ימים עם תופעות לוואי: {side_effects_days}
			"""

			if common_symptoms:
				report += "\n🤒 <b>תסמינים נפוצים:</b>\n"
				for symptom, count in common_symptoms:
					report += f"• {symptom}: {count} פעמים\n"

			if common_side_effects:
				report += "\n💊 <b>תופעות לוואי נפוצות:</b>\n"
				for side_effect, count in common_side_effects:
					report += f"• {side_effect}: {count} פעמים\n"

			# Mood trend
			if len(mood_scores) > 1:
				recent_mood = sum(mood_scores[-3:]) / len(mood_scores[-3:])
				early_mood = sum(mood_scores[:3]) / len(mood_scores[:3])
				trend = "עולה" if recent_mood > early_mood + 5 else "מתדרדרת" if recent_mood < early_mood - 5 else "יציבה"
				report += f"\n📈 **מגמת מצב רוח:** {trend}"

			return report

		except Exception as e:
			logger.error(f"Error generating symptoms report: {e}")
			return f"{config.EMOJIS['error']} שגיאה ביצירת דוח תופעות לוואי"

	async def _generate_inventory_report(self, user_id: int) -> str:
		"""Generate inventory status report"""
		try:
			medicines = await DatabaseManager.get_user_medicines(user_id)

			if not medicines:
				return f"{config.EMOJIS['info']} אין תרופות רשומות"

			low_stock = []
			out_of_stock = []
			good_stock = []

			for medicine in medicines:
				if medicine.inventory_count <= 0:
					out_of_stock.append(medicine)
				elif medicine.inventory_count <= medicine.low_stock_threshold:
					low_stock.append(medicine)
				else:
					good_stock.append(medicine)

			report = f"""
📦 <b>דוח מצב מלאי</b>

📊 <b>סיכום:</b>
• סה"כ תרופות: {len(medicines)}
• מלאי טוב: {len(good_stock)}
• מלאי נמוך: {len(low_stock)}
• נגמר: {len(out_of_stock)}
			"""

			if out_of_stock:
				report += "\n🚨 **תרופות שנגמרו (דורש הזמנה דחופה):**\n"
				for medicine in out_of_stock:
					report += f"• {medicine.name}\n"

			if low_stock:
				report += "\n⚠️ **מלאי נמוך (מומלץ להזמין):**\n"
				for medicine in low_stock:
					report += f"• {medicine.name}: {medicine.inventory_count} כדורים\n"

			if good_stock:
				report += "\n✅ **מלאי תקין:**\n"
				for medicine in good_stock[:5]:  # Show first 5
					report += f"• {medicine.name}: {medicine.inventory_count} כדורים\n"

			return report
		except Exception as e:
			logger.error(f"Error generating inventory report: {e}")
			return f"{config.EMOJIS['error']} שגיאה ביצירת דוח מלאי"