from __future__ import annotations

import copy
from dataclasses import dataclass
from itertools import product
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Mapping, Sequence
import warnings
import xml.etree.ElementTree as ET

from keyball_config.devices import ModelConfig
from keyball_config.vitaly_v6_keycodes import (
    BASIC_KEYCODES,
    STANDARD_ATOMIC_KEYCODES,
)


KeySpec = str | dict[str, str]

_LAYER_ACTIONS = {"MO", "LT", "TG", "TO", "DF", "PDF", "OSL", "LM", "TT"}
_KEYBALL_NON_LAYER_KEYCODES = {
    *(f"QK_KB_{index}" for index in range(10)),
    *(f"QK_KB_{index}" for index in range(11, 17)),
}
_KNOWN_WRAPPERS = {
    "HYPR",
    "LALT",
    "LAG",
    "LCA",
    "LCAG",
    "LCTL",
    "LGUI",
    "LSA",
    "LSG",
    "LSFT",
    "MEH",
    "RALT",
    "RAG",
    "RCS",
    "RCTL",
    "RGUI",
    "RSA",
    "RSG",
    "RSFT",
}
_VALID_MODIFIERS = {"KC_NO"} | {
    "|".join(
        name
        for name, enabled in zip(
            (f"MOD_{side}CTL", f"MOD_{side}SFT", f"MOD_{side}ALT", f"MOD_{side}GUI"),
            mask,
        )
        if enabled
    )
    for side in ("L", "R")
    for mask in product((False, True), repeat=4)
    if any(mask)
}
_CALL = re.compile(r"(?P<name>[A-Z][A-Z0-9_]*)\((?P<arguments>.*)\)")
_MODIFIER_LABELS = {
    "MOD_LCTL": "LCtrl",
    "MOD_LSFT": "LShift",
    "MOD_LALT": "LAlt",
    "MOD_LGUI": "LGui",
    "MOD_RCTL": "RCtrl",
    "MOD_RSFT": "RShift",
    "MOD_RALT": "RAlt",
    "MOD_RGUI": "RGui",
}
_WRAPPER_LABELS = {
    "LCTL": "LCtrl",
    "LSFT": "LShift",
    "LALT": "LAlt",
    "LGUI": "LGui",
    "RCTL": "RCtrl",
    "RSFT": "RShift",
    "RALT": "RAlt",
    "RGUI": "RGui",
    "HYPR": "Hyper",
    "MEH": "Meh",
    "LCAG": "LCtrl+LAlt+LGui",
    "LSG": "LShift+LGui",
    "LAG": "LAlt+LGui",
    "RSG": "RShift+RGui",
    "RAG": "RAlt+RGui",
    "LCA": "LCtrl+LAlt",
    "LSA": "LShift+LAlt",
    "RSA": "RShift+RAlt",
    "RCS": "RCtrl+RShift",
}


def _side_aware_label(label: str, physical_side: str | None) -> str:
    if physical_side not in {"L", "R"}:
        return label
    return "+".join(
        part[1:] if part.startswith(physical_side) else part
        for part in label.split("+")
    )


_ATOMIC_LABELS = {
    "KC_NO": "",
    "KC_TRANSPARENT": "",
    "KC_TRNS": "",
    "KC_BACKSPACE": "Bksp",
    "KC_PAGE_UP": "PgUp",
    "KC_PAGE_DOWN": "PgDn",
    "KC_PRINT_SCREEN": "PrtSc",
    "KC_ESCAPE": "Esc",
    "KC_DELETE": "Del",
    "KC_APPLICATION": "Menu",
    "KC_LEFT_CTRL": "LCtrl",
    "KC_LEFT_SHIFT": "LShift",
    "KC_LEFT_ALT": "LAlt",
    "KC_LEFT_GUI": "LGui",
    "KC_RIGHT_CTRL": "RCtrl",
    "KC_RIGHT_SHIFT": "RShift",
    "KC_RIGHT_ALT": "RAlt",
    "KC_RIGHT_GUI": "RGui",
    "KC_LEFT": "◀",
    "KC_UP": "▲",
    "KC_DOWN": "▼",
    "KC_RIGHT": "▶",
    "KC_MINUS": "-",
    "KC_EQUAL": "=",
    "KC_LEFT_BRACKET": "[",
    "KC_RIGHT_BRACKET": "]",
    "KC_BACKSLASH": "\\",
    "KC_SEMICOLON": ";",
    "KC_QUOTE": "'",
    "KC_GRAVE": "`",
    "KC_COMMA": ",",
    "KC_DOT": ".",
    "KC_SLASH": "/",
    "QK_MOUSE_CURSOR_LEFT": "Mouse ←",
    "QK_MOUSE_CURSOR_RIGHT": "Mouse →",
    "QK_MOUSE_CURSOR_UP": "Mouse ↑",
    "QK_MOUSE_CURSOR_DOWN": "Mouse ↓",
    "QK_MOUSE_WHEEL_LEFT": "Wheel ←",
    "QK_MOUSE_WHEEL_RIGHT": "Wheel →",
    "QK_MOUSE_WHEEL_UP": "Wheel ↑",
    "QK_MOUSE_WHEEL_DOWN": "Wheel ↓",
    "QK_MOUSE_ACCELERATION_0": "Mouse Accel 0",
    "QK_MOUSE_ACCELERATION_1": "Mouse Accel 1",
    "QK_MOUSE_ACCELERATION_2": "Mouse Accel 2",
    **{f"QK_MOUSE_BUTTON_{index}": f"Mouse {index}" for index in range(1, 9)},
}
# The Vial firmware used by the canonical Keyball44 backup defines indices 0–16.
_KEYBALL_LABELS = dict(
    enumerate(
        (
            "DPI+",
            "DPI-",
            "Snp+",
            "Snp-",
            "Snp",
            "SnpT",
            "Drg",
            "DrgT",
            "Drg+",
            "Drg-",
            "ATG",
            "A50",
            "A50-",
            "A100",
            "ATV",
            "TInfo",
            "T_SAVE",
        )
    )
)
_SHIFTED_LABELS = {
    "KC_1": "!",
    "KC_2": "@",
    "KC_3": "#",
    "KC_4": "$",
    "KC_5": "%",
    "KC_6": "^",
    "KC_7": "&",
    "KC_8": "*",
    "KC_9": "(",
    "KC_0": ")",
    "KC_MINUS": "_",
    "KC_EQUAL": "+",
    "KC_LEFT_BRACKET": "{",
    "KC_RIGHT_BRACKET": "}",
    "KC_BACKSLASH": "|",
    "KC_SEMICOLON": ":",
    "KC_QUOTE": '"',
    "KC_GRAVE": "~",
    "KC_COMMA": "<",
    "KC_DOT": ">",
    "KC_SLASH": "?",
}
_MODEL_PROTOCOLS = {
    "keyball39": (1, 6, 9),
    "keyball44": (1, 6, 9),
}


