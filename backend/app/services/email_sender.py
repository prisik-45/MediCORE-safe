import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from backend.app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


def _build_html_message(to_email: str, subject: str, html_content: str, from_email: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.attach(MIMEText(html_content, "html"))
    return msg


def _send_gmail_api_email(to_email: str, subject: str, html_content: str) -> bool:
    from_email = settings.gmail_api_sender
    if not (
        settings.google_client_id
        and settings.google_client_secret
        and settings.google_refresh_token
        and from_email
    ):
        logger.warning(
            "Gmail API credentials not configured. Email to %s with subject '%s' skipped.",
            to_email,
            subject,
        )
        return False

    try:
        token_response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": settings.google_refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=15,
        )
        token_response.raise_for_status()
        access_token = token_response.json().get("access_token")
        if not access_token:
            logger.error("Gmail API token refresh succeeded but no access_token was returned")
            return False

        msg = _build_html_message(to_email, subject, html_content, from_email)
        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        user_id = settings.gmail_user_id or "me"
        send_response = httpx.post(
            f"https://gmail.googleapis.com/gmail/v1/users/{user_id}/messages/send",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"raw": raw_message},
            timeout=15,
        )
        send_response.raise_for_status()
        logger.info("Successfully sent email to %s via Gmail API", to_email)
        return True
    except httpx.HTTPStatusError as e:
        logger.error(
            "Gmail API failed to send email to %s: status=%s body=%s",
            to_email,
            e.response.status_code,
            e.response.text[:500],
        )
        return False
    except Exception as e:
        logger.error("Gmail API failed to send email to %s: %s", to_email, e)
        return False


def send_transactional_email(to_email: str, subject: str, html_content: str):
    """Sends a transactional email via Gmail API."""
    return _send_gmail_api_email(to_email, subject, html_content)
