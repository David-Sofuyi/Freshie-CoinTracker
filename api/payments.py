"""Paystack NGN payment adapter. Secrets are read only from server environment."""
import hashlib
import hmac
import os
import time
import httpx

BASE = "https://api.paystack.co"


def _headers():
    secret = os.getenv("PAYSTACK_SECRET_KEY", "")
    if not secret:
        raise RuntimeError("PAYSTACK_SECRET_KEY is not configured")
    return {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}


def request(method, path, **kwargs):
    response = httpx.request(method, BASE + path, headers=_headers(), timeout=25, **kwargs)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("status"):
        raise RuntimeError(payload.get("message", "Paystack request failed"))
    return payload.get("data", {})


def verify_webhook(raw_body: bytes, signature: str) -> bool:
    """Support Paystack's timestamped Paystack-Signature and legacy signature."""
    if not signature:
        return False
    # Current format: t=<unix>,v1=<key-id>:<hex>[,v1=...], signed with whsec_ secret.
    webhook_secret = os.getenv("PAYSTACK_WEBHOOK_SECRET", "")
    if signature.startswith("t=") and webhook_secret:
        timestamp = None
        signatures = []
        for part in signature.split(","):
            key, sep, value = part.strip().partition("=")
            if not sep:
                continue
            if key == "t":
                if timestamp is not None or not value.isdigit():
                    return False
                timestamp = int(value)
            elif key == "v1" and ":" in value:
                signatures.append(value.split(":", 1)[1])
        if timestamp is None or abs(int(time.time()) - timestamp) > 300:
            return False
        expected = hmac.new(webhook_secret.encode(), str(timestamp).encode() + b"." + raw_body, hashlib.sha512).hexdigest()
        return any(len(sig) == 128 and hmac.compare_digest(expected, sig) for sig in signatures)

    # Legacy X-Paystack-Signature uses the Paystack secret key and raw body only.
    secret = os.getenv("PAYSTACK_SECRET_KEY", "")
    if not secret or len(signature) != 128:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)
