"""FastAPI app: REST + WebSocket under /api, with Django mounted at "/"."""
import asyncio
import json
import os
import uuid
from decimal import Decimal
from contextlib import asynccontextmanager

from asgiref.sync import sync_to_async
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.hashers import make_password, check_password
from django.core.mail import send_mail
from django.utils import timezone
from datetime import timedelta
import secrets
from django.core.exceptions import ValidationError
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status

from market.models import ApiToken, Holding, PriceAlert, PriceSnapshot, WatchlistItem, PasswordResetCode, WalletAccount, WalletTransaction, PaystackDedicatedAccount
from django.conf import settings

from . import schemas
from .deps import current_user
from .poller import hub, poll_forever
from .portfolio import valuate
from .price_client import PriceUnavailable, price_client
from . import payments
from .wallet import balance as wallet_balance, get_wallet, post_deposit, transfer_between_users, reserve_withdrawal, finalize_withdrawal, reverse_withdrawal, fail_deposit

router = APIRouter(prefix="/api")


@router.get("/coins", tags=["prices"])
async def coin_markets(
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=250),
    q: str = Query(default="", max_length=100),
    vs: str | None = None,
):
    """Browse all CoinGecko-listed coins in live, paginated market-cap order."""
    try:
        if q.strip():
            return await price_client.search_markets(q, vs)
        return await price_client.get_market_page(page, per_page, vs)
    except PriceUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"CoinGecko unavailable: {exc}")


@router.get("/health")
async def health():
    return {"status": "ok"}


# ---------- Live prices ----------
@router.get("/prices", response_model=list[schemas.Price], tags=["prices"])
async def prices(
    ids: str = Query(default="", description="Comma separated CoinGecko ids, e.g. bitcoin,ethereum"),
    vs: str = Query(default=None, description="Quote currency, e.g. usd, eur, ngn"),
):
    coin_ids = [i for i in ids.split(",") if i.strip()] or settings.DEFAULT_COINS
    try:
        data = await price_client.get_prices(coin_ids, vs)
    except PriceUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Price provider unavailable: {exc}")
    return list(data.values())


@router.get("/prices/{coin_id}", response_model=schemas.Price, tags=["prices"])
async def price(coin_id: str, vs: str | None = None):
    try:
        data = await price_client.get_prices([coin_id], vs)
    except PriceUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Price provider unavailable: {exc}")
    if coin_id.lower() not in data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown coin id")
    return data[coin_id.lower()]


@router.get("/prices/{coin_id}/history", response_model=list[schemas.SnapshotOut], tags=["prices"])
async def history(coin_id: str, limit: int = Query(100, ge=1, le=1000)):
    qs = PriceSnapshot.objects.filter(coin_id=coin_id.lower()).order_by("-captured_at")[:limit]
    return [s async for s in qs]


@router.websocket("/ws/prices")
async def ws_prices(ws: WebSocket):
    await ws.accept()
    hub.clients.add(ws)
    try:
        if hub.latest:
            await ws.send_json({"type": "prices", "data": list(hub.latest.values())})
        while True:
            await ws.receive_text()  # keep the connection open; ignore client messages
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)


# ---------- Auth ----------
@router.post("/auth/register", response_model=schemas.TokenOut, status_code=201, tags=["auth"])
async def register(body: schemas.RegisterIn):
    User = get_user_model()
    if await User.objects.filter(username__iexact=body.username).aexists():
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")
    if not body.email or "@" not in body.email:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A valid email address is required")
    if await User.objects.filter(email__iexact=body.email).aexists():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email address already registered")

    def _create():
        user = User(username=body.username, email=body.email or "")
        validate_password(body.password, user)  # Django's configured password rules
        user.set_password(body.password)
        user.save()
        return user

    try:
        user = await sync_to_async(_create)()
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, list(exc.messages))
    token, _ = await ApiToken.objects.aget_or_create(user=user)
    email_sent = False
    try:
        await sync_to_async(send_mail)(
            "Welcome to CryptoTracker",
            f"Hello {user.username},\n\nYour CryptoTracker account has been created successfully.\n\nIf you did not create this account, please contact support.",
            settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False,
        )
        email_sent = True
    except Exception:
        # Keep account creation successful, but explicitly report that delivery failed.
        email_sent = False
    return {"token": token.key, "username": user.username, "email_notification_sent": email_sent}


