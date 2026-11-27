<!-- SPDX-License-Identifier: GPL-3.0-only -->
# Bundles and `player.json` v1

Design: lab `proposals/0025` §2.7 and `proposals/0024` §6. Example: [`examples/bundle/`](../examples/bundle/).

## A bundle
```
my-set/
  player.json      optional; without it the Player plays patches/ in name order
  patches/*.json   Studio patches, unchanged (the Player never writes them)
  scripts/*.py     scripts the setlist runs (trusted code)
  presets/         snapshots the Player saves
```
Check it with `python -m player check my-set [--lab LABDIR] [--scripts] [--json]`. The command exits
non-zero only when there is an error. `--scripts` runs each entry script with `--print-config` to
check its OSC rows. Scripts are trusted code (0025 §4.5).

## Top level
| Key | Type | Notes |
|---|---|---|
| `format`, `version` | `"wirescape.player"`, `1` | required |
| `title` | string | shown in the UI |
| `setlist` | entries (below) | required |
| `controls`, `pages` | global controls and pages | global controls may use only `macro` and `script` targets |
| `hardware` | bindings (below) | MIDI and OSC sources, read through the engine |
| `programChange` | `{"enabled", "device" (glob, default "*"), "channel" (1–16 or "any"), "debounceMs" (0–1000, default 150)}` | |
| `osc` | `{"controlPort": 0 or 1024–65535}` | the engine's control OSC port (lab P1-e2) |

Unknown keys are warnings, not errors, so a newer file still plays on an older Player.

## Setlist entry
`{"patch", "title", "program" (0–127), "recall" ("last" default, or "patch"), "controls", "pages", "scripts"}`.
`scripts` is a list of `{"file": "scripts/x.py", "port": 9000}`. `recall: "last"` keeps live values across
switches and reboots; `"patch"` clears them on every load of the entry.

**Program Change:** if any entry has `program`, PC *n* selects that entry. Otherwise PC *n* selects index
*n*. A PC with no entry is ignored and counted in the state's `warnings`.

## Controls and targets
A control is `{"id": "[a-z0-9_-]{1,32}", "label"?, "target"}`. IDs are unique across the global list and
each entry. The target is exactly one of:
| Form | Shape | Moves | Where |
|---|---|---|---|
| `macro` | `{"page": 1.., "knob": 1..8}`: the *page*-th `essentials.macro` module in the patch, parameter `knob<k>` | `setParam` | global or entry |
| `param` | `{"module": <patch node id>, "param": "<id>"}`: any parameter, setParam-only ones included | `setParam` | entry only |
| `modAmount` | `{"from": {"module","port"}, "to": {"module","param"}}`: one ordinary modulation cable | `setModAmount`, amount −1..1 | entry only |
| `script` | `{"file": "scripts/x.py", "control": "<declared id>"}` | sent to the script | global or entry |

A **mapping cable** is a modulation cable whose source module is `essentials.macro`, `midi.cc_to_cv` or
`osc.in`. It belongs to Studio, so a `modAmount` target on one is an error. The Player never edits
structure. It never creates cables and never changes ranges.

**Labels:** `label` if set, else the macro's label, else `"<module name> <id> · <parameter name>"`.

## Hardware map
`{"source": …, "control": "<id>"}` or `{"source": …, "action": "next"|"prev"|"panic"|{"select": n}}`, plus
`"takeover": "jump"` (default) or `"pickup"` (the knob is ignored until it crosses the current value).
- **MIDI source:** `{"midi": {"device": "*", "channel": 1–16|"any", "cc": 0–127}}` or with `"note"` instead
  of `cc`. CC maps to `norm = value/127`. A button fires on CC ≥ 64 after < 64, or on note-on.
- **OSC source:** `{"osc": {"address": "/ws/knob/1", "arg": 0, "min": 0, "max": 1}}`. It arrives through the
  engine's control port.

The Player opens no MIDI port and no socket. The engine reports controllers (lab P1-e, task H-7).
**Latency:** an in-patch mapping (Studio map mode) runs inside the engine and is the low-latency path.
Use `player.json` for patch-independent controls, setParam-only targets, cable amounts and script
controls (0025 §2.8).

## Check rows
| Level | Code | When |
|---|---|---|
| error | `schema` | structure, types, ranges, unknown control IDs, a global patch-specific target, the same hardware source bound twice |
| error | `missing-patch`, `bad-patch` | a setlist patch is missing or not a native patch |
| error | `missing-script` | an entry script or a script target's file is missing |
| error | `missing-target` | a `param` or `modAmount` target is not in its entry's patch |
| error | `mapping-cable` | a `modAmount` target is a mapping cable |
| error | `duplicate-program` | two entries share `program` |
| error | `control-port-clash` | a patch OSC In listens on `osc.controlPort` |
| warning | `unknown-key` | a key this Player does not know (ignored) |
| warning | `macro-unresolved` | a macro address resolves in no patch of the bundle |
| warning | `mapping-owned` | a `param` binding on a parameter an in-patch mapping drives |
| warning | `cc-also-mapped` | a hardware CC that a patch's CC to CV also maps |
| warning | `script-control-unmapped` | a declared text, notes, label or unbounded number has no v1 mapping (with `--scripts`; once per script/control) |
| warning | `script-row-missing` | a script output with no enabled OSC In row in an entry that runs it (with `--scripts`) |
| warning | `no-catalogue` | no catalogue was available, so parameter IDs were not checked |
| info | `in-patch-faster` | a hardware CC bound to a modulatable `param`: an in-patch mapping has lower latency |
| info | `lab-check-unavailable` | `--lab` was given but that lab has no `tools/patch_library.py` |

Parameter IDs are checked against the catalogue snapshot at `LAB_PIN` (`tests/data/catalogue.json`, or
`--catalogue FILE`). With `--lab DIR`, the lab's own patch check also runs on `patches/` once lab OB-h6
provides it.
