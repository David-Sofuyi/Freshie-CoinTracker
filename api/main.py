"""FastAPI app: REST + WebSocket under /api, with Django mounted at "/"."""
import asyncio
from contextlib import asynccontextmanager

from asgiref.sync import sync_to_async
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.hashers import make_password, check_password
from mnemonic import Mnemonic
from market.models import AccountRecovery
from django.core.exceptions import ValidationError
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from market.models import ApiToken, Holding, PriceAlert, PriceSnapshot, WatchlistItem
from django.conf import settings

from . import schemas
from .deps import current_user
from .poller import hub, poll_forever
from .portfolio import valuate
from .price_client import PriceUnavailable, price_client

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
@router.post("/auth/register", response_model=schemas.RegisterOut, status_code=201, tags=["auth"])
async def register(body: schemas.RegisterIn):
    User = get_user_model()
    if await User.objects.filter(username__iexact=body.username).aexists():
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")

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
    # BIP-39 128-bit entropy produces a cryptographically random 12-word phrase.
    recovery_phrase = Mnemonic("english").generate(strength=128)
    await AccountRecovery.objects.acreate(user=user, phrase_hash=make_password(recovery_phrase))
    token = await ApiToken.objects.acreate(user=user)
    return {"token": token.key, "recovery_phrase": recovery_phrase}


@router.post("/auth/recover", status_code=200, tags=["auth"])
async def recover_password(body: schemas.RecoverPasswordIn):
    User = get_user_model()
    try:
        user = await User.objects.aget(username__iexact=body.username)
        recovery = await AccountRecovery.objects.aget(user=user)
    except (User.DoesNotExist, AccountRecovery.DoesNotExist):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid username or recovery phrase")
    valid = await sync_to_async(check_password)(body.recovery_phrase.strip().lower(), recovery.phrase_hash)
    if not valid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid username or recovery phrase")

    def _reset():
        validate_password(body.new_password, user)
        user.set_password(body.new_password)
        user.save(update_fields=["password"])
    try:
        await sync_to_async(_reset)()
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, list(exc.messages))
    await ApiToken.objects.filter(user=user).adelete()
    return {"message": "Password reset successful. Please register/sign in again."}


@router.post("/auth/token", response_model=schemas.TokenOut, tags=["auth"])
async def login(body: schemas.LoginIn):
    user = await sync_to_async(authenticate)(username=body.username, password=body.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    token, _ = await ApiToken.objects.aget_or_create(user=user)
    return {"token": token.key}


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
