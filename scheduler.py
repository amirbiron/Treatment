"""
Advanced scheduling system for medicine reminders
Using APScheduler 3.11.0 with async support
"""

import asyncio
import logging
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional, Callable, Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, JobExecutionEvent

from config import config
from database import DatabaseManager, MedicineSchedule, Medicine, User

logger = logging.getLogger(__name__)


class MedicineScheduler:
    """Advanced scheduler for medicine reminders with smart features"""
    
    def __init__(self, bot_instance=None):
        self.bot = bot_instance
        self.scheduler = None
        self.job_callbacks: Dict[str, Callable] = {}
        self.reminder_attempts: Dict[str, int] = {}
        
        # Configure APScheduler
        jobstores = {
            'default': MemoryJobStore()
        }
        executors = {
            'default': AsyncIOExecutor()
        }
        
        job_defaults = {
            'coalesce': True,
            'max_instances': 3,
            'misfire_grace_time': 30
        }
        
        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone='UTC'
        )
        
        # Add event listeners
        self.scheduler.add_listener(
            self._job_executed_listener,
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
        )
    
    async def start(self):
        """Start the scheduler"""
        try:
            self.scheduler.start()
            logger.info("Medicine scheduler started successfully")
            
            # Schedule weekly reports
            await self._schedule_weekly_reports()
            
            # Schedule daily caregiver reports
            await self._schedule_caregiver_reports()
            
            # Schedule inventory checks
            await self._schedule_inventory_checks()
            
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
            raise
    
    async def stop(self):
        """Stop the scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logger.info("Medicine scheduler stopped")
    
    async def schedule_medicine_reminder(
        self, 
        user_id: int, 
        medicine_id: int, 
        reminder_time: time,
        timezone: str = "UTC"
    ) -> str:
        """Schedule a daily medicine reminder"""
        job_id = f"medicine_reminder_{user_id}_{medicine_id}_{reminder_time.strftime('%H%M')}"
        
        try:
            # Remove existing job if it exists
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
            
            # Create cron trigger for daily reminder
            trigger = CronTrigger(
                hour=reminder_time.hour,
                minute=reminder_time.minute,
                timezone=timezone
            )
            
            # Schedule the job
            self.scheduler.add_job(
                func=self._send_medicine_reminder,
                trigger=trigger,
                id=job_id,
                args=[user_id, medicine_id],
                name=f"Medicine reminder for user {user_id}",
                replace_existing=True
            )
            
            logger.info(f"Scheduled medicine reminder: {job_id}")
            return job_id
            
        except Exception as e:
            logger.error(f"Failed to schedule medicine reminder: {e}")
            raise
    
    async def schedule_snooze_reminder(
        self, 
        user_id: int, 
        medicine_id: int, 
        snooze_minutes: int = None
    ) -> str:
        """Schedule a snoozed reminder"""
        if snooze_minutes is None:
            snooze_minutes = config.REMINDER_SNOOZE_MINUTES
        
        job_id = f"snooze_reminder_{user_id}_{medicine_id}_{datetime.now().timestamp()}"
        remind_time = datetime.now() + timedelta(minutes=snooze_minutes)
        
        try:
            trigger = DateTrigger(run_date=remind_time)
            
            self.scheduler.add_job(
                func=self._send_snoozed_reminder,
                trigger=trigger,
                id=job_id,
                args=[user_id, medicine_id],
                name=f"Snoozed reminder for user {user_id}",
                replace_existing=True
            )
            
            logger.info(f"Scheduled snooze reminder: {job_id} for {remind_time}")
            return job_id
            
        except Exception as e:
            logger.error(f"Failed to schedule snooze reminder: {e}")
            raise
    
    async def cancel_medicine_reminders(self, user_id: int, medicine_id: int = None):
        """Cancel medicine reminders for a user or specific medicine"""
        pattern = f"medicine_reminder_{user_id}"
        if medicine_id:
            pattern += f"_{medicine_id}"
        
        jobs_to_remove = []
        for job in self.scheduler.get_jobs():
            if job.id.startswith(pattern):
                jobs_to_remove.append(job.id)
        
        for job_id in jobs_to_remove:
            self.scheduler.remove_job(job_id)
            logger.info(f"Cancelled job: {job_id}")
    
    async def _send_medicine_reminder(self, user_id: int, medicine_id: int):
        """Send medicine reminder to user"""
        try:
            if not self.bot:
                logger.error("Bot instance not available")
                return
            
            # Get medicine details
            medicine = await DatabaseManager.get_medicine_by_id(medicine_id)
            if not medicine or not medicine.is_active:
                logger.info(f"Medicine {medicine_id} not found or inactive")
                return
            
            user = await DatabaseManager.get_user_by_id(user_id)
            if not user or not user.is_active:
                logger.info(f"User {user_id} not found or inactive")
                return
            
            # Create reminder message
            message = f"""
{config.EMOJIS['reminder']} *זמן לקחת תרופה!*

