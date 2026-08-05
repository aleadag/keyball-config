# Research: Macro-definition legends in Keyball renderings

> **Date:** 2026-08-06
> **Bead:** keyball44-6qh
> **Status:** Complete

## Summary

Yes. The saved Vial backup already contains each macro as an ordered list of
commands, and the renderer already resolves `QK_MACRO_n` keycodes before
serializing the keymap for keymap-drawer. The current limitation is local:
`_macro_label` only uses a macro's text when the macro consists of exactly one
text command, so the real `accept`, `continue`, and `reject` macros fall back to
`Macro 1`, `Macro 2`, and `Macro 3` because each also taps Enter.

## Key Findings

### The backup contains the macro definitions needed for a legend

> **Confidence:** high — the canonical backup and the repository's JSON
> inspection both expose the same command structure.

`keyball44.vil` stores four macros:

- macro 0: text `=>`
- macro 1: text `accept`, then tap `KC_ENTER`
- macro 2: text `continue`, then tap `KC_ENTER`
- macro 3: text `reject`, then tap `KC_ENTER`

The active keymap uses `QK_MACRO_1`, `QK_MACRO_2`, and `QK_MACRO_3` on layer 4.
This means the desired human-readable names are already present in the
canonical backup; no firmware or Vial export change is needed. [S1]

### The current fallback is caused by an overly narrow local rule

> **Confidence:** high — the condition and fallback are explicit in the
> current implementation, and the behavior is covered by a focused test.

`_macro_label` accepts only a macro with one printable `text` command of at
most eight characters. Any macro with a second command returns `Macro <index>`.
The current renderer therefore produces the labels `Macro 1`, `Macro 2`, and
`Macro 3` for the three multi-command macros. [S2]

### The existing rendering seam is sufficient

> **Confidence:** high — the renderer already passes each source keycode and
> the complete validated Vial object through the label-normalization path.

The renderer invokes `_key_spec(source_keycode, vil, ...)` for every selected
key and serializes the returned string or structured key specification into
the normalized YAML consumed by keymap-drawer. A macro legend can therefore be
implemented in `_macro_label` with focused unit tests; the Vial converter,
geometry code, and SVG post-validation do not need to change. [S3]

## Comparisons

| Label policy | Result for current macros | Trade-off |
|---|---|---|
| Use the first printable `text` command | `accept`, `continue`, `reject` | Compact and readable; does not show the trailing Enter action |
| Render every command | e.g. `accept` plus Enter | More complete, but likely too wide/noisy for a 52px key |
| Keep `Macro n` | `Macro 1`, `Macro 2`, `Macro 3` | Stable but does not explain what the key does |

## Codebase Context

- `keyball_config/keymap.py:240-258` resolves macro labels and contains the
  exact single-text restriction.
- `keyball_config/keymap.py:285-287` makes the resolved macro label the tap
  value before wrapper and tap-dance processing.
- `keyball_config/keymap.py:450-458` normalizes the generated YAML using the
  Vial-derived key specifications.
- `tests/test_keymap.py:342-350` covers the canonical macro index boundary and
  single-text labels, but does not cover a text command followed by Enter.
- `tests/test_keymap.py:455-467` already exercises multi-command macro data for
  layer reachability, so the Vial command shape is established in the tests.

## Recommendations

1. Change `_macro_label` to use a short printable `text` command as the macro
   legend even when the macro contains additional commands. Preserve the
   `Macro n` fallback when no useful text command exists.
2. Add tests for the real multi-command shape (`text` followed by `tap`) and
   for macros with no text command. Add one rendering-level assertion that the
   generated SVG contains `accept`, `continue`, and `reject` instead of the
   generic labels.
3. Start with the compact text-only legend. If the full command sequence is
   later desired, add a separate compact notation after inspecting the rendered
   result; raw command dumps would make these small keys hard to read.

## Recommended Beads

- `bd create "Show readable labels for multi-command Vial macros" -t feature -p 2 --notes "Severity: Important\nConfidence: Confirmed\nEvidence: keyball_config/keymap.py:240-258; keyball44.vil macro data"` — implement the recommended compact macro legend and its rendering tests.

## Open Questions

- Should the legend show only the macro's text name (`accept`) or also indicate
  the trailing Enter action? The compact text-only policy is recommended for the
  first change.

## Sources

- [Canonical Keyball44 Vial backup](https://github.com/aleadag/keyball-config/blob/main/keyball44.vil) — repository data — 2026-08-06 — macro command definitions and active `QK_MACRO_n` placements.
- [Macro label resolution](https://github.com/aleadag/keyball-config/blob/main/keyball_config/keymap.py#L240-L258) — repository implementation — 2026-08-06 — single-text restriction and generic fallback.
- [Keymap normalization path](https://github.com/aleadag/keyball-config/blob/main/keyball_config/keymap.py#L450-L458) — repository implementation — 2026-08-06 — Vial-derived key specs are serialized before keymap-drawer runs.
- [Macro label tests](https://github.com/aleadag/keyball-config/blob/main/tests/test_keymap.py#L342-L350) — repository tests — 2026-08-06 — canonical macro indices and single-text behavior.
- [keymap-drawer README](https://github.com/caksoylar/keymap-drawer/blob/v0.23.0/README.md) — Primary/Official — 2026-03-17 — keymap YAML to SVG rendering interface.