@router.post("/auth/password/forgot", status_code=202, tags=["auth"])
async def request_password_reset(body: schemas.PasswordResetRequestIn):
    """Send a short-lived reset code without revealing whether an email is registered."""
    User = get_user_model()
    user = await User.objects.filter(email__iexact=body.email).afirst()
    if user and user.is_active:
        recent = await PasswordResetCode.objects.filter(user=user, created_at__gt=timezone.now() - timedelta(seconds=60)).aexists()
        if recent:
            return {"message": "If an account exists for that email, a reset code has been sent."}
        code = f"{secrets.randbelow(1_000_000):06d}"
        await PasswordResetCode.objects.filter(user=user, used_at__isnull=True).aupdate(used_at=timezone.now())
        await PasswordResetCode.objects.acreate(
            user=user, code_hash=make_password(code),
            expires_at=timezone.now() + timedelta(minutes=settings.PASSWORD_RESET_CODE_MINUTES),
        )
        try:
            await sync_to_async(send_mail)(
                "Your CryptoTracker password reset code",
                f"Your password reset code is {code}. It expires in {settings.PASSWORD_RESET_CODE_MINUTES} minutes. If you did not request this, ignore this email.",
                settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False,
            )
        except Exception:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Unable to send email right now. Please try again later.")
    return {"message": "If an account exists for that email, a reset code has been sent."}


@router.post("/auth/password/reset", status_code=200, tags=["auth"])
async def reset_password(body: schemas.PasswordResetConfirmIn):
    User = get_user_model()
    user = await User.objects.filter(email__iexact=body.email).afirst()
    if not user:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset code")
    reset = await PasswordResetCode.objects.filter(user=user, used_at__isnull=True, expires_at__gt=timezone.now(), attempts__lt=5).afirst()
    if not reset:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset code")
    if not check_password(body.code, reset.code_hash):
        reset.attempts += 1
        await reset.asave(update_fields=["attempts"])
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset code")
    try:
        await sync_to_async(validate_password)(body.new_password, user)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, list(exc.messages))
    def _finish_reset():
        user.set_password(body.new_password)
        user.save(update_fields=["password"])
        reset.used_at = timezone.now()
        reset.save(update_fields=["used_at"])
        ApiToken.objects.filter(user=user).delete()
    await sync_to_async(_finish_reset)()
    return {"message": "Password reset successful. Please sign in with your new password."}


