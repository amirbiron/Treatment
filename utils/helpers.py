from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pytz


# ===============================
# Validation helpers
# ===============================

def validate_medicine_name(name: Optional[str]) -> Tuple[bool, str]:
	if not name or not isinstance(name, str):
		return False, "שם תרופה נדרש"
	name = name.strip()
	if len(name) < 2:
		return False, "שם קצר מדי"
	if len(name) > 200:
		return False, "שם ארוך מדי"
	# Allow Hebrew, English letters, digits, spaces, dash, quotes, mg symbols like מ"ג
	if not re.match(r"^[\w\s\-\"'א-ת]+$", name, re.UNICODE):
		return False, "שם מכיל תווים לא חוקיים"
	return True, ""


def validate_dosage(dosage: Optional[str]) -> Tuple[bool, str]:
	if not dosage or not isinstance(dosage, str):
		return False, "מינון נדרש"
	dosage = dosage.strip()
	if not dosage:
		return False, "מינון נדרש"
	if len(dosage) > 100:
		return False, "מינון ארוך מדי"
	return True, ""


def _hebrew_number_to_float(text: str) -> Optional[float]:
	mapping = {
		"אפס": 0,
		"אחד": 1,
		"שתיים": 2,
		"שתים": 2,
		"שלוש": 3,
		"ארבע": 4,
		"חמש": 5,
		"שש": 6,
		"שבע": 7,
		"שמונה": 8,
		"תשע": 9,
		"עשר": 10,
		"עשרה": 10,
	}
	return float(mapping[text]) if text in mapping else None


def validate_inventory_count(value: Any) -> Tuple[bool, str, Optional[float]]:
	if value is None:
		return False, "כמות נדרשת", None
	if isinstance(value, (int, float)):
		count = float(value)
	else:
		text = str(value).strip()
		if text == "":
			return False, "כמות נדרשת", None
		# Hebrew numbers
		heb = _hebrew_number_to_float(text)
		if heb is not None:
			count = heb
		else:
			try:
				count = float(text)
			except ValueError:
				return False, "מספר לא תקין", None
	if count < 0:
		return False, "כמות שלילית אינה מותרת", None
	if count > 9999:
		return False, "כמות גדולה מדי", None
	return True, "", count


def validate_telegram_id(value: Any) -> Tuple[bool, str]:
	try:
		num = int(value)
	except Exception:
		return False, "מספר מזהה לא תקין"
	if num <= 0:
		return False, "מספר מזהה לא תקין"
	# Basic bounds check (typical user IDs 1.. around 10^13)
	if len(str(abs(num))) < 3 or len(str(abs(num))) > 16:
		return False, "מספר מזהה לא תקין"
	return True, ""


def validate_phone_number(phone: Optional[str]) -> Tuple[bool, str]:
	if not phone:
		return False, "מספר טלפון נדרש"
	p = phone.strip()
	pattern = re.compile(r"^(?:\+972|0)(?:[2-9]|5\d)\-?\s?\d{7,8}$")
	# Accept formats like 050-123-4567, 050 123 4567, +972501234567, 021234567
	p_norm = p.replace(" ", "").replace("-", "")
	if re.match(r"^(\+972|0)\d{8,10}$", p_norm):
		return True, ""
	if pattern.match(p):
		return True, ""
	return False, "מספר טלפון לא תקין"


# ===============================
# Time & date helpers
# ===============================

def parse_time_string(text: Optional[str]) -> Optional[time]:
	if not text:
		return None
	s = text.strip()
	# Accept 08:30, 8:30, 08.30, 08-30, 08 : 30, 0830
	m = re.match(r"^(\d{1,2})\s*[:\.-]?\s*(\d{2})$", s)
	if not m:
		return None
	h = int(m.group(1))
	mi = int(m.group(2))
	if not (0 <= h <= 23 and 0 <= mi <= 59):
		return None
	return time(h, mi)


_HE_MONTHS = [
	"ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
	"יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר",
]

_HE_DAYS = [
	"יום שני", "יום שלישי", "יום רביעי", "יום חמישי",
	"יום שישי", "יום שבת", "יום ראשון"
]


def _he_day_name(dt: date) -> str:
	# Python weekday(): Monday=0 .. Sunday=6; we map accordingly
	return _HE_DAYS[dt.weekday()]


def format_datetime_hebrew(dt: datetime) -> str:
	day_name = _he_day_name(dt.date())
	month_name = _HE_MONTHS[dt.month - 1]
	return f"{day_name}, {dt.day} {month_name} {dt.year} {dt.strftime('%H:%M')}"


def format_date_hebrew(d: date) -> str:
	day_name = _he_day_name(d)
	month_name = _HE_MONTHS[d.month - 1]
	return f"{day_name}, {d.day} {month_name} {d.year}"


def format_time_hebrew(t: time) -> str:
	return t.strftime("%H:%M")


def get_next_occurrence(t: time, now: Optional[datetime] = None) -> datetime:
	now = now or datetime.now()
	candidate = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
	if candidate < now:
		candidate += timedelta(days=1)
	return candidate


