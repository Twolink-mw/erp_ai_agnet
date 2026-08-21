"""조회 결과 PDF를 SMTP로 첨부 발송한다.

이 모듈은 순수 발송 계층이다. DB/MCP/SQL에 전혀 접근하지 않는다.
PDF 렌더링은 pdf_report.build_pdf()에 위임한다. 새 데이터를 조회하는
기능을 여기에 추가하지 말 것.

표준 라이브러리(smtplib, email)만 사용한다 — 외부 패키지를 추가하지 않는다.
"""

from __future__ import annotations

import re
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from . import config

_CRLF_RE = re.compile(r"[\r\n]+")

# RFC 5322를 완벽히 구현하지는 않는 실용적 형식 검증 — 헤더 인젝션 방지가
# 목적이 아니라(그건 sanitize_header_value가 담당) 명백히 잘못된 입력을 거른다.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailDomainNotAllowedError(ValueError):
    """수신자 도메인이 ALLOWED_EMAIL_DOMAINS 화이트리스트에 없을 때."""


class EmailSendError(RuntimeError):
    """SMTP 발송 과정에서 어떤 이유로든 실패했을 때."""


def sanitize_header_value(value: str) -> str:
    """이메일 헤더(제목 등)에서 CR/LF를 제거해 헤더 인젝션을 방지한다."""
    return _CRLF_RE.sub(" ", value or "").strip()


def _domain_allowed(domain: str, allowed_domains: list[str]) -> bool:
    domain = domain.lower()
    for allowed in allowed_domains:
        if domain == allowed or domain.endswith("." + allowed):
            return True
    return False


def validate_recipient(email: str) -> str:
    """이메일 형식과 사내 도메인 화이트리스트를 검증하고 정규화된 주소를 돌려준다.

    형식 오류는 ValueError, 화이트리스트 밖 도메인은 EmailDomainNotAllowedError.
    """
    candidate = (email or "").strip()
    if not candidate or not _EMAIL_RE.match(candidate):
        raise ValueError(f"올바르지 않은 이메일 형식입니다: {email!r}")

    domain = candidate.rsplit("@", 1)[-1]
    if not _domain_allowed(domain, config.ALLOWED_EMAIL_DOMAINS):
        raise EmailDomainNotAllowedError(f"허용되지 않은 이메일 도메인입니다: {domain}")

    return candidate


def validate_recipients(emails: list[str]) -> list[str]:
    """수신자 목록 전체를 검증한다. 하나라도 실패하면 전체 실패시킨다."""
    if not emails:
        raise ValueError("수신자가 없습니다.")

    deduped: list[str] = []
    seen: set[str] = set()
    for email in emails:
        key = (email or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(email)

    return [validate_recipient(email) for email in deduped]


@dataclass
class EmailReportPayload:
    to: list[str]
    subject: str
    body_text: str
    pdf_bytes: bytes
    pdf_filename: str


def build_message(payload: EmailReportPayload) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = sanitize_header_value(payload.subject)
    msg["From"] = config.SMTP_FROM
    msg["To"] = ", ".join(sanitize_header_value(addr) for addr in payload.to)
    msg.set_content(payload.body_text)
    msg.add_attachment(
        payload.pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=payload.pdf_filename,
    )
    return msg


def send_email(payload: EmailReportPayload) -> None:
    """SMTP로 리포트를 발송한다. 실패하면 EmailSendError로 감싸 원래 예외를 숨긴다."""
    try:
        msg = build_message(payload)
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as smtp:
            if config.SMTP_USE_TLS:
                smtp.starttls()
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
    except Exception as exc:
        raise EmailSendError("이메일 발송에 실패했습니다.") from exc
