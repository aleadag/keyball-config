# Live Vial Definition Backup Design

**Status:** Approved by the user on 2026-08-05.

## Goal

Make each backup self-describing enough to reproduce the physical drawing Vial
shows for the connected firmware. The existing `.vil` keymap remains the
canonical configuration, while the live Vial definition is captured as a
paired rendering input.

## Decision

`nix run .#backup` will produce two sibling files for the detected model:

- `<model>.vil`: the existing Vial keymap/settings export.
- `<model>.vial.json`: the raw Vial definition downloaded from the keyboard,
  including `matrix`, `layouts.keymap`, and `layouts.labels`.

The pinned Vitaly package will be patched with a `save --definition <path>`
option. Vitaly already downloads the Vial definition while saving; the option
writes that same parsed definition without adding it to the `.vil` format.

The Python backup flow will validate both temporary outputs, re-check both
repository targets for concurrent changes, and publish the pair with rollback
if the second replacement fails. Existing dirty-target, inode, symlink, and
export validation protections remain in force.

## Rendering

When the sibling `.vial.json` exists, rendering will parse its KLE
`layouts.keymap` data. It will select the active layout-option variant from the
`.vil` `layout_options` value, map KLE wire coordinates to the validated Vial
matrix positions, preserve KLE offsets and rotations as QMK-style geometry,
and pass the generated geometry to keymap-drawer.

Older repositories that contain only `.vil` files will continue to render from
the pinned QMK `info.json` geometry. A present but malformed companion file is
an error rather than a silent fallback.

## Boundaries and safety

- The backup command reads the connected keyboard; it does not mutate device
  state.
- The live definition is stored separately from `.vil`, so Vitaly can still
  load the canonical configuration without depending on custom fields.
- Only model-derived, repository-root companion filenames are accepted.
- The Nix source filter includes companion snapshots as inputs but generated
  site output continues to exclude backup and intermediate files.

## Verification

Tests will cover the Vitaly command arguments, definition-file validation,
companion-target safety, cleanup and rollback behavior, KLE option selection,
rotation/offset preservation, malformed definitions, legacy fallback, and
deterministic rendering. The full `nix flake check --print-build-logs` gate
must pass before the feature bead is closed.