def time_until(target: datetime, now: Optional[datetime] = None) -> str:
	now = now or datetime.now()
	delta = target - now
	if delta.total_seconds() <= 0:
		return "עבר"
	hours = int(delta.total_seconds() // 3600)
	minutes = int((delta.total_seconds() % 3600) // 60)
	parts = []
	if hours:
		parts.append(f"{hours} שעות")
	if minutes or not parts:
		parts.append(f"{minutes} דקות")
	return " ו".join(parts)


# ===============================
# Text helpers
# ===============================

def clean_text(text: Optional[str], max_length: Optional[int] = None) -> str:
	if not text:
		return ""
	s = re.sub(r"\s+", " ", text).strip()
	if max_length is not None and len(s) > max_length:
		return s[:max_length] + "..."
	return s


def truncate_text(text: Optional[str], max_length: int) -> str:
	if not text:
		return ""
	if len(text) <= max_length:
		return text
	return text[:max_length] + "..."


def format_list_hebrew(items: Sequence[str], conjunction: str = "ו") -> str:
	items = [i for i in items if i]
	if not items:
		return ""
	if len(items) == 1:
		return items[0]
	if len(items) == 2:
		# For the Hebrew conjunction 'ו' (which attaches to the next word), do not add a space.
		# For other conjunctions like 'או', add spaces around the conjunction.
		if conjunction.strip() == "ו":
			return f"{items[0]} {conjunction}{items[1]}"
		else:
			return f"{items[0]} {conjunction} {items[1]}"
	return ", ".join(items[:-1]) + f" {conjunction}{items[-1]}"


# ===============================
# Data processing
# ===============================

def calculate_adherence_rate(taken: int, total: int) -> float:
	if total <= 0:
		return 0.0
	return round((taken / total) * 100, 1 if (taken * 10) % total else 1)


def calculate_average_mood(scores: Sequence[int]) -> float:
	valid = [s for s in scores if isinstance(s, (int, float)) and 0 <= s <= 10]
	if not valid:
		return 0.0
	return sum(valid) / len(valid)


def group_by_date(items: Iterable[Any], date_attr: str) -> Dict[date, List[Any]]:
	result: Dict[date, List[Any]] = {}
	for item in items:
		value = getattr(item, date_attr)
		if isinstance(value, datetime):
			d = value.date()
		elif isinstance(value, date):
			d = value
		else:
			raise ValueError("Invalid date attribute")
		result.setdefault(d, []).append(item)
	return result


def calculate_streaks(dates: Sequence[date]) -> Dict[str, int]:
	if not dates:
		return {"current": 0, "longest": 0}
	sorted_dates = sorted(set(dates))
	longest = 1
	current = 1
	for i in range(1, len(sorted_dates)):
		if sorted_dates[i] == sorted_dates[i - 1] + timedelta(days=1):
			current += 1
			longest = max(longest, current)
		else:
			current = 1
	# Current streak ends today if last date is today; otherwise derive from tail run
	return {"current": current if sorted_dates[-1] == date.today() else current, "longest": longest}


def paginate_items(items: Sequence[Any], page: int, page_size: int) -> Tuple[List[Any], int, bool]:
	if page <= 0:
		page = 1
	if page_size <= 0:
		page_size = 10
	total = len(items)
	total_pages = (total + page_size - 1) // page_size if total else 1
	start = (page - 1) * page_size
	end = start + page_size
	page_items = list(items[start:end])
	has_more = page < total_pages
	return page_items, total_pages, has_more


# ===============================
# Formatting helpers
# ===============================

def format_medication_schedule(schedules: Sequence[time]) -> str:
	if not schedules:
		return "לא מוגדר"
	return ", ".join(sorted([t.strftime("%H:%M") for t in schedules]))


def format_inventory_status(inventory_count: float, threshold: float) -> str:
	if inventory_count <= 0:
		return "❌ נגמר המלאי"
	if inventory_count <= threshold:
		return "⚠️ מלאי נמוך"
	return "✅"


def format_adherence_rate(rate: float) -> str:
	if rate >= 90:
		return "🟢 מצוין"
	elif rate >= 80:
		return "🟡 טוב"
	else:
		return "🔴 נמוך"


def safe_int(value: Any, default: int = 0) -> int:
	try:
		return int(value)
	except Exception:
		return default


def safe_float(value: Any, default: float = 0.0) -> float:
	try:
		return float(value)
	except Exception:
		return default


def safe_str(value: Any, default: str = "") -> str:
	if value is None:
		return default
	return str(value)


def create_progress_bar(current: int, total: int, width: int = 10) -> str:
	current = max(0, current)
	total = max(0, total)
	if total == 0:
		filled = 0
		percent = 0.0
	else:
		percent = (current / total) * 100
		filled = int(round(width * current / float(total)))
	bar = "█" * filled + "░" * (width - filled)
	return f"[{bar}] {percent:.1f}%"


# ===============================
# Simple in-memory cache
# ===============================

@dataclass
class _CacheItem:
	value: Any
	expires_at: Optional[datetime]


class SimpleCache:
	def __init__(self, default_ttl: Optional[int] = None):
		self._store: Dict[str, _CacheItem] = {}
		self._default_ttl = default_ttl

	def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
		expires_at = None
		ttl = ttl if ttl is not None else self._default_ttl
		if ttl is not None and ttl > 0:
			expires_at = datetime.now() + timedelta(seconds=ttl)
		self._store[key] = _CacheItem(value=value, expires_at=expires_at)

	def get(self, key: str) -> Optional[Any]:
		item = self._store.get(key)
		if not item:
			return None
		if item.expires_at and datetime.now() >= item.expires_at:
			del self._store[key]
			return None
		return item.value

	def remove(self, key: str) -> bool:
		if key in self._store:
			del self._store[key]
			return True
		return False

	def clear(self) -> None:
		self._store.clear()