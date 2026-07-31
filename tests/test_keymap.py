from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import re
import tempfile
import unittest
import warnings

from keyball_config.devices import load_registry
from keyball_config.keymap import (
    load_and_validate_vil,
    normalized_vil,
    reachable_layers,
)


FIXTURES = Path(__file__).parent / "fixtures" / "vial"


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
                    "KC_TRNS",
                    "KC_TRANSPARENT",
                    "KC_NO",
                    "_______",
                    "XXXXXXX",
                    "QK_MOUSE_BUTTON_1",
                    "TD(0)",
                ]
            }
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertEqual(reachable_layers(vil), (0,))

        self.assertEqual(caught, [])


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = load_registry(Path("config/models.json"))["keyball44"]

    def test_valid_fixture_loads(self) -> None:
        vil = load_and_validate_vil(FIXTURES / "valid-keyball44.vil", self.model)

        self.assertEqual(vil["version"], 1)
        self.assertEqual(len(vil["layout"]), 2)

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


if __name__ == "__main__":
    unittest.main()
