<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Install the Player on Raspberry Pi OS

**Applies to:** Headless H-8 (Player v1); use the engine built from this checkout's `LAB_PIN`.  
**You need:** Raspberry Pi OS Bookworm 64-bit with Python 3.11+, a local graphical session for the optional kiosk, the build dependencies below, and a trusted bundle.  
**Time:** About 20 minutes after the engine is built.

The Player service and kiosk run separately. The Player API is localhost only; the supplied unit is device-off. The owner explicitly enables hardware only after the null-audio check. No pip install is required on the target.

## 1. Prepare the files

From the headless checkout on the target, install the lab's headless build dependencies (owner only):

```sh
sudo apt update
sudo apt install -y git build-essential pkg-config python3 python3-venv libasound2-dev libportaudio2 libasound2-plugins
python3 -m venv .tools/build-tools
. .tools/build-tools/bin/activate
python -m pip install cmake==4.2.3 ninja==1.13.0
python tools/build_engine.py --check
python tools/build_engine.py build ./engine-work
```

**Check:** the report lists no missing items; the build prints the full pin, compiler and SHA-256 and stages `./wirescape-engine`. Use a new empty work directory on retries. For realtime audio, follow the lab INSTALL.md Raspberry Pi limits instructions for the service account, as applicable.

Install the staged files:

```sh
python3 --version
python3 tools/labpin.py show
sudo install -d -m 0755 /opt/wirescape-headless/bin
sudo cp -a player scripting ui /opt/wirescape-headless/
sudo install -m 0755 ./wirescape-engine /opt/wirescape-headless/bin/
sudo install -d -m 0755 /opt/wirescape-headless/tests
sudo cp -a tests/data /opt/wirescape-headless/tests/
```

**Check:** Python is 3.11 or later; `test -x /opt/wirescape-headless/bin/wirescape-engine` exits 0. Do not substitute an unrelated binary.

## 2. Install and start the Player

```sh
getent passwd wirescape-player || sudo useradd --system --user-group --no-create-home --shell /usr/sbin/nologin wirescape-player
sudo install -m 0644 systemd/wirescape-player.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wirescape-player.service
systemctl status wirescape-player.service --no-pager
curl -fsS http://127.0.0.1:8770/api/v1/state
```

**Check:** the service is active and the state JSON has an engine state and an empty bundle warning if no bundle is installed. READY means the API listens, not that the engine has loaded a graph.

## 3. Install a trusted bundle

From the headless checkout, stage the example in a readable location:

```sh
sudo cp -a examples/bundle /opt/wirescape-headless/example-bundle
cd /opt/wirescape-headless
sudo -u wirescape-player python3 -m player check example-bundle
sudo -u wirescape-player python3 -m player install example-bundle --state /var/lib/wirescape-player
sudo systemctl restart wirescape-player.service
curl -fsS http://127.0.0.1:8770/api/v1/state
```

**Check:** install reports success, the setlist is present, and current.index is 0 for a fresh install. Warnings need not block installation; errors do. Never run untrusted script files. Reinstall through the install command, not by editing the installed patch in place.

## 4. Optional local kiosk

In the local graphical desktop session, as the desktop user (not root):

```sh
sudo apt install chromium
mkdir -p ~/.config/systemd/user
```

From the checkout:

```sh
install -m 0644 systemd/wirescape-ui.service ~/.config/systemd/user/
systemctl --user import-environment WAYLAND_DISPLAY
systemctl --user daemon-reload
systemctl --user enable --now wirescape-ui.service
systemctl --user status wirescape-ui.service --no-pager
```

**Check:** Chromium shows the Player UI full screen; the Player service remains independent. On a desktop that uses X11, import DISPLAY and XAUTHORITY instead of WAYLAND_DISPLAY. On distributions that do not activate graphical-session.target, arrange for the desktop session to start the user unit, not a system service running Chromium as root.

## 5. Owner-only hardware consent

Only the owner performs this step after testing device-off. Use `sudo systemctl edit wirescape-player.service` and replace ExecStart with the exact needed flags, for example audio only:

```ini
[Service]
ExecStart=
ExecStart=/usr/bin/python3 -m player run --state /var/lib/wirescape-player --engine /opt/wirescape-headless/bin/wirescape-engine --engine-arg=--confirm-audio
```

Grant the dedicated service account access to the intended devices according to the OS permissions. Add `--engine-arg=--confirm-midi` or `--engine-arg=--confirm-lan` only if needed. LAN consent is for the engine OSC routes, not remote access to the Player API.

```sh
sudo systemctl daemon-reload
sudo systemctl restart wirescape-player.service
journalctl -u wirescape-player.service -n 50 --no-pager
```

**Check:** the API reports the actual device state. To go back to device-off, remove the owner override and restart. No agent or CI run grants consent. Continue with [HARDWARE_SMOKE.md](HARDWARE_SMOKE.md) for the first owner run.

## 6. Recovery

```sh
systemctl show wirescape-player.service -p WatchdogUSec -p NRestarts
journalctl -u wirescape-player.service -n 100 --no-pager
systemctl --user restart wirescape-ui.service
curl -fsS http://127.0.0.1:8770/api/v1/state
```

**Check:** WatchdogUSec is 10s. Restarting the kiosk does not restart the engine. SIGTERM saves state; the Player restores the last bundle/entry/values on boot, or uses its good copy if the live state is damaged. The PG8 hardware restart and long soak are owner runs, not claimed by this guide.

## If it fails

| Symptom | Cause | Fix |
|---|---|---|
| Service fails at start | Missing binary, wrong architecture or Python | Check pin, executable and journal; rebuild at the pin. |
| API is up but engine restarts | Engine failure | Inspect journal and engine lastExit; keep null audio while diagnosing. |
| Bundle refused | Check errors | Run check on source, fix it, then reinstall. |
| Browser not visible | Graphical session environment missing | Import the correct display environment and start the user unit inside the desktop. |
| Audio unavailable | Null audio default or device permissions | Owner verifies permissions and passes explicit consent only when ready. |
| Watchdog restarts Player | Event loop stalled | Inspect journal; do not raise the watchdog timeout to hide the fault. |
