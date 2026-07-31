from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from dataclasses import replace
from itertools import product
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Sequence
import unittest
import warnings

from keyball_config.backup import CommandResult
from keyball_config.cli import main
from keyball_config.devices import load_registry
from keyball_config.keymap import (
    RenderError,
    RenderTools,
    load_and_validate_vil,
    normalized_vil,
    reachable_layers,
    render_backup,
    render_present,
)
from keyball_config.vitaly_v6_keycodes import (
    BASIC_KEYCODES,
    STANDARD_ATOMIC_KEYCODES,
    VITALY_COMMIT,
    VITALY_VERSION,
)


FIXTURES = Path(__file__).parent / "fixtures" / "vial"
CONVERTER_FIXTURES = Path(__file__).parent / "fixtures" / "converter"


def fixture_vil(layers: dict[int, list[str]]) -> dict[str, object]:
    last_layer = max(layers, default=0)
    layout = [[[]] for _ in range(last_layer + 1)]
    for layer, keycodes in layers.items():
        layout[layer] = [keycodes]
    return {
        "version": 1,
        "uid": 1,
        "vial_protocol": 6,
        "via_protocol": 9,
        "layout": layout,
        "combo": [],
        "tap_dance": [],
        "key_override": [],
        "macro": [],
        "alt_repeat_key": [],
    }


