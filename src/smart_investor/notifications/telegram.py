"""Telegram notification service."""

import os
from typing import Any

try:
    from telegram import Bot
    from telegram.error import TelegramError
except ImportError:
    Bot = None
    TelegramError = None

from .base import NotificationResult, NotificationService


class TelegramNotifier(NotificationService):
    """Telegram notification service using python-telegram-bot."""

    def __init__(
        self,
        token: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        """Initialize Telegram notifier.

        Args:
            token: Telegram bot token (or TELEGRAM_TOKEN env var)
            chat_id: Default chat ID to send to (or TELEGRAM_CHAT_ID env var)
        """
        super().__init__()

        self.token = token or os.getenv("TELEGRAM_TOKEN")
        self.default_chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self._bot: "Bot" | None = None

    @property
    def bot(self) -> "Bot":
        """Get Telegram bot, creating if necessary."""
        if self._bot is None:
            if Bot is None:
                raise RuntimeError("python-telegram-bot not installed")
            if not self.token:
                raise RuntimeError("Telegram token not configured")
            self._bot = Bot(token=self.token)
        return self._bot

    async def send(
        self,
        message: str,
        chat_id: str | None = None,
        parse_mode: str = "HTML",
        **kwargs: Any,
    ) -> NotificationResult:
        """Send Telegram notification.

        Args:
            message: Message text
            chat_id: Chat ID to send to (overrides default)
            parse_mode: Parse mode (HTML, Markdown, MarkdownV2)
            **kwargs: Additional parameters

        Returns:
            NotificationResult with status
        """
        if Bot is None:
            return NotificationResult.fail(
                channel="telegram",
                error="python-telegram-bot not installed"
            )

        if not self.token:
            return NotificationResult.fail(
                channel="telegram",
                error="Telegram token not configured"
            )

        target_chat = chat_id or self.default_chat_id
        if not target_chat:
            return NotificationResult.fail(
                channel="telegram",
                error="Chat ID not configured"
            )

        try:
            # Format message for Telegram
            formatted_message = self._format_for_telegram(message, parse_mode)

            # Send message
            result = await self.bot.send_message(
                chat_id=target_chat,
                text=formatted_message,
                parse_mode=parse_mode,
            )

            return NotificationResult.ok(
                channel="telegram",
                message=f"Message sent to chat {target_chat}",
                message_id=result.message_id,
                chat_id=target_chat,
            )

        except TelegramError as e:
            return NotificationResult.fail(
                channel="telegram",
                error=f"Telegram API error: {e}"
            )
        except Exception as e:
            return NotificationResult.fail(
                channel="telegram",
                error=str(e)
            )

    def _format_for_telegram(self, text: str, parse_mode: str) -> str:
        """Format text for Telegram.

        Args:
            text: Plain text message
            parse_mode: Parse mode (HTML, Markdown)

        Returns:
            Formatted message
        """
        if parse_mode == "HTML":
            # Convert to HTML
            text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            # Convert markdown-like formatting to HTML
            lines = []
            for line in text.split("\n"):
                # Headers (lines starting with emoji or ##)
                if line and line[0] in "🎯📊⚠️📢":
                    line = f"<b>{line}</b>"
                elif line.startswith("##"):
                    line = f"<b>{line[2:].strip()}</b>"

                # Bold text between ** **
                import re
                line = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', line)

                # Dividers
                if line.startswith("─"):
                    line = "━" * 20

                lines.append(line)

            return "\n".join(lines)

        elif parse_mode in ("Markdown", "MarkdownV2"):
            # Escape special characters for MarkdownV2
            if parse_mode == "MarkdownV2":
                special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
                for char in special_chars:
                    text = text.replace(char, f"\\{char}")

            return text

        return text

    async def send_formatted_alert(
        self,
        title: str,
        stocks: list[dict],
    ) -> NotificationResult:
        """Send a formatted stock alert.

        Args:
            title: Alert title
            stocks: List of stock data dictionaries

        Returns:
            NotificationResult with status
        """
        lines = [
            f"<b>{title}</b>",
            "",
            "━" * 20,
        ]

        for stock in stocks[:15]:
            ticker = stock.get("ticker", "N/A")
            div_yield = stock.get("dividend_yield")
            years = stock.get("years_of_dividend")

            line = f"• <b>{ticker}</b>"
            if div_yield:
                line += f" | {div_yield:.2f}%"
            if years:
                line += f" | {years}yr"

            lines.append(line)

        if len(stocks) > 15:
            lines.append(f"\n<i>... and {len(stocks) - 15} more stocks</i>")

        return await self.send("\n".join(lines), parse_mode="HTML")
