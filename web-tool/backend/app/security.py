import asyncio
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


AUTH_REQUIRED = env_flag("REQUIRE_AUTH", False)
RATE_LIMIT_REQUESTS = int(os.getenv("ANALYSIS_RATE_LIMIT", "60"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("ANALYSIS_RATE_WINDOW_SECONDS", "60"))


class SlidingWindowRateLimiter:
    def __init__(self, limit=RATE_LIMIT_REQUESTS, window_seconds=RATE_LIMIT_WINDOW_SECONDS):
        self.limit = max(1, int(limit))
        self.window_seconds = max(1, int(window_seconds))
        self.events = defaultdict(deque)
        self.lock = threading.Lock()

    def consume(self, key: str, cost: int = 1):
        cost = max(1, int(cost))
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self.lock:
            bucket = self.events[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) + cost > self.limit:
                retry_after = max(1, int(self.window_seconds - (now - bucket[0]))) if bucket else 1
                raise HTTPException(
                    status_code=429,
                    detail="Analysis rate limit reached. Please retry shortly.",
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.extend([now] * cost)


rate_limiter = SlidingWindowRateLimiter()
_firebase_app = None
_firebase_lock = threading.Lock()


def _verify_firebase_token(token: str):
    global _firebase_app
    try:
        import firebase_admin
        from firebase_admin import auth as firebase_auth
    except ImportError as exc:
        raise RuntimeError("firebase-admin is required when REQUIRE_AUTH=true.") from exc

    project_id = os.getenv("FIREBASE_PROJECT_ID") or os.getenv("VITE_FIREBASE_PROJECT_ID")
    if not project_id:
        raise RuntimeError("FIREBASE_PROJECT_ID is required when REQUIRE_AUTH=true.")

    with _firebase_lock:
        if _firebase_app is None:
            _firebase_app = firebase_admin.initialize_app(options={"projectId": project_id})
    return firebase_auth.verify_id_token(token, app=_firebase_app)


async def get_principal(
    request: Request,
    authorization: str | None = Header(default=None),
):
    client_ip = request.client.host if request.client else "unknown"
    if not AUTH_REQUIRED:
        return {"uid": None, "rate_key": f"ip:{client_ip}", "authenticated": False}

    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Sign in is required to analyze images.")

    try:
        decoded = await asyncio.to_thread(_verify_firebase_token, token)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail="The sign-in token is invalid or expired.") from exc

    uid = decoded.get("uid") or decoded.get("sub")
    if not uid:
        raise HTTPException(status_code=401, detail="The sign-in token has no user identifier.")
    return {"uid": uid, "rate_key": f"user:{uid}", "authenticated": True}
