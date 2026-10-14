"""Notification system for Smart Investor alerts."""

from .base import NotificationResult, NotificationService
from .email import EmailNotifier
from .slack import SlackNotifier
from .telegram import TelegramNotifier

__all__ = [
    "NotificationService",
    "NotificationResult",
    "EmailNotifier",
    "SlackNotifier",
    "TelegramNotifier",
]