{config.EMOJIS['medicine']} *{medicine.name}*
💊 מינון: {medicine.dosage}

{config.EMOJIS['inventory']} מלאי נותר: {medicine.inventory_count} כדורים
            """
            
            if medicine.inventory_count <= medicine.low_stock_threshold:
                message += f"\n{config.EMOJIS['warning']} *מלאי נמוך! כדאי להזמין עוד*"
            
            # Send reminder with inline keyboard
            from utils.keyboards import get_reminder_keyboard
            keyboard = get_reminder_keyboard(medicine_id)
            
            await self.bot.send_message(
                chat_id=user.telegram_id,
                text=message,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            
            # Track reminder attempt
            reminder_key = f"{user_id}_{medicine_id}"
            self.reminder_attempts[reminder_key] = self.reminder_attempts.get(reminder_key, 0) + 1
            
            logger.info(f"Sent medicine reminder to user {user_id} for medicine {medicine_id}")
            
        except Exception as e:
            logger.error(f"Failed to send medicine reminder: {e}")
    
    async def _send_snoozed_reminder(self, user_id: int, medicine_id: int):
        """Send snoozed reminder to user"""
        try:
            reminder_key = f"{user_id}_{medicine_id}"
            attempts = self.reminder_attempts.get(reminder_key, 0)
            
            if attempts >= config.MAX_REMINDER_ATTEMPTS:
                # Mark as missed and notify caregivers
                await self._mark_dose_missed(user_id, medicine_id)
                await self._notify_caregivers_missed_dose(user_id, medicine_id)
                
                # Reset attempt counter
                self.reminder_attempts[reminder_key] = 0
                return
            
            # Send another reminder
            await self._send_medicine_reminder(user_id, medicine_id)
            
        except Exception as e:
            logger.error(f"Failed to send snoozed reminder: {e}")
    
    async def _schedule_weekly_reports(self):
        """Schedule weekly reports for all users"""
        try:
            trigger = CronTrigger(
                day_of_week=config.WEEKLY_REPORT_DAY,
                hour=int(config.WEEKLY_REPORT_TIME.split(':')[0]),
                minute=int(config.WEEKLY_REPORT_TIME.split(':')[1]),
                timezone='UTC'
            )
            
            self.scheduler.add_job(
                func=self._send_weekly_reports,
                trigger=trigger,
                id="weekly_reports",
                name="Send weekly reports to all users",
                replace_existing=True
            )
            
            logger.info("Scheduled weekly reports")
            
        except Exception as e:
            logger.error(f"Failed to schedule weekly reports: {e}")
    
    async def _schedule_caregiver_reports(self):
        """Schedule daily reports for caregivers"""
        try:
            trigger = CronTrigger(
                hour=int(config.CAREGIVER_DAILY_REPORT_TIME.split(':')[0]),
                minute=int(config.CAREGIVER_DAILY_REPORT_TIME.split(':')[1]),
                timezone='UTC'
            )
            
            self.scheduler.add_job(
                func=self._send_caregiver_reports,
                trigger=trigger,
                id="caregiver_daily_reports",
                name="Send daily reports to caregivers",
                replace_existing=True
            )
            
            logger.info("Scheduled caregiver daily reports")
            
        except Exception as e:
            logger.error(f"Failed to schedule caregiver reports: {e}")
    
    async def _schedule_inventory_checks(self):
        """Schedule inventory low stock checks"""
        try:
            # Check inventory every 6 hours
            trigger = IntervalTrigger(hours=6)
            
            self.scheduler.add_job(
                func=self._check_low_inventory,
                trigger=trigger,
                id="inventory_check",
                name="Check low inventory levels",
                replace_existing=True
            )
            
            logger.info("Scheduled inventory checks")
            
        except Exception as e:
            logger.error(f"Failed to schedule inventory checks: {e}")
    
    async def _send_weekly_reports(self):
        """Send weekly reports to all active users"""
        try:
            users = await DatabaseManager.get_all_active_users()
            for user in users:
                await self._generate_and_send_weekly_report(user.id)
        except Exception as e:
            logger.error(f"Failed to send weekly reports: {e}")
    
    async def _send_caregiver_reports(self):
        """Send daily reports to all caregivers"""
        try:
            caregivers = await DatabaseManager.get_all_active_caregivers()
            for caregiver in caregivers:
                await self._generate_and_send_caregiver_report(caregiver)
        except Exception as e:
            logger.error(f"Failed to send caregiver reports: {e}")
    
    async def _check_low_inventory(self):
        """Check for medicines with low inventory and send alerts"""
        try:
            low_stock_medicines = await DatabaseManager.get_low_stock_medicines()
            for medicine in low_stock_medicines:
                await self._send_low_stock_alert(medicine)
        except Exception as e:
            logger.error(f"Failed to check inventory: {e}")
    
    async def _job_executed_listener(self, event: JobExecutionEvent):
        """Listen to job execution events"""
        if event.exception:
            logger.error(f"Job {event.job_id} crashed: {event.exception}")
        else:
            logger.debug(f"Job {event.job_id} executed successfully")
    
    async def _mark_dose_missed(self, user_id: int, medicine_id: int):
        """Mark a dose as missed in the database"""
        try:
            await DatabaseManager.log_dose_missed(medicine_id, datetime.now())
        except Exception as e:
            logger.error(f"Failed to mark dose as missed: {e}")
    
    async def _notify_caregivers_missed_dose(self, user_id: int, medicine_id: int):
        """Notify caregivers about missed dose"""
        try:
            caregivers = await DatabaseManager.get_user_caregivers(user_id)
            medicine = await DatabaseManager.get_medicine_by_id(medicine_id)
            user = await DatabaseManager.get_user_by_id(user_id)
            
            if not medicine or not user:
                return
            
            message = f"""
{config.EMOJIS['warning']} *התראה: תרופה לא נלקחה*

