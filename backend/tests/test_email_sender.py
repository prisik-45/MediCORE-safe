import sys
from pathlib import Path
from types import SimpleNamespace

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.services import email_sender


def make_settings(**overrides):
    values = {
        "gmail_api_sender": "sender@example.com",
        "google_client_id": "client-id",
        "google_client_secret": "client-secret",
        "google_refresh_token": "refresh-token",
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

    monkeypatch.setattr(email_sender, "settings", make_settings())
    monkeypatch.setattr(email_sender.httpx, "post", fake_post)

    result = email_sender.send_transactional_email("employee@example.com", "Invite", "<p>Hello</p>")

    assert result is True
    assert len(calls) == 2
    assert calls[0][0] == "https://oauth2.googleapis.com/token"
    assert calls[0][1]["data"]["refresh_token"] == "refresh-token"
    assert calls[0][1]["data"]["grant_type"] == "refresh_token"
    assert calls[1][0] == "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    assert calls[1][1]["headers"]["Authorization"] == "Bearer access-token"
    assert "raw" in calls[1][1]["json"]


def test_gmail_api_reports_missing_credentials(monkeypatch):
    monkeypatch.setattr(
        email_sender,
        "settings",
        make_settings(google_refresh_token=""),
    )

    result = email_sender.send_transactional_email("employee@example.com", "Invite", "<p>Hello</p>")

    assert result is False


def test_gmail_api_handles_invalid_grant_error(monkeypatch, caplog):
    def fake_post(url, **kwargs):
        request = httpx.Request("POST", url)
        if url == "https://oauth2.googleapis.com/token":
            return httpx.Response(
                400,
                json={"error": "invalid_grant", "error_description": "Token has been expired or revoked."},
                request=request,
            )
        return httpx.Response(200, json={"id": "message-id"}, request=request)

    monkeypatch.setattr(email_sender, "settings", make_settings())
    monkeypatch.setattr(email_sender.httpx, "post", fake_post)

    result = email_sender.send_transactional_email("employee@example.com", "Invite", "<p>Hello</p>")

    assert result is False
    assert "invalid_grant" in caplog.text
    assert "Testing" in caplog.text