@router.post("/auth/token", response_model=schemas.TokenOut, tags=["auth"])
async def login(body: schemas.LoginIn):
    user = await sync_to_async(authenticate)(username=body.username, password=body.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    token, _ = await ApiToken.objects.aget_or_create(user=user)
    return {"token": token.key, "username": user.username}


@router.get("/auth/me", response_model=schemas.UserOut, tags=["auth"])
async def me(user=Depends(current_user)):
    return {"id": user.id, "username": user.username, "email": user.email}


# ---------- Watchlist ----------
@router.get("/watchlist", response_model=list[schemas.WatchlistOut], tags=["watchlist"])
async def get_watchlist(user=Depends(current_user)):
    return [{"coin_id": w.coin_id} async for w in WatchlistItem.objects.filter(user=user)]


@router.post("/watchlist", response_model=schemas.WatchlistOut, status_code=201, tags=["watchlist"])
async def add_watchlist(body: schemas.WatchlistIn, user=Depends(current_user)):
    coin_id = body.coin_id.lower()
    try:
        known = await price_client.get_prices([coin_id])
    except PriceUnavailable:
        known = {coin_id: {}}  # provider down: accept, it will be validated on next poll
    if coin_id not in known:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown coin id")
    await WatchlistItem.objects.aget_or_create(user=user, coin_id=coin_id)
    return {"coin_id": coin_id}


@router.delete("/watchlist/{coin_id}", status_code=204, tags=["watchlist"])
async def remove_watchlist(coin_id: str, user=Depends(current_user)):
    await WatchlistItem.objects.filter(user=user, coin_id=coin_id.lower()).adelete()


# ---------- Alerts ----------
@router.get("/alerts", response_model=list[schemas.AlertOut], tags=["alerts"])
async def list_alerts(user=Depends(current_user)):
    return [a async for a in PriceAlert.objects.filter(user=user)]


@router.post("/alerts", response_model=schemas.AlertOut, status_code=201, tags=["alerts"])
async def create_alert(body: schemas.AlertIn, user=Depends(current_user)):
    return await PriceAlert.objects.acreate(
        user=user,
        coin_id=body.coin_id.lower(),
        vs_currency=body.vs_currency.lower(),
        direction=body.direction,
        target_price=body.target_price,
    )


@router.delete("/alerts/{alert_id}", status_code=204, tags=["alerts"])
async def delete_alert(alert_id: int, user=Depends(current_user)):
    deleted, _ = await PriceAlert.objects.filter(pk=alert_id, user=user).adelete()
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")


# ---------- Portfolio ----------
@router.get("/portfolio", response_model=schemas.PortfolioOut, tags=["portfolio"])
async def get_portfolio(user=Depends(current_user)):
    holdings = [h async for h in Holding.objects.filter(user=user)]
    prices = {}
    if holdings:
        try:
            prices = await price_client.get_prices([h.coin_id for h in holdings])
        except PriceUnavailable:
            prices = {}  # still return holdings, just without live values
    return valuate(holdings, prices, settings.DEFAULT_VS_CURRENCY)


@router.put("/portfolio", response_model=schemas.HoldingOut, tags=["portfolio"])
async def upsert_holding(body: schemas.HoldingIn, user=Depends(current_user)):
    """Create or replace your position in a coin."""
    holding, _ = await Holding.objects.aupdate_or_create(
        user=user,
        coin_id=body.coin_id.lower(),
        defaults={"amount": body.amount, "avg_buy_price": body.avg_buy_price},
    )
    return holding


@router.delete("/portfolio/{coin_id}", status_code=204, tags=["portfolio"])
async def delete_holding(coin_id: str, user=Depends(current_user)):
    deleted, _ = await Holding.objects.filter(user=user, coin_id=coin_id.lower()).adelete()
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holding not found")



# ---------- Wallets and payment rails ----------
def _payments_enabled():
    return os.getenv("PAYMENTS_ENABLED", "0") == "1"


@router.get("/wallets", tags=["wallets"])
async def wallets(user=Depends(current_user)):
    def _read():
        output = []
        for currency in ("NGN", "USD"):
            wallet = get_wallet(user, currency)
            output.append({"currency": currency, "balance": str(wallet_balance(wallet))})
        return output
    return await sync_to_async(_read, thread_sensitive=True)()


@router.get("/wallets/transactions", tags=["wallets"])
async def wallet_transactions(user=Depends(current_user), limit: int = Query(50, ge=1, le=200)):
    from django.db.models import Q
    rows = WalletTransaction.objects.filter(Q(user=user) | Q(entries__user=user)).distinct().order_by("-created_at")[:limit]
    return [{"reference": x.reference, "type": x.transaction_type, "currency": x.currency,
             "amount": str(x.amount), "status": x.status, "description": x.description,
             "created_at": x.created_at.isoformat()} async for x in rows]


@router.post("/wallets/deposit", status_code=201, tags=["wallets"])
async def initiate_wallet_deposit(body: schemas.WalletDepositIn, user=Depends(current_user)):
    if not _payments_enabled():
        raise HTTPException(503, "Payments are disabled until Paystack business approval and production configuration are complete")
    if not os.getenv("PAYSTACK_SECRET_KEY"):
        raise HTTPException(503, "Paystack is not configured")
    reference = "CTD-" + uuid.uuid4().hex
    tx = await WalletTransaction.objects.acreate(user=user, transaction_type="deposit", currency="NGN",
        amount=body.amount, reference=reference, status="pending", provider="paystack", description="Awaiting Paystack payment")
    try:
        data = await sync_to_async(payments.request)("POST", "/transaction/initialize", json={
            "email": user.email, "amount": int(body.amount * 100), "currency": "NGN", "reference": reference,
            "metadata": {"user_id": user.pk, "wallet_transaction": reference}})
    except Exception as exc:
        # Keep the reference pending: a timeout may happen after Paystack accepted it.
        raise HTTPException(502, f"Could not initialize Paystack payment; reconcile reference {reference}: {exc}")
    tx.provider_reference = reference
    tx.metadata = {"authorization_url": data.get("authorization_url"), "access_code": data.get("access_code")}
    await tx.asave(update_fields=["provider_reference", "metadata", "updated_at"])
    return {"reference": reference, "authorization_url": data.get("authorization_url"), "access_code": data.get("access_code")}


@router.post("/wallets/transfer", status_code=201, tags=["wallets"])
async def wallet_transfer(body: schemas.WalletTransferIn, user=Depends(current_user)):
    reference = "CTT-" + uuid.uuid4().hex
    try:
        tx = await sync_to_async(transfer_between_users, thread_sensitive=True)(user, body.recipient_username, body.currency, body.amount, reference)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"reference": tx.reference, "status": tx.status, "amount": str(tx.amount), "currency": tx.currency}


