"""이메일 리포트 발송 계층 테스트.

핵심 계약:
1. mailer.validate_recipient(s)는 도메인 화이트리스트와 형식을 검증한다.
2. sanitize_header_value는 헤더 인젝션(CRLF)을 제거한다.
3. /api/report/email은 SMTP 발송을 mailer.send_email에 위임하고, 새 SQL/MCP 접근을
   절대 하지 않는다 (순수 발송 엔드포인트 — test_pdf_report.py와 동일한 계약).
"""

import pytest
from fastapi.testclient import TestClient

from backend.app import config, main, mailer

SAMPLE_CONTENT = "# 매출 요약\n\n상반기 매출은 1,000,000원입니다.\n\n| 월 | 매출 |\n| --- | --- |\n| 1월 | 1,000,000 |\n"


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def allow_company_domain(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_EMAIL_DOMAINS", ["company.com"])
    monkeypatch.setattr(mailer.config, "ALLOWED_EMAIL_DOMAINS", ["company.com"])


@pytest.fixture
def smtp_configured(monkeypatch, allow_company_domain):
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.company.com")
    monkeypatch.setattr(mailer.config, "SMTP_HOST", "smtp.company.com")


# --- mailer.validate_recipient(s) -------------------------------------------


def test_validate_recipient_allows_whitelisted_domain(allow_company_domain):
    assert mailer.validate_recipient("user@company.com") == "user@company.com"


def test_validate_recipient_allows_subdomain(allow_company_domain):
    assert mailer.validate_recipient("user@mail.company.com") == "user@mail.company.com"


def test_validate_recipient_is_case_insensitive(allow_company_domain):
    assert mailer.validate_recipient("user@Company.COM") == "user@Company.COM"


def test_validate_recipient_rejects_non_whitelisted_domain(allow_company_domain):
    with pytest.raises(mailer.EmailDomainNotAllowedError):
        mailer.validate_recipient("attacker@evil.com")


def test_validate_recipient_rejects_bad_format(allow_company_domain):
    with pytest.raises(ValueError):
        mailer.validate_recipient("not-an-email")


def test_validate_recipients_requires_nonempty_list(allow_company_domain):
    with pytest.raises(ValueError):
        mailer.validate_recipients([])


def test_validate_recipients_dedupes(allow_company_domain):
    result = mailer.validate_recipients(["a@company.com", "a@company.com"])
    assert result == ["a@company.com"]


def test_validate_recipients_fails_entirely_if_one_invalid(allow_company_domain):
    with pytest.raises(ValueError):
        mailer.validate_recipients(["a@company.com", "b@evil.com"])


# --- sanitize_header_value ---------------------------------------------------


def test_sanitize_header_value_strips_crlf_injection():
    injected = "제목\r\nBcc: attacker@evil.com"
    sanitized = mailer.sanitize_header_value(injected)
    assert "\r" not in sanitized
    assert "\n" not in sanitized
    assert "Bcc:" in sanitized  # 텍스트 자체는 남되 개행만 제거되어 헤더 분리가 불가능해진다


# --- /api/report/email 엔드포인트 -------------------------------------------


def test_report_email_endpoint_success(client, smtp_configured, monkeypatch):
    calls = []
    monkeypatch.setattr(mailer, "send_email", lambda payload: calls.append(payload))

    res = client.post(
        "/api/report/email",
        json={"title": "매출 리포트", "content": SAMPLE_CONTENT, "to": ["user@company.com"]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "sent"
    assert body["to"] == ["user@company.com"]
    assert len(calls) == 1


def test_report_email_endpoint_rejects_non_whitelisted_domain(client, smtp_configured):
    res = client.post(
        "/api/report/email",
        json={"content": SAMPLE_CONTENT, "to": ["attacker@evil.com"]},
    )
    assert res.status_code == 403


def test_report_email_endpoint_rejects_empty_recipients(client, smtp_configured):
    res = client.post("/api/report/email", json={"content": SAMPLE_CONTENT, "to": []})
    assert res.status_code == 422


def test_report_email_endpoint_rejects_bad_format(client, smtp_configured):
    res = client.post(
        "/api/report/email",
        json={"content": SAMPLE_CONTENT, "to": ["not-an-email"]},
    )
    assert res.status_code == 422


def test_report_email_endpoint_disabled_without_smtp_config(client, monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "")
    monkeypatch.setattr(config, "ALLOWED_EMAIL_DOMAINS", [])
    res = client.post(
        "/api/report/email",
        json={"content": SAMPLE_CONTENT, "to": ["user@company.com"]},
    )
    assert res.status_code == 503


def test_report_email_endpoint_maps_send_failure_to_502(client, smtp_configured, monkeypatch):
    def boom(payload):
        raise mailer.EmailSendError("SMTP 연결 실패")

    monkeypatch.setattr(mailer, "send_email", boom)
    res = client.post(
        "/api/report/email",
        json={"content": SAMPLE_CONTENT, "to": ["user@company.com"]},
    )
    assert res.status_code == 502


# --- GET /api/report/email/presets ------------------------------------------


def test_email_presets_returns_configured_list(client, monkeypatch):
    monkeypatch.setattr(
        config, "EMAIL_PRESET_RECIPIENTS", ["sales@company.com", "manager@company.com"]
    )
    res = client.get("/api/report/email/presets")
    assert res.status_code == 200
    assert res.json() == {"presets": ["sales@company.com", "manager@company.com"]}


def test_email_presets_returns_empty_list_when_unset(client, monkeypatch):
    monkeypatch.setattr(config, "EMAIL_PRESET_RECIPIENTS", [])
    res = client.get("/api/report/email/presets")
    assert res.status_code == 200
    assert res.json() == {"presets": []}


def test_email_presets_available_even_when_email_disabled(client, monkeypatch):
    """이메일 기능이 꺼져 있어도 프리셋 조회는 200이어야 한다(프론트가 항상 호출 가능)."""
    monkeypatch.setattr(config, "SMTP_HOST", "")
    monkeypatch.setattr(config, "ALLOWED_EMAIL_DOMAINS", [])
    monkeypatch.setattr(config, "EMAIL_PRESET_RECIPIENTS", ["sales@company.com"])
    res = client.get("/api/report/email/presets")
    assert res.status_code == 200
    assert res.json() == {"presets": ["sales@company.com"]}


def test_email_presets_does_not_touch_mcp(client, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("프리셋 조회가 MCP/챗 세션을 열어서는 안 된다")

    monkeypatch.setattr(main, "run_chat", boom)
    assert client.get("/api/report/email/presets").status_code == 200


def test_report_email_endpoint_does_not_touch_mcp(client, smtp_configured, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("이메일 엔드포인트가 MCP/챗 세션을 열어서는 안 된다")

    monkeypatch.setattr(main, "run_chat", boom)
    monkeypatch.setattr(mailer, "send_email", lambda payload: None)

    res = client.post(
        "/api/report/email",
        json={"content": SAMPLE_CONTENT, "to": ["user@company.com"]},
    )
    assert res.status_code == 200