def _friendly_modifiers(
    value: str, physical_side: str | None = None
) -> str | None:
    if value not in _VALID_MODIFIERS:
        return None
    if value == "KC_NO":
        return ""
    parts = value.split("|")
    sides = {part[4] for part in parts}
    if len(sides) != 1:
        return None
    return "+".join(
        _side_aware_label(_MODIFIER_LABELS[part], physical_side)
        for part in parts
    )


def _atomic_label(keycode: str, physical_side: str | None = None) -> str:
    if keycode in _ATOMIC_LABELS:
        return _side_aware_label(_ATOMIC_LABELS[keycode], physical_side)
    match = re.fullmatch(r"QK_KB_(\d+)", keycode)
    if match and _canonical_number(match[1], 16):
        return _KEYBALL_LABELS[int(match[1])]
    if _known_atomic_keycode(keycode) and keycode.startswith("KC_"):
        return keycode[3:].replace("_", " ").title()
    return keycode


def _tap_text(spec: KeySpec, fallback: str) -> str:
    if isinstance(spec, str):
        return spec
    return spec.get("t", fallback)


def _macro_label(keycode: str, vil: Mapping[str, object]) -> str | None:
    match = re.fullmatch(r"QK_MACRO_(\d+)", keycode)
    if match is None or not _canonical_number(match[1], 31):
        return None
    index = int(match[1])
    macros = vil.get("macro", [])
    if not isinstance(macros, list) or index >= len(macros):
        return f"Macro {index}"
    macro = macros[index]
    if (
        isinstance(macro, list)
        and len(macro) == 1
        and macro[0][0] == "text"
        and isinstance(macro[0][1], str)
        and 0 < len(macro[0][1]) <= 8
        and all(character.isprintable() for character in macro[0][1])
    ):
        return macro[0][1]
    return f"Macro {index}"


class _TapDanceCycle(Exception):
    pass


def _key_spec(
    keycode: str, vil: Mapping[str, object], physical_side: str | None = None
) -> KeySpec:
    try:
        return _key_spec_nested(keycode, vil, frozenset(), {}, physical_side)
    except _TapDanceCycle:
        return keycode