@router.post("/wallets/withdraw", status_code=202, tags=["wallets"])
async def wallet_withdraw(body: schemas.WalletWithdrawalIn, user=Depends(current_user)):
    if not _payments_enabled():
        raise HTTPException(503, "Withdrawals are disabled until Paystack business approval and production configuration are complete")
    reference = "CTW-" + uuid.uuid4().hex
    try:
        resolved = await sync_to_async(payments.request)("GET", "/bank/resolve", params={
            "account_number": body.account_number, "bank_code": body.bank_code})
        resolved_name = (resolved.get("account_name") or "").strip()
        if not resolved_name or resolved_name.casefold() != body.account_name.strip().casefold():
            raise ValueError("The account name does not match the bank's verified account name")
        recipient = await sync_to_async(payments.request)("POST", "/transferrecipient", json={
            "type": "nuban", "name": resolved_name, "account_number": body.account_number,
            "bank_code": body.bank_code, "currency": "NGN"})
        tx = await sync_to_async(reserve_withdrawal, thread_sensitive=True)(user, "NGN", body.amount, reference,
            {"recipient_code": recipient["recipient_code"], "account_number": body.account_number, "bank_code": body.bank_code})
        try:
            transfer = await sync_to_async(payments.request)("POST", "/transfer", json={
                "source": "balance", "amount": int(body.amount * 100), "recipient": recipient["recipient_code"],
                "reason": "CryptoTracker wallet withdrawal", "reference": reference})
        except Exception:
            # A network timeout can occur after Paystack accepted the transfer. Keep the
            # reservation pending and reconcile by reference; never refund on an ambiguous result.
            raise
        tx.provider_reference = transfer.get("transfer_code") or reference
        tx.metadata = {**tx.metadata, "transfer_code": transfer.get("transfer_code"), "transfer_id": transfer.get("id")}
        await tx.asave(update_fields=["provider_reference", "metadata", "updated_at"])
        return {"reference": reference, "status": "pending", "message": "Withdrawal submitted to Paystack for processing"}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Paystack withdrawal could not be submitted: {exc}")


@router.get("/wallets/ngn/virtual-account", tags=["wallets"])
async def get_ngn_virtual_account(user=Depends(current_user)):
    account = await PaystackDedicatedAccount.objects.filter(user=user).afirst()
    if not account:
        return {"status": "not_created", "message": "No dedicated NGN account has been assigned."}
    return {"status": account.status, "account_name": account.account_name,
            "account_number": account.account_number, "bank_name": account.bank_name,
            "currency": account.currency}


