from __future__ import annotations

import copy
from itertools import product
import json
from pathlib import Path
import re
from typing import Mapping, Sequence
import warnings

from keyball_config.devices import ModelConfig
from keyball_config.vitaly_v6_keycodes import (
    BASIC_KEYCODES,
    STANDARD_ATOMIC_KEYCODES,
)


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