👤 מטופל: {user.first_name} {user.last_name or ''}
💊 תרופה: {medicine.name}
⏰ זמן מתוכנן: {datetime.now().strftime('%H:%M')}

הודעה זו נשלחת לאחר {config.MAX_REMINDER_ATTEMPTS} ניסיונות תזכורת.
            """
            
            for caregiver in caregivers:
                if caregiver.is_active and caregiver.caregiver_telegram_id and caregiver.caregiver_telegram_id > 0:
                    await self.bot.send_message(
                        chat_id=caregiver.caregiver_telegram_id,
                        text=message,
                        parse_mode='Markdown'
                    )
            
        except Exception as e:
            logger.error(f"Failed to notify caregivers: {e}")
    
    def get_scheduled_jobs(self, user_id: int = None) -> List[Dict[str, Any]]:
        """Get list of scheduled jobs, optionally filtered by user"""
        jobs = []
        for job in self.scheduler.get_jobs():
            if user_id and not job.id.startswith(f"medicine_reminder_{user_id}"):
                continue
                
            jobs.append({
                'id': job.id,
                'name': job.name,
                'next_run': job.next_run_time,
                'trigger': str(job.trigger)
            })
        
        return jobs


# Global scheduler instance
medicine_scheduler = MedicineScheduler()