@router.post("/wallets/ngn/virtual-account", status_code=202, tags=["wallets"])
async def create_ngn_virtual_account(body: schemas.DedicatedAccountRequestIn, user=Depends(current_user)):
    """Create a Paystack DVA only after registered-business and compliance gates are enabled."""
    if not body.consent:
        raise HTTPException(400, "Customer consent is required before requesting a dedicated account")
    paystack_secret = os.getenv("PAYSTACK_SECRET_KEY", "")
    test_mode = os.getenv("PAYSTACK_DVA_TEST_MODE", "0") == "1" and paystack_secret.startswith("sk_test_")
    if not paystack_secret:
        raise HTTPException(503, "Paystack is not configured")
    if not test_mode:
        if os.getenv("BUSINESS_REGISTERED", "0") != "1":
            raise HTTPException(503, "Dedicated accounts are unavailable until CryptoTracker is registered as a business")
        if os.getenv("PAYSTACK_DVA_ENABLED", "0") != "1":
            raise HTTPException(503, "Paystack has not approved dedicated virtual accounts for this business")
        if os.getenv("PAYSTACK_DVA_VALIDATION_REQUIRED", "1") == "1":
            raise HTTPException(503, "Paystack customer identity validation must be completed through its approved verification flow before account assignment")
    account = await PaystackDedicatedAccount.objects.filter(user=user).afirst()
    if account and account.account_number:
        return {"status": account.status, "account_number": account.account_number, "bank_name": account.bank_name, "account_name": account.account_name}
    try:
        if account:
            customer_code = account.customer_code
            customer_metadata = account.provider_metadata
        else:
            customer = await sync_to_async(payments.request)("POST", "/customer", json={
                "email": user.email, "first_name": body.first_name, "last_name": body.last_name, "phone": body.phone})
            customer_code = customer["customer_code"]
            customer_metadata = {"customer_id": customer.get("id")}
            account = await PaystackDedicatedAccount.objects.acreate(
                user=user, customer_code=customer_code, status="pending",
                consented_at=timezone.now(), provider_metadata=customer_metadata)
        dva = await sync_to_async(payments.request)("POST", "/dedicated_account", json={
            "customer": customer_code, "preferred_bank": "test-bank" if test_mode else body.preferred_bank})
    except Exception as exc:
        raise HTTPException(502, f"Paystack account assignment failed; retry using the same customer record: {exc}")
    bank = dva.get("bank") or {}
    account.account_name = dva.get("account_name", "")
    account.account_number = dva.get("account_number", "")
    account.bank_name = bank.get("name", "")
    account.bank_slug = bank.get("slug", "")
    account.status = "active" if dva.get("active") else "pending"
    account.provider_metadata = customer_metadata
    await account.asave(update_fields=["account_name", "account_number", "bank_name", "bank_slug", "status", "provider_metadata", "updated_at"])
    return {"status": account.status, "account_name": account.account_name,
            "account_number": account.account_number, "bank_name": account.bank_name, "currency": "NGN"}


@router.post("/wallets/usd/deposit", status_code=202, tags=["wallets"])
async def initiate_usd_deposit(body: schemas.USDDepositIn, user=Depends(current_user)):
    # Paystack's published policy excludes cryptocurrency and mobile-wallet businesses
    # from international payment processing. Never route CryptoTracker USD funds through it.
    if os.getenv("USD_PAYMENTS_ENABLED", "0") != "1" or not os.getenv("USD_PAYMENTS_PROVIDER"):
        raise HTTPException(503, "USD deposits are disabled until an eligible USD card and bank-transfer provider is contracted and configured")
    raise HTTPException(503, "The configured USD provider adapter has not passed compliance and settlement certification")


@router.post("/wallets/usd/withdraw", status_code=202, tags=["wallets"])
async def initiate_usd_withdrawal(body: schemas.USDWithdrawalIn, user=Depends(current_user)):
    if os.getenv("USD_PAYMENTS_ENABLED", "0") != "1" or not os.getenv("USD_PAYMENTS_PROVIDER"):
        raise HTTPException(503, "USD withdrawals are disabled until an eligible USD payout provider and settlement account are approved")
    raise HTTPException(503, "The configured USD payout adapter has not passed compliance and settlement certification")


