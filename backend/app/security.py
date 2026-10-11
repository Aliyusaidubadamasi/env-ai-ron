"""API-key auth, rate limiting, and hardened upload handling."""
from __future__ import annotations

import hmac
import io
import logging
import os
import time
from collections import defaultdict, deque

from fastapi import Depends, Header, HTTPException, Request, UploadFile
from PIL import Image

from . import config

log = logging.getLogger("env-ai-ron.security")
Image.MAX_IMAGE_PIXELS = config.MAX_IMAGE_PIXELS  # decompression-bomb guard

_DEV_KEY = "dev-planner-key"


def planner_keys() -> list[str]:
    raw = os.environ.get("ENVAIRON_PLANNER_KEYS", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if keys:
        return keys
    if os.environ.get("ENVAIRON_ENV", "dev") == "production":
        raise RuntimeError("ENVAIRON_PLANNER_KEYS must be set in production")
    return [_DEV_KEY]


def require_planner(x_api_key: str | None = Header(default=None)) -> str:
    """Municipal planners authenticate with an API key (swap for OIDC/SSO in production)."""
    if x_api_key:
        for k in planner_keys():
            if hmac.compare_digest(x_api_key.encode(), k.encode()):
                return k[:4] + "…"
    raise HTTPException(401, "Missing or invalid X-API-Key")


class RateLimiter:
    """Sliding-window limiter per client IP (in-memory; use Redis behind a load balancer)."""

    def __init__(self, limit: int, window_s: int):
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque] = defaultdict(deque)

    def __call__(self, request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        q = self.hits[ip]
        while q and q[0] < now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            raise HTTPException(429, "Too many requests, please slow down")
        q.append(now)


upload_limiter = RateLimiter(limit=40, window_s=60)
analysis_limiter = RateLimiter(limit=6, window_s=60)

MAGIC = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpeg",
    b"II*\x00": "tiff",
    b"MM\x00*": "tiff",
}


def sniff(data: bytes) -> str | None:
    for sig, kind in MAGIC.items():
        if data.startswith(sig):
            return kind
    return None


async def read_limited(file: UploadFile, max_mb: int = config.MAX_UPLOAD_MB) -> bytes:
    """Read an upload in chunks and abort as soon as it exceeds the size cap."""
    limit = max_mb * 1024 * 1024
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(413, f"File larger than {max_mb} MB")
    if not buf:
        raise HTTPException(400, "Empty file")
    return bytes(buf)


def open_image_safely(data: bytes) -> Image.Image:
    kind = sniff(data[:12])
    if kind not in ("png", "jpeg", "tiff"):
        raise HTTPException(415, "Unsupported image type: use JPEG, PNG or GeoTIFF")
    try:
        im = Image.open(io.BytesIO(data))
        im.verify()
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:  # noqa: BLE001 - any decoder failure is a bad upload
        raise HTTPException(400, f"Unreadable image: {type(e).__name__}") from e
    return im.convert("RGB")


def security_headers(path: str) -> dict[str, str]:
    csp = ("default-src 'self'; img-src 'self' data: blob: https://*.tile.openstreetmap.org https://tile.openstreetmap.org; "
           "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
           "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    return {
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
        "Permissions-Policy": "geolocation=(self), camera=(self), microphone=()",
        "Content-Security-Policy": csp,
        "Cache-Control": "no-store" if path.startswith("/api/") else "public, max-age=300",
    }


Planner = Depends(require_planner)
