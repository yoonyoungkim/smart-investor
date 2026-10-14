"""Email notification service."""

import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

try:
    import aiosmtplib
except ImportError:
    aiosmtplib = None

from .base import NotificationResult, NotificationService


class EmailNotifier(NotificationService):
    """Email notification service using SMTP."""

    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        from_email: str | None = None,
        to_emails: list[str] | None = None,
        use_tls: bool = True,
    ) -> None:
        """Initialize email notifier.

        Args:
            smtp_host: SMTP server host (or SMTP_HOST env var)
            smtp_port: SMTP server port (or SMTP_PORT env var)
            username: SMTP username (or SMTP_USERNAME env var)
            password: SMTP password (or SMTP_PASSWORD env var)
            from_email: Sender email (or SMTP_FROM env var)
            to_emails: List of recipient emails (or SMTP_TO env var, comma-separated)
            use_tls: Whether to use TLS
        """
        super().__init__()

        self.smtp_host = smtp_host or os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = smtp_port or int(os.getenv("SMTP_PORT", "587"))
        self.username = username or os.getenv("SMTP_USERNAME")
        self.password = password or os.getenv("SMTP_PASSWORD")
        self.from_email = from_email or os.getenv("SMTP_FROM")
        self.use_tls = use_tls

        to_env = os.getenv("SMTP_TO", "")
        self.to_emails = to_emails or [e.strip() for e in to_env.split(",") if e.strip()]

    async def send(
        self,
        message: str,
        subject: str = "Smart Investor Alert",
        to_emails: list[str] | None = None,
        **kwargs: Any,
    ) -> NotificationResult:
        """Send email notification.

        Args:
            message: Message body
            subject: Email subject
            to_emails: Override recipient list
            **kwargs: Additional parameters

        Returns:
            NotificationResult with status
        """
        if aiosmtplib is None:
            return NotificationResult.fail(
                channel="email",
                error="aiosmtplib not installed"
            )

        if not self.username or not self.password:
            return NotificationResult.fail(
                channel="email",
                error="SMTP credentials not configured"
            )

        recipients = to_emails or self.to_emails
        if not recipients:
            return NotificationResult.fail(
                channel="email",
                error="No recipient emails configured"
            )

        try:
            # Create email message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.from_email or self.username
            msg["To"] = ", ".join(recipients)

            # Plain text version
            text_part = MIMEText(message, "plain", "utf-8")
            msg.attach(text_part)

            # HTML version (simple conversion)
            html_message = self._text_to_html(message)
            html_part = MIMEText(html_message, "html", "utf-8")
            msg.attach(html_part)

            # Send email
            await aiosmtplib.send(
                msg,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.username,
                password=self.password,
                start_tls=self.use_tls,
            )

            return NotificationResult.ok(
                channel="email",
                message=f"Email sent to {len(recipients)} recipients",
                recipients=recipients,
            )

        except Exception as e:
            return NotificationResult.fail(
                channel="email",
                error=str(e)
            )

    def _text_to_html(self, text: str) -> str:
        """Convert plain text to simple HTML.

        Args:
            text: Plain text message

        Returns:
            HTML formatted message
        """
        # Escape HTML
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # Convert line breaks
        text = text.replace("\n", "<br>\n")

        # Wrap in HTML
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            </style>
        </head>
        <body>
            <div class="container">
                {text}
            </div>
        </body>
        </html>
        """