@router.get("/trading/status", tags=["trading"])
async def trading_status():
    return {"provider": "luno", "configured": bool(os.getenv("LUNO_API_KEY_ID") and os.getenv("LUNO_API_KEY_SECRET")),
            "business_approved": os.getenv("LUNO_BUSINESS_APPROVED", "0") == "1",
            "trading_enabled": os.getenv("LUNO_TRADING_ENABLED", "0") == "1",
            "message": "Trading remains disabled until Luno business approval, customer custody architecture, and regulatory approvals are complete."}


@router.post("/payments/paystack/webhook", include_in_schema=False)
async def paystack_webhook(request: Request):
    raw = await request.body()
    signature = request.headers.get("paystack-signature") or request.headers.get("x-paystack-signature", "")
    if not payments.verify_webhook(raw, signature):
        raise HTTPException(401, "Invalid webhook signature")
    try:
        event = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "Invalid webhook payload")
    event_type = event.get("event")
    data = event.get("data") or {}
    if event_type == "charge.failed":
        await sync_to_async(fail_deposit, thread_sensitive=True)(data.get("reference"))
    elif event_type == "charge.success":
        reference = data.get("reference")
        pending = await WalletTransaction.objects.filter(reference=reference, transaction_type="deposit", status="pending", currency="NGN").afirst()
        try:
            verified = await sync_to_async(payments.request)("GET", f"/transaction/verify/{reference}")
            if verified.get("status") != "success" or verified.get("currency") != "NGN":
                return {"received": True, "credited": False}
            if pending:
                if int(verified.get("amount", 0)) == int(pending.amount * 100):
                    await sync_to_async(post_deposit, thread_sensitive=True)(pending.user, "NGN", pending.amount, reference, "paystack", reference)
            else:
                # DVA transfers arrive without a pre-created checkout transaction. Match the
                # verified Paystack customer code to exactly one assigned account.
                customer = verified.get("customer") or {}
                customer_code = customer.get("customer_code")
                dva = await PaystackDedicatedAccount.objects.filter(customer_code=customer_code, status="active").select_related("user").afirst() if customer_code else None
                amount_kobo = int(verified.get("amount", 0))
                if dva and amount_kobo > 0 and verified.get("reference") == reference:
                    amount = Decimal(amount_kobo) / Decimal("100")
                    await sync_to_async(post_deposit, thread_sensitive=True)(dva.user, "NGN", amount, reference, "paystack_dva", reference)
        except Exception:
            # Return 500 so Paystack retries; ledger posting is idempotent by reference.
            raise HTTPException(503, "Payment verification temporarily unavailable")
    elif event_type in ("transfer.success", "transfer.failed"):
        transfer_code = data.get("transfer_code") or data.get("reference")
        await sync_to_async(finalize_withdrawal, thread_sensitive=True)(transfer_code, event_type == "transfer.success")
    elif event_type == "transfer.reversed":
        transfer_code = data.get("transfer_code") or data.get("reference")
        await sync_to_async(reverse_withdrawal, thread_sensitive=True)(transfer_code)
    return {"received": True}


# Luno account keys control the assets in the linked Luno account. A single platform key
# must never be used as if it represented segregated customer accounts. Trading stays off
# until the custody/agency model and customer-level account linking are approved.
@router.post("/trades", tags=["trading"])
async def create_trade(body: schemas.TradeRequestIn, user=Depends(current_user)):
    if os.getenv("LUNO_TRADING_ENABLED", "0") != "1" or os.getenv("LUNO_BUSINESS_APPROVED", "0") != "1":
        raise HTTPException(503, "Luno trading is disabled until the business account is approved and customer-level custody and compliance controls are certified")
    raise HTTPException(503, "Luno credentials alone are insufficient: customer sub-account allocation, order reconciliation, and safeguarding must be implemented and audited before trading can execute")


def create_app(django_asgi_app) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(poll_forever())
        try:
            yield
        finally:
            task.cancel()

    app = FastAPI(
        title="Freshie CoinTracker API",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.include_router(router)
    app.mount("/", django_asgi_app)  # everything else -> Django
    return app
