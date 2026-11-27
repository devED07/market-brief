"""Shared utilities for Market Brief: time formatting, HTTP sessions, and atomic writes."""

import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

NEW_YORK = ZoneInfo("America/New_York")
HEADERS = {"User-Agent": "Mozilla/5.0 (personal market brief app)"}

_thread_local = threading.local()


def short_title(title: str) -> str:
    """Compact release title for charts and summaries."""
    return (
        title.replace("Non-Farm Employment Change", "NFP")
        .replace("Federal Funds Rate", "Fed decision")
        .replace(" m/m", "")
        .replace(" y/y", "")
        .replace(" q/q", "")
    )


def fmt_time(dt: datetime, tz, fmt: str = "%I:%M %p") -> str:
    """Format dt in tz, stripping leading zeros cleanly for 12-hour clocks and days."""
    s = dt.astimezone(tz).strftime(fmt)
    if "%I" in fmt or "%d" in fmt:
        s = s.replace(" 0", " ")
        if fmt.startswith("%I") or fmt.startswith("%d"):
            s = s.lstrip("0")
    return s


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write text to path via a temp file + os.replace so partial reads cannot occur."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as f:
            f.write(text)
            f.flush()
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, data) -> None:
    """Serialize data as JSON and write it atomically."""
    atomic_write_text(path, json.dumps(data))


def make_session(retries: int = 2, backoff: float = 0.8) -> requests.Session:
    """Create a requests.Session with connection pooling and transient-status retries."""
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def thread_session(retries: int = 2, backoff: float = 0.8) -> requests.Session:
    """Return a per-thread cached requests.Session."""
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = make_session(retries=retries, backoff=backoff)
        _thread_local.session = session
    return session
