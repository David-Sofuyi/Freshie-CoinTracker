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
    username: Optional[str] = None
    email_notification_sent: Optional[bool] = None


class UserOut(BaseModel):
    id: int
    username: str
    email: Optional[str] = None


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
    email: str = Field(min_length=5, max_length=254)


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


class PasswordResetRequestIn(BaseModel):
    email: str = Field(min_length=5, max_length=254)


class PasswordResetConfirmIn(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(min_length=8, max_length=128)


class WalletDepositIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: Literal["NGN"] = "NGN"


class WalletTransferIn(BaseModel):
    recipient_username: str = Field(min_length=3, max_length=150)
    amount: Decimal = Field(gt=0, max_digits=24, decimal_places=8)
    currency: Literal["NGN", "USD"]


class WalletWithdrawalIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: Literal["NGN"] = "NGN"
    account_number: str = Field(min_length=10, max_length=10, pattern=r"^\d{10}$")
    bank_code: str = Field(min_length=2, max_length=10)
    account_name: str = Field(min_length=2, max_length=120)


class DedicatedAccountRequestIn(BaseModel):
    first_name: str = Field(min_length=2, max_length=80)
    last_name: str = Field(min_length=2, max_length=80)
    phone: str = Field(min_length=7, max_length=20)
    preferred_bank: str = Field(default="test-bank", min_length=2, max_length=80)
    consent: bool


class USDDepositIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: Literal["USD"] = "USD"
    payment_method: Literal["card", "bank_transfer"]


class USDWithdrawalIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: Literal["USD"] = "USD"
    bank_country: str = Field(min_length=2, max_length=2)
    bank_name: str = Field(min_length=2, max_length=100)
    account_name: str = Field(min_length=2, max_length=120)
    account_number: str = Field(min_length=4, max_length=34)


class TradeRequestIn(BaseModel):
    side: Literal["buy", "sell"]
    coin: str = Field(min_length=2, max_length=12)
    amount: Decimal = Field(gt=0, max_digits=24, decimal_places=10)
    quote_currency: Literal["NGN", "USD"] = "NGN"
