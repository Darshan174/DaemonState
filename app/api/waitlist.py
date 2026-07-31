from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models import WaitlistSignup


router = APIRouter()
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class WaitlistRegistration(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    website: str = Field(default="", max_length=255)

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


@router.post("/waitlist", status_code=201)
async def register_waitlist_signup(
    payload: WaitlistRegistration,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    # A filled honeypot is treated as a successful request so automated
    # submissions get no signal and do not pollute the waitlist.
    if payload.website:
        return {
            "status": "registered",
            "message": "You're on the DaemonState waitlist.",
        }

    session.add(WaitlistSignup(email=payload.email))
    try:
        await session.commit()
    except IntegrityError:
        # Returning the same response for an existing email keeps signup
        # idempotent and avoids exposing whether an address is registered.
        await session.rollback()

    return {
        "status": "registered",
        "message": "You're on the DaemonState waitlist.",
    }
