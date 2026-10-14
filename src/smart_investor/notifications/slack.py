"""Slack notification service."""

import os
from pathlib import Path
from typing import Any

try:
    from slack_sdk.errors import SlackApiError
    from slack_sdk.web.async_client import AsyncWebClient

    _IMPORT_ERROR = None
except ImportError as exc:  # pragma: no cover - depends on the environment
    AsyncWebClient = None
    SlackApiError = None
    # slack_sdk's async client imports aiohttp, so "slack_sdk is installed" is
    # not enough - report which module is actually missing rather than blaming
    # slack_sdk when aiohttp is the one absent.
    _IMPORT_ERROR = str(exc)

from .base import NotificationResult, NotificationService


class SlackNotifier(NotificationService):
    """Slack notification service using Slack SDK."""

    def __init__(
        self,
        token: str | None = None,
        channel: str | None = None,
    ) -> None:
        """Initialize Slack notifier.

        Args:
            token: Slack bot token (or SLACK_TOKEN env var)
            channel: Default channel to post to (or SLACK_CHANNEL env var)
        """
        super().__init__()

        self.token = token or os.getenv("SLACK_TOKEN")
        self.default_channel = channel or os.getenv("SLACK_CHANNEL", "#smart-investor")
        self._client: AsyncWebClient | None = None

    @property
    def client(self) -> "AsyncWebClient":
        """Get Slack client, creating if necessary."""
        if self._client is None:
            if AsyncWebClient is None:
                raise RuntimeError(
                    f"Slack async client unavailable ({_IMPORT_ERROR}). "
                    f"Install it with: pip install 'slack-sdk' aiohttp"
                )
            if not self.token:
                raise RuntimeError("Slack token not configured")
            self._client = AsyncWebClient(token=self.token)
        return self._client

    async def send(
        self,
        message: str,
        channel: str | None = None,
        blocks: list[dict] | None = None,
        **kwargs: Any,
    ) -> NotificationResult:
        """Send Slack notification.

        Args:
            message: Message text
            channel: Channel to post to (overrides default)
            blocks: Slack block kit blocks for rich formatting
            **kwargs: Additional parameters

        Returns:
            NotificationResult with status
        """
        if AsyncWebClient is None:
            return NotificationResult.fail(
                channel="slack",
                error=f"Slack async client unavailable ({_IMPORT_ERROR}). "
                      f"Install it with: pip install 'slack-sdk' aiohttp"
            )

        if not self.token:
            return NotificationResult.fail(
                channel="slack",
                error="Slack token not configured"
            )

        target_channel = channel or self.default_channel

        try:
            # Build message payload
            payload = {
                "channel": target_channel,
                "text": message,
            }

            if blocks:
                payload["blocks"] = blocks
            else:
                # Create simple blocks from text
                payload["blocks"] = self._text_to_blocks(message)

            # Send message
            response = await self.client.chat_postMessage(**payload)

            return NotificationResult.ok(
                channel="slack",
                message=f"Message sent to {target_channel}",
                ts=response.get("ts"),
                channel_id=response.get("channel"),
            )

        except SlackApiError as e:
            return NotificationResult.fail(
                channel="slack",
                error=f"Slack API error: {e.response['error']}"
            )
        except Exception as e:
            return NotificationResult.fail(
                channel="slack",
                error=str(e)
            )

    async def send_file(
        self,
        path: str,
        comment: str = "",
        channel: str | None = None,
        title: str | None = None,
    ) -> NotificationResult:
        """Upload a file to Slack.

        ``files.completeUploadExternal`` accepts only a channel ID (``C…``), not
        the ``#name`` form ``chat.postMessage`` takes. Resolving a name would
        need the ``channels:read`` scope, so callers pass the ID that
        :meth:`send` returns in its metadata instead.

        Args:
            path: Local path of the file to upload.
            comment: Message posted alongside the file.
            channel: Channel ID to upload to. A ``#name`` is rejected by Slack.
            title: File title shown in Slack.

        Returns:
            NotificationResult with status
        """
        if AsyncWebClient is None:
            return NotificationResult.fail(
                channel="slack",
                error=f"Slack async client unavailable ({_IMPORT_ERROR}). "
                      f"Install it with: pip install 'slack-sdk' aiohttp",
            )

        if not self.token:
            return NotificationResult.fail(channel="slack", error="Slack token not configured")

        target_channel = channel or self.default_channel
        file_path = Path(path)

        if not file_path.exists():
            return NotificationResult.fail(channel="slack", error=f"File not found: {file_path}")

        if target_channel.startswith("#"):
            return NotificationResult.fail(
                channel="slack",
                error=f"File upload needs a channel ID, not '{target_channel}'. "
                      f"Pass the channel_id returned by send(), or set "
                      f"SLACK_CHANNEL to the ID (starts with C).",
            )

        try:
            response = await self.client.files_upload_v2(
                file=str(file_path),
                filename=file_path.name,
                title=title or file_path.name,
                initial_comment=comment or None,
                channel=target_channel,
            )
            return NotificationResult.ok(
                channel="slack",
                message=f"Uploaded {file_path.name} to {target_channel}",
                file_id=(response.get("file") or {}).get("id"),
            )
        except Exception as e:
            return NotificationResult.fail(channel="slack", error=str(e))

    def _text_to_blocks(self, text: str) -> list[dict]:
        """Convert plain text to Slack blocks.

        Args:
            text: Plain text message

        Returns:
            List of Slack block kit blocks
        """
        blocks = []

        lines = text.split("\n")
        current_section = []

        for line in lines:
            if line.startswith("─") or line.strip() == "":
                # Divider or empty line - flush current section
                if current_section:
                    blocks.append({
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "\n".join(current_section)
                        }
                    })
                    current_section = []

                if line.startswith("─"):
                    blocks.append({"type": "divider"})
            else:
                # Convert emojis and formatting
                line = line.replace("•", "•")  # Keep bullet points
                current_section.append(line)

        # Flush remaining section
        if current_section:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "\n".join(current_section)
                }
            })

        return blocks

    async def send_rich_alert(
        self,
        title: str,
        stocks: list[dict],
        color: str = "good",
    ) -> NotificationResult:
        """Send a rich formatted stock alert.

        Args:
            title: Alert title
            stocks: List of stock data dictionaries
            color: Attachment color (good, warning, danger)

        Returns:
            NotificationResult with status
        """
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": title
                }
            },
            {"type": "divider"},
        ]

        for stock in stocks[:10]:
            stock_text = f"*{stock.get('ticker', 'N/A')}*"
            if stock.get("dividend_yield"):
                stock_text += f" | Yield: {stock['dividend_yield']:.2f}%"
            if stock.get("years_of_dividend"):
                stock_text += f" | Years: {stock['years_of_dividend']}"

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": stock_text
                }
            })

        if len(stocks) > 10:
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"_... and {len(stocks) - 10} more stocks_"
                }]
            })

        return await self.send(title, blocks=blocks)
