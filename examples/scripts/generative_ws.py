# SPDX-License-Identifier: GPL-3.0-only
"""Generative patch driver: Euclidean drums, a random-walk melody, a Markov chord pad
and two slow CVs, sent as OSC to a Wirescape OSC In module through the `ws` helper.

Addresses (the "Script (/ws/...)" preset, lab proposal 0022, OB-h5), unchanged from the
pre-helper version:
  /ws/pitch/<voice>  MIDI note number 0-127 (the row maps it to 1 V/oct, C4 = 0)
  /ws/gate/<voice>   1 / 0
  /ws/vel/<voice>    0-1
  /ws/trig/<n>       message alone fires a trigger (1 kick, 2 hat)
  /ws/cv/1 ... 4     0-1
Voice 1 is the melody, voices 2-4 the pad. `python -I generative_ws.py --print-config`
prints the declaration, including the OSC In rows to paste into the patch.

`ws.py` sits next to this file (it is MIT: copy it with your scripts).
"""
import math
import os
import random
import time
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ws  # noqa: E402

BPM, STEPS = 112, 16                     # 16th-note grid
SCALE = [0, 2, 3, 5, 7, 8, 10]           # natural minor
ROOT = 57                                # A3
MELODY, PAD = 1, (2, 3, 4)               # voice numbers

voices = ws.voice("Voice", voices=4, addresses={"pitch": "/ws/pitch/*", "gate": "/ws/gate/*", "vel": "/ws/vel/*"})
drums = ws.trig("Drums", address="/ws/trig/*", channels=2)
cvs = [ws.cv(f"CV {c}", 0, 1, address=f"/ws/cv/{c}") for c in (1, 2, 3, 4)]
density = ws.knob("Density", 0, 1, 0.85)


def euclid(hits: int, steps: int, rotate: int = 0) -> list[bool]:
    return [((i + rotate) * hits) % steps < hits for i in range(steps)]


KICK, HAT = euclid(5, STEPS), euclid(7, STEPS, rotate=2)
CHORDS = {0: [3, 5], 3: [5, 0], 5: [0, 3, 4], 4: [0]}  # scale degree -> next degrees


def note(degree: int, octave: int = 0) -> int:
    return ROOT + 12 * (octave + degree // len(SCALE)) + SCALE[degree % len(SCALE)]


def init() -> None:
    # Send every channel once, in index order, so poly channel numbers stay stable.
    for v in (MELODY, *PAD):
        voices.send(v, ROOT)
        voices.off(v)
    for c in cvs:
        c.send(0.5)


def run(bars: int | None = None) -> None:
    init()
    step_s = 60 / BPM / 4
    start = time.perf_counter()
    walk, chord_root, cv_walk, step = 7, 0, 0.5, 0
    while bars is None or step < bars * STEPS:
        s = step % STEPS
        if KICK[s]:
            drums.send(1)
        if HAT[s] and random.random() < float(density.value):
            drums.send(2)

        if s % 2 == 0:                                   # melody on 8ths
            voices.off(MELODY)
            if random.random() < 0.75:                   # 25 % rests
                walk = max(0, min(14, walk + random.choice([-2, -1, -1, 1, 1, 2])))
                voices.on(MELODY, note(walk), 0.9 if s % 8 == 0 else 0.6)

        if s == 0:                                       # new chord each bar (Markov)
            chord_root = random.choice(CHORDS[chord_root])
            for v, offset in zip(PAD, (0, 2, 4)):
                voices.on(v, note(chord_root + offset, -1), 0.5)
        # held pad gates are re-sent every 500 ms by the helper (the gate row times out at 2 s)

        cv_walk = max(0.0, min(1.0, cv_walk + random.uniform(-0.03, 0.03)))
        cvs[0].send(cv_walk)                                      # e.g. filter cutoff
        cvs[1].send(0.5 + 0.5 * math.sin(step * 2 * math.pi / 64))  # 4-bar sweep

        step += 1
        ws.wait_until(start + step * step_s)             # no drift


ws.start(name="generative_ws", port=9000)
if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass  # the helper sends 0 to every held gate on exit
