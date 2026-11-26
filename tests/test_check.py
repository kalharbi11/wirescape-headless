# SPDX-License-Identifier: GPL-3.0-only
"""H-2: player.json v1 and every bundle-check row of lab proposals/0025 §2.7."""
import io
import json
import contextlib
import unittest

from player import bundle as B
from player.catalogue import Catalogue
from player.check import _all_controls, check, main as check_main, ERROR, WARNING, INFO
from tests.helpers import TempBundle, mapped_patch, player

CAT = Catalogue.load()
MAPPED = "patches/mapped.json"


def run(doc, extra=None, declarations=None):
    tb = TempBundle(doc, extra_patches=extra)
    try:
        b = B.load(tb.root)
        return check(b, CAT, declarations), b
    finally:
        tb.cleanup()


def codes(findings, level=None):
    return [f.code for f in findings if level is None or f.level == level]


def entry(patch, **kw):
    return dict(patch=patch, **kw)


class ExampleBundle(unittest.TestCase):
    def test_example_bundle_has_no_errors(self):
        tb = TempBundle()
        self.addCleanup(tb.cleanup)
        b = B.load(tb.root)
        f = check(b, CAT)
        self.assertEqual(codes(f, ERROR), [])
        forms = {B.target_form(c["target"]) for _, c in _all_controls(b)}
        self.assertEqual(forms, {"macro", "param", "modAmount", "script"})

    def test_cli_exit_codes(self):
        tb = TempBundle()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(check_main([str(tb.root)]), 0)
            (tb.root / "player.json").write_text(json.dumps(player([entry("patches/nope.json")])))
            self.assertEqual(check_main([str(tb.root)]), 1)
            (tb.root / "player.json").write_text("{not json")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(check_main([str(tb.root)]), 1)
        tb.cleanup()

    def test_no_player_json_plays_patches_in_name_order(self):
        tb = TempBundle(keep_player_json=False)
        b = B.load(tb.root)
        names = [e.patch for e in b.entries]
        self.assertEqual(names, sorted(names))
        self.assertEqual(len(names), 6)
        self.assertEqual(codes(check(b, CAT), ERROR), [])
        tb.cleanup()


class Errors(unittest.TestCase):
    def test_schema_violation(self):
        f, _ = run({"format": "wirescape.player", "version": 2, "setlist": "x"})
        self.assertIn("schema", codes(f, ERROR))

    def test_bad_control_id_and_bad_target(self):
        f, _ = run(player([entry("patches/basics-01-first-tone.json",
                                 controls=[{"id": "Bad Id", "target": {"param": {"module": 2, "param": "frequency"}}},
                                           {"id": "ok", "target": {"param": {"module": 2}}}])]))
        self.assertEqual(codes(f, ERROR).count("schema"), 2)

    def test_missing_patch(self):
        f, _ = run(player([entry("patches/nope.json")]))
        self.assertIn("missing-patch", codes(f, ERROR))

    def test_missing_script(self):
        f, _ = run(player([entry("patches/basics-01-first-tone.json", scripts=[{"file": "scripts/nope.py"}])]))
        self.assertIn("missing-script", codes(f, ERROR))
        f, _ = run(player(controls=[{"id": "s", "target": {"script": {"file": "scripts/nope.py", "control": "x"}}}]))
        self.assertIn("missing-script", codes(f, ERROR))

    def test_script_outside_scripts_folder(self):
        f, _ = run(player([entry("patches/basics-01-first-tone.json", scripts=[{"file": "patches/x.py"}])]))
        self.assertIn("schema", codes(f, ERROR))

    def test_missing_param_target(self):
        for target in ({"param": {"module": 99, "param": "frequency"}},
                       {"param": {"module": 2, "param": "no_such"}}):
            f, _ = run(player([entry("patches/basics-01-first-tone.json", controls=[{"id": "x", "target": target}])]))
            self.assertIn("missing-target", codes(f, ERROR), target)

    def test_missing_mod_amount_target(self):
        t = {"modAmount": {"from": {"module": 9, "port": "control"}, "to": {"module": 2, "param": "cutoff"}}}
        f, _ = run(player([entry("patches/basics-01-first-tone.json", controls=[{"id": "x", "target": t}])]))
        self.assertIn("missing-target", codes(f, ERROR))

    def test_mod_amount_on_mapping_cable_is_error(self):
        t = {"modAmount": {"from": {"module": 1, "port": "knob1"}, "to": {"module": 4, "param": "cutoff"}}}
        f, _ = run(player([entry(MAPPED, controls=[{"id": "x", "target": t}])]), {"mapped.json": mapped_patch()})
        self.assertIn("mapping-cable", codes(f, ERROR))
        ordinary = {"modAmount": {"from": {"module": 5, "port": "control"}, "to": {"module": 4, "param": "cutoff"}}}
        f, _ = run(player([entry(MAPPED, controls=[{"id": "x", "target": ordinary}])]), {"mapped.json": mapped_patch()})
        self.assertEqual(codes(f, ERROR), [])

    def test_global_control_patch_specific(self):
        f, _ = run(player(controls=[{"id": "x", "target": {"param": {"module": 2, "param": "frequency"}}}]))
        self.assertIn("schema", codes(f, ERROR))
        self.assertTrue(any("patch-specific" in x.message for x in f))

    def test_duplicate_program(self):
        f, _ = run(player([entry("patches/basics-01-first-tone.json", program=3),
                           entry("patches/basics-05-random-melody.json", program=3)]))
        self.assertIn("duplicate-program", codes(f, ERROR))

    def test_same_hardware_source_twice(self):
        src = {"midi": {"device": "*", "channel": 1, "cc": 74}}
        f, _ = run(player(hardware=[{"source": src, "action": "next"}, {"source": src, "action": "prev"}]))
        self.assertIn("schema", codes(f, ERROR))
        self.assertTrue(any("already bound" in x.message for x in f))

    def test_patch_osc_in_on_control_port(self):
        f, _ = run(player([entry(MAPPED)], osc={"controlPort": 9100}), {"mapped.json": mapped_patch()})
        self.assertIn("control-port-clash", codes(f, ERROR))
        f, _ = run(player([entry(MAPPED)], osc={"controlPort": 9200}), {"mapped.json": mapped_patch()})
        self.assertNotIn("control-port-clash", codes(f))


