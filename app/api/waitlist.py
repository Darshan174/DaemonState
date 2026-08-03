from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models import WaitlistSignup
from app.time import utc_now


router = APIRouter()
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
WAITLIST_CONSENT_VERSION = "2026-08-03"
_ATTRIBUTION_FIELDS = (
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
)


class WaitlistRegistration(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    website: str = Field(default="", max_length=255)
    referrer: str | None = Field(default=None, max_length=1024)
    utm_source: str | None = Field(default=None, max_length=255)
    utm_medium: str | None = Field(default=None, max_length=255)
    utm_campaign: str | None = Field(default=None, max_length=255)
    utm_term: str | None = Field(default=None, max_length=255)
    utm_content: str | None = Field(default=None, max_length=255)
    consent_version: str = Field(
        default=WAITLIST_CONSENT_VERSION,
        min_length=1,
        max_length=32,
    )

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if (
            not _EMAIL_PATTERN.fullmatch(email)
            or email.startswith(".")
            or ".." in email
            or len(email.rsplit("@", 1)[0]) > 64
        ):
            raise ValueError("Enter a valid email address")
        return email

    @field_validator(*_ATTRIBUTION_FIELDS, mode="before")
    @classmethod
    def clean_attribution_value(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Attribution values must be strings")
        normalized = value.strip()
        if not normalized:
            return None
        if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
            raise ValueError("Attribution values cannot contain control characters")
        return normalized

    @field_validator("referrer")
    @classmethod
    def clean_referrer(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        parsed = urlsplit(value.strip())
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Referrer must be a public HTTP URL")
        # Query strings and fragments can contain user-specific data. They are
        # intentionally excluded because origin and path are sufficient for
        # campaign attribution.
        return urlunsplit((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            "",
            "",
        ))

    @field_validator("consent_version")
    @classmethod
    def known_consent_version(cls, value: str) -> str:
        if value != WAITLIST_CONSENT_VERSION:
            raise ValueError("Unsupported waitlist consent version")
        return value


@router.post("/waitlist", status_code=201)
async def register_waitlist_signup(
    payload: WaitlistRegistration,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    # A filled honeypot is treated as a successful request so automated
    # submissions get no signal and do not pollute the waitlist.
    if payload.website.strip():
        return {
            "status": "registered",
            "message": "You're on the DaemonState waitlist.",
        }

    signup = WaitlistSignup(
        email=payload.email,
        referrer=payload.referrer,
        utm_source=payload.utm_source,
        utm_medium=payload.utm_medium,
        utm_campaign=payload.utm_campaign,
        utm_term=payload.utm_term,
        utm_content=payload.utm_content,
        consent_at=utc_now(),
        consent_version=payload.consent_version,
    )
    session.add(signup)
    try:
        await session.commit()
    except IntegrityError:
        # Returning the same response for an existing email keeps signup
        # idempotent and avoids exposing whether an address is registered.
        await session.rollback()
        existing = await session.scalar(
            select(WaitlistSignup).where(WaitlistSignup.email == payload.email)
        )
        if existing is None:
            raise

    return {
        "status": "registered",
        "message": "You're on the DaemonState waitlist.",
    }
