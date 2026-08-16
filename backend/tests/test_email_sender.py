import sys
from pathlib import Path
from types import SimpleNamespace

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.services import email_sender


def make_settings(**overrides):
    values = {
        "transactional_email_provider": "smtp",
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_username": "",
        "smtp_password": "",
        "smtp_sender": "sender@example.com",
        "gmail_api_sender": "",
        "google_client_id": "",
        "google_client_secret": "",
        "google_refresh_token": "",
        "gmail_user_id": "me",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_send_email_uses_gmail_api_when_configured(monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        request = httpx.Request("POST", url)
        if url == "https://oauth2.googleapis.com/token":
            return httpx.Response(200, json={"access_token": "access-token"}, request=request)
        return httpx.Response(200, json={"id": "message-id"}, request=request)

    monkeypatch.setattr(
        email_sender,
        "settings",
        make_settings(
            transactional_email_provider="gmail_api",
            google_client_id="client-id",
            google_client_secret="client-secret",
            google_refresh_token="refresh-token",
            gmail_api_sender="sender@example.com",
        ),
    )
    monkeypatch.setattr(email_sender.httpx, "post", fake_post)

    result = email_sender.send_smtp_email("employee@example.com", "Invite", "<p>Hello</p>")

    assert result is True
    assert calls[0][0] == "https://oauth2.googleapis.com/token"
    assert calls[1][0] == "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    assert calls[1][1]["headers"]["Authorization"] == "Bearer access-token"
    assert "raw" in calls[1][1]["json"]


def test_gmail_api_reports_missing_credentials(monkeypatch):
    monkeypatch.setattr(
        email_sender,
        "settings",
        make_settings(transactional_email_provider="gmail_api"),
    )

    result = email_sender.send_smtp_email("employee@example.com", "Invite", "<p>Hello</p>")

    assert result is False


def test_smtp_remains_default_provider(monkeypatch):
    smtp_calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            smtp_calls.append(("connect", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def starttls(self, *args, **kwargs):
            smtp_calls.append(("starttls", kwargs.get("context")))

        def login(self, username, password):
            smtp_calls.append(("login", username, password))

        def sendmail(self, from_email, to_email, message):
            smtp_calls.append(("sendmail", from_email, to_email, message))

    monkeypatch.setattr(
        email_sender,
        "settings",
        make_settings(smtp_username="sender@example.com", smtp_password="app-password"),
    )
    monkeypatch.setattr(email_sender.smtplib, "SMTP", FakeSMTP)

    result = email_sender.send_smtp_email("employee@example.com", "Invite", "<p>Hello</p>")

    assert result is True
    assert smtp_calls[0] == ("connect", "smtp.gmail.com", 587, 10)
    assert smtp_calls[-1][0] == "sendmail"
