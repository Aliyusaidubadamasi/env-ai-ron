"""File-backed store for analyses and community observations.

MVP choice: plain files so the prototype runs with zero infrastructure. The same layout maps
directly onto PostgreSQL/PostGIS tables (see docs/ARCHITECTURE.md) and S3-style object storage.
Analysis ids are random 128-bit hex strings and are validated before touching the filesystem,
so a request can never address a path outside the store.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

from . import config

_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SITE_RE = re.compile(r"^S\d{3,5}$")
_lock = threading.Lock()


def new_id() -> str:
    return uuid.uuid4().hex


def valid_id(x: str) -> bool:
    return bool(_ID_RE.match(x or ""))


def valid_site(x: str) -> bool:
    return bool(_SITE_RE.match(x or ""))


def analysis_dir(aid: str, create: bool = False) -> Path:
    if not valid_id(aid):
        raise KeyError("bad analysis id")
    d = config.STORE_DIR / "analyses" / aid
    if create:
        (d / "overlays").mkdir(parents=True, exist_ok=True)
        (d / "observations").mkdir(parents=True, exist_ok=True)
    elif not d.exists():
        raise KeyError("analysis not found")
    return d


def save_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":")))
    tmp.replace(path)


def load_json(path: Path):
    return json.loads(path.read_text())


def get_meta(aid: str) -> dict:
    return load_json(analysis_dir(aid) / "meta.json")


def set_meta(aid: str, **updates) -> dict:
    with _lock:
        d = analysis_dir(aid)
        meta = load_json(d / "meta.json")
        meta.update(updates)
        save_json(d / "meta.json", meta)
        return meta


def list_analyses() -> list[dict]:
    root = config.STORE_DIR / "analyses"
    out = []
    if root.exists():
        for d in root.iterdir():
            if valid_id(d.name) and (d / "meta.json").exists():
                out.append(load_json(d / "meta.json"))
    return sorted(out, key=lambda m: -m.get("created", 0))


def append_observation(aid: str, site_id: str, record: dict) -> None:
    with _lock:
        path = analysis_dir(aid) / "observations.json"
        data = load_json(path) if path.exists() else {}
        data.setdefault(site_id, []).append(record)
        save_json(path, data)


def load_observations(aid: str, site_id: str | None = None):
    path = analysis_dir(aid) / "observations.json"
    data = load_json(path) if path.exists() else {}
    return data.get(site_id, []) if site_id else data


def now() -> float:
    return time.time()
