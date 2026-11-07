from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, get_principal
from app.core.database import get_db
from app.models.entities import OnboardingProfile

router = APIRouter()

VALID_ACTIVITIES = {
    "forex_trading",
    "mining",
    "contracts",
    "futures_trading",
    "propfirms",
    "trading_indices",
    "investment",
    "liquidity_pools",
}

VALID_INDICES_BROKERS = {"weltrade", "deriv", "spredix"}


class OnboardingIn(BaseModel):
    email: EmailStr
    age: int = Field(ge=18, le=120)
    country: str = Field(min_length=1, max_length=120)
    wallet_network: str = Field(min_length=1, max_length=40)
    wallet_address: str = Field(min_length=10, max_length=200)
    activities: list[str] = Field(min_length=1, max_length=8)
    indices_broker: str = Field(default="", max_length=60)


def _payload(row: OnboardingProfile) -> dict:
    return {
        "id": str(row.id),
        "user_id": str(row.user_id),
        "email": row.email,
        "age": row.age,
        "country": row.country,
        "wallet_network": row.wallet_network,
        "wallet_address": row.wallet_address,
        "activities": row.activities,
        "indices_broker": row.indices_broker,
        "completed_at": row.completed_at.isoformat(),
    }


@router.post("/onboarding")
def save_onboarding(
    payload: OnboardingIn,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    invalid = [a for a in payload.activities if a not in VALID_ACTIVITIES]
    if invalid:
        raise HTTPException(400, f"Unknown activities: {', '.join(invalid)}")

    if "trading_indices" in payload.activities:
        broker = payload.indices_broker.lower().strip()
        if broker not in VALID_INDICES_BROKERS:
            raise HTTPException(400, "Choose a broker for trading indices: weltrade, deriv, or spredix")

    row = db.scalar(
        select(OnboardingProfile).where(OnboardingProfile.user_id == principal.user.id)
    )

    if row is None:
        row = OnboardingProfile(
            id=uuid4(),
            user_id=principal.user.id,
            email=str(payload.email),
            age=payload.age,
            country=payload.country,
            wallet_network=payload.wallet_network,
            wallet_address=payload.wallet_address,
            activities=payload.activities,
            indices_broker=payload.indices_broker.lower().strip(),
            completed_at=datetime.now(timezone.utc),
        )
        db.add(row)
    else:
        row.email = str(payload.email)
        row.age = payload.age
        row.country = payload.country
        row.wallet_network = payload.wallet_network
        row.wallet_address = payload.wallet_address
        row.activities = payload.activities
        row.indices_broker = payload.indices_broker.lower().strip()
        row.completed_at = datetime.now(timezone.utc)

    db.commit()
    return _payload(row)


@router.get("/onboarding/me")
def get_my_onboarding(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    row = db.scalar(
        select(OnboardingProfile).where(OnboardingProfile.user_id == principal.user.id)
    )
    if row is None:
        raise HTTPException(404, "Onboarding profile not found")
    return _payload(row)
