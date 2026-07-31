from __future__ import annotations

import copy
import json
from pathlib import Path
import re
from typing import Mapping, Sequence
import warnings

from keyball_config.devices import ModelConfig


_LAYER_ACTIONS = {"MO", "LT", "TG", "TO", "DF", "OSL"}
_KEYBALL_NON_LAYER_KEYCODES = {
    *(f"QK_KB_{index}" for index in range(10)),
    *(f"QK_KB_{index}" for index in range(11, 17)),
}
_KNOWN_WRAPPERS = {
    "A",
    "C",
    "G",
    "HYPR",
    "LALT",
    "LCAG",
    "LCTL",
    "LGUI",
    "LSFT",
    "MEH",
    "MT",
    "OSM",
    "RALT",
    "RCTL",
    "RGUI",
    "RSFT",
    "S",
}
_KNOWN_ATOMIC_KEYCODES = {
    "_______",
    "XXXXXXX",
    *(f"KC_{value}" for value in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
    *(f"KC_F{value}" for value in range(1, 12)),
    "KC_APPLICATION",
    "KC_BACKSLASH",
    "KC_BACKSPACE",
    "KC_COMMA",
    "KC_DELETE",
    "KC_DOT",
    "KC_DOWN",
    "KC_END",
    "KC_ENTER",
    "KC_EQUAL",
    "KC_ESCAPE",
    "KC_GRAVE",
    "KC_HOME",
    "KC_INTERNATIONAL_1",
    "KC_KP_ASTERISK",
    "KC_KP_MINUS",
    "KC_KP_PLUS",
    "KC_KP_SLASH",
    "KC_LANGUAGE_1",
    "KC_LEFT",
    "KC_LEFT_ALT",
    "KC_LEFT_BRACKET",
    "KC_LEFT_CTRL",
    "KC_LEFT_GUI",
    "KC_LEFT_SHIFT",
    "KC_MINUS",
    "KC_NO",
    "KC_PAGE_DOWN",
    "KC_PAGE_UP",
    "KC_PRINT_SCREEN",
    "KC_QUOTE",
    "KC_RIGHT",
    "KC_RIGHT_BRACKET",
    "KC_SEMICOLON",
    "KC_SLASH",
    "KC_SPACE",
    "KC_TAB",
    "KC_TRANSPARENT",
    "KC_TRNS",
    "KC_UP",
    "MOD_LALT",
    "MOD_LCTL",
    "MOD_LGUI",
    "MOD_LSFT",
    "MOD_RALT",
    "MOD_RCTL",
    "MOD_RGUI",
    "MOD_RSFT",
    "QK_MACRO_0",
    "QK_MOUSE_BUTTON_1",
    "QK_MOUSE_BUTTON_2",
    "QK_MOUSE_BUTTON_3",
    "QK_MOUSE_BUTTON_4",
    "QK_MOUSE_CURSOR_DOWN",
    "QK_MOUSE_CURSOR_LEFT",
    "QK_MOUSE_CURSOR_RIGHT",
    "QK_MOUSE_CURSOR_UP",
}
_CALL = re.compile(r"(?P<name>[A-Z][A-Z0-9_]*)\((?P<arguments>.*)\)")
_MODEL_PROTOCOLS = {
    "keyball39": (1, 6, 9),
    "keyball44": (1, 6, 9),
}


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

    _validate_optional_structures(raw)
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
    elif name == "TD":
        nested = ()
    elif name in _KNOWN_WRAPPERS:
        nested = arguments
    else:
        _warn_unknown(keycode, path)
        nested = arguments
    for index, argument in enumerate(nested):
        yield from _layer_targets(argument.strip(), f"{path}:{name}[{index}]")


def _layer_action_targets(
    name: str, arguments: tuple[str, ...], keycode: str, path: str
):
    expected_arity = 2 if name == "LT" else 1
    has_layer = bool(arguments) and arguments[0].strip().isdigit()
    valid_tap_key = (
        name != "LT"
        or len(arguments) == 2
        and _known_atomic_keycode(arguments[1].strip())
    )
    if len(arguments) == expected_arity and has_layer and valid_tap_key:
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
    return keycode in _KNOWN_ATOMIC_KEYCODES


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
