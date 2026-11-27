import json
import subprocess
from pathlib import Path

from brief import publish as PUB


def _git_cmd(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return r.stdout.strip()


def test_publish_separates_branches_and_migrates_legacy(tmp_path, monkeypatch):
    remote_dir = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote_dir)], check=True, capture_output=True)

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(PUB, "DATA_DIR", data_dir)
    monkeypatch.setenv("MB_PUBLISH_REMOTE", str(remote_dir))

    # 1. Seed legacy gh-pages with state/alert_state.json and meta.json (no `state` branch yet)
    seed = tmp_path / "seed"
    seed.mkdir()
    _git_cmd(seed, "init")
    _git_cmd(seed, "checkout", "-b", "gh-pages")
    (seed / "index.html").write_text("old", encoding="utf-8")
    (seed / "meta.json").write_text(json.dumps({"generated": 1000}), encoding="utf-8")
    (seed / "state").mkdir()
    (seed / "state" / "alert_state.json").write_text('{"sent":["x"]}', encoding="utf-8")
    _git_cmd(seed, "add", "-A")
    _git_cmd(seed, "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-m", "legacy")
    _git_cmd(seed, "push", str(remote_dir), "HEAD:gh-pages")

    # 2. restore_state() detects legacy gh-pages and restores into data_dir
    msg = PUB.restore_state()
    assert "migrated" in msg
    assert (data_dir / "alert_state.json").read_text(encoding="utf-8") == '{"sent":["x"]}'
    assert json.loads((data_dir / "last_meta.json").read_text(encoding="utf-8"))["generated"] == 1000

    # 3. publish() pushes index.html ONLY (no state/) to gh-pages, and state files to `state`
    (data_dir / "score_history.json").write_text('[{"t":2000,"gold":1.0}]', encoding="utf-8")
    PUB.publish("<html>new</html>", 2000, "Update test")

    gh_files = _git_cmd(remote_dir, "ls-tree", "-r", "--name-only", "gh-pages").splitlines()
    assert sorted(gh_files) == [".nojekyll", "index.html", "meta.json"]

    state_files = _git_cmd(remote_dir, "ls-tree", "-r", "--name-only", "state").splitlines()
    assert "alert_state.json" in state_files
    assert "score_history.json" in state_files
    assert "meta.json" in state_files

    # 4. Subsequent restore_state() reads directly from `state` branch
    (data_dir / "alert_state.json").unlink()
    msg2 = PUB.restore_state()
    assert "migrated" not in msg2
    assert (data_dir / "alert_state.json").read_text(encoding="utf-8") == '{"sent":["x"]}'
