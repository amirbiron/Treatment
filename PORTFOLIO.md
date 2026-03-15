```yaml
name: "Treatment - בוט תזכורת תרופות"
repo: "https://github.com/amirbiron/Treatment"
status: "פעיל (בייצור)"

one_liner: "בוט טלגרם חכם לתזכורת תרופות עם מעקב מלאי, יומן תופעות לוואי, מצב מטפל, ודוחות תקופתיים — מותאם לזקנים ומטפלים."

stack:
  - Python 3.11+
  - python-telegram-bot 22.3 (עם job-queue)
  - SQLAlchemy 2.0 + aiosqlite (SQLite)
  - Motor (MongoDB async, אופציונלי)
  - APScheduler 3.11
  - tornado
  - aiohttp / httpx
  - python-dotenv
  - pytz
  - python-dateutil

key_features:
  - "תזכורות אוטומטיות בזמן מדויק עם snooze"
  - "מעקב מלאי כדורים עם התראות מלאי נמוך"
  - "יומן תופעות לוואי ומעקב מצב רוח (סקלה 1-10)"
  - "מצב מטפל - הוספת מטפלים ובני משפחה עם דיווחים אוטומטיים"
  - "דוחות שבועיים ויומיים אוטומטיים"
  - "ממשק בעברית עם כפתורים גדולים - מותאם לזקנים"
  - "תמיכה ב-webhook (ייצור) ו-polling (פיתוח)"
  - "CI/CD עם GitHub Actions"

architecture:
  summary: |
    ארכיטקטורה מודולרית מבוססת handlers. SQLAlchemy עם aiosqlite למסד נתונים
    אסינכרוני. APScheduler לתזמון תזכורות. Handlers מופרדים לפי תחום:
    תרופות, תזכורות, תור, דוחות, מטפלים. Utils לפונקציות עזר, מקלדות, וזמנים.
  entry_points:
    - "main.py - נקודת כניסה, הגדרת Application והפעלת handlers"
    - "config.py - הגדרות (Config class), משתני סביבה, הודעות"
    - "database.py - מודלים SQLAlchemy ופונקציות DB"
    - "scheduler.py - מנוע תזמון APScheduler"
    - "handlers/medicine_handler.py - ניהול תרופות"
    - "handlers/reminder_handler.py - תזכורות ו-snooze"
    - "handlers/appointments_handler.py - ניהול תורים"
    - "handlers/reports_handler.py - דוחות שבועיים/יומיים"
    - "handlers/caregiver_handler.py - מצב מטפל"
    - "utils/keyboards.py - תפריטים וכפתורים"
    - "utils/helpers.py - פונקציות עזר"
    - "utils/time.py - פונקציות זמן"

demo:
  live_url: "" # TODO: בדוק ידנית
  video_url: "" # TODO: בדוק ידנית

setup:
  quickstart: |
    1. git clone <repository-url> && cd Treatment
    2. python -m venv venv && source venv/bin/activate
    3. pip install -r requirements.txt
    4. cp .env.example .env  # מלא BOT_TOKEN, BOT_USERNAME
    5. python main.py

your_role: "פיתוח מלא - ארכיטקטורה, מודלים, handlers, scheduler, בדיקות, CI/CD"

tradeoffs:
  - "SQLite עם aiosqlite במקום PostgreSQL - פשטות פריסה, מספיק לקנה מידה קטן"
  - "תמיכה כפולה SQLite/MongoDB - גמישות על חשבון מורכבות"
  - "APScheduler במקום Celery - פשטות ללא צורך ב-Redis/RabbitMQ"
  - "ארכיטקטורת handlers מודולרית - תחזוקתיות על חשבון מעט boilerplate"

metrics: {} # TODO: בדוק ידנית

faq:
  - q: "האם הבוט מחליף ייעוץ רפואי?"
    a: "לא. הבוט מיועד לעזרה בלבד ואינו תחליף לייעוץ רפואי מקצועי"
  - q: "איך מוסיפים מטפל?"
    a: "דרך פקודות הבוט במצב מטפל — handlers/caregiver_handler.py"
  - q: "איפה נשמרים הנתונים?"
    a: "ב-SQLite מקומי (ברירת מחדל) או MongoDB (לפי DB_BACKEND)"
```
