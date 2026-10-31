# needle-drop

## Project status

Scaffolding is in place: the update script and its tests, systemd service and
timer files, `config/default.yaml`, `requirements.txt`, `docs/design.md`, and
CI (ruff + pytest in `.github/workflows/validate-pr.yml`). The audio path is
implemented (`audio_source.py`, `audio_sink.py`, `pipeline.py`: sound card →
queue → OwnTone pipe, with an undelivered-bytes counter; tested in
`tests/test_pipeline.py`). `__main__.py` wires the config reader, audio path and
OwnTone speaker selection into an always-on streamer (no gate yet; it refuses to
start without `speaker_name`). The gate, status page and calibrate command are
**not yet implemented**. The gate design
below is the target; follow it when implementing the listener unless the user
directs otherwise. Keep this section current as features land.

## What it does

**needle-drop** is a Python program for a Raspberry Pi that listens to a
record player (via a HiFiBerry DAC+ ADC) and streams the audio to an AirPlay 2
speaker only while a record is actually playing — untouched, with no noise
reduction. It hands audio to **OwnTone** (a separate AirPlay server) through a
named pipe; OwnTone does the actual AirPlay streaming.

```
Record player → cable → HiFiBerry → needle-drop → OwnTone → HomePod
```

## Repository layout

```
src/needledrop/        the listener program (always-on streaming; gate not yet implemented)
tests/                  automatic checks
config/default.yaml     standard settings (committed, sensible defaults)
requirements.txt
deploy/                 update script and systemd service/timer files
docs/design.md          full technical design
.github/workflows/      CI checks
```

## Core architecture: the gate

The central concept is a **gate** state machine that decides when audio is
forwarded to OwnTone: `Idle → Arming → Streaming → Cooling down → Idle`.

- It measures incoming audio level (optionally a filtered copy emphasising
  high "scratchy" frequencies where crackle lives, distinct from mains hum)
  to decide when a record is really playing, but always forwards the
  **original, unfiltered** audio to the speaker — never the filtered copy.
- Key tunables (in `config/default.yaml`, overridden on-device): `start_delay_s`,
  `stop_delay_s`, `preroll_s`, `fade_out_s`, start/stop levels. A
  `needle-drop calibrate` command guides the user through sample recordings
  and suggests values.
- **Invariant to preserve:** `preroll_s` must never be less than
  `start_delay_s + 0.5`; the program should refuse to start if this is
  violated, since pre-roll exists specifically to cover the start delay so no
  audio is lost.
- No audio is ever dropped, skipped, or sped up to "catch up" — delay is
  acceptable, loss is not. Audio is queued briefly if OwnTone is slow rather
  than dropped, with an "undelivered audio" counter exposed on the status
  page that should always read zero.

## Configuration layering

Two layers, not to be conflated:
- `config/default.yaml` — committed, sensible defaults.
- `/etc/needle-drop/config.yaml` — device-only (lives only on the Pi),
  overrides defaults, holds calibrated levels and speaker name. Never
  touched by updates. Missing keys fall back to the default file.

**Never commit calibrated/device-specific settings or secrets** — this is a
public repository.

## Deployment model

The Pi pulls updates itself (pull-based, nothing pushed to it):
- A systemd timer runs an update script every 5 minutes; it checks GitHub for
  changes to `main`.
- It only pulls/restarts when the gate is **Idle** (never interrupts an
  in-progress or cooling-down record).
- After restarting, it health-checks after ~8 seconds and **rolls back** to
  the previous version automatically if unhealthy.
- Everything (listener, OwnTone, update timer) is enabled at boot and must
  tolerate dependencies (sound card, OwnTone, speaker) not being ready yet by
  waiting/retrying rather than failing.

## Build, test, and lint

- Dependencies: `pip install -r requirements.txt` (pinned versions). Dependabot
  (`.github/dependabot.yml`) opens weekly grouped PRs for pip and GitHub Actions.
- Style checks: **ruff** (`ruff check .` and `ruff format --check .`; no ruff config file, so defaults apply)
- Tests: **pytest** (run a single test with `pytest tests/path/to/test_file.py::test_name`)
- CI runs on Python **3.13** (`.github/workflows/validate-pr.yml`); dependency
  pins must install and pass on 3.13.
- Every change goes through a pull request; ruff and pytest must pass before
  merging to `main`. Anything merged to `main` auto-deploys to the Pi via the
  update timer described above.

## Pull Requests

When creating a PR that resolves a GitHub issue:

- **Always include "Closes: #X"** in the commit message or PR description (where X is the issue number)
- This automatically closes the issue when the PR is merged
- See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full PR submission guide
