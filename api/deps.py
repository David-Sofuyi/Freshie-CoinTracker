from asgiref.sync import sync_to_async
from fastapi import Depends, Header, HTTPException, status

from market.models import ApiToken


async def current_user(authorization: str | None = Header(default=None)):
    """Authenticate via `Authorization: Bearer <token>` using Django's ApiToken model."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    key = authorization.split(" ", 1)[1].strip()
    try:
        token = await ApiToken.objects.select_related("user").aget(key=key)
    except ApiToken.DoesNotExist:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    if not token.user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User disabled")
    return token.user
