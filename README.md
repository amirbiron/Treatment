# 💊 Medicine Reminder Bot

בוט טלגרם חכם לתזכורת תרופות עם תכונות מתקדמות לזקנים ומטפלים.

## 🌟 תכונות עיקריות

### 🎯 תזכורות חכמות
- ⏰ תזכורות אוטומטיות בזמן מדויק
- 🔄 אפשרות snooze של התזכורות
- 📱 הודעות Push בטלגרם
- 🔁 תזכורות חוזרות אם לא מאושר

### 📊 מעקב מלאי
- 📦 מעקב כמות כדורים במלאי
- ⚠️ התראות מלאי נמוך
- 📉 ירידה אוטומטית במלאי בכל נטילה
- 📋 הצעות להזמנה מראש

### 📝 יומן תופעות לוואי
- 🩺 רישום תופעות לוואי יומיות
- 😊 מעקב מצב רוח (סקלה 1-10)
- 📈 דוחות תקופתיים
- 📧 שליחה לרופא/מטפל

### 👥 מצב מטפל
- 👨‍⚕️ הוספת מטפלים ובני משפחה
- 📊 דיווחים יומיים אוטומטיים
- 🚨 התראות על תרופות שלא נלקחו
- 🎛️ ניהול מרחוק של התרופות

### 🖥️ ממשק ידידותי
- 🔘 כפתורים גדולים וברורים
- 🇮🇱 ממשק בעברית
- 👵 מותאם לזקנים
- 📲 פשוט לשימוש

## 🛠️ התקנה ופריסה

### דרישות מקדימות

- Python 3.11+
- חשבון Telegram Bot (יצירה דרך @BotFather)
- חשבון Render (לפריסה בענן)

### התקנה מקומית

1. **שכפול הפרויקט:**
   ```bash
   git clone https://github.com/yourusername/medicine-reminder-bot.git
   cd medicine-reminder-bot
   ```

2. **יצירת סביבה וירטואלית:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # או
   venv\Scripts\activate  # Windows
   ```

3. **התקנת תלויות:**
   ```bash
   pip install -r requirements.txt
   ```

4. **הגדרת משתני סביבה:**
   צרו קובץ `.env` בתיקיית השורש:
   ```env
   BOT_TOKEN=your_bot_token_here
   BOT_USERNAME=your_bot_username
   DEBUG=True
   LOG_LEVEL=INFO
   DEFAULT_TIMEZONE=Asia/Jerusalem
   ```

5. **הפעלת הבוט:**
   ```bash
   python main.py
   ```

### 🚀 פריסה ב-Render

1. **הכנת הפרויקט:**
   - העלו את הקוד ל-GitHub
   - ודאו שיש קובץ `requirements.txt` ו-`runtime.txt`

2. **יצירת שירות ב-Render:**
   - היכנסו ל-[Render Dashboard](https://dashboard.render.com)
   - לחצו "New" → "Web Service"
   - חברו את הריפוזיטורי מ-GitHub

3. **הגדרות השירות:**
   ```
   Name: medicine-reminder-bot
   Environment: Python 3
   Build Command: pip install -r requirements.txt
   Start Command: python main.py
   ```

4. **הגדרת משתני סביבה ב-Render:**
   ```
   BOT_TOKEN=your_bot_token_here
   BOT_USERNAME=your_bot_username
   WEBHOOK_URL=https://your-app-name.onrender.com
   DEBUG=False
   LOG_LEVEL=INFO
   DATABASE_URL=sqlite+aiosqlite:///./medicine_bot.db
   DEFAULT_TIMEZONE=Asia/Jerusalem
   ```

5. **פריסה:**
   - לחצו "Create Web Service"
   - Render יבנה ויפרוס את הבוט אוטומטית
   - הבוט יעבוד במצב webhook

## ⚙️ הגדרות מתקדמות

### משתני סביבה נוספים

```env
# הגדרות תזכורות
REMINDER_SNOOZE_MINUTES=5
MAX_REMINDER_ATTEMPTS=3

# הגדרות מלאי
DEFAULT_LOW_STOCK_THRESHOLD=5.0
INVENTORY_WARNING_DAYS=3

# הגדרות דוחות
WEEKLY_REPORT_DAY=0  # 0=יום ב', 6=יום א'
WEEKLY_REPORT_TIME=09:00
CAREGIVER_DAILY_REPORT_TIME=20:00

