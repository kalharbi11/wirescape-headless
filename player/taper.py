# SPDX-License-Identifier: GPL-3.0-only
"""Parameter taper: knob travel 0..1 <-> plain value (0025 §2.5 "Taper").

A line-for-line port of lab `apps/studio/src/modules/registry.ts` `normToValue`,
`valueToNorm` and `quantize` at lab commit 11a68c2 (LAB_PIN). JavaScript `Math.round`
rounds halves up, so `_js_round` does the same. Tested against values computed from the
catalogue at LAB_PIN (tests/test_taper.py).
"""
from __future__ import annotations

import math
from typing import Mapping, Any

Param = Mapping[str, Any]


def _clamp01(n: float) -> float:
    return 0.0 if n < 0 else 1.0 if n > 1 else n


def _js_round(x: float) -> float:
    return math.floor(x + 0.5)


def _is_log(p: Param) -> bool:
    return p.get("taper") == "log" and p["minimum"] > 0 and p["maximum"] > 0


def quantize(p: Param, v: float) -> float:
    lo, hi = p["minimum"], p["maximum"]
    x = min(hi, max(lo, v))
    step = p.get("step") or 0
    if step > 0:
        x = _js_round((x - lo) / step) * step + lo
    return min(hi, max(lo, x))


def norm_to_value(p: Param, n: float) -> float:
    t = _clamp01(n)
    lo, hi = p["minimum"], p["maximum"]
    if _is_log(p):
        v = lo * math.pow(hi / lo, t)
    else:
        v = lo + (hi - lo) * t
    return quantize(p, v)


def value_to_norm(p: Param, v: float) -> float:
    lo, hi = p["minimum"], p["maximum"]
    x = min(hi, max(lo, v))
    if _is_log(p):
        return _clamp01(math.log(x / lo) / math.log(hi / lo))
    span = hi - lo
    return 0.0 if span == 0 else _clamp01((x - lo) / span)


def display(p: Param, v: float) -> str:
    """A short human string: value at the parameter's decimals, plus its unit."""
    choices = p.get("choices")
    if choices:
        i = _js_round(v)
        for c in choices:
            if isinstance(c, dict) and c.get("value") == i:
                return str(c.get("label", i))
    d = int(p.get("decimals", 2))
    unit = p.get("unit") or ""
    return f"{v:.{d}f}{(' ' + unit) if unit else ''}"
