"""Publishing for the hosted version on GitHub.

The dashboard lives on a branch called gh-pages, which GitHub Pages serves
at https://<your-username>.github.io/<repo>/. Every update replaces that
branch with one fresh commit, so the repo never grows.

The app's small memory files (which alerts were already sent, the cached
calendar) travel along in a state/ folder on the same branch, so the next
run carries on where the last one stopped.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import DATA_DIR

BRANCH = "gh-pages"
STATE_FILES = ("alert_state.json", "calendar_cache.json", "headlines_cache.json")
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
    host = os.environ.get("GITHUB_SERVER_URL", "https://github.com").split("://", 1)[-1]
    return f"https://x-access-token:{token}@{host}/{repo}.git"


def _clean(text: str) -> str:
    token = os.environ.get("GITHUB_TOKEN")
    return text.replace(token, "***") if token else text


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(_clean(f"git {args[0]} failed: {r.stderr.strip() or r.stdout.strip()}"))
    return r


def restore_state() -> str:
    """Copies state files from the last published update into data/."""
    tmp = Path(tempfile.mkdtemp(prefix="mb-state-"))
    try:
        r = _git("clone", "-q", "--depth=1", "--single-branch", "--branch", BRANCH,
                 _remote(), str(tmp / "repo"), check=False)
        if r.returncode != 0:
            return "No earlier update found. This looks like the first run."
        src = tmp / "repo" / "state"
        found = []
        DATA_DIR.mkdir(exist_ok=True)
        for name in STATE_FILES:
            if (src / name).exists():
                shutil.copy2(src / name, DATA_DIR / name)
                found.append(name)
        return f"Picked up saved state ({', '.join(found) or 'nothing saved yet'})."
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def publish(html: str, generated_ms: int, summary: str) -> None:
    """Replaces the gh-pages branch with the new dashboard and state."""
    work = Path(tempfile.mkdtemp(prefix="mb-site-"))
    try:
        (work / "index.html").write_text(html, encoding="utf-8")
        (work / "meta.json").write_text(json.dumps({"generated": generated_ms}), encoding="utf-8")
        (work / ".nojekyll").write_text("", encoding="utf-8")  # serve files as they are
        (work / "state").mkdir()
        for name in STATE_FILES:
            if (DATA_DIR / name).exists():
                shutil.copy2(DATA_DIR / name, work / "state" / name)

        _git("init", "-q", cwd=work)
        _git("checkout", "-q", "-b", BRANCH, cwd=work)
        _git("add", "-A", cwd=work)
        _git("-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}",
             "commit", "-q", "-m", summary, cwd=work)
        last_error = None
        for _ in range(3):
            r = _git("push", "-q", "--force", _remote(), f"HEAD:{BRANCH}", cwd=work, check=False)
            if r.returncode == 0:
                return
            last_error = _clean(r.stderr.strip())
        raise RuntimeError(f"Couldn't publish the dashboard: {last_error}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
