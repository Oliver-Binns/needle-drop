# needle-drop

## Project status

This repository currently contains only `README.md` and `LICENSE` — no source
code, tests, or CI configuration exist yet. The structure, commands, and
conventions below are the **planned** design as described in the README.
When implementing code, follow this plan unless the user directs otherwise,
and update this file once real tooling (ruff config, pytest, workflows) lands.

## What it does

**needle-drop** is a Python program for a Raspberry Pi that listens to a
record player (via a HiFiBerry DAC+ ADC) and streams the audio to an AirPlay 2
speaker only while a record is actually playing — untouched, with no noise
reduction. It hands audio to **OwnTone** (a separate AirPlay server) through a
named pipe; OwnTone does the actual AirPlay streaming.

```
Record player → cable → HiFiBerry → needle-drop → OwnTone → HomePod
```

## Planned repository layout

```
src/needledrop/        the listener program
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

## Build, test, and lint (planned)

- Style checks: **ruff**
- Tests: **pytest** (run a single test with `pytest tests/path/to/test_file.py::test_name`)
- Every change goes through a pull request; ruff and pytest must pass before
  merging to `main`. Anything merged to `main` auto-deploys to the Pi via the
  update timer described above.