def _key_spec_nested(
    keycode: str,
    vil: Mapping[str, object],
    active_dances: frozenset[str],
    dance_memo: dict[str, KeySpec],
    physical_side: str | None = None,
) -> KeySpec:
    if keycode in active_dances:
        raise _TapDanceCycle
    if keycode in dance_memo:
        return dance_memo[keycode]
    macro = _macro_label(keycode, vil)
    if macro is not None:
        return macro
    call = _CALL.fullmatch(keycode)
    if call is None:
        return _atomic_label(keycode, physical_side)
    arguments = _split_arguments(call["arguments"])
    if arguments is None:
        return keycode
    name = call["name"]
    if name == "MT" and len(arguments) == 2:
        hold = _friendly_modifiers(arguments[0], physical_side)
        if hold is not None and arguments[1] in BASIC_KEYCODES:
            tap = _tap_text(
                _key_spec(arguments[1], vil, physical_side), arguments[1]
            )
            return {"t": tap, "h": hold} if hold else tap
    if (
        name == "LT"
        and len(arguments) == 2
        and _canonical_number(arguments[0], 15)
        and arguments[1] in BASIC_KEYCODES
    ):
        return {
            "t": _tap_text(
                _key_spec(arguments[1], vil, physical_side), arguments[1]
            ),
            "h": f"L{arguments[0]}",
        }
    if name == "OSM" and len(arguments) == 1:
        modifier = _friendly_modifiers(arguments[0], physical_side)
        if modifier is not None:
            return {"t": modifier, "h": "one-shot"} if modifier else ""
    layer_qualifiers = {
        "MO": "hold",
        "TG": "toggle",
        "TO": "switch",
        "DF": "default",
        "PDF": "default",
        "OSL": "one-shot",
        "TT": "tap-toggle",
    }
    if (
        name in layer_qualifiers
        and len(arguments) == 1
        and _canonical_number(arguments[0], 31)
    ):
        return {"t": f"L{arguments[0]}", "h": layer_qualifiers[name]}
    if name == "LM" and len(arguments) == 2 and _canonical_number(arguments[0], 15):
        modifier = _friendly_modifiers(arguments[1], physical_side)
        if modifier is not None:
            return {"t": f"L{arguments[0]}", "h": modifier or "hold"}
    if name == "TD" and len(arguments) == 1 and _canonical_number(arguments[0], 255):
        dances = vil.get("tap_dance", [])
        index = int(arguments[0])
        if isinstance(dances, list) and index < len(dances):
            dance = dances[index]
            if isinstance(dance, list) and len(dance) == 5:
                fields = (("t", ""), ("h", ""), ("tr", "2× "), ("br", "T+H "))
                result: dict[str, str] = {}
                next_active_dances = active_dances | {keycode}
                for action, (field, prefix) in zip(dance[:4], fields, strict=True):
                    if action != "KC_NO":
                        result[field] = prefix + _tap_text(
                            _key_spec_nested(
                                action,
                                vil,
                                next_active_dances,
                                dance_memo,
                                physical_side,
                            ),
                            action,
                        )
                dance_memo[keycode] = result
                return result
    if (
        name in {"LSFT", "RSFT"}
        and len(arguments) == 1
        and arguments[0] in BASIC_KEYCODES
        and arguments[0] in _SHIFTED_LABELS
    ):
        return _SHIFTED_LABELS[arguments[0]]
    if (
        name in _WRAPPER_LABELS
        and len(arguments) == 1
        and arguments[0] in BASIC_KEYCODES
    ):
        label = _side_aware_label(_WRAPPER_LABELS[name], physical_side)
        inner = _tap_text(
            _key_spec(arguments[0], vil, physical_side), arguments[0]
        )
        return f"{label}+{inner}" if inner else label
    return keycode


@dataclass(frozen=True)
class RenderTools:
    converter: Path
    keymap: Path
    geometry_root: Path


class RenderError(RuntimeError):
    """A backup could not be converted into a fresh, valid SVG."""


def render_backup(
    source: Path,
    output_svg: Path,
    model: ModelConfig,
    tools: RenderTools,
    runner,
) -> None:
    try:
        vil = load_and_validate_vil(source, model)
        selected_layers = reachable_layers(vil, model.include_layers)
        positions = _physical_positions(model, vil)
        geometry = _filtered_geometry(
            tools.geometry_root / model.geometry_path, positions
        )
    except (OSError, ValueError) as error:
        raise RenderError(str(error)) from error

    output_svg.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{model.slug}-render-", dir=output_svg.parent
    ) as directory:
        temporary = Path(directory)
        normalized_input = temporary / f"{model.slug}.vil"
        converter_yaml = temporary / "converter.yaml"
        normalized_yaml = temporary / f"{model.slug}.yaml"
        geometry_path = temporary / f"{model.slug}-geometry.json"
        rendered_svg = temporary / f"{model.slug}.svg"
        normalized_input.write_bytes(normalized_vil(vil, selected_layers))
        geometry_path.write_bytes(geometry)

        converter_result = _run_render_command(
            "converter",
            runner,
            (
                str(tools.converter),
                *model.converter_args,
                "--geometry",
                str(tools.geometry_root / model.geometry_path),
                "--input",
                str(normalized_input),
                "--output",
                str(converter_yaml),
            ),
            source.parent,
        )
        _require_render_command("converter", converter_result)
        try:
            converted = converter_yaml.read_text()
        except OSError as error:
            raise RenderError(f"converter did not create YAML: {error}") from error
        if not converted:
            raise RenderError("converter created empty YAML")
        normalized_yaml.write_bytes(
            _normalize_converter_yaml(
                converted,
                vil,
                selected_layers,
                positions,
                len(vil["layout"][0]) * len(vil["layout"][0][0]),
            )
        )

        keymap_result = _run_render_command(
            "keymap-drawer",
            runner,
            (
                str(tools.keymap),
                "draw",
                "-j",
                str(geometry_path),
                "-o",
                str(rendered_svg),
                str(normalized_yaml),
            ),
            temporary,
        )
        _require_render_command("keymap-drawer", keymap_result)
        _validate_svg(rendered_svg)
        os.replace(rendered_svg, output_svg)


