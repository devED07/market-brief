"""Publishing for the hosted version on GitHub.

The dashboard lives on a branch called gh-pages, which GitHub Pages serves
at https://<your-username>.github.io/<repo>/. Every update replaces that
branch with one fresh commit, so the repo never grows.

The app's small memory files (which alerts were already sent, the cached
calendar and prices) travel along on a separate `state` branch, keeping
internal state off the public GitHub Pages root.
"""

import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .config import DATA_DIR
from .util import atomic_write_json, atomic_write_text

BRANCH = "gh-pages"
STATE_BRANCH = "state"
STATE_FILES = (
    "alert_state.json",
    "calendar_cache.json",
    "headlines_cache.json",
    "release_log.json",
    "actuals.json",
    "geo_cache.json",
    "geo_history.json",
    "snaps_cache.json",
    "score_history.json",
)
BOT_NAME = "market-brief-bot"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


def _remote() -> str:
    # For testing on a computer, point this at any git repo.
    override = os.environ.get("MB_PUBLISH_REMOTE")
    if override:
        return override
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        raise RuntimeError("Hosted mode needs GITHUB_REPOSITORY and GITHUB_TOKEN (set by the workflow).")
    host = os.environ.get("GITHUB_SERVER_URL", "https://github.com").split("://", 1)[-1].rstrip("/")
    return f"https://{host}/{repo}.git"


def _auth_b64() -> str:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return ""
    return base64.b64encode(f"x-access-token:{token}".encode("ascii")).decode("ascii")


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    if os.environ.get("MB_PUBLISH_REMOTE"):
        return env
    b64 = _auth_b64()
    if b64:
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
        env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: basic {b64}"
    return env


def _clean(text: str) -> str:
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        text = text.replace(token, "***")
    b64 = _auth_b64()
    if b64:
        text = text.replace(b64, "***")
    return text


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=cwd, env=_git_env(), capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(_clean(f"git {args[0]} failed: {r.stderr.strip() or r.stdout.strip()}"))
    return r


def restore_state() -> str:
    """Copies state files from the `state` branch (or legacy `gh-pages/state`) into data/."""
    tmp = Path(tempfile.mkdtemp(prefix="mb-state-"))
    remote = _remote()
    try:
        repo_dir = tmp / "repo"
        migrated = False
        r = _git("clone", "-q", "--depth=1", "--single-branch", "--branch", STATE_BRANCH,
                 remote, str(repo_dir), check=False)
        if r.returncode != 0:
            shutil.rmtree(repo_dir, ignore_errors=True)
            r = _git("clone", "-q", "--depth=1", "--single-branch", "--branch", BRANCH,
                     remote, str(repo_dir), check=False)
            if r.returncode != 0:
                return "No earlier update found. This looks like the first run."
            migrated = True

        src = (repo_dir / "state") if (repo_dir / "state").is_dir() else repo_dir
        found = []
        DATA_DIR.mkdir(exist_ok=True)
        if (repo_dir / "meta.json").exists():
            shutil.copy2(repo_dir / "meta.json", DATA_DIR / "last_meta.json")
        for name in STATE_FILES:
            candidate = src / name
            if not candidate.exists() and src is not repo_dir:
                candidate = repo_dir / name
            if candidate.exists():
                shutil.copy2(candidate, DATA_DIR / name)
                found.append(name)
        where = " (migrated from legacy gh-pages)" if migrated else ""
        return f"Picked up saved state{where} ({', '.join(found) or 'nothing saved yet'})."
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _push_branch(work: Path, branch: str, summary: str, label: str) -> None:
    remote = _remote()
    _git("init", "-q", cwd=work)
    _git("checkout", "-q", "-b", branch, cwd=work)
    _git("add", "-A", cwd=work)
    _git("-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}",
         "commit", "-q", "-m", summary, cwd=work)
    last_error = None
    for attempt in range(3):
        r = _git("push", "-q", "--force", remote, f"HEAD:{branch}", cwd=work, check=False)
        if r.returncode == 0:
            return
        last_error = _clean(r.stderr.strip() or r.stdout.strip())
        if attempt < 2:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Couldn't publish {label}: {last_error}")


def publish(html: str, generated_ms: int, summary: str) -> None:
    """Replaces gh-pages with the public dashboard and `state` with internal state."""
    site_work = Path(tempfile.mkdtemp(prefix="mb-site-"))
    state_work = Path(tempfile.mkdtemp(prefix="mb-state-pub-"))
    try:
        atomic_write_text(site_work / "index.html", html)
        atomic_write_json(site_work / "meta.json", {"generated": generated_ms})
        atomic_write_text(site_work / ".nojekyll", "")

        atomic_write_json(state_work / "meta.json", {"generated": generated_ms})
        for name in STATE_FILES:
            if (DATA_DIR / name).exists():
                shutil.copy2(DATA_DIR / name, state_work / name)

        _push_branch(site_work, BRANCH, summary, "the dashboard")
        _push_branch(state_work, STATE_BRANCH, summary, "saved state")
    finally:
        shutil.rmtree(site_work, ignore_errors=True)
        shutil.rmtree(state_work, ignore_errors=True)
