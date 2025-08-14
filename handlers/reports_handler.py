"""
Reports Handler
Handles generation and sending of various reports: weekly, monthly, adherence, symptoms
"""

import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, 
    ConversationHandler, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler,
    filters
)

from config import config
from database import DatabaseManager
from utils.keyboards import (
    get_reports_keyboard,
    get_main_menu_keyboard,
    get_cancel_keyboard,
    get_confirmation_keyboard
)
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
    format_list_hebrew
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
            "full": "דוח מקיף"
        }
        
        # Date range options
        self.date_ranges = {
            "last_7_days": "7 ימים אחרונים",
            "last_14_days": "14 ימים אחרונים", 
            "last_30_days": "30 ימים אחרונים",
            "last_3_months": "3 חודשים אחרונים",
            "custom": "תקופה מותאמת אישית"
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
                SELECT_REPORT_TYPE: [
                    CallbackQueryHandler(self.handle_report_type_selection, pattern="^rtype_")
                ],
                SELECT_DATE_RANGE: [
                    CallbackQueryHandler(self.handle_date_range_selection, pattern="^range_")
                ],
                CONFIRM_SEND: [
                    CallbackQueryHandler(self.confirm_send_report, pattern="^send_confirm_"),
                    CallbackQueryHandler(self.cancel_send_report, pattern="^send_cancel_")
                ]
            },
            fallbacks=[
                CommandHandler("cancel", self.cancel_report),
                CallbackQueryHandler(self.cancel_report, pattern="^cancel$")
            ],
            per_message=False
        )
    
    def get_handlers(self) -> List:
        """Get additional command handlers"""
        return [
            CommandHandler("generate_report", self.start_custom_report),
            CommandHandler("send_to_doctor", self.send_to_doctor_flow),
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
            
            # Calculate date range (last 7 days)
            end_date = date.today()
            start_date = end_date - timedelta(days=7)
            
            # Generate report
            report = await self._generate_adherence_report(user.id, start_date, end_date)
            symptoms_report = await self._generate_symptoms_report(user.id, start_date, end_date)
            
            # Combine reports
            full_report = self._combine_reports([report, symptoms_report])
            
            message = f"""
{config.EMOJIS['report']} <b>דוח שבועי</b>
📅 {format_date_hebrew(start_date)} - {format_date_hebrew(end_date)}

{full_report}

{config.EMOJIS['info']} דוח זה נשלח אוטומטית למטפלים שלכם.
            """
            
            # Send to user
            keyboard = [
                [
                    InlineKeyboardButton(
                        f"📧 שלח לרופא",
                        callback_data="report_action_send_doctor"
                    ),
                    InlineKeyboardButton(
                        f"📱 שתף",
                        callback_data="report_action_share"
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"{config.EMOJIS['home']} תפריט ראשי",
                        callback_data="main_menu"
                    )
                ]
            ]
            
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await update.message.reply_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            # Send to caregivers
            await self._send_report_to_caregivers(user.id, "דוח שבועי", full_report)
            
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
            full_report = self._combine_reports([
                adherence_report,
                symptoms_report, 
                inventory_report,
                trends_report
            ])
            
            message = f"""
{config.EMOJIS['report']} <b>דוח חודשי מקיף</b>
📅 {format_date_hebrew(start_date)} - {format_date_hebrew(end_date)}

{full_report}

{config.EMOJIS['info']} דוח זה מתאים להצגה לרופא או למטפל.
            """
            
            keyboard = [
                [
                    InlineKeyboardButton(
                        f"📧 שלח לרופא",
                        callback_data="report_action_send_doctor"
                    ),
                    InlineKeyboardButton(
                        f"💾 שמור כקובץ",
                        callback_data="export_report_monthly"
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"📊 דוח מפורט נוסף",
                        callback_data="report_detailed"
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"{config.EMOJIS['home']} תפריט ראשי",
                        callback_data="main_menu"
                    )
                ]
            ]
            
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await update.message.reply_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
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
                    InlineKeyboardButton(
                        f"📅 דוח שבועי",
                        callback_data="report_weekly"
                    ),
                    InlineKeyboardButton(
                        f"📊 דוח חודשי",
                        callback_data="report_monthly"
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"💊 דוח נטילת תרופות",
                        callback_data="report_adherence"
                    ),
                    InlineKeyboardButton(
                        f"🩺 דוח תופעות לוואי",
                        callback_data="report_symptoms"
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"📋 דוח מקיף",
                        callback_data="report_full"
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"📧 שלח לרופא",
                        callback_data="report_send_doctor"
                    )
                ],
                [
                    InlineKeyboardButton(
                        f"{config.EMOJIS['back']} חזור",
                        callback_data="main_menu"
                    )
                ]
            ]
            
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await update.message.reply_text(
                    message,
                    parse_mode='HTML',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
        except Exception as e:
            logger.error(f"Error showing reports menu: {e}")
            await self._send_error_message(update, "שגיאה בהצגת תפריט הדוחות")
    
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
                doses = await DatabaseManager.get_medicine_doses_in_range(
                    medicine.id, start_date, end_date
                )
                
                med_taken = len([d for d in doses if d.status == 'taken'])
                med_missed = len([d for d in doses if d.status == 'missed'])
                med_skipped = len([d for d in doses if d.status == 'skipped'])
                med_total = len(doses)
                
                if med_total > 0:
                    adherence_rate = (med_taken / med_total) * 100
                    
                    medicine_stats.append({
                        'name': medicine.name,
                        'taken': med_taken,
                        'total': med_total,
                        'adherence': adherence_rate
                    })
                    
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
                progress_bar = create_progress_bar(stat['taken'], stat['total'], 8)
                report += f"• <b>{stat['name']}:</b> {progress_bar} {stat['adherence']:.1f}%\n"
            
            # Add recommendations
            if overall_adherence >= 90:
                report += f"\n{config.EMOJIS['success']} <b>מצוין!</b> שיעור ציות גבוה מאוד."
            elif overall_adherence >= 80:
                report += f"\n{config.EMOJIS['warning']} <b>טוב.</b> יש מקום לשיפור קל."
            else:
                report += f"\n{config.EMOJIS['error']} <b>דורש תשומת לב.</b> מומלץ להתייעץ עם הרופא."
            
            return report
            
        except Exception as e:
            logger.error(f"Error generating adherence report: {e}")
            return f"{config.EMOJIS['error']} שגיאה ביצירת דוח נטילת תרופות"
    
    async def _generate_symptoms_report(self, user_id: int, start_date: date, end_date: date) -> str:
        """Generate symptoms and side effects report"""
        try:
            # Get symptom logs in date range
            symptom_logs = await DatabaseManager.get_symptom_logs_in_range(
                user_id, start_date, end_date
            )
            
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
                    all_symptoms.extend(log.symptoms.split(', '))
                if log.side_effects:
                    all_side_effects.extend(log.side_effects.split(', '))
            
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
                report += f"\n🤒 <b>תסמינים נפוצים:</b>\n"
                for symptom, count in common_symptoms:
                    report += f"• {symptom}: {count} פעמים\n"
            
            if common_side_effects:
                report += f"\n💊 <b>תופעות לוואי נפוצות:</b>\n"
                for side_effect, count in common_side_effects:
                    report += f"• {side_effect}: {count} פעמים\n"
            
            # Mood trend
            if len(mood_scores) > 1:
                recent_mood = sum(mood_scores[-3:]) / len(mood_scores[-3:])
                early_mood = sum(mood_scores[:3]) / len(mood_scores[:3])
                trend = "עולה" if recent_mood > early_mood else "יורדת" if recent_mood < early_mood else "יציבה"
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
                report += f"\n🚨 **תרופות שנגמרו (דורש הזמנה דחופה):**\n"
                for medicine in out_of_stock:
                    report += f"• {medicine.name}\n"
            
            if low_stock:
                report += f"\n⚠️ **מלאי נמוך (מומלץ להזמין):**\n"
                for medicine in low_stock:
                    report += f"• {medicine.name}: {medicine.inventory_count} יחידות\n"
            
            if good_stock:
                report += f"\n✅ **מלאי תקין:**\n"
                for medicine in good_stock[:5]:  # Show first 5
                    report += f"• {medicine.name}: {medicine.inventory_count} יחידות\n"
                
                if len(good_stock) > 5:
                    report += f"ועוד {len(good_stock) - 5} תרופות...\n"
            
            return report
            
        except Exception as e:
            logger.error(f"Error generating inventory report: {e}")
            return f"{config.EMOJIS['error']} שגיאה ביצירת דוח מלאי"
    
    async def _generate_trends_report(self, user_id: int, start_date: date, end_date: date) -> str:
        """Generate trends analysis report"""
        try:
            # Get adherence data over time
            daily_adherence = await self._calculate_daily_adherence(user_id, start_date, end_date)
            
            if not daily_adherence:
                return f"{config.EMOJIS['info']} אין מספיק נתונים לניתוח מגמות"
            
            # Calculate trends
            dates = list(daily_adherence.keys())
            rates = list(daily_adherence.values())
            
            if len(rates) < 3:
                return f"{config.EMOJIS['info']} דרושים לפחות 3 ימים לניתוח מגמות"
            
            # Simple trend analysis
            recent_avg = sum(rates[-3:]) / 3
            early_avg = sum(rates[:3]) / 3
            
            trend_direction = "משתפרת" if recent_avg > early_avg + 5 else "מתדרדרת" if recent_avg < early_avg - 5 else "יציבה"
            
            # Best and worst days
            best_rate = max(rates)
            worst_rate = min(rates)
            
            report = f"""
📈 <b>ניתוח מגמות</b>

🎯 <b>מגמת ציות:</b> {trend_direction}
• ממוצע בתחילת התקופה: {early_avg:.1f}%
• ממוצע בסוף התקופה: {recent_avg:.1f}%

📊 <b>נתונים נוספים:</b>
• שיעור ציות הכי גבוה: {best_rate:.1f}%
• שיעור ציות הכי נמוך: {worst_rate:.1f}%
• יציבות: {"גבוהה" if max(rates) - min(rates) < 20 else "בינונית" if max(rates) - min(rates) < 40 else "נמוכה"}
"""
            
            # Recommendations based on trends
            if trend_direction == "מתדרדרת":
                report += f"\n💡 <b>המלצות:</b>\n• כדאי לבדוק סיבות לירידה בציות\n• ייתכן שצריך התאמת זמני התזכורות\n• מומלץ התייעצות עם הרופא"
            elif trend_direction == "משתפרת":
                report += f"\n🎉 <b>כל הכבוד!</b> המגמה חיובית, המשיכו כך!"
            
            return report
            
        except Exception as e:
            logger.error(f"Error generating trends report: {e}")
            return f"{config.EMOJIS['error']} שגיאה ביצירת ניתוח מגמות"
    
    async def _send_report_to_caregivers(self, user_id: int, report_title: str, report_content: str):
        """Send report to all caregivers"""
        try:
            caregivers = await DatabaseManager.get_user_caregivers(user_id, active_only=True)
            user = await DatabaseManager.get_user_by_id(user_id)
            
            if not caregivers or not user:
                return
            
            message = f"""
{config.EMOJIS['report']} <b>{report_title}</b>
👤 <b>מטופל:</b> {user.first_name} {user.last_name or ''}
📅 <b>תאריך:</b> {format_datetime_hebrew(datetime.now())}

{report_content}

{config.EMOJIS['info']} דוח זה נשלח אוטומטיות למטפלים.
            """
            
            for caregiver in caregivers:
                if 'view' in caregiver.permissions or 'manage' in caregiver.permissions:
                    try:
                        from main import bot  # Avoid circular import
                        if bot:
                            await bot.send_message(
                                chat_id=caregiver.caregiver_telegram_id,
                                text=message,
                                parse_mode='HTML'
                            )
                    except Exception as e:
                        logger.error(f"Failed to send report to caregiver {caregiver.id}: {e}")
            
        except Exception as e:
            logger.error(f"Error sending report to caregivers: {e}")
    
    def _combine_reports(self, reports: List[str]) -> str:
        """Combine multiple reports into one"""
        combined = "\n\n".join([report for report in reports if report])
        return combined
    
    def _get_mood_emoji(self, mood_score: float) -> str:
        """Get emoji for mood score"""
        if mood_score <= 2:
            return "😩"
        elif mood_score <= 4:
            return "😟"
        elif mood_score <= 6:
            return "😐"
        elif mood_score <= 8:
            return "😊"
        else:
            return "😄"
    
    async def _calculate_daily_adherence(self, user_id: int, start_date: date, end_date: date) -> Dict[date, float]:
        """Calculate daily adherence rates"""
        try:
            daily_rates = {}
            current_date = start_date
            
            while current_date <= end_date:
                # Get doses for this day
                day_doses = await DatabaseManager.get_doses_for_date(user_id, current_date)
                
                if day_doses:
                    taken = len([d for d in day_doses if d.status == 'taken'])
                    total = len(day_doses)
                    daily_rates[current_date] = (taken / total) * 100 if total > 0 else 0
                
                current_date += timedelta(days=1)
            
            return daily_rates
            
        except Exception as e:
            logger.error(f"Error calculating daily adherence: {e}")
            return {}
    
    async def cancel_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel report generation"""
        try:
            user_id = update.effective_user.id
            
            if user_id in self.user_report_data:
                del self.user_report_data[user_id]
            
            message = f"{config.EMOJIS['info']} יצירת הדוח בוטלה"
            
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(
                    message,
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                await update.message.reply_text(
                    message,
                    reply_markup=get_main_menu_keyboard()
                )
            
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error canceling report: {e}")
            return ConversationHandler.END
    
    async def _send_error_message(self, update: Update, error_text: str):
        """Send error message to user"""
        try:
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    f"{config.EMOJIS['error']} {error_text}",
                    reply_markup=get_main_menu_keyboard()
                )
            else:
                await update.message.reply_text(
                    f"{config.EMOJIS['error']} {error_text}",
                    reply_markup=get_main_menu_keyboard()
                )
        except Exception as e:
            logger.error(f"Error sending error message: {e}")


# Global instance
reports_handler = ReportsHandler()
