from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ModelConfig:
    slug: str
    backup_filename: str
    name_tokens: tuple[str, ...]
    model_number: str
    geometry_path: str
    converter_args: tuple[str, ...]
    page_label: str
    include_layers: tuple[int, ...]


@dataclass(frozen=True)
class DeviceRecord:
    product_name: str
    product_id: int
    manufacturer_name: str
    vendor_id: int
    release: int
    serial: str
    path: str


_PRODUCT_LINE = re.compile(r'Product name: "(?P<name>[^"]*)" id: (?P<id>\d+),')
_MANUFACTURER_LINE = re.compile(
    r'Manufacturer name: "(?P<name>[^"]*)", id: (?P<id>\d+),'
)
_DETAIL_LINE = re.compile(
    r'Release: (?P<release>\d+), Serial: "(?P<serial>[^"]*)", Path: "(?P<path>[^"]*)"'
)


def load_registry(path: Path) -> dict[str, ModelConfig]:
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid model registry {path}: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("model registry must be an object keyed by slug")

    models: dict[str, ModelConfig] = {}
    for slug, entry in raw.items():
        if not isinstance(slug, str) or not isinstance(entry, dict):
            raise ValueError("model registry entries must have string slugs and object values")
        models[slug] = _parse_model(slug, entry)
    if not models:
        raise ValueError("model registry must define at least one model")
    return models


def parse_devices(output: str) -> tuple[DeviceRecord, ...]:
    if not output:
        return ()

    lines = output.splitlines()
    records: list[DeviceRecord] = []
    index = 0
    while index < len(lines):
        if len(lines) - index < 3:
            raise ValueError(
                "malformed Vitaly device output: expected complete three-line records"
            )
        product = _PRODUCT_LINE.fullmatch(lines[index])
        manufacturer = _MANUFACTURER_LINE.fullmatch(lines[index + 1])
        details = _DETAIL_LINE.fullmatch(lines[index + 2])
        if not product or not manufacturer or not details:
            raise ValueError(
                "malformed Vitaly device output: expected complete three-line records "
                f"at record {index // 3 + 1}"
            )
        records.append(
            DeviceRecord(
                product_name=product["name"],
                product_id=int(product["id"]),
                manufacturer_name=manufacturer["name"],
                vendor_id=int(manufacturer["id"]),
                release=int(details["release"]),
                serial=details["serial"],
                path=details["path"],
            )
        )
        index += 3
        if index < len(lines) and lines[index] == "":
            index += 1
    return tuple(records)


def select_device(
    records: Sequence[DeviceRecord], models: Mapping[str, ModelConfig]
) -> tuple[DeviceRecord, ModelConfig]:
    if not records:
        raise ValueError("no compatible devices reported by Vitaly")

    product_ids = [record.product_id for record in records]
    duplicate_ids = sorted({value for value in product_ids if product_ids.count(value) > 1})
    if duplicate_ids:
        raise ValueError(
            "Vitaly selector collision for product ID "
            + ", ".join(str(value) for value in duplicate_ids)
        )
    if len(records) != 1:
        raise ValueError(
            f"expected exactly one compatible device, Vitaly reported {len(records)}"
        )

    device = records[0]
    matches = [model for model in models.values() if _matches_model(device.product_name, model)]
    if not matches:
        raise ValueError(f"unsupported product name: {device.product_name!r}")
    if len(matches) != 1:
        raise ValueError(f"ambiguous product name: {device.product_name!r}")
    return device, matches[0]


def _parse_model(slug: str, entry: dict[str, object]) -> ModelConfig:
    required_strings = (
        "slug",
        "backup_filename",
        "model_number",
        "geometry_path",
        "page_label",
    )
    for field in required_strings:
        if not isinstance(entry.get(field), str) or not entry[field]:
            raise ValueError(f"model {slug!r} has invalid {field}")
    if entry["slug"] != slug:
        raise ValueError(f"model registry key {slug!r} does not match its slug")

    geometry_path = str(entry["geometry_path"])
    geometry = Path(geometry_path)
    if geometry.is_absolute() or ".." in geometry.parts:
        raise ValueError(f"model {slug!r} geometry_path must be authored and relative")

    name_tokens = _string_tuple(entry.get("name_tokens"), slug, "name_tokens")
    converter_args = _string_tuple(entry.get("converter_args"), slug, "converter_args")
    include_layers = entry.get("include_layers")
    if not isinstance(include_layers, list) or any(
        not isinstance(layer, int) or isinstance(layer, bool) or layer < 0
        for layer in include_layers
    ):
        raise ValueError(f"model {slug!r} has invalid include_layers")

    return ModelConfig(
        slug=slug,
        backup_filename=str(entry["backup_filename"]),
        name_tokens=name_tokens,
        model_number=str(entry["model_number"]),
        geometry_path=geometry_path,
        converter_args=converter_args,
        page_label=str(entry["page_label"]),
        include_layers=tuple(include_layers),
    )


def _string_tuple(value: object, slug: str, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ValueError(f"model {slug!r} has invalid {field}")
    return tuple(value)


def _matches_model(product_name: str, model: ModelConfig) -> bool:
    name = product_name.casefold()
    has_name_token = any(
        re.search(rf"(?<![a-z0-9]){re.escape(token.casefold())}(?![a-z0-9])", name)
        for token in model.name_tokens
    )
    has_model_number = re.search(
        rf"(?<![a-z0-9]){re.escape(model.model_number)}(?![a-z0-9])", name
    )
    return has_name_token and has_model_number is not None
