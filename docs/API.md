<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Player API v1

The contract between any UI and the Player service. Design: lab `proposals/0025` §2.5.
Machine-readable contract: [`api/player-api.v1.schema.json`](../api/player-api.v1.schema.json). Every
command, reply, state document and event that the fake and the real Player produce is validated against
it in CI (`tests/test_api.py`).

**Try it with no engine:** `python -m player fake`, then open `http://127.0.0.1:8770/api/v1/state`.

## Transport
- HTTP/1.1 on `127.0.0.1:8770` (`--api-port`/`--port`). **Loopback only** in v1; there is no LAN binding.
- `POST` needs `Content-Type: application/json`. A request whose `Origin` is not the server's own is
  refused with 403, so a web page from elsewhere cannot drive the Player.
- Every response closes the connection, except the event stream.

| Endpoint | Use | Schema |
|---|---|---|
| `GET /api/v1/state` | the whole state document | `$defs/state` |
| `POST /api/v1/command` | one command; HTTP 200 for both ok and refused, 400 only for malformed JSON | body `$defs/command`, answer `$defs/reply` |
| `GET /api/v1/events` | Server-Sent Events; add `?controller=1` for raw controller events | each frame `{event, data}` is `$defs/event` |
| `GET /ui/…` | the reference UI's static files | — |

## Versioning
`state.api` is `"1.<minor>"`. New fields, commands, events and codes bump the minor; clients ignore what
they do not know. A breaking change gets `/api/v2/`, served beside v1 for at least one Player release. A PR
that changes the API changes the schema, this page and the fake player together.

## Replies
```json
{"ok": true, "result": {"index": 2}}
{"ok": false, "code": "not-found", "message": "no setlist entry 99"}
{"ok": false, "code": "engine", "engineCode": "limit", "message": "Graph capacity exceeded"}
```
Codes: `invalid`, `not-found`, `busy`, `refused`, `unavailable` (the engine is restarting, or the
feature is not in this version), `engine` (the engine refused; `engineCode` is its code).

## Commands (v1.0)
| Type | Fields | Result / notes |
|---|---|---|
| `select` | `index` | switches through the arbiter: one `loadGraph` in flight, the latest request wins. A request while a switch is in flight returns `{"index", "queued": true}` |
| `next`, `prev` | — | count from the latest *requested* entry and wrap, so three quick presses move three entries |
| `set` | `control` **or** `target`; `value` (plain) **or** `norm` (0..1 through the parameter's taper) | `{"key","value","norm"}`. `target` reaches any parameter or ordinary cable of the loaded patch, in or out of `player.json`. An unresolved target is `not-found` |
| `reset` | optional `control` or `target` | back to the patch's value; with no field, every live value of the entry |
| `panic` | — | engine `panic` |
| `params.list` | — | `modules` (each parameter with catalogue metadata, `key`, `value`, `norm`, `mapped`) and modulation `cables` (`key`, `amount`, `mapping`) |
| `bundle.list`, `bundle.load`, `bundle.check` | `name` | `load` switches bundle, then selects entry 0; `check` returns the bundle-check findings |
| `audio.devices`, `audio.select`, `audio.buffer`, `audio.rate` | `deviceId`, `frames` (64–1024), `hz` (44100/48000/96000) | engine passthrough |
| `midi.devices`, `midi.enable` | `deviceId`, `on` | engine passthrough |
| `engine.restart` | — | counted as a restart, with no backoff |
| `script.start`, `script.stop`, `script.restart` | `file` | `unavailable` until H-11 |
| `config.get`, `config.put` | `json` | `get` returns `player.json`; `put` is `unavailable` until Stage 2 |
| `fake.inject` | `what`: `engineCrash`, `engineStall`, `scriptCrash`, `controller` (+ `event`) | **fake only**; the real Player answers `unavailable` |

Value keys (used in `values` events and `set` results): `param:<module>:<param>`,
`mod:<from module>:<from port>><to module>:<param>`, `script:<file>:<control>`.

## State document
Top-level keys: `api`, `rev` (increases on every structural change), `player`, `engine` (`state` is
`starting|running|restarting|stalled|stopped`; `restarts`; `lastExit`; `audio`; `capabilities`), `bundle`
(`name`, `title`, `check`), `setlist`, `current` (`index`, `switching`, `pending`, `error`), `pages`
(global pages first, then the loaded entry's), `controls` (by ID: `label`, `kind`, `target`, `min`, `max`,
`step`, `unit`, `taper`, `choices`, `value`, `norm`, `display`, `resolved`), `scripts`, `midi`, `osc`
(`controlPort`, `routes`) and `warnings`. The schema has every field.

## Events
| Event | Data | Rate |
|---|---|---|
| `state` | the whole state document | on connect (always first) and on every structural change |
| `values` | `{"rev", "values": {"<key>": {"value","norm"}}}` | coalesced, ≤ 30 Hz |
| `status` | `engine`, `scripts` and `osc` health | ≤ 4 Hz |
| `controller` | `{"events": [...]}`, raw observations in the lab controller-stream shape (0025 §3.2) | only with `?controller=1` |

A client that falls 256 events behind loses its stream and should reconnect. The first event of the new
stream is a full `state`.

## Examples
`api/examples/` holds one request and reply per command family, taken from the fake player.
