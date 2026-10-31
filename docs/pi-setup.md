# Pi setup and first-run checks

This is a practical runbook for installing `needle-drop` on a Raspberry Pi and verifying that startup and autodeploy are working.

## 1) One-time install

```bash
# Runtime user (recommended, even on a dedicated Pi)
sudo useradd -r -m -s /usr/sbin/nologin -G audio needledrop
echo 'needledrop ALL=(root) NOPASSWD: /usr/bin/systemctl restart needle-drop' \
  | sudo tee /etc/sudoers.d/needle-drop

# Code + config locations
sudo mkdir -p /opt/needle-drop /etc/needle-drop
sudo chown needledrop: /opt/needle-drop

# Clone repository
sudo -u needledrop git clone https://github.com/Oliver-Binns/needle-drop.git /opt/needle-drop

# Python environment
sudo -u needledrop python3 -m venv /opt/needle-drop/.venv
sudo -u needledrop /opt/needle-drop/.venv/bin/python -m pip install -U pip setuptools wheel
sudo -u needledrop /opt/needle-drop/.venv/bin/pip install -r /opt/needle-drop/requirements.txt

# Install systemd units
sudo cp /opt/needle-drop/deploy/*.service /opt/needle-drop/deploy/*.timer /etc/systemd/system/
sudo chmod +x /opt/needle-drop/deploy/update.sh
```

## 2) Service runtime path fix (`src/` layout)

`needle-drop` uses a `src/` layout, so systemd needs `PYTHONPATH` set:

```bash
sudo systemctl edit needle-drop
```

Add:

```ini
[Service]
Environment="PYTHONPATH=/opt/needle-drop/src"
```

Apply:

```bash
sudo systemctl daemon-reload
```

### Device config

Create `/etc/needle-drop/config.yaml` (readable by `needledrop`); `speaker_name` is required:

```yaml
speaker_name: "Living Room"   # exact, case-sensitive OwnTone output name
```

Also install `portaudio19-dev python3-dev` before `pip install -r requirements.txt` (builds pyaudio),
and make sure OwnTone watches the `owntone_pipe` path (default `/srv/music/vinyl.pipe`).

## 3) Enable and start

```bash
sudo systemctl enable --now needle-drop.service needle-drop-deploy.timer
sudo systemctl enable owntone
```

## 4) Verify service health

```bash
systemctl status needle-drop --no-pager
journalctl -u needle-drop -n 100 --no-pager
```

Expected: service stays up (no restart loop).

## 5) Verify autodeploy

```bash
systemctl status needle-drop-deploy.timer --no-pager
journalctl -u needle-drop-deploy -n 100 --no-pager
```

Expected: timer runs every 5 minutes and update checks log either:
- `No update available.`, or
- update apply/restart/health-check steps.

## 6) Common errors

### `No module named needledrop`

The service is missing `PYTHONPATH=/opt/needle-drop/src`. Re-check the systemd override and run:

```bash
sudo systemctl daemon-reload
sudo systemctl restart needle-drop
```

### `No module named needledrop.__main__`

The deployed revision is too old. Pull/update to a revision that includes `src/needledrop/__main__.py` (merged to `main`).

### `pip install` fails in venv

Try refreshing packaging tools first:

```bash
sudo -u needledrop /opt/needle-drop/.venv/bin/python -m pip install -U pip setuptools wheel
sudo -u needledrop /opt/needle-drop/.venv/bin/pip install -r /opt/needle-drop/requirements.txt
```

## 7) Deployment expectations

- Autodeploy tracks **`main` only**.
- A PR branch does not deploy until merged.
- Default check interval is 5 minutes (`needle-drop-deploy.timer`).
