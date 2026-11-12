from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class Price(BaseModel):
    coin_id: str
    vs_currency: str
    price: float
    change_24h: Optional[float] = None
    market_cap: Optional[float] = None
    last_updated_at: Optional[int] = None


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    token: str


class RegisterOut(BaseModel):
    token: str
    recovery_phrase: str


class RecoverPasswordIn(BaseModel):
    username: str = Field(min_length=3, max_length=150)
    recovery_phrase: str = Field(min_length=20, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)


class WatchlistIn(BaseModel):
    coin_id: str = Field(min_length=1, max_length=64)


class WatchlistOut(BaseModel):
    coin_id: str


class AlertIn(BaseModel):
    coin_id: str = Field(min_length=1, max_length=64)
    direction: Literal["above", "below"]
    target_price: Decimal = Field(gt=0)
    vs_currency: str = "usd"


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    coin_id: str
    vs_currency: str
    direction: str
    target_price: Decimal
    triggered: bool
    triggered_at: Optional[datetime] = None


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    price: Decimal
    change_24h: Optional[Decimal] = None
    captured_at: datetime


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=150)
    password: str = Field(min_length=8, max_length=128)
    email: Optional[str] = None


class HoldingIn(BaseModel):
    coin_id: str = Field(min_length=1, max_length=64)
    amount: Decimal = Field(gt=0)
    avg_buy_price: Decimal = Field(default=Decimal(0), ge=0)


class HoldingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    coin_id: str
    amount: Decimal
    avg_buy_price: Decimal


class HoldingValue(BaseModel):
    coin_id: str
    amount: Decimal
    avg_buy_price: Decimal
    price: Optional[Decimal] = None
    value: Optional[Decimal] = None
    cost: Decimal
    pnl: Optional[Decimal] = None
    pnl_pct: Optional[Decimal] = None


class PortfolioOut(BaseModel):
    vs_currency: str
    total_value: Decimal
    total_cost: Decimal
    total_pnl: Decimal
    total_pnl_pct: Optional[Decimal] = None
    holdings: list[HoldingValue]