# הגדרות ממשק
MAX_MEDICINES_PER_PAGE=5
KEYBOARD_TIMEOUT_SECONDS=300
MAX_CAREGIVERS_PER_USER=5
```

### הגדרת בוט טלגרם

1. **יצירת בוט:**
   - שלחו `/newbot` ל-@BotFather
   - בחרו שם ויוזרניים לבוט
   - שמרו את הטוקן שתקבלו

2. **הגדרות נוספות (אופציונלי):**
   ```
   /setdescription - תיאור הבוט
   /setabouttext - מידע על הבוט
   /setuserpic - תמונת פרופיל
   /setcommands - רשימת פקודות
   ```

3. **רשימת פקודות מומלצת:**
   ```
   start - התחלת השימוש
   help - הצגת עזרה
   add_medicine - הוספת תרופה
   my_medicines - הצגת התרופות
   next_reminders - תזכורות קרובות
   snooze - דחיית תזכורת
   log_symptoms - רישום תופעות לוואי
   weekly_report - דוח שבועי
   settings - הגדרות
   ```

## 🏗️ מבנה הפרויקט

```
medicine-reminder-bot/
├── main.py                 # נקודת כניסה ראשית
├── config.py              # הגדרות והודעות
├── database.py            # מודלים ונהלי DB
├── scheduler.py           # מנוע התזמונים
├── requirements.txt       # תלויות Python
├── runtime.txt           # גרסת Python
├── README.md             # מדריך זה
├── handlers/             # מטפלי פקודות
│   ├── medicine_handler.py
│   ├── reminder_handler.py
│   ├── symptoms_handler.py
│   ├── caregiver_handler.py
│   └── reports_handler.py
└── utils/               # כלי עזר
    ├── keyboards.py     # תפריטים וכפתורים
    ├── helpers.py       # פונקציות עזר
    └── validators.py    # בדיקות תקינות
```

## 🔧 פיתוח ותחזוקה

### הפעלה במצב פיתוח

```bash
# הגדרת DEBUG=True ב-.env
DEBUG=True
LOG_LEVEL=DEBUG

# הפעלת הבוט
python main.py
```

### בדיקות

```bash
# הרצת בדיקות (כאשר יתווספו)
python -m pytest tests/

# בדיקת איכות קוד
flake8 .
black .
```

### לוגים ומעקב

הבוט כולל לוגים מפורטים:
- 📊 פעילות משתמשים
- ⚠️ שגיאות ותקלות
- 📈 סטטיסטיקות שימוש
- 🔍 דיבוג (במצב פיתוח)

### גיבויים

**חשוב:** הקפידו לגבות את מסד הנתונים:
```bash
# גיבוי מקומי
cp medicine_bot.db backup_$(date +%Y%m%d).db

# גיבוי עם SQLite
sqlite3 medicine_bot.db ".backup backup.db"
```

## 🤝 תרומה לפרויקט

1. Fork הפרויקט
2. יצרו branch חדש (`git checkout -b feature/AmazingFeature`)
3. בצעו commit (`git commit -m 'Add some AmazingFeature'`)
4. Push ל-branch (`git push origin feature/AmazingFeature`)
5. פתחו Pull Request

## 🐛 דיווח בעיות

אם מצאתם בעיה:
1. בדקו אם הבעיה כבר דווחה ב-Issues
2. צרו Issue חדש עם פרטים מלאים
3. כללו לוגים ושגיאות אם יש
4. תארו איך לשחזר את הבעיה

## 📋 מאפיינים מתוכננים

- [ ] 🌐 תמיכה בשפות נוספות
- [ ] 📊 דשבורד ווב למטפלים
- [ ] 🔔 הודעות SMS (בנוסף לטלגרם)
- [ ] 📱 אפליקציה ניידת
- [ ] 🏥 אינטגרציה עם מערכות בריאות
- [ ] 🤖 בינה מלאכותית לזיהוי תרופות
- [ ] 📈 אנליטיקס מתקדמת

## ⚠️ הגבלות ואחריות

- הבוט מיועד לעזרה בלבד ואינו תחליף לייעוץ רפואי
- השתמשו בבוט באחריותכם
- התייעצו עם רופא לפני שינויים בטיפול
- הבוט אינו מחובר למערכות רפואיות רשמיות

## 📞 תמיכה

- 📧 Email: support@example.com
- 💬 Telegram: @SupportBot
- 🌐 אתר: https://example.com
- 📚 דוקומנטציה: https://docs.example.com

## 📜 רישיון

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 תודות

- Python Telegram Bot Library
- APScheduler
- SQLAlchemy
- Render Platform
- כל התורמים לפרויקט

---

<div align="center">

**💊 בוט תזכורת התרופות - דואג לבריאות שלכם 24/7**

Made with ❤️ in Israel

</div>

## Revert Guide (Rollback to a stable baseline)

If recent deploys introduced regressions, you can revert to a stable state prior to the last problematic merges.

- Last two merges likely related to current issues:
  - PR #25: `68f8752` — Merge pull request #25 (debug-bot-errors-in-logs)
  - PR #23: `bf705a7` — Merge pull request #23 (fix-appointment-booking)
- Stable baseline before these merges:
  - Post-PR #22 merge: `7f8f1cb`

### Option A: Revert the problematic merges (preferred first)

Use the merge revert (-m 1) to undo the merges cleanly, in a new branch:

```bash
# Create a hotfix branch
git checkout -b hotfix/revert-problematic-merges

# Revert PR #25
git revert -m 1 68f8752

# Revert PR #23 (if still needed)
git revert -m 1 bf705a7

# Resolve conflicts if any, commit, push and open a PR
```

### Option B: Branch from the stable baseline

If you prefer to branch from the last known-good commit and re-apply only desired changes:

```bash
git checkout -b hotfix/from-7f8f1cb 7f8f1cb
# Build/test, then push and open a PR
```

### Notes
- After reverting, rebuild and verify: scheduler start/stop, webhook handling, medicines edit flows, and symptoms logging.
- If you do not have terminal access, a maintainer can execute the above steps on your behalf. This file documents the exact commit IDs so the operation can be performed safely later.