class Warnings(unittest.TestCase):
    def test_macro_resolves_in_no_patch(self):
        f, _ = run(player(controls=[{"id": "m", "target": {"macro": {"page": 1, "knob": 1}}}]))
        self.assertIn("macro-unresolved", codes(f, WARNING))
        f, _ = run(player([entry(MAPPED)], controls=[{"id": "m", "target": {"macro": {"page": 1, "knob": 1}}}]),
                   {"mapped.json": mapped_patch()})
        self.assertNotIn("macro-unresolved", codes(f))

    def test_param_binding_on_mapping_owned_param(self):
        f, _ = run(player([entry(MAPPED, controls=[{"id": "r", "target": {"param": {"module": 4, "param": "resonance"}}}])]),
                   {"mapped.json": mapped_patch()})
        self.assertIn("mapping-owned", codes(f, WARNING))

    def test_cc_also_mapped_in_patch(self):
        hw = [{"source": {"midi": {"device": "*", "channel": 1, "cc": 20}}, "action": "next"}]
        f, _ = run(player([entry(MAPPED)], hardware=hw), {"mapped.json": mapped_patch()})
        self.assertIn("cc-also-mapped", codes(f, WARNING))
        hw = [{"source": {"midi": {"device": "*", "channel": 2, "cc": 20}}, "action": "next"}]
        f, _ = run(player([entry(MAPPED)], hardware=hw), {"mapped.json": mapped_patch()})
        self.assertNotIn("cc-also-mapped", codes(f))

    def test_script_output_without_osc_in_row(self):
        decl = {"format": "wirescape.script", "version": 1,
                "outputs": [{"name": "Kick", "address": "/ws/kick", "kind": "trigger"},
                            {"name": "Snare", "address": "/ws/snare", "kind": "trigger"}]}
        doc = player([entry(MAPPED, scripts=[{"file": "scripts/generative_ws.py"}])])
        f, _ = run(doc, {"mapped.json": mapped_patch()}, {"scripts/generative_ws.py": decl})
        missing = [x for x in f if x.code == "script-row-missing"]
        self.assertEqual(len(missing), 1)
        self.assertIn("/ws/snare", missing[0].message)

    def test_unknown_key_is_a_warning_not_an_error(self):
        f, _ = run(player(future={"x": 1}))
        self.assertIn("unknown-key", codes(f, WARNING))
        self.assertEqual(codes(f, ERROR), [])


class Info(unittest.TestCase):
    def test_hardware_cc_on_modulatable_param(self):
        doc = player([entry("patches/basics-08-clocked-groove.json",
                            controls=[{"id": "p", "target": {"param": {"module": 4, "param": "frequency"}}}])],
                     hardware=[{"source": {"midi": {"device": "*", "channel": 1, "cc": 74}}, "control": "p"}])
        f, _ = run(doc)
        self.assertIn("in-patch-faster", codes(f, INFO))


class Resolution(unittest.TestCase):
    def test_macro_page_is_the_nth_macro_module(self):
        p = mapped_patch()
        p["modules"].append({"id": 7, "module": "essentials.macro"})
        self.assertEqual(B.resolve_param(p, {"macro": {"page": 1, "knob": 3}}), (1, "knob3"))
        self.assertEqual(B.resolve_param(p, {"macro": {"page": 2, "knob": 8}}), (7, "knob8"))
        self.assertIsNone(B.resolve_param(p, {"macro": {"page": 3, "knob": 1}}))

    def test_program_map(self):
        _, b = run(player([entry("patches/basics-01-first-tone.json"), entry("patches/basics-05-random-melody.json")]))
        self.assertEqual(b.program_map(), {0: 0, 1: 1})
        _, b = run(player([entry("patches/basics-01-first-tone.json", program=7)]))
        self.assertEqual(b.program_map(), {7: 0})


if __name__ == "__main__":
    unittest.main()