def render_present(
    repo: Path,
    output: Path,
    models: Mapping[str, ModelConfig],
    tools: RenderTools,
    runner,
    only_model: str | None = None,
) -> tuple[Path, ...]:
    if only_model is not None and only_model not in models:
        raise RenderError(f"unknown model: {only_model}")
    selected = [models[only_model]] if only_model is not None else [
        models[slug] for slug in sorted(models)
    ]
    present = [model for model in selected if (repo / model.backup_filename).is_file()]
    if not present:
        if only_model is not None:
            raise RenderError(f"backup is missing for model: {only_model}")
        raise RenderError("no supported backups are present")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".keyball-render-", dir=output.parent) as directory:
        staging = Path(directory)
        for model in present:
            render_backup(
                repo / model.backup_filename,
                staging / f"{model.slug}.svg",
                model,
                tools,
                runner,
            )
        output.mkdir(parents=True, exist_ok=True)
        rendered: list[Path] = []
        for model in present:
            target = output / f"{model.slug}.svg"
            os.replace(staging / target.name, target)
            rendered.append(target)
    return tuple(rendered)


def _require_render_command(name: str, result) -> None:
    if result.returncode != 0 or result.stderr:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise RenderError(f"{name} failed: {detail}")


def _run_render_command(name: str, runner, args: Sequence[str], cwd: Path):
    try:
        return runner(args, cwd)
    except OSError as error:
        raise RenderError(f"cannot start {name}: {error}") from error


def _physical_positions(
    model: ModelConfig, vil: Mapping[str, object]
) -> tuple[tuple[str, int], ...]:
    layout = vil["layout"]
    assert isinstance(layout, list)
    columns = len(layout[0][0])
    coordinates: list[tuple[str, int, int]] = []
    if model.slug == "keyball44" and columns in (6, 7):
        for row in range(3):
            coordinates.extend(
                (f"L{row}{column}", row, column) for column in range(6)
            )
            coordinates.extend(
                (f"R{row}{column}", row + 4, column)
                for column in range(5, -1, -1)
            )
        left_columns = (1, 2, 3, 4, 5) if columns == 6 else (1, 2, 3, 5, 6)
        right_columns = (5, 4, 3, 2, 1) if columns == 6 else (6, 5, 4, 3, 2)
        coordinates.extend(
            (f"L3{index + 1}", 3, column)
            for index, column in enumerate(left_columns)
        )
        coordinates.extend(
            (f"R3{5 - index}", 7, column)
            for index, column in enumerate(right_columns)
        )
        optional = (("L32", "L33"), ("R32", "R33"))
    elif model.slug == "keyball39" and columns == 6:
        for row in range(3):
            coordinates.extend((f"L{row}{column}", row, column) for column in range(5))
            coordinates.extend(
                (f"R{row}{column}", row + 4, column)
                for column in range(4, -1, -1)
            )
        coordinates.extend((f"L3{column}", 3, column) for column in range(6))
        coordinates.extend(
            (f"R3{column}", 7, column) for column in range(5, -1, -1)
        )
        optional = (
            ("L31", "L32", "L33"),
            ("R31", "R32", "R33"),
        )
    else:
        raise ValueError(
            f"no reviewed physical ordering for {model.slug} {columns} columns"
        )

    absent_labels = {
        label
        for group in optional
        if all(_label_is_unused(layout, coordinates, label) for label in group)
        for label in group
    }
    return tuple(
        (label, row * columns + column)
        for label, row, column in coordinates
        if label not in absent_labels
    )


def _label_is_unused(
    layout: list[object], coordinates: Sequence[tuple[str, int, int]], label: str
) -> bool:
    row, column = next(
        (row, column) for candidate, row, column in coordinates if candidate == label
    )
    return all(layer[row][column] == "KC_NO" for layer in layout)