class ReachabilityTests(unittest.TestCase):
    def test_reachability_handles_nested_cycle(self) -> None:
        vil = fixture_vil(
            {0: ["MO(2)"], 2: ["LT(3,KC_A)"], 3: ["TG(2)"]}
        )

        self.assertEqual(reachable_layers(vil), (0, 2, 3))

    def test_unreachable_non_empty_layer_is_excluded(self) -> None:
        vil = fixture_vil({0: ["KC_A"], 3: ["KC_B"]})

        self.assertEqual(reachable_layers(vil), (0,))

    def test_reachable_empty_layer_is_included(self) -> None:
        vil = fixture_vil({0: ["MO(2)"], 2: []})

        self.assertEqual(reachable_layers(vil), (0, 2))

    def test_every_supported_action_is_followed(self) -> None:
        vil = fixture_vil(
            {
                0: [
                    "MO(1)",
                    "LT(2,KC_A)",
                    "TG(3)",
                    "TO(4)",
                    "DF(5)",
                    "OSL(6)",
                ],
                6: [],
            }
        )

        self.assertEqual(reachable_layers(vil), (0, 1, 2, 3, 4, 5, 6))

    def test_malformed_layer_actions_are_diagnosed(self) -> None:
        invalid_actions = (
            "MO(1",
            "MO()",
            "MO(1,KC_A)",
            "MO(KC_A)",
            "TG()",
            "TG(1,KC_A)",
            "TO(KC_A)",
            "DF(1,KC_A)",
            "OSL(1,KC_A)",
            "LT(1)",
            "LT(1,)",
            "LT(1,KC_A,KC_B)",
            "LT(KC_A,KC_B)",
            "TO(1))",
        )
        for action in invalid_actions:
            with self.subTest(action=action):
                vil = fixture_vil({0: [action], 1: []})
                with self.assertWarnsRegex(
                    UserWarning,
                    rf"{re.escape(action)}.*layout\[0\]\[0\]\[0\].*include_layers",
                ):
                    reachable_layers(vil)

    def test_invalid_extra_argument_does_not_hide_nested_transition(self) -> None:
        vil = fixture_vil({0: ["MO(1,TO(2))"], 1: [], 2: []})

        with self.assertWarnsRegex(
            UserWarning,
            r"MO\(1,TO\(2\)\).*layout\[0\]\[0\]\[0\].*include_layers",
        ):
            layers = reachable_layers(vil)

        self.assertIn(2, layers)

    def test_unbalanced_nested_action_is_diagnosed(self) -> None:
        vil = fixture_vil({0: ["MO(1,TO(2)"], 1: [], 2: []})

        with self.assertWarnsRegex(
            UserWarning,
            r"MO\(1,TO\(2\).*layout\[0\]\[0\]\[0\].*include_layers",
        ):
            reachable_layers(vil)

    def test_layer_actions_are_found_in_every_vial_keycode_structure(self) -> None:
        vil = fixture_vil({0: ["KC_A"], 6: []})
        vil["combo"] = [["KC_A", "KC_B", "KC_NO", "KC_NO", "MO(1)"]]
        vil["tap_dance"] = [["TG(2)", "KC_NO", "KC_NO", "KC_NO", 200]]
        vil["key_override"] = [
            {"trigger": "KC_C", "replacement": "TO(3)", "layers": 65535}
        ]
        vil["macro"] = [[["tap", "DF(4)"], ["text", "MO(99) is text"]]]
        vil["alt_repeat_key"] = [
            {"keycode": "KC_D", "alt_keycode": "OSL(5)"}
        ]

        self.assertEqual(reachable_layers(vil), (0, 1, 2, 3, 4, 5))

    def test_include_layers_only_adds_valid_layers(self) -> None:
        vil = fixture_vil({0: ["MO(2)"], 2: [], 4: ["KC_D"]})

        self.assertEqual(reachable_layers(vil, (4, 2, 4)), (0, 2, 4))

    def test_invalid_include_layers_are_rejected(self) -> None:
        vil = fixture_vil({0: ["KC_A"], 1: ["KC_B"]})

        for include_layers in ((-1,), (True,), (2,)):
            with self.subTest(include_layers=include_layers):
                with self.assertRaisesRegex(ValueError, "include_layers"):
                    reachable_layers(vil, include_layers)

    def test_automatic_mouse_custom_keycode_reaches_reviewed_layer(self) -> None:
        vil = fixture_vil({0: ["QK_KB_10"], 1: []})

        self.assertEqual(reachable_layers(vil), (0, 1))

    def test_reviewed_keyball_non_layer_codes_do_not_warn(self) -> None:
        reviewed = [f"QK_KB_{index}" for index in range(10)]
        reviewed.extend(f"QK_KB_{index}" for index in range(11, 17))
        vil = fixture_vil(
            {0: reviewed}
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertEqual(reachable_layers(vil), (0,))

        self.assertEqual(caught, [])

    def test_unknown_custom_keycode_warns_with_actionable_path(self) -> None:
        vil = fixture_vil({0: ["MY_LAYER_SWITCH"]})

        with self.assertWarnsRegex(
            UserWarning, r"MY_LAYER_SWITCH.*layout\[0\]\[0\]\[0\].*include_layers"
        ):
            self.assertEqual(reachable_layers(vil), (0,))

    def test_prefixed_unknown_custom_keycodes_warn(self) -> None:
        for keycode in ("KC_MY_LAYER_SWITCH", "RGB_MY_LAYER", "QK_MY_LAYER"):
            with self.subTest(keycode=keycode):
                vil = fixture_vil({0: [keycode]})
                with self.assertWarnsRegex(
                    UserWarning,
                    rf"{keycode}.*layout\[0\]\[0\]\[0\].*include_layers",
                ):
                    self.assertEqual(reachable_layers(vil), (0,))

    def test_real_backup_reachability_is_warning_free(self) -> None:
        model = load_registry(Path("config/models.json"))["keyball44"]
        vil = load_and_validate_vil(Path("keyball44.vil"), model)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertEqual(reachable_layers(vil), (0, 1, 2, 3, 4, 9))

        self.assertEqual(caught, [])

    def test_ordinary_keycodes_and_transparent_no_op_are_quiet(self) -> None:
        vil = fixture_vil(
            {
                0: [
                    "KC_A",
                    "KC_TRANSPARENT",
                    "KC_NO",
                    "QK_MOUSE_BUTTON_1",
                    "TD(0)",
                ]
            }
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertEqual(reachable_layers(vil), (0,))

        self.assertEqual(caught, [])

    def test_vitaly_canonical_f12_and_caps_lock_are_quiet(self) -> None:
        vil = fixture_vil({0: ["KC_F12", "KC_CAPS_LOCK"]})

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertEqual(reachable_layers(vil), (0,))

        self.assertEqual(caught, [])

    def test_every_vitaly_layer_form_adds_its_target(self) -> None:
        vil = fixture_vil(
            {
                0: [
                    "TO(1)",
                    "MO(2)",
                    "DF(3)",
                    "PDF(4)",
                    "TG(5)",
                    "OSL(6)",
                    "LM(7,MOD_LCTL)",
                    "TT(8)",
                    "LT(9,KC_F12)",
                ],
                9: [],
            }
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertEqual(reachable_layers(vil), tuple(range(10)))

        self.assertEqual(caught, [])

    def test_representative_vitaly_non_layer_composites_are_quiet(self) -> None:
        vil = fixture_vil(
            {
                0: [
                    "LCTL(KC_F12)",
                    "RSG(KC_CAPS_LOCK)",
                    "OSM(MOD_LCTL|MOD_LSFT)",
                    "MT(MOD_RALT|MOD_RGUI,KC_ENTER)",
                    "TD(255)",
                ]
            }
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertEqual(reachable_layers(vil), (0,))

        self.assertEqual(caught, [])

    def test_noncanonical_and_custom_vitaly_values_warn(self) -> None:
        for keycode in (
            "KC_MY_LAYER_SWITCH",
            "QK_KB_17",
            "QK_USER_0",
            "0x7e20",
            "KC_CAPSLOCK",
        ):
            with self.subTest(keycode=keycode):
                vil = fixture_vil({0: [keycode]})
                with self.assertWarnsRegex(
                    UserWarning,
                    rf"{re.escape(keycode)}.*layout\[0\]\[0\]\[0\].*include_layers",
                ):
                    self.assertEqual(reachable_layers(vil), (0,))

    def test_every_vitaly_standard_atomic_keycode_is_quiet(self) -> None:
        vil = fixture_vil({0: sorted(STANDARD_ATOMIC_KEYCODES)})

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertEqual(reachable_layers(vil), (0,))

        self.assertEqual(caught, [])

    def test_every_vitaly_basic_keycode_is_a_valid_lt_tap_argument(self) -> None:
        vil = fixture_vil({0: [f"LT(0,{keycode})" for keycode in BASIC_KEYCODES]})

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertEqual(reachable_layers(vil), (0,))

        self.assertEqual(caught, [])

    def test_every_vitaly_modifier_wrapper_is_quiet(self) -> None:
        wrappers = (
            "LCTL",
            "LSFT",
            "LALT",
            "LGUI",
            "RCTL",
            "RSFT",
            "RALT",
            "RGUI",
            "HYPR",
            "MEH",
            "LCAG",
            "LSG",
            "LAG",
            "RSG",
            "RAG",
            "LCA",
            "LSA",
            "RSA",
            "RCS",
        )
        vil = fixture_vil({0: [f"{wrapper}(KC_A)" for wrapper in wrappers]})

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertEqual(reachable_layers(vil), (0,))

        self.assertEqual(caught, [])

    def test_every_vitaly_modifier_combination_is_valid(self) -> None:
        modifiers = {"KC_NO"}
        for side in ("L", "R"):
            names = tuple(f"MOD_{side}{name}" for name in ("CTL", "SFT", "ALT", "GUI"))
            modifiers.update(
                "|".join(name for name, enabled in zip(names, mask) if enabled)
                for mask in product((False, True), repeat=4)
                if any(mask)
            )
        vil = fixture_vil(
            {
                0: [
                    *(f"OSM({mods})" for mods in modifiers),
                    *(f"MT({mods},KC_A)" for mods in modifiers),
                ]
            }
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertEqual(reachable_layers(vil), (0,))

        self.assertEqual(caught, [])

    def test_mixed_side_modifier_combinations_warn(self) -> None:
        keycode = "OSM(MOD_RCTL|MOD_LSFT)"
        vil = fixture_vil({0: [keycode]})

        with self.assertWarnsRegex(UserWarning, re.escape(keycode)):
            self.assertEqual(reachable_layers(vil), (0,))

    def test_vitaly_input_only_composite_aliases_warn(self) -> None:
        for keycode in ("C(KC_A)", "LT1(KC_A)"):
            with self.subTest(keycode=keycode):
                vil = fixture_vil({0: [keycode]})
                with self.assertWarnsRegex(UserWarning, re.escape(keycode)):
                    self.assertEqual(reachable_layers(vil), (0,))

    def test_invalid_composite_inner_custom_keycode_is_traversed(self) -> None:
        vil = fixture_vil({0: ["LCTL(QK_KB_10)"], 1: []})

        with self.assertWarnsRegex(
            UserWarning, r"LCTL\(QK_KB_10\).*layout\[0\]\[0\]\[0\]"
        ):
            self.assertEqual(reachable_layers(vil), (0, 1))


class VitalyVocabularyGeneratorTests(unittest.TestCase):
    def test_generated_vocabulary_has_pinned_provenance_and_expected_sets(self) -> None:
        self.assertEqual(VITALY_VERSION, "0.1.32")
        self.assertEqual(VITALY_COMMIT, "7ba52b0cf121e411434adcebf111e54b0ee470eb")
        self.assertEqual(len(STANDARD_ATOMIC_KEYCODES), 656)
        self.assertEqual(len(BASIC_KEYCODES), 220)
        self.assertIn("KC_F12", BASIC_KEYCODES)
        self.assertIn("KC_CAPS_LOCK", BASIC_KEYCODES)
        self.assertNotIn("QK_KB_0", STANDARD_ATOMIC_KEYCODES)
        self.assertNotIn("QK_USER_0", STANDARD_ATOMIC_KEYCODES)

    def test_generator_writes_and_checks_a_reproducible_module(self) -> None:
        source_text = """\
pub static FULLNAMES: LazyLock<HashMap<u16, &str>> = LazyLock::new(|| {
    let mut m = HashMap::new();
    m.insert(0x0000, "KC_NO");
    m.insert(0x0045, "KC_F12");
    m.insert(0x7E00, "QK_KB_0");
    m.insert(0x7E40, "QK_USER_0");
    m
});
"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "code_to_name.rs"
            output = Path(directory) / "vitaly_v6_keycodes.py"
            source.write_text(source_text)
            command = [
                sys.executable,
                "scripts/generate_vitaly_v6_keycodes.py",
                "--source",
                str(source),
                "--output",
                str(output),
            ]

            generated = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            contents = output.read_text()
            self.assertIn(
                'VITALY_COMMIT = "7ba52b0cf121e411434adcebf111e54b0ee470eb"',
                contents,
            )
            self.assertIn('0x0045: "KC_F12"', contents)
            self.assertNotIn("QK_KB_0", contents)
            self.assertNotIn("QK_USER_0", contents)

            checked = subprocess.run(
                [*command, "--check"], capture_output=True, text=True
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = load_registry(Path("config/models.json"))["keyball44"]

    def test_valid_fixture_loads(self) -> None:
        vil = load_and_validate_vil(FIXTURES / "valid-keyball44.vil", self.model)

        self.assertEqual(vil["version"], 1)
        self.assertEqual(len(vil["layout"]), 2)

    def test_keyball39_eight_by_six_fixture_loads(self) -> None:
        model = load_registry(Path("config/models.json"))["keyball39"]

        vil = load_and_validate_vil(FIXTURES / "valid-keyball39.vil", model)

        self.assertEqual(len(vil["layout"]), 1)
        self.assertEqual((len(vil["layout"][0]), len(vil["layout"][0][0])), (8, 6))

    def test_keyball39_rejects_observed_keyball44_eight_by_seven_shape(self) -> None:
        model = load_registry(Path("config/models.json"))["keyball39"]

        with self.assertRaisesRegex(ValueError, "matrix shape.*keyball39"):
            load_and_validate_vil(Path("keyball44.vil"), model)

    def test_real_backup_validates_without_geometry_assumptions(self) -> None:
        model = replace(self.model, geometry_path="not-a-physical-layout.json")

        vil = load_and_validate_vil(Path("keyball44.vil"), model)

        self.assertEqual(len(vil["layout"]), 10)

    def test_malformed_json_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid Vial backup"):
            load_and_validate_vil(FIXTURES / "malformed.vil", self.model)

    def test_required_metadata_and_layout_are_validated(self) -> None:
        invalid_values = (
            {},
            {"version": 1, "uid": 1, "vial_protocol": 6, "via_protocol": 9},
            {
                "version": 1,
                "uid": 1,
                "vial_protocol": 6,
                "via_protocol": 9,
                "layout": [],
            },
            {
                "version": 1,
                "uid": 1,
                "vial_protocol": 6,
                "via_protocol": 9,
                "layout": [[[46]]],
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.vil"
            for value in invalid_values:
                with self.subTest(value=value):
                    path.write_text(json.dumps(value))
                    with self.assertRaisesRegex(ValueError, "Vial|layout"):
                        load_and_validate_vil(path, self.model)

    def test_keycode_structures_require_keycode_strings(self) -> None:
        vil = fixture_vil({0: ["KC_A"]})
        vil["combo"] = [["KC_A", "KC_B", "KC_NO", "KC_NO", None]]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.vil"
            path.write_text(json.dumps(vil))

            with self.assertRaisesRegex(ValueError, r"combo\[0\]\[4\].*keycode"):
                load_and_validate_vil(path, self.model)

    def test_macro_keycode_commands_require_keycode_strings(self) -> None:
        vil = fixture_vil({0: ["KC_A"]})
        vil["macro"] = [[["tap", 42]]]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.vil"
            path.write_text(json.dumps(vil))

            with self.assertRaisesRegex(ValueError, r"macro\[0\]\[0\].*keycode"):
                load_and_validate_vil(path, self.model)

    def test_layout_requires_at_least_one_row_and_column(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.vil"
            for layout in ([[]], [[[]]]):
                with self.subTest(layout=layout):
                    vil = fixture_vil({0: ["KC_A"]})
                    vil["layout"] = layout
                    path.write_text(json.dumps(vil))

                    with self.assertRaisesRegex(ValueError, "row|column"):
                        load_and_validate_vil(path, self.model)

    def test_layout_rejects_jagged_rows(self) -> None:
        vil = fixture_vil({0: ["KC_A"]})
        vil["layout"] = [[["KC_A"], ["KC_B", "KC_C"]]]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.vil"
            path.write_text(json.dumps(vil))

            with self.assertRaisesRegex(ValueError, "jagged|columns"):
                load_and_validate_vil(path, self.model)

    def test_layout_rejects_inconsistent_layer_shapes(self) -> None:
        vil = fixture_vil({0: ["KC_A"]})
        vil["layout"] = [[["KC_A", "KC_B"]], [["KC_C"]]]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.vil"
            path.write_text(json.dumps(vil))

            with self.assertRaisesRegex(ValueError, "layer.*shape|rows.*columns"):
                load_and_validate_vil(path, self.model)


class NormalizationTests(unittest.TestCase):
    def test_normalized_vil_is_stable_and_preserves_layer_indices(self) -> None:
        vil = fixture_vil({0: ["MO(2)"], 1: ["KC_B"], 2: ["KC_C"]})

        first = normalized_vil(vil, (2, 0))
        second = normalized_vil(dict(reversed(tuple(vil.items()))), (0, 2))

        self.assertEqual(first, second)
        self.assertTrue(first.endswith(b"\n"))
        normalized = json.loads(first)
        self.assertEqual(
            normalized["layout"],
            [[["MO(2)"]], [["KC_NO"]], [["KC_C"]]],
        )

    def test_sparse_normalization_keeps_shape_and_original_layer_number(self) -> None:
        vil = fixture_vil(
            {
                0: ["MO(3)", "KC_A"],
                1: ["KC_B", "KC_C"],
                2: ["KC_D", "KC_E"],
                3: ["TO(0)", "KC_F"],
                4: ["KC_G", "KC_H"],
            }
        )

        normalized = json.loads(normalized_vil(vil, (0, 3)))

        self.assertEqual(len(normalized["layout"]), 4)
        self.assertEqual(normalized["layout"][0], [["MO(3)", "KC_A"]])
        self.assertEqual(normalized["layout"][1], [["KC_NO", "KC_NO"]])
        self.assertEqual(normalized["layout"][2], [["KC_NO", "KC_NO"]])
        self.assertEqual(normalized["layout"][3], [["TO(0)", "KC_F"]])

    def test_normalized_vil_rejects_invalid_layers(self) -> None:
        vil = fixture_vil({0: ["KC_A"]})

        for layers in ((), (-1,), (True,), (1,)):
            with self.subTest(layers=layers):
                with self.assertRaisesRegex(ValueError, "layers"):
                    normalized_vil(vil, layers)


class FakeRenderRunner:
    def __init__(
        self,
        *,
        svg: bytes | None = b'<svg xmlns="http://www.w3.org/2000/svg"/>\n',
        converter_yaml: str | None = None,
    ) -> None:
        self.svg = svg
        self.converter_yaml = converter_yaml
        self.calls: list[tuple[tuple[str, ...], Path]] = []
        self.converter_inputs: list[bytes] = []
        self.keymap_inputs: list[bytes] = []
        self.geometry_inputs: list[bytes] = []

    def __call__(self, args: Sequence[str], cwd: Path) -> CommandResult:
        command = tuple(str(arg) for arg in args)
        self.calls.append((command, cwd))
        if command[0].endswith("vial-converter"):
            source = Path(command[command.index("--input") + 1])
            output = Path(command[command.index("--output") + 1])
            self.converter_inputs.append(source.read_bytes())
            if self.converter_yaml is not None:
                output.write_text(self.converter_yaml)
                return CommandResult(0, "converted\n", "")
            vil = json.loads(source.read_text())
            lines = [f'layout: {{"qmk_info_json":"unused"}}', "layers:"]
            for layer_index, layer in enumerate(vil["layout"]):
                lines.append(f"  L{layer_index}:")
                for keycode in (key for row in layer for key in row):
                    lines.append("    - " + json.dumps(keycode))
            if len(layer[0]) == 7:
                lines.extend(
                    (
                        "combos:",
                        '  - {"k":"Mouse1","l":["L0"],"p":[46,45]}',
                    )
                )
            output.write_text("\n".join(lines) + "\n")
            return CommandResult(0, "converted\n", "")
        if command[0].endswith("keymap"):
            source = Path(command[-1])
            output = Path(command[command.index("-o") + 1])
            self.keymap_inputs.append(source.read_bytes())
            self.geometry_inputs.append(
                Path(command[command.index("-j") + 1]).read_bytes()
            )
            if self.svg is not None:
                output.write_bytes(self.svg)
            return CommandResult(0, "", "")
        raise AssertionError(command)


class RenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.models = load_registry(Path("config/models.json"))
        self.tools = RenderTools(
            converter=Path("/tools/vial-converter"),
            keymap=Path("/tools/keymap"),
            geometry_root=CONVERTER_FIXTURES,
        )

    def test_both_models_render_twice_byte_identically(self) -> None:
        for slug in ("keyball39", "keyball44"):
            with self.subTest(slug=slug), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                runner = FakeRenderRunner()
                source = CONVERTER_FIXTURES / f"{slug}.vil"
                first = root / "first.svg"
                second = root / "second.svg"

                render_backup(source, first, self.models[slug], self.tools, runner)
                render_backup(source, second, self.models[slug], self.tools, runner)

                self.assertEqual(first.read_bytes(), second.read_bytes())
                self.assertEqual(runner.keymap_inputs[0], runner.keymap_inputs[1])
                self.assertEqual(runner.converter_inputs[0], runner.converter_inputs[1])

    def test_sparse_placeholder_layers_are_not_rendered(self) -> None:
        runner = FakeRenderRunner()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "keyball44.svg"
            render_backup(
                CONVERTER_FIXTURES / "keyball44.vil",
                output,
                self.models["keyball44"],
                self.tools,
                runner,
            )

        yaml_text = runner.keymap_inputs[0].decode()
        self.assertIn("  L0:", yaml_text)
        self.assertIn("  L3:", yaml_text)
        self.assertNotIn("  L1:", yaml_text)
        self.assertNotIn("  L2:", yaml_text)

    def test_canonical_combo_position_46_is_rebased_to_left_ball_geometry(self) -> None:
        runner = FakeRenderRunner()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "keyball44.svg"
            render_backup(
                CONVERTER_FIXTURES / "keyball44.vil",
                output,
                self.models["keyball44"],
                self.tools,
                runner,
            )

        yaml_text = runner.keymap_inputs[0].decode()
        self.assertNotIn('"p":[46,45]', yaml_text)
        self.assertIn('"p":[31,32]', yaml_text)
        geometry = json.loads(runner.geometry_inputs[0])
        labels = [
            key["label"]
            for key in geometry["layouts"]["LAYOUT_no_ball"]["layout"]
        ]
        self.assertEqual(len(labels), 44)
        self.assertNotIn("L32", labels)
        self.assertNotIn("L33", labels)

    def test_missing_or_malformed_svg_preserves_existing_output(self) -> None:
        bad_outputs = (None, b"", b"not xml", b"<html/>")
        for generated in bad_outputs:
            with self.subTest(generated=generated), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "keyball39.svg"
                output.write_bytes(b"old svg")
                runner = FakeRenderRunner(svg=generated)

                with self.assertRaises(RenderError):
                    render_backup(
                        CONVERTER_FIXTURES / "keyball39.vil",
                        output,
                        self.models["keyball39"],
                        self.tools,
                        runner,
                    )

                self.assertEqual(output.read_bytes(), b"old svg")
                self.assertEqual(
                    [path.name for path in output.parent.iterdir()], [output.name]
                )

    def test_malformed_converter_yaml_is_rejected_before_drawing(self) -> None:
        runner = FakeRenderRunner(converter_yaml="layers:\n  L0: []\n")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "keyball39.svg"
            with self.assertRaisesRegex(RenderError, "converter YAML"):
                render_backup(
                    CONVERTER_FIXTURES / "keyball39.vil",
                    output,
                    self.models["keyball39"],
                    self.tools,
                    runner,
                )

        self.assertEqual(len(runner.calls), 1)

    def test_duplicate_converter_layer_is_rejected(self) -> None:
        keys = "\n".join('    - "KC_A"' for _ in range(48))
        runner = FakeRenderRunner(
            converter_yaml=(
                'layout: {"qmk_info_json":"unused"}\n'
                f"layers:\n  L0:\n{keys}\n  L0:\n{keys}\n"
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RenderError, "duplicate.*L0"):
                render_backup(
                    CONVERTER_FIXTURES / "keyball39.vil",
                    Path(directory) / "keyball39.svg",
                    self.models["keyball39"],
                    self.tools,
                    runner,
                )

    def test_malformed_converter_combo_schema_is_rejected(self) -> None:
        keys = "\n".join('    - "KC_A"' for _ in range(48))
        malformed = (
            {"k": "Escape", "l": "L0", "p": [0, 1]},
            {"k": "Escape", "l": ["L0"], "p": "0,1"},
            {"k": "Escape", "l": ["L0"], "p": [True, 1]},
            {"k": "Escape", "l": ["L0"], "p": [0, -1]},
            {"k": "Escape", "l": ["L9"], "p": [0, 1]},
            {"k": "Escape", "l": ["L9"], "p": [48, 1]},
            {"l": ["L0"], "p": [0, 1]},
            {"k": None, "l": ["L0"], "p": [0, 1]},
            {"k": "Escape", "l": ["L0"], "p": [0, 1], "unexpected": True},
            {
                "k": {"unexpected": []},
                "l": ["L0"],
                "p": [0, 1],
                "unexpected": True,
            },
            {"k": {"t": []}, "l": ["L0"], "p": [0, 1]},
            {"k": {"h": 1}, "l": ["L0"], "p": [0, 1]},
            {"k": {"s": None}, "l": ["L0"], "p": [0, 1]},
            {"k": {"type": True}, "l": ["L0"], "p": [0, 1]},
        )
        for combo in malformed:
            with self.subTest(combo=combo), tempfile.TemporaryDirectory() as directory:
                runner = FakeRenderRunner(
                    converter_yaml=(
                        'layout: {"qmk_info_json":"unused"}\n'
                        f"layers:\n  L0:\n{keys}\ncombos:\n"
                        f"  - {json.dumps(combo)}\n"
                    )
                )
                with self.assertRaisesRegex(RenderError, "combo"):
                    render_backup(
                        CONVERTER_FIXTURES / "keyball39.vil",
                        Path(directory) / "keyball39.svg",
                        self.models["keyball39"],
                        self.tools,
                        runner,
                    )

    def test_real_composite_converter_combo_key_is_accepted(self) -> None:
        keys = "\n".join('    - "KC_A"' for _ in range(48))
        combo = {
            "k": {"t": "Escape", "h": "", "s": "Shift", "type": "held"},
            "l": ["L0"],
            "p": [0, 1],
        }
        runner = FakeRenderRunner(
            converter_yaml=(
                'layout: {"qmk_info_json":"unused"}\n'
                f"layers:\n  L0:\n{keys}\ncombos:\n"
                f"  - {json.dumps(combo)}\n"
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            render_backup(
                CONVERTER_FIXTURES / "keyball39.vil",
                Path(directory) / "keyball39.svg",
                self.models["keyball39"],
                self.tools,
                runner,
            )

        self.assertIn(b'"h":""', runner.keymap_inputs[0])

    def test_converter_layer_requires_exact_electrical_matrix_size(self) -> None:
        keys = "\n".join('    - "KC_A"' for _ in range(42))
        runner = FakeRenderRunner(
            converter_yaml=(
                'layout: {"qmk_info_json":"unused"}\n'
                f"layers:\n  L0:\n{keys}\n"
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RenderError, "electrical matrix.*48"):
                render_backup(
                    CONVERTER_FIXTURES / "keyball39.vil",
                    Path(directory) / "keyball39.svg",
                    self.models["keyball39"],
                    self.tools,
                    runner,
                )

    def test_tool_start_failure_is_reported_as_render_error(self) -> None:
        def unavailable(args: Sequence[str], cwd: Path) -> CommandResult:
            raise OSError("tool is unavailable")

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RenderError, "converter.*unavailable"):
                render_backup(
                    CONVERTER_FIXTURES / "keyball39.vil",
                    Path(directory) / "keyball39.svg",
                    self.models["keyball39"],
                    self.tools,
                    unavailable,
                )

    def test_render_present_defaults_to_all_and_model_filter_is_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            repo.mkdir()
            for slug in self.models:
                (repo / f"{slug}.vil").write_bytes(
                    (CONVERTER_FIXTURES / f"{slug}.vil").read_bytes()
                )
            output = Path(directory) / "build"

            rendered = render_present(
                repo, output, self.models, self.tools, FakeRenderRunner()
            )
            only = render_present(
                repo,
                output,
                self.models,
                self.tools,
                FakeRenderRunner(),
                only_model="keyball39",
            )

            self.assertEqual(
                [path.name for path in rendered],
                ["keyball39.svg", "keyball44.svg"],
            )
            self.assertEqual([path.name for path in only], ["keyball39.svg"])

    def test_render_present_requires_a_backup_and_known_present_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            repo.mkdir()
            output = Path(directory) / "build"
            with self.assertRaisesRegex(RenderError, "no supported backups"):
                render_present(
                    repo, output, self.models, self.tools, FakeRenderRunner()
                )
            with self.assertRaisesRegex(RenderError, "unknown model"):
                render_present(
                    repo,
                    output,
                    self.models,
                    self.tools,
                    FakeRenderRunner(),
                    only_model="keyball61",
                )

    def test_cli_render_defaults_to_all_and_accepts_diagnostic_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            repo.mkdir()
            for slug in self.models:
                (repo / f"{slug}.vil").write_bytes(
                    (CONVERTER_FIXTURES / f"{slug}.vil").read_bytes()
                )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    ("render", "--output", "build"),
                    repo=repo,
                    registry_path=Path("config/models.json"),
                    runner=FakeRenderRunner(),
                    render_tools=self.tools,
                )
            with redirect_stdout(io.StringIO()):
                diagnostic = main(
                    ("render", "--output", "build", "--model", "keyball39"),
                    repo=repo,
                    registry_path=Path("config/models.json"),
                    runner=FakeRenderRunner(),
                    render_tools=self.tools,
                )

            self.assertEqual(result, 0)
            self.assertEqual(diagnostic, 0)
            self.assertEqual(
                stdout.getvalue().splitlines(),
                [
                    str(repo / "build" / "keyball39.svg"),
                    str(repo / "build" / "keyball44.svg"),
                ],
            )


class RealRenderingIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("vial-converter") and shutil.which("keymap"),
        "pinned render tools are not on PATH",
    )
    def test_pinned_tools_render_both_fixtures_byte_identically(self) -> None:
        converter = Path(shutil.which("vial-converter") or "")
        geometry_root = converter.resolve().parent.parent / "share" / "keyball-geometry"
        if not geometry_root.is_dir():
            self.skipTest("packaged Keyball geometry is not available")
        tools = RenderTools(
            converter=converter,
            keymap=Path(shutil.which("keymap") or ""),
            geometry_root=geometry_root,
        )
        models = load_registry(Path("config/models.json"))
        from keyball_config.backup import run_command

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for slug in ("keyball39", "keyball44"):
                first = root / f"{slug}-first.svg"
                second = root / f"{slug}-second.svg"
                render_backup(
                    CONVERTER_FIXTURES / f"{slug}.vil",
                    first,
                    models[slug],
                    tools,
                    run_command,
                )
                render_backup(
                    CONVERTER_FIXTURES / f"{slug}.vil",
                    second,
                    models[slug],
                    tools,
                    run_command,
                )
                self.assertEqual(first.read_bytes(), second.read_bytes())


if __name__ == "__main__":
    unittest.main()
