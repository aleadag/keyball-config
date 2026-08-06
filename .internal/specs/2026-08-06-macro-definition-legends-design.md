# Macro-definition legends design

> **Date:** 2026-08-06
> **Research:** `.internal/research/2026-08-06-macro-definition-legends.md`
> **Bead:** `keyball44-fre`

## Goal

Show a short, useful legend for Vial macros whose definition includes a text
command followed by other commands. For the current Keyball44 backup, the
macro keys should read `accept`, `continue`, and `reject` instead of generic
`Macro 1`, `Macro 2`, and `Macro 3`.

## Decision

Extend the existing `_macro_label` policy in `keyball_config/keymap.py`:

1. Recognize canonical `QK_MACRO_0` through `QK_MACRO_31` as today.
2. Scan the macro's commands for the first `text` command whose value is a
   printable string of one to eight characters.
3. Return that text as the key legend even when the macro has additional
   `tap`, `down`, `up`, or `delay` commands.
4. Retain `Macro <index>` when the macro has no useful text command, when the
   index is absent, or when the keycode is outside the pinned canonical range.

The renderer, Vial converter, geometry path, and site contract remain
unchanged. The change is intentionally a compact per-key legend; it does not
attempt to serialize every macro command onto a small keycap.

## Testing

Add focused unit coverage for a text command after another command and for a
macro with no text command. Existing canonical-index and single-text tests
must remain green. Run the focused keymap suite and the complete Nix flake
checks, including the real rendering checks.

## Out of scope

- Showing the trailing Enter action or arbitrary macro command sequences in the
  keycap legend.
- Adding a separate macro reference table to the generated site.
- Changing macro validation, backup format, converter behavior, or geometry.

## Follow-up decision (2026-08-06)

Macro legends use the native keymap-drawer corner field `tr`: the generated
spec is `{"t": "<label>", "tr": "M"}`. The top-right `M` distinguishes a
macro from friendly app-key labels without widening the main legend.

The displayed macro text command is limited to six characters. Text longer
than six characters keeps its first five characters and receives the
single-character ellipsis `…`; the original macro text remains unchanged in
the canonical Vial backup. Generic `Macro <index>` fallbacks retain their
index and are not truncated. The generated site legend explains both the `M`
marker and the ellipsis.
