<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Design a Player UI

**Applies to:** headless Player API v1, H-6 and H-9. Record the exact headless commit and LAB_PIN in your project.
**You need:** Python 3.11+, this checkout, a modern browser; development dependencies only for the smoke test.
**Time:** about 15 minutes for the one-page example. No engine, MIDI or audio device needed.

## 1. Start the fake Player

From the repository root:

```sh
python -m player fake --bundle examples/bundle
```

**Check:** the terminal prints `http://127.0.0.1:8770/api/v1/state`. Open that URL: the document contains `api: "1.0"`, `setlist`, `current`, `engine`, `controls` and `pages`.

## 2. Make one page

The UI is a replaceable client, not the audio engine or a patch editor. Keep the service and UI separate. The full working example is [examples/ui-minimal/index.html](../examples/ui-minimal/index.html). It has no imports, no framework, no build and no reference-UI dependency.

Create your own HTML page using these pieces:

- A status element with `role="status"` and an error element with `role="alert"`.
- Three buttons with `data-command="prev"`, `"next"` and `"panic"`.
- One `EventSource("/api/v1/events")`. Subscribe to the named `state` event, parse its JSON, then find the entry whose `index` equals `current.index`. Use `textContent` for labels, never HTML from the patch. A new connection always starts with a full state. Subscribe to `status` to update engine health, accepting only matching revisions.
- On each button click, `fetch("/api/v1/command", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({type:button.dataset.command})})`. Parse the reply even on HTTP 200: `ok:false` is a refusal; display its `code` and `message`. Do not invent state changes; wait for the SSE state.
- On event-stream error, display disconnected and let EventSource reconnect. Never restart the engine just because the UI lost its connection.

Try the example with the Player's same-origin static server, without replacing its reference page:

```sh
cp -n examples/ui-minimal/index.html ui/my-minimal.html
```

Open `http://127.0.0.1:8770/ui/my-minimal.html`.

**Check:** the patch name appears; Next and Previous change it; Panic sends a command and leaves the Player running. Close and reopen the browser: current state remains intact.

## 3. Expand to controls

Read [API.md](API.md) for every command and [the schema](../api/player-api.v1.schema.json) for exact field shapes.

- Render pages in state order. Resolve each page's control IDs through `state.controls`. Disabled/unresolved controls remain visible with a reason.
- Use the API's `norm` (0–1) for continuous sliders, so the Player handles taper, quantization and ranges; use plain `value` for discrete choices. Send `{"type":"set","control":"tempo","norm":0.5}` only when that control exists. Use `params.list` and a structured `target` for parameters or ordinary modulation cables outside the configured pages.
- Apply `values` events only if their revision equals the current state revision; match by value key, not label. Use the event/reply value to update the control and avoid replacing a slider while the user is dragging it. Do not send commands in response to incoming values.
- Show script state and restart count. Unsupported commands return `unavailable` until their service implementation lands. Do not emulate audio or script control locally.
- Use device IDs as returned by the API, never hard-code device names. No UI network connection to the engine, device, script or OSC/MIDI socket. Do not write patches, scripts or player.json directly.

**Check:** select Clocked groove in the reference UI, then try the tempo control; the command reply and subsequent values event agree.

## 4. Make it touch-first

At 800 × 480, use a dark theme, readable type, at least 48 × 48 CSS-pixel targets and scrollable content. No hover-only actions. Keep Panic visible, show connection/engine status, and distinguish disabled controls and active setlist entries. Preserve keyboard focus and label inputs. Do not put the audio path or engine restart logic into the page.

**Check:** browser developer tools at 800 × 480; all actions can be reached without horizontal document scrolling, and touch targets meet the minimum size.

## 5. Run the smoke test

Stop the manually started fake (Ctrl-C); the test starts its own on an ephemeral localhost port.

```sh
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -m unittest discover -s tests/ui -p 'test_minimal.py' -v
```

On a fresh Linux CI image use `python -m playwright install --with-deps chromium`.

**Check:** the minimal UI test passes: state, next, previous, panic. It uses only the fake Player. Remove your temporary copy with `rm ui/my-minimal.html` when done.

## If it fails

| Symptom | Cause | Fix |
|---|---|---|
| 403 on command | wrong Origin | serve your page at the Player's /ui/ path, not file:// or another HTTP origin |
| 404 on page | file outside static root | copy the example into ui/ with a unique name |
| Connected but command refused | invalid field, target absent or feature unavailable | show the reply and consult API.md; never fake success |
| Stale controls | wrong revision or lost SSE | accept the next full state on reconnect |
| Browser missing in test | Playwright browser not installed | run the install command above |
| UI resource use too high | expensive rendering | update bound fields in place and follow [H-f2 protocol](guides/UI_COST.md) |

The real engine/device consent flags are the owner's decision, not part of a UI design.
