# fmt: off
"""
Handlers Package
All conversation and callback handlers for Medicine Reminder Bot
"""

from .medicine_handler import MedicineHandler, medicine_handler
from .reminder_handler import ReminderHandler, reminder_handler

# Import when available
try:
	from .symptoms_handler import SymptomsHandler, symptoms_handler
except ImportError:
	symptoms_handler = None

try:
	from .caregiver_handler import caregiver_handler
except ImportError:
	caregiver_handler = None

try:
	from .reports_handler import reports_handler
except ImportError:
	reports_handler = None

__version__ = "1.0.0"
__author__ = "Medicine Reminder Bot Team"

# Global handler instances
handlers = {
	'medicine': medicine_handler,
	'reminder': reminder_handler,
	'symptoms': symptoms_handler,
	'caregiver': caregiver_handler,
	'reports': reports_handler,
}


def get_all_handlers():
	"""Get all available handler instances"""
	return {k: v for k, v in handlers.items() if v is not None}


def get_all_conversation_handlers():
	"""Get all conversation handlers"""
	conv_handlers = []

	# Medicine handler
	if medicine_handler:
		conv_handlers.append(medicine_handler.get_conversation_handler())

	# Symptoms handler
	if symptoms_handler:
		conv_handlers.append(symptoms_handler.get_conversation_handler())

	# Caregiver handler
	if caregiver_handler:
		conv_handlers.append(caregiver_handler.get_conversation_handler())

	# Reports handler
	if reports_handler:
		conv_handlers.append(reports_handler.get_conversation_handler())

	return conv_handlers


def get_all_callback_handlers():
	"""Get all callback handlers"""
	callback_handlers = []

	# Reminder handlers
	if reminder_handler:
		callback_handlers.extend(reminder_handler.get_handlers())

	# Symptoms handlers
	if symptoms_handler:
		callback_handlers.extend(symptoms_handler.get_handlers())

	# Caregiver handlers
	if caregiver_handler:
		callback_handlers.extend(caregiver_handler.get_handlers())

	# Reports handlers
	if reports_handler:
		callback_handlers.extend(reports_handler.get_handlers())

	return callback_handlers


__all__ = [
	"MedicineHandler", "medicine_handler",
	"ReminderHandler", "reminder_handler",
	"SymptomsHandler", "symptoms_handler",
	"caregiver_handler", "reports_handler",
	"handlers", "get_all_handlers",
	"get_all_conversation_handlers", "get_all_callback_handlers",
]