def _filtered_geometry(path: Path, positions: Sequence[tuple[str, int]]) -> bytes:
    try:
        geometry = json.loads(path.read_text())
        physical = geometry["layouts"]["LAYOUT_no_ball"]["layout"]
        by_label = {entry["label"]: entry for entry in physical}
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError(f"invalid pinned geometry {path}: {error}") from error
    labels = [label for label, _ in positions]
    if len(by_label) != len(physical) or any(label not in by_label for label in labels):
        raise ValueError(
            f"pinned geometry labels do not match reviewed {path.stem} ordering"
        )
    geometry["layouts"] = {
        "LAYOUT_no_ball": {"layout": [by_label[label] for label in labels]}
    }
    return (
        json.dumps(geometry, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def _normalize_converter_yaml(
    text: str,
    vil: Mapping[str, object],
    selected_layers: Sequence[int],
    positions: Sequence[tuple[str, int]],
    expected_key_count: int,
) -> bytes:
    layers, combos = _parse_converter_yaml(text)
    selected_names = [f"L{index}" for index in selected_layers]
    if any(name not in layers for name in selected_names):
        raise RenderError("converter YAML is missing a selected layer")
    selected_indices = [index for _, index in positions]
    old_to_new = {old: new for new, old in enumerate(selected_indices)}
    lines = [
        "layout: {}",
        "layers:",
    ]
    if any(
        len(values) != expected_key_count for values in layers.values()
    ):
        raise RenderError(
            "converter YAML layer does not match electrical matrix size "
            f"{expected_key_count}"
        )
    layout = vil["layout"]
    assert isinstance(layout, list)
    for name in selected_names:
        source_layer = layout[int(name[1:])]
        assert isinstance(source_layer, list)
        source_keycodes = [keycode for row in source_layer for keycode in row]
        lines.append(f"  {name}:")
        for label, index in positions:
            lines.append(
                "    - "
                + _serialize_key_spec(
                    _key_spec(source_keycodes[index], vil, label[:1])
                )
            )

    combo_definitions = _active_combo_definitions(vil)
    represented_definitions: set[int] = set()
    seen_definition_layers: set[tuple[int, int]] = set()
    correlated_combos: list[tuple[dict[str, object], str]] = []
    for combo in combos:
        if any(name not in layers for name in combo["l"]):
            raise RenderError("converter combo references an undeclared layer")
        if any(position >= expected_key_count for position in combo["p"]):
            raise RenderError("converter combo position exceeds electrical matrix")
        record_triggers: tuple[str, ...] | None = None
        record_layer_indices: list[int] = []
        for layer_name in combo["l"]:
            layer_index = int(layer_name[1:])
            record_layer_indices.append(layer_index)
            if layer_index >= len(layout):
                raise RenderError(
                    "converter combo layer does not match validated Vial layout"
                )
            source_layer = layout[layer_index]
            assert isinstance(source_layer, list)
            layer_keycodes = [keycode for row in source_layer for keycode in row]
            converter_triggers = tuple(
                layer_keycodes[position] for position in combo["p"]
            )
            if record_triggers is None:
                record_triggers = converter_triggers
            elif converter_triggers != record_triggers:
                raise RenderError(
                    "converter combo declares layers with inconsistent triggers"
                )
        assert record_triggers is not None
        matches = [
            (index, output_keycode)
            for index, (source_triggers, output_keycode) in enumerate(
                combo_definitions
            )
            if record_triggers == source_triggers
        ]
        if len(matches) != 1:
            raise RenderError(
                "converter combo trigger set does not match exactly one validated Vial combo"
            )
        definition_index, output_keycode = matches[0]
        for layer_index in record_layer_indices:
            definition_layer = (definition_index, layer_index)
            if definition_layer in seen_definition_layers:
                raise RenderError(
                    "converter combo contains a duplicate canonical combo layer record"
                )
            seen_definition_layers.add(definition_layer)
        represented_definitions.add(definition_index)
        correlated_combos.append((combo, output_keycode))
    if represented_definitions != set(range(len(combo_definitions))):
        raise RenderError(
            "converter combo coverage does not match every validated Vial combo"
        )

    normalized_combos = []
    for combo, output_keycode in correlated_combos:
        combo_layers = [name for name in combo.get("l", []) if name in selected_names]
        if not combo_layers:
            continue
        try:
            key_positions = [old_to_new[position] for position in combo["p"]]
        except (KeyError, TypeError) as error:
            raise RenderError("converter combo references a non-physical key") from error
        normalized = dict(combo)
        normalized["k"] = _key_spec(output_keycode, vil)
        normalized["l"] = combo_layers
        normalized["p"] = key_positions
        normalized_combos.append(normalized)
    if normalized_combos:
        lines.append("combos:")
        lines.extend(
            "  - "
            + json.dumps(combo, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            for combo in normalized_combos
        )
    return ("\n".join(lines) + "\n").encode()


def _active_combo_definitions(
    vil: Mapping[str, object],
) -> tuple[tuple[tuple[str, ...], str], ...]:
    combos = vil.get("combo", [])
    assert isinstance(combos, list)
    active = tuple(
        (tuple(keycode for keycode in entry[:4] if keycode != "KC_NO"), entry[4])
        for entry in combos
        if entry[4] != "KC_NO"
        and sum(keycode != "KC_NO" for keycode in entry[:4]) >= 2
    )
    trigger_sets = tuple(tuple(sorted(triggers)) for triggers, _ in active)
    if len(set(trigger_sets)) != len(trigger_sets):
        raise RenderError("validated Vial combos contain ambiguous duplicate triggers")
    return active


def _serialize_key_spec(spec: KeySpec) -> str:
    return json.dumps(spec, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _parse_converter_yaml(text: str) -> tuple[dict[str, list[str]], list[dict[str, object]]]:
    lines = text.splitlines()
    if len(lines) < 2 or not lines[0].startswith("layout: ") or lines[1] != "layers:":
        raise RenderError("malformed converter YAML header")
    layers: dict[str, list[str]] = {}
    combos: list[dict[str, object]] = []
    current: list[str] | None = None
    section = "layers"
    for line in lines[2:]:
        layer_match = re.fullmatch(r"  (L[0-9]+):", line)
        if layer_match and section == "layers":
            name = layer_match.group(1)
            if name in layers:
                raise RenderError(f"duplicate converter layer: {name}")
            current = []
            layers[name] = current
        elif line == "combos:":
            section = "combos"
            current = None
        elif (
            section == "layers"
            and line.startswith("    - ")
            and current is not None
        ):
            value = line[6:]
            _validate_yaml_value(value)
            current.append(value)
        elif section == "combos" and line.startswith("  - "):
            try:
                combo = json.loads(line[4:])
            except json.JSONDecodeError as error:
                raise RenderError("malformed converter combo") from error
            if not isinstance(combo, dict):
                raise RenderError("malformed converter combo")
            _validate_converter_combo(combo)
            combos.append(combo)
        elif line:
            raise RenderError(f"unsupported converter YAML line: {line!r}")
    if not layers or any(not values for values in layers.values()):
        raise RenderError("converter YAML contains no complete layers")
    return layers, combos


def _validate_converter_combo(combo: Mapping[str, object]) -> None:
    if set(combo) != {"k", "l", "p"}:
        raise RenderError("malformed converter combo: expected only k, l, and p")
    key = combo["k"]
    if isinstance(key, str):
        valid_key = bool(key)
    elif isinstance(key, dict):
        valid_key = (
            bool(key)
            and set(key) <= {"t", "h", "s", "type"}
            and all(isinstance(value, str) for value in key.values())
        )
    else:
        valid_key = False
    if not valid_key:
        raise RenderError("malformed converter combo: k must be a key value")
    layers = combo["l"]
    if (
        not isinstance(layers, list)
        or not layers
        or any(
            not isinstance(layer, str)
            or re.fullmatch(r"L(?:0|[1-9][0-9]*)", layer) is None
            for layer in layers
        )
    ):
        raise RenderError("malformed converter combo: l must be a list of layers")
    positions = combo["p"]
    if (
        not isinstance(positions, list)
        or len(positions) < 2
        or any(
            not isinstance(position, int)
            or isinstance(position, bool)
            or position < 0
            for position in positions
        )
    ):
        raise RenderError(
            "malformed converter combo: p must contain non-negative positions"
        )


def _validate_yaml_value(value: str) -> None:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_+ -]*", value):
        return
    try:
        json.loads(value)
    except json.JSONDecodeError as error:
        raise RenderError(f"malformed converter key value: {value!r}") from error


def _validate_svg(path: Path) -> None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise RenderError("keymap-drawer did not create a non-empty SVG")
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        raise RenderError(f"keymap-drawer created malformed SVG: {error}") from error
    if root.tag.rsplit("}", 1)[-1] != "svg":
        raise RenderError("keymap-drawer output root is not SVG")


def load_and_validate_vil(path: Path, model: ModelConfig) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid Vial backup {path}: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError(f"invalid Vial backup for {model.slug}: root must be an object")

    protocols = _MODEL_PROTOCOLS.get(model.slug)
    if protocols is None:
        raise ValueError(f"unsupported Vial model: {model.slug}")
    for field, expected in zip(
        ("version", "vial_protocol", "via_protocol"), protocols, strict=True
    ):
        if raw.get(field) != expected or isinstance(raw.get(field), bool):
            raise ValueError(
                f"invalid Vial backup for {model.slug}: expected {field} {expected}"
            )
    if not isinstance(raw.get("uid"), int) or isinstance(raw["uid"], bool):
        raise ValueError(f"invalid Vial backup for {model.slug}: uid must be an integer")

    layout = raw.get("layout")
    if not isinstance(layout, list) or not layout:
        raise ValueError(f"invalid Vial layout for {model.slug}: expected non-empty layers")
    expected_shape: tuple[int, int] | None = None
    for layer_index, layer in enumerate(layout):
        shape = _validate_keycode_matrix(layer, f"layout[{layer_index}]")
        if expected_shape is None:
            expected_shape = shape
        elif shape != expected_shape:
            raise ValueError(
                f"invalid Vial layout layer {layer_index} shape: expected "
                f"{expected_shape[0]} rows and {expected_shape[1]} columns"
            )

    assert expected_shape is not None
    _validate_optional_structures(raw)
    if expected_shape not in model.matrix_shapes:
        raise ValueError(
            f"matrix shape {expected_shape} is not allowed for {model.slug}"
        )
    return raw


def reachable_layers(
    vil: Mapping[str, object], include_layers: Sequence[int] = ()
) -> tuple[int, ...]:
    layout = vil.get("layout")
    if not isinstance(layout, list) or not layout:
        raise ValueError("Vial layout must contain layer 0")
    included = _validate_layers(include_layers, len(layout), "include_layers")

    reachable = {0}
    pending = [0]
    global_keycodes = tuple(_global_keycodes(vil))
    globals_scanned = False
    while pending:
        layer_index = pending.pop()
        sources = list(_matrix_keycodes(layout[layer_index], f"layout[{layer_index}]"))
        if not globals_scanned:
            sources.extend(global_keycodes)
            globals_scanned = True
        for keycode, path in sources:
            for target in _layer_targets(keycode, path):
                if target < 0 or target >= len(layout):
                    raise ValueError(
                        f"layer action {keycode!r} at {path} references missing layer {target}"
                    )
                if target not in reachable:
                    reachable.add(target)
                    pending.append(target)

    return tuple(sorted(reachable | included))


def normalized_vil(vil: Mapping[str, object], layers: Sequence[int]) -> bytes:
    layout = vil.get("layout")
    if not isinstance(layout, list) or not layout:
        raise ValueError("Vial layout must contain layer 0")
    selected = _validate_layers(layers, len(layout), "layers")
    if not selected:
        raise ValueError("layers must contain at least one layer")

    layer_zero = layout[0]
    _validate_keycode_matrix(layer_zero, "layout[0]")
    blank = [["KC_NO" for _ in row] for row in layer_zero]
    last_layer = max(selected)
    normalized = copy.deepcopy(dict(vil))
    normalized["layout"] = [
        copy.deepcopy(layout[index] if index in selected else blank)
        for index in range(last_layer + 1)
    ]
    return (
        json.dumps(
            normalized,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()


def _validate_layers(
    layers: Sequence[int], layer_count: int, field: str
) -> set[int]:
    values: set[int] = set()
    for layer in layers:
        if (
            not isinstance(layer, int)
            or isinstance(layer, bool)
            or layer < 0
            or layer >= layer_count
        ):
            raise ValueError(
                f"{field} must contain integer layers present in the Vial layout"
            )
        values.add(layer)
    return values


def _validate_keycode_matrix(value: object, path: str) -> tuple[int, int]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"invalid Vial {path}: expected at least one row")
    column_count: int | None = None
    for row_index, row in enumerate(value):
        if not isinstance(row, list):
            raise ValueError(f"invalid Vial {path}[{row_index}]: expected a row")
        if not row:
            raise ValueError(
                f"invalid Vial {path}[{row_index}]: expected at least one column"
            )
        if column_count is None:
            column_count = len(row)
        elif len(row) != column_count:
            raise ValueError(
                f"invalid Vial {path}: jagged rows, expected {column_count} columns"
            )
        for column_index, keycode in enumerate(row):
            if not isinstance(keycode, str):
                raise ValueError(
                    f"invalid Vial {path}[{row_index}][{column_index}]: "
                    "expected a keycode string"
                )
    assert column_count is not None
    return len(value), column_count


def _validate_optional_structures(vil: Mapping[str, object]) -> None:
    combo = vil.get("combo", [])
    if not isinstance(combo, list):
        raise ValueError("invalid Vial combo: expected a list")
    for index, entry in enumerate(combo):
        if not isinstance(entry, list) or len(entry) != 5:
            raise ValueError(f"invalid Vial combo[{index}]: expected five keycodes")
        for key_index, keycode in enumerate(entry):
            if not isinstance(keycode, str):
                raise ValueError(
                    f"invalid Vial combo[{index}][{key_index}]: expected a keycode string"
                )

    tap_dance = vil.get("tap_dance", [])
    if not isinstance(tap_dance, list):
        raise ValueError("invalid Vial tap_dance: expected a list")
    for index, entry in enumerate(tap_dance):
        if (
            not isinstance(entry, list)
            or len(entry) != 5
            or any(not isinstance(keycode, str) for keycode in entry[:4])
            or not isinstance(entry[4], int)
            or isinstance(entry[4], bool)
        ):
            raise ValueError(
                f"invalid Vial tap_dance[{index}]: expected four keycodes and a timeout"
            )

    overrides = vil.get("key_override", [])
    if not isinstance(overrides, list):
        raise ValueError("invalid Vial key_override: expected a list")
    for index, entry in enumerate(overrides):
        if not isinstance(entry, dict) or any(
            not isinstance(entry.get(field), str) for field in ("trigger", "replacement")
        ):
            raise ValueError(
                f"invalid Vial key_override[{index}]: expected trigger and replacement keycodes"
            )

    macros = vil.get("macro", [])
    if not isinstance(macros, list):
        raise ValueError("invalid Vial macro: expected a list")
    for macro_index, macro in enumerate(macros):
        if not isinstance(macro, list):
            raise ValueError(f"invalid Vial macro[{macro_index}]: expected commands")
        for command_index, command in enumerate(macro):
            if not isinstance(command, list) or len(command) != 2:
                raise ValueError(
                    f"invalid Vial macro[{macro_index}][{command_index}]: "
                    "expected a command and value"
                )
            name, value = command
            command_path = f"macro[{macro_index}][{command_index}]"
            if name in {"tap", "down", "up"} and not isinstance(value, str):
                raise ValueError(
                    f"invalid Vial {command_path}: expected a keycode string"
                )
            if name == "text" and not isinstance(value, str):
                raise ValueError(f"invalid Vial {command_path}: expected text")
            if name == "delay" and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                raise ValueError(f"invalid Vial {command_path}: expected a delay")
            if name not in {"tap", "down", "up", "text", "delay"}:
                raise ValueError(f"invalid Vial {command_path}: unknown command {name!r}")

    alternate = vil.get("alt_repeat_key", [])
    if not isinstance(alternate, list):
        raise ValueError("invalid Vial alt_repeat_key: expected a list")
    for index, entry in enumerate(alternate):
        if not isinstance(entry, dict) or any(
            not isinstance(entry.get(field), str)
            for field in ("keycode", "alt_keycode")
        ):
            raise ValueError(
                f"invalid Vial alt_repeat_key[{index}]: expected keycode strings"
            )


def _matrix_keycodes(value: object, path: str):
    if not isinstance(value, list):
        raise ValueError(f"invalid Vial {path}: expected rows")
    for row_index, row in enumerate(value):
        if not isinstance(row, list):
            raise ValueError(f"invalid Vial {path}[{row_index}]: expected a row")
        for column_index, keycode in enumerate(row):
            if not isinstance(keycode, str):
                raise ValueError(
                    f"invalid Vial {path}[{row_index}][{column_index}]: expected keycode"
                )
            yield keycode, f"{path}[{row_index}][{column_index}]"


def _global_keycodes(vil: Mapping[str, object]):
    for index, entry in enumerate(vil.get("combo", [])):
        for key_index, keycode in enumerate(entry):
            yield keycode, f"combo[{index}][{key_index}]"

    for index, entry in enumerate(vil.get("tap_dance", [])):
        for key_index, keycode in enumerate(entry[:4]):
            yield keycode, f"tap_dance[{index}][{key_index}]"

    for index, entry in enumerate(vil.get("key_override", [])):
        for field in ("trigger", "replacement"):
            yield entry[field], f"key_override[{index}].{field}"

    keycode_commands = {"tap", "down", "up"}
    for macro_index, macro in enumerate(vil.get("macro", [])):
        for command_index, command in enumerate(macro):
            if command[0] in keycode_commands:
                yield command[1], f"macro[{macro_index}][{command_index}][1]"

    for index, entry in enumerate(vil.get("alt_repeat_key", [])):
        for field in ("keycode", "alt_keycode"):
            yield entry[field], f"alt_repeat_key[{index}].{field}"


def _layer_targets(keycode: str, path: str):
    if keycode == "QK_KB_10":
        yield 1
        return
    if keycode in _KEYBALL_NON_LAYER_KEYCODES or _known_atomic_keycode(keycode):
        return

    call = _CALL.fullmatch(keycode)
    if call is None:
        _warn_unknown(keycode, path)
        return
    name = call["name"]
    arguments = _split_arguments(call["arguments"])
    if arguments is None:
        _warn_invalid_action(keycode, path)
        return
    if name in _LAYER_ACTIONS:
        yield from _layer_action_targets(name, arguments, keycode, path)
        return
    if name in _KNOWN_WRAPPERS:
        if len(arguments) == 1 and arguments[0] in BASIC_KEYCODES:
            return
        _warn_invalid_keycode(keycode, path)
    elif name == "OSM":
        if len(arguments) == 1 and arguments[0] in _VALID_MODIFIERS:
            return
        _warn_invalid_keycode(keycode, path)
    elif name == "MT":
        if (
            len(arguments) == 2
            and arguments[0] in _VALID_MODIFIERS
            and arguments[1] in BASIC_KEYCODES
        ):
            return
        _warn_invalid_keycode(keycode, path)
    elif name == "TD":
        if len(arguments) == 1 and _canonical_number(arguments[0], 255):
            return
        _warn_invalid_keycode(keycode, path)
    else:
        _warn_unknown(keycode, path)
    for index, argument in enumerate(arguments):
        candidate = argument.strip()
        if candidate and candidate not in _VALID_MODIFIERS:
            yield from _layer_targets(candidate, f"{path}:{name}[{index}]")


def _layer_action_targets(
    name: str, arguments: tuple[str, ...], keycode: str, path: str
):
    expected_arity = 2 if name in {"LT", "LM"} else 1
    max_layer = 15 if name in {"LT", "LM"} else 31
    has_layer = bool(arguments) and arguments[0].isdigit()
    valid_layer = has_layer and _canonical_number(arguments[0], max_layer)
    valid_second_argument = (
        name not in {"LT", "LM"}
        or len(arguments) == 2
        and (
            arguments[1] in BASIC_KEYCODES
            if name == "LT"
            else arguments[1] in _VALID_MODIFIERS
        )
    )
    if (
        len(arguments) == expected_arity
        and valid_layer
        and valid_second_argument
    ):
        yield int(arguments[0])
        return

    _warn_invalid_action(keycode, path)
    if has_layer:
        yield int(arguments[0])
        nested = arguments[1:]
    else:
        nested = arguments
    for index, argument in enumerate(nested):
        candidate = argument.strip()
        if candidate and not candidate.isdigit():
            yield from _layer_targets(candidate, f"{path}:{name}[{index}]")


def _known_atomic_keycode(keycode: str) -> bool:
    return keycode in STANDARD_ATOMIC_KEYCODES


def _canonical_number(value: str, maximum: int) -> bool:
    return value.isdigit() and str(int(value)) == value and int(value) <= maximum


def _split_arguments(value: str) -> tuple[str, ...] | None:
    if not value:
        return ()
    arguments: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(value):
        if character == "(":
            depth += 1
        elif character == ")":
            if depth == 0:
                return None
            depth -= 1
        elif character == "," and depth == 0:
            arguments.append(value[start:index])
            start = index + 1
    if depth:
        return None
    arguments.append(value[start:])
    return tuple(arguments)


def _warn_unknown(keycode: str, path: str) -> None:
    warnings.warn(
        f"unknown custom keycode {keycode!r} at {path}; review whether it "
        "changes layers and add any hidden target to the model include_layers",
        UserWarning,
        stacklevel=3,
    )


def _warn_invalid_action(keycode: str, path: str) -> None:
    warnings.warn(
        f"invalid layer action {keycode!r} at {path}; review whether it "
        "changes layers and add any hidden target to the model include_layers",
        UserWarning,
        stacklevel=3,
    )


def _warn_invalid_keycode(keycode: str, path: str) -> None:
    warnings.warn(
        f"invalid Vial keycode {keycode!r} at {path}; review whether it "
        "changes layers and add any hidden target to the model include_layers",
        UserWarning,
        stacklevel=3,
    )
