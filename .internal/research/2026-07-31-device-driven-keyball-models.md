# Research: Device-driven Keyball39 and Keyball44 workflow

> **Date:** 2026-07-31
> **Bead:** keyball44-34p
> **Status:** Complete

## Summary

Vitaly can enumerate compatible keyboards and expose their USB product name and product ID, but v0.1.32 has no machine-readable device output and its `-i` selector is product-ID-only. A safe generalized backup must parse the pinned output format, require exactly one compatible device, normalize a supported 39/44 product name to a stable model slug, and select pinned model-specific physical geometry.

## Key Findings

### Device discovery is human-readable and version-sensitive

> **Confidence:** high — the tagged Vitaly source and live command agree, and the source claim was independently verified.

`vitaly devices` prints records containing product name, product ID, manufacturer, vendor ID, release, serial, and HID path. Vitaly v0.1.32 exposes no JSON output flag. Its global `-i` option filters only on USB product ID, so it is not a guaranteed unique-device selector. [S1] [S2]

The live device currently reports:

```text
Product name: "trackball 44 V3" id: 16718,
Manufacturer name: "MCK", id: 16717,
Release: 1, Serial: "vial:f64c2b3c", Path: "/dev/hidraw3"
```

That identity differs from upstream Keyball44's product metadata. The workflow must not use upstream VID/PID as the installed-firmware detection key.

### Detection should fail closed before backup

> **Confidence:** high — Vitaly's enumeration and PID-only filter directly imply the collision/multiple-device risk; exact model-name policy remains a design choice.

The backup wrapper should parse the version-pinned output and require exactly one compatible device overall. Zero devices, multiple devices, or one unrecognized device must fail before creating or replacing a backup. Once recognized, the wrapper may pass the observed PID to `vitaly -i`, but the one-device invariant is what prevents accidental multi-device writes.

The verified Keyball44 product string is `trackball 44 V3`. No live Keyball39 product string was available in this session, so an exact Keyball39 allowlist cannot yet be grounded. The design must either accept a conservative `keyball|trackball` plus `39|44` recognizer or obtain an actual Keyball39 sample before implementing an exact allowlist.

### Both models have distinct pinned physical metadata

> **Confidence:** high — the official model-specific metadata directly identifies each keyboard and layout, and the claim was independently verified.

The official Yowkees/keyball repository contains separate Keyball39 and Keyball44 metadata. Both expose `LAYOUT_no_ball`; their model-specific `via.json` files contain the richer staggered/rotated geometry and ball-availability layout options. Pin the upstream repository commit and select the corresponding metadata from the normalized model slug. [S3] [S4] [S5]

## Comparisons

| Detection policy | Generality | False-positive risk | Missing evidence |
|---|---|---|---|
| Conservative name recognizer (`keyball`/`trackball` + exact model number) | Supports firmware display-name variants | Low but non-zero | Keyball39 live name |
| Exact product-name allowlist | Fail-closed and auditable | Lowest | Cannot support Keyball39 until sampled |
| Upstream VID/PID mapping | Simple | Already wrong for the live custom firmware | Not viable |

## Codebase Context

The tracked backup is currently named `keyball44.vil`, and the in-progress design was initially model-specific. Live enumeration confirms a Keyball44-compatible Vial device, but its custom firmware identity is `trackball 44 V3` with VID/PID `16717/16718`. No Keyball39 device was connected for verification.

## Recommendations

1. Make the backup command parse `vitaly devices` from the pinned Vitaly version and require exactly one enumerated compatible device.
2. Normalize the observed product name to `keyball39` or `keyball44`; never infer the model from upstream VID/PID.
3. Use the normalized slug for backup naming, geometry selection, local output, and Pages navigation.
4. Pin the official Keyball repository and use model-specific geometry.
5. Derive visible/reachable layers from each `.vil` rather than retaining the Keyball44-specific layer list in shared logic.

## Open Questions

- Should model detection use a conservative name recognizer, or wait for an exact Keyball39 product-name sample?
- Should one repository retain backups for both models simultaneously, or represent only the most recently detected model?

## Sources

- [Vitaly v0.1.32 README](https://github.com/bskaplou/vitaly/blob/v0.1.32/README.md) — Primary/Official — 2026-01-14 — device output and selection behavior.
- [Vitaly v0.1.32 CLI source](https://github.com/bskaplou/vitaly/blob/v0.1.32/src/main.rs) — Primary/Official — 2026-01-14 — arguments, PID filtering, and output format.
- [Keyball39 `info.json`](https://github.com/Yowkees/keyball/blob/78de67c49f38836aca06bccd87b42d297d89e1b4/qmk_firmware/keyboards/keyball/keyball39/info.json) — Primary/Official — 2026-07-22 — model and QMK layout metadata.
- [Keyball44 `info.json`](https://github.com/Yowkees/keyball/blob/78de67c49f38836aca06bccd87b42d297d89e1b4/qmk_firmware/keyboards/keyball/keyball44/info.json) — Primary/Official — 2026-07-22 — model and QMK layout metadata.
- [Keyball39 `via.json`](https://github.com/Yowkees/keyball/blob/78de67c49f38836aca06bccd87b42d297d89e1b4/qmk_firmware/keyboards/keyball/keyball39/via.json) and [Keyball44 `via.json`](https://github.com/Yowkees/keyball/blob/78de67c49f38836aca06bccd87b42d297d89e1b4/qmk_firmware/keyboards/keyball/keyball44/via.json) — Primary/Official — 2026-07-22 — physical geometry and layout options.
- [QMK `info.json` reference](https://docs.qmk.fm/reference_info_json#layouts) — Primary/Official — 2026-07-31 — physical layout schema.
