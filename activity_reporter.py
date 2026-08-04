"""
קובץ פשוט לדיווח פעילות - העתק את הקובץ הזה לכל בוט

חשוב: pymongo הוא דרייבר סינכרוני. הבוט רץ על asyncio, ולכן קריאה ישירה
ל-update_one מתוך handler חוסמת את ה-event loop כולו. אם מונגו לא זמין,
ברירת המחדל של pymongo היא להמתין 30 שניות לבחירת שרת - וכאן יש שני upserts,
כלומר עד 60 שניות של event loop תקוע לכל אינטראקציה. Telegram נותן ל-webhook
כ-60 שניות, ואחר כך שולח את אותו update שוב ושוב.
לכן: טיימאאוטים קצרים, הרצה ב-thread נפרד, ומפסק (circuit breaker) שמכבה
את הדיווח זמנית אחרי כשלונות רצופים.
"""
import asyncio
import logging
import threading
import time

from datetime import datetime, timezone

from pymongo import MongoClient

logger = logging.getLogger(__name__)

# טיימאאוטים קצרים - דיווח פעילות הוא אנליטיקה, לא נתיב קריטי
SERVER_SELECTION_TIMEOUT_MS = 2000
CONNECT_TIMEOUT_MS = 2000
SOCKET_TIMEOUT_MS = 2000

# מפסק: אחרי כך וכך כשלונות רצופים, מפסיקים לנסות למשך COOLDOWN שניות
FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 300

# תקרה למספר דיווחים שממתינים במקביל ב-thread pool
MAX_PENDING_REPORTS = 32


class SimpleActivityReporter:
    def __init__(self, mongodb_uri, service_id, service_name=None):
        """
        mongodb_uri: חיבור למונגו (אותו מהבוט המרכזי)
        service_id: מזהה השירות ב-Render
        service_name: שם הבוט (אופציונלי)
        """
        self.service_id = service_id
        self.service_name = service_name or service_id
        self.client = None
        self.db = None
        self.connected = False

        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._disabled_until = 0.0
        self._pending = 0

        if not mongodb_uri:
            logger.warning("Activity reporter disabled: no MongoDB URI configured")
            return

        try:
            self.client = MongoClient(
                mongodb_uri,
                serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS,
                connectTimeoutMS=CONNECT_TIMEOUT_MS,
                socketTimeoutMS=SOCKET_TIMEOUT_MS,
            )
            self.db = self.client["render_bot_monitor"]
            self.connected = True
        except Exception as exc:
            self.connected = False
            logger.warning(f"Activity reporter disabled: cannot init MongoDB client ({exc})")

    def _should_skip(self):
        """האם המפסק פתוח כרגע"""
        if not self.connected:
            return True
        with self._lock:
            return time.monotonic() < self._disabled_until

    def _record_success(self):
        with self._lock:
            self._consecutive_failures = 0
            self._disabled_until = 0.0

    def _record_failure(self):
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= FAILURE_THRESHOLD:
                self._disabled_until = time.monotonic() + COOLDOWN_SECONDS
                failures = self._consecutive_failures
                self._consecutive_failures = 0
            else:
                failures = None
        if failures is not None:
            logger.warning(
                f"Activity reporting paused for {COOLDOWN_SECONDS}s after {failures} consecutive MongoDB failures"
            )

    def _report_blocking(self, user_id):
        """הכתיבה בפועל למונגו - סינכרוני, חייב לרוץ מחוץ ל-event loop"""
        try:
            now = datetime.now(timezone.utc)

            # עדכון אינטראקציית המשתמש
            self.db.user_interactions.update_one(
                {"service_id": self.service_id, "user_id": user_id},
                {
                    "$set": {"last_interaction": now},
                    "$inc": {"interaction_count": 1},
                    "$setOnInsert": {"created_at": now}
                },
                upsert=True
            )

            # עדכון פעילות השירות
            self.db.service_activity.update_one(
                {"_id": self.service_id},
                {
                    "$set": {
                        "last_user_activity": now,
                        "service_name": self.service_name,
                        "updated_at": now
                    },
                    "$setOnInsert": {
                        "created_at": now,
                        "status": "active",
                        "total_users": 0,
                        "suspend_count": 0
                    }
                },
                upsert=True
            )
            self._record_success()

        except Exception as exc:
            # שקט - אל תיכשל את הבוט אם יש בעיה
            logger.debug(f"Activity report failed: {exc}")
            self._record_failure()

    def report_activity(self, user_id):
        """
        דיווח פעילות. בטוח לקריאה מתוך async handler:
        אם יש event loop פעיל, העבודה מועברת ל-thread ולא מחכים לה.
        """
        if self._should_skip():
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is None:
            # הקשר סינכרוני (סקריפט/טסט) - אפשר לרוץ ישירות
            self._report_blocking(user_id)
            return

        with self._lock:
            if self._pending >= MAX_PENDING_REPORTS:
                # מונגו איטי; לא נערים עוד עבודה
                return
            self._pending += 1

        def _run():
            try:
                self._report_blocking(user_id)
            finally:
                with self._lock:
                    self._pending -= 1

        try:
            # fire-and-forget: לא ממתינים ל-future, ה-event loop ממשיך מיד
            loop.run_in_executor(None, _run)
        except Exception as exc:
            with self._lock:
                self._pending -= 1
            logger.debug(f"Could not schedule activity report: {exc}")


# דוגמה לשימוש קל
def create_reporter(mongodb_uri, service_id, service_name=None):
    """יצירת reporter פשוט"""
    return SimpleActivityReporter(mongodb_uri, service_id, service_name)
