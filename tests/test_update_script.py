from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPDATE_SCRIPT = ROOT / "deploy" / "update.sh"


def run(
    cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None
) -> str:
    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def setup_git_identity(repo: Path) -> None:
    run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    run(["git", "config", "user.name", "Test User"], cwd=repo)


def make_remote_and_clone(tmp_path: Path) -> tuple[Path, Path, str]:
    remote_work = tmp_path / "remote-work"
    remote_bare = tmp_path / "remote.git"
    clone_repo = tmp_path / "deployed-repo"

    run(["git", "init", "-b", "main", str(remote_work)])
    setup_git_identity(remote_work)

    (remote_work / "requirements.txt").write_text("pytest==7.4.2\n", encoding="utf-8")
    run(["git", "add", "requirements.txt"], cwd=remote_work)
    run(["git", "commit", "-m", "initial"], cwd=remote_work)
    initial_commit = run(["git", "rev-parse", "HEAD"], cwd=remote_work)

    run(["git", "clone", "--bare", str(remote_work), str(remote_bare)])
    run(["git", "remote", "add", "origin", str(remote_bare)], cwd=remote_work)
    run(["git", "push", "-u", "origin", "main"], cwd=remote_work)
    run(["git", "clone", str(remote_bare), str(clone_repo)])

    return remote_work, clone_repo, initial_commit


def add_remote_commit(remote_work: Path, message: str, content: str) -> str:
    data_file = remote_work / "data.txt"
    data_file.write_text(content, encoding="utf-8")
    run(["git", "add", "data.txt"], cwd=remote_work)
    run(["git", "commit", "-m", message], cwd=remote_work)
    new_commit = run(["git", "rev-parse", "HEAD"], cwd=remote_work)
    run(["git", "push"], cwd=remote_work)
    return new_commit


def make_fake_bin(tmp_path: Path) -> tuple[Path, Path, Path]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()

    systemctl_log = tmp_path / "systemctl.log"
    pip_log = tmp_path / "pip.log"

    systemctl_script = """#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "$FAKE_SYSTEMCTL_LOG"

if [ "$1" = "restart" ]; then
  exit 0
fi

if [ "$1" = "is-active" ]; then
  count_file="$FAKE_SYSTEMCTL_COUNT_FILE"
  count=0
  if [ -f "$count_file" ]; then
    count="$(cat "$count_file")"
  fi
  count=$((count + 1))
  echo "$count" > "$count_file"

  case "${FAKE_SYSTEMCTL_PATTERN:-always-success}" in
    always-success)
      exit 0
      ;;
    fail-first-then-success)
      if [ "$count" -eq 1 ]; then
        exit 3
      fi
      exit 0
      ;;
    always-fail)
      exit 3
      ;;
  esac
fi

exit 0
"""

    pip_script = """#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "$FAKE_PIP_LOG"
exit 0
"""

    (fake_bin / "systemctl").write_text(systemctl_script, encoding="utf-8")
    (fake_bin / "pip").write_text(pip_script, encoding="utf-8")
    os.chmod(fake_bin / "systemctl", 0o755)
    os.chmod(fake_bin / "pip", 0o755)

    return fake_bin, systemctl_log, pip_log


def run_update_script(
    repo: Path,
    fake_bin: Path,
    systemctl_log: Path,
    pip_log: Path,
    systemctl_pattern: str = "always-success",
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "NEEDLEDROP_REPO_DIR": str(repo),
            "NEEDLEDROP_HEALTH_DELAY_S": "0",
            "NEEDLEDROP_PIP_BIN": str(fake_bin / "pip"),
            "FAKE_SYSTEMCTL_LOG": str(systemctl_log),
            "FAKE_SYSTEMCTL_COUNT_FILE": str(systemctl_log.with_suffix(".count")),
            "FAKE_SYSTEMCTL_PATTERN": systemctl_pattern,
            "FAKE_PIP_LOG": str(pip_log),
        }
    )
    return subprocess.run(
        [str(UPDATE_SCRIPT)],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_update_script_noop_when_no_new_commit(tmp_path: Path) -> None:
    _, clone_repo, initial_commit = make_remote_and_clone(tmp_path)
    fake_bin, systemctl_log, pip_log = make_fake_bin(tmp_path)

    result = run_update_script(clone_repo, fake_bin, systemctl_log, pip_log)

    assert result.returncode == 0
    assert "No update available." in result.stdout
    assert run(["git", "rev-parse", "HEAD"], cwd=clone_repo) == initial_commit
    assert not systemctl_log.exists()
    assert not pip_log.exists()


def test_update_script_applies_update_and_records_backup_ref(tmp_path: Path) -> None:
    remote_work, clone_repo, initial_commit = make_remote_and_clone(tmp_path)
    new_commit = add_remote_commit(remote_work, "update", "new-content")
    fake_bin, systemctl_log, pip_log = make_fake_bin(tmp_path)

    result = run_update_script(clone_repo, fake_bin, systemctl_log, pip_log)

    assert result.returncode == 0
    assert "Update applied successfully" in result.stdout
    assert run(["git", "rev-parse", "HEAD"], cwd=clone_repo) == new_commit
    assert (
        run(["git", "rev-parse", "refs/needle-drop-backup/latest"], cwd=clone_repo)
        == initial_commit
    )
    assert "restart needle-drop.service" in systemctl_log.read_text(encoding="utf-8")
    assert "is-active --quiet needle-drop.service" in systemctl_log.read_text(
        encoding="utf-8"
    )
    assert "install -r requirements.txt" in pip_log.read_text(encoding="utf-8")


def test_update_script_rolls_back_after_failed_health_check(tmp_path: Path) -> None:
    remote_work, clone_repo, initial_commit = make_remote_and_clone(tmp_path)
    add_remote_commit(remote_work, "bad-update", "breakage")
    fake_bin, systemctl_log, pip_log = make_fake_bin(tmp_path)

    result = run_update_script(
        clone_repo,
        fake_bin,
        systemctl_log,
        pip_log,
        systemctl_pattern="fail-first-then-success",
    )

    assert result.returncode == 0
    assert "Update failed; attempting rollback." in result.stdout
    assert "Rollback succeeded; service is healthy." in result.stdout
    assert run(["git", "rev-parse", "HEAD"], cwd=clone_repo) == initial_commit
    pip_commands = pip_log.read_text(encoding="utf-8")
    assert pip_commands.count("install -r requirements.txt") == 2
