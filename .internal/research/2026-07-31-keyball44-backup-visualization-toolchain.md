# Research: Keyball44 backup and visualization toolchain

> **Date:** 2026-07-31
> **Bead:** keyball44-0op
> **Status:** Complete

## Summary

The supported workflow is `vitaly` backup to `.vil`, conversion of that Vial-specific JSON to keymap-drawer YAML, then SVG rendering. `keymap-drawer` cannot parse `.vil` directly, so a pinned Vial-aware converter is required; a Nix flake can provide all three tools reproducibly.

## Key Findings

### The `.vil` backup is the authoritative device snapshot

> **Confidence:** high — the tagged Vitaly documentation and implementation agree, and the documentation claim was independently re-fetched.

Vitaly v0.1.32 documents `vitaly -i <product-id> save -f <file>.vil` as the command that dumps the current configuration to a file. Without `-i`, Vitaly runs subcommands against every connected compatible device, so the workflow should select the Keyball44 product ID and document that only one matching device should be connected. [S1]

The existing `keyball44.vil` is compact JSON containing 10 layers, three configured combos, one configured tap dance, settings, macros, overrides, and protocol metadata. It is therefore a fuller backup than a layer-only keymap representation.

### keymap-drawer needs an intermediate YAML file

> **Confidence:** high — the version-pinned official README and CLI source directly describe the accepted inputs and outputs, and the claim was independently re-fetched.

keymap-drawer v0.23.0 parses QMK JSON, ZMK keymaps, or experimental Kanata configuration; it does not expose a Vial `.vil` parser. Its draw command consumes keymap YAML and emits SVG. The official README lists YellowAfterlife's Vial To Keymap Drawer as the separate converter for `.vil` files. [S2] [S3]

### The existing Vial converter has a scriptable native path

> **Confidence:** high — the converter README directly documents the conversion purpose and native invocation, and the claim was independently re-fetched.

YAL-Tools/vial-to-keymap-drawer converts `.vil` files to keymap-drawer YAML. On Linux and macOS its native build runs under Neko and accepts command-line options for the keyboard, layout ordering, layer names, key labels, and output file. The converter should be pinned to a commit because it has no tagged package release. [S3]

The converter warns that Vial's stored key order may differ from QMK's physical order. Keyball44 conversion therefore needs a one-time checked ordering/layout configuration, followed by a repeatable conversion command. [S3]

### Nix can provide a reproducible environment

> **Confidence:** high for x86_64 Linux — current nixpkgs evaluation and a clean Vitaly derivation build succeeded; Darwin was not build-tested.

Current nixpkgs provides `keymap-drawer` 0.23.0 as the `keymap` executable and provides Neko 2.4.1. It does not provide a `vitaly` package. Vitaly can be packaged locally with `rustPlatform.buildRustPackage`, pinned to v0.1.32 with its upstream `Cargo.lock`; Linux requires `pkg-config` and `udev`. [S1] [S4] [S5]

## Comparisons

| Approach | Fidelity | Reproducibility | Maintenance |
|---|---|---|---|
| Pinned Vial converter → YAML → SVG | Preserves Vial-aware features and supports labels/ordering | High when converter and nixpkgs are pinned | Two small local Nix packages/wrappers |
| Hand-maintained YAML | Can be polished manually | High | Can drift from the device backup |
| New repo-specific converter | Potentially exact for this file | High | Reimplements keycodes, combos, tap dances, and ordering |

## Codebase Context

The repository currently contains `keyball44.vil` and project/agent metadata only. The backup is valid JSON with Vial protocol 6 and VIA protocol 9 data. There is no flake, task runner, converter configuration, keymap YAML, SVG, README, or prior Beads knowledge entry for this workflow.

## Recommendations

1. Treat `keyball44.vil` as the canonical restorable backup.
2. Pin nixpkgs, Vitaly v0.1.32, keymap-drawer 0.23.0, and a specific Vial converter commit in a flake.
3. Provide separate `backup`, `render`, and combined `update` commands so rendering can be tested without a connected keyboard.
4. Use the upstream Vial converter, with tracked Keyball44-specific ordering and label configuration, rather than writing a new parser.
5. Render a tracked SVG for immediate viewing. Decide during design whether the generated YAML is also tracked or treated as a build artifact.
6. Make backup fail before replacing the prior `.vil` when no unique intended keyboard is available, and generate outputs through temporary files before atomic replacement.

## Open Questions

- Should the generated, human-editable `keyball44.yaml` be committed, or generated locally from the canonical `.vil`?
- Which Keyball44 product ID should the backup command select?
- Should empty layers 5 and 6 and alternate layouts 7–9 be included in the default visualization?

## Sources

- [Vitaly v0.1.32 README](https://github.com/bskaplou/vitaly/blob/v0.1.32/README.md) — Primary/Official — 2026-01-14 — save command, device selection, installation.
- [Vitaly v0.1.32 save implementation](https://github.com/bskaplou/vitaly/blob/v0.1.32/src/commands/save.rs) — Primary/Official — 2026-01-14 — serialized backup scope and file write.
- [keymap-drawer v0.23.0 README](https://github.com/caksoylar/keymap-drawer/blob/v0.23.0/README.md) — Primary/Official — 2026-03-17 — parse/draw pipeline and Vial converter reference.
- [keymap-drawer v0.23.0 CLI source](https://github.com/caksoylar/keymap-drawer/blob/v0.23.0/keymap_drawer/__main__.py) — Primary/Official — 2026-03-17 — accepted inputs and output formats.
- [Vial To Keymap Drawer README](https://github.com/YAL-Tools/vial-to-keymap-drawer/blob/fb1af9de01ff7edc8bf0230e65c84e40645503ad/README.md) — Primary/Official — 2026-04-21 — native converter usage and ordering caveats.
- [keymap-drawer on PyPI](https://pypi.org/project/keymap-drawer/) — Primary/Registry — 2026-03-17 — current version and Python requirement.
