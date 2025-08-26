import os
import asyncio
import types
import pytest

# Disable config validation during tests
os.environ.setdefault("DISABLE_CONFIG_VALIDATION", "1")

from scheduler import medicine_scheduler


class StubUser:
	def __init__(self, id_: int, telegram_id: int = None, timezone: str = "Asia/Jerusalem", is_active: bool = True):
		self.id = id_
		self.telegram_id = telegram_id or id_
		self.timezone = timezone
		self.is_active = is_active


class StubMedicine:
	def __init__(self, id_: int, user_id: int, name: str = "TestMed", dosage: str = "1 tab"):
		self.id = id_
		self.user_id = user_id
		self.name = name
		self.dosage = dosage
		self.inventory_count = 30
		self.low_stock_threshold = 5
		self.is_active = True


class StubBot:
	def __init__(self):
		self.sent = []

	async def send_message(self, chat_id: int, text: str, parse_mode: str = None, reply_markup=None):
		self.sent.append({"chat_id": chat_id, "text": text})


@pytest.mark.asyncio
async def test_schedule_snooze_uses_db_user_id(monkeypatch):
	"""schedule_snooze_reminder should pass stable DB user id in job args."""
	# Arrange: given a Telegram id that resolves to a DB user with id 42
	telegram_id = 999_111_222
	db_user = StubUser(id_=42, telegram_id=telegram_id)
	calls = {}

	async def fake_get_user_by_id(uid):
		return None

	async def fake_get_user_by_telegram_id(tid):
		assert tid == telegram_id
		return db_user

	def fake_add_job(func, trigger, id, args, name, replace_existing):
		# Capture args to assert stable id was used
		calls["args"] = list(args)
		calls["id"] = id
		return types.SimpleNamespace(id=id)

	monkeypatch.setattr("database.DatabaseManager.get_user_by_id", fake_get_user_by_id)
	monkeypatch.setattr("database.DatabaseManager.get_user_by_telegram_id", fake_get_user_by_telegram_id)
	monkeypatch.setattr(medicine_scheduler.scheduler, "add_job", fake_add_job)

	# Act
	job_id = await medicine_scheduler.schedule_snooze_reminder(user_id=telegram_id, medicine_id=7, snooze_minutes=1)

	# Assert: first arg passed to job is stable DB user id (42), not Telegram id
	assert calls["args"][0] == db_user.id
	assert calls["args"][1] == 7
	assert job_id == calls["id"]


@pytest.mark.asyncio
async def test_send_medicine_reminder_fallback_to_telegram_id(monkeypatch):
	"""_send_medicine_reminder should fallback to Telegram ID lookup if DB id not found."""
	telegram_id = 555_666_777
	user = StubUser(id_=101, telegram_id=telegram_id)
	medicine = StubMedicine(id_=7, user_id=user.id)
	bot = StubBot()
	medicine_scheduler.bot = bot

	async def fake_get_medicine_by_id(mid):
		assert mid == medicine.id
		return medicine

	async def fake_get_user_by_id(uid):
		# Simulate missing DB user when called with Telegram id
		return None

	async def fake_get_user_by_telegram_id(tid):
		assert tid == telegram_id
		return user

	monkeypatch.setattr("database.DatabaseManager.get_medicine_by_id", fake_get_medicine_by_id)
	monkeypatch.setattr("database.DatabaseManager.get_user_by_id", fake_get_user_by_id)
	monkeypatch.setattr("database.DatabaseManager.get_user_by_telegram_id", fake_get_user_by_telegram_id)

	# Act: call with Telegram id to exercise fallback path
	await medicine_scheduler._send_medicine_reminder(user_id=telegram_id, medicine_id=medicine.id)

	# Assert: message was sent
	assert len(bot.sent) == 1
	assert bot.sent[0]["chat_id"] == user.telegram_id
	assert "זמן לקחת תרופה" in bot.sent[0]["text"]