# Macro-definition legends Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use beads-superpowers:subagent-driven-development (recommended) or beads-superpowers:executing-plans to implement this plan task-by-task. Each Task becomes a bead (`bd create -t task --parent <epic-id>`). Steps within tasks use checkbox (`- [ ]`) syntax for human readability.

**Goal:** Display the first short printable text command from multi-command Vial macros as their key legend.

**Architecture:** Keep the change inside `_macro_label`, the existing per-key
label seam. The helper will scan validated macro commands for a useful text
value, while preserving the current canonical index and generic fallback
behavior. Unit tests will prove the new policy and its fallback without
touching the converter or geometry pipeline.

**Tech Stack:** Python 3.13, `unittest`, Nix development shell, keymap-drawer integration checks.

## Global Constraints

- Only canonical `QK_MACRO_0` through `QK_MACRO_31` receive macro expansion.
- A displayed macro text must be printable and between one and eight characters.
- Macros without a useful text command continue to display `Macro <index>`.
- Do not change Vial validation, backup serialization, converter invocation, geometry, or site structure.

---

### Task 1: Add the failing macro-label regression tests

**Files:**
- Modify: `tests/test_keymap.py` near `KeyLegendTests.test_numeric_aliases_require_canonical_pinned_indices`

**Interfaces:**
- Consumes: existing `fixture_vil` and `_key_spec` helpers.
- Produces: regression coverage showing the approved behavior before the implementation changes.

**Acceptance Criteria:**
- A macro with `tap KC_ENTER` followed by `text accept` is expected to render as `accept`.
- A macro containing no useful text is expected to retain `Macro 0`.

- [x] **Step 1: Write the failing tests**

```python
    def test_multi_command_macros_use_their_short_text_label(self) -> None:
        vil = fixture_vil({0: ["KC_A"]})
        vil["macro"] = [[["tap", "KC_ENTER"], ["text", "accept"]]]

        self.assertEqual(_key_spec("QK_MACRO_0", vil), "accept")

    def test_macros_without_text_keep_the_generic_label(self) -> None:
        vil = fixture_vil({0: ["KC_A"]})
        vil["macro"] = [[["tap", "KC_ENTER"], ["delay", 100]]]

        self.assertEqual(_key_spec("QK_MACRO_0", vil), "Macro 0")
```

- [x] **Step 2: Run the tests and verify the new behavior fails**

Run:

```bash
nix develop path:. --command python -m unittest tests.test_keymap.KeyLegendTests.test_multi_command_macros_use_their_short_text_label tests.test_keymap.KeyLegendTests.test_macros_without_text_keep_the_generic_label
```

Expected: the first test fails because the current helper returns `Macro 0` for a multi-command macro; the fallback test remains green.

### Task 2: Expand the macro label scan minimally

**Files:**
- Modify: `keyball_config/keymap.py:240-258`

**Interfaces:**
- Consumes: the validated Vial macro command list already passed through `vil`.
- Produces: the existing `str | None` label result used by `_key_spec_nested`.

**Acceptance Criteria:**
- The first suitable `text` command is returned regardless of other commands in the macro.
- Invalid or non-text commands do not become legends.
- Existing single-text labels and generic fallbacks remain unchanged.

- [x] **Step 1: Implement only the scan needed by the failing test**

Replace the exact-single-command condition with a loop over the macro commands:

```python
    if isinstance(macro, list):
        for command in macro:
            if (
                isinstance(command, list)
                and len(command) == 2
                and command[0] == "text"
                and isinstance(command[1], str)
                and 0 < len(command[1]) <= 8
                and all(character.isprintable() for character in command[1])
            ):
                return command[1]
    return f"Macro {index}"
```

- [x] **Step 2: Run the two regression tests again**

Run the command from Task 1. Expected: both tests pass.

### Task 3: Run the complete verification gates

**Files:**
- No additional files.

**Interfaces:**
- Consumes: the updated macro label helper and its tests.
- Produces: verified keymap labels with no unrelated renderer changes.

**Acceptance Criteria:**
- The complete keymap and backup test suites pass.
- All Nix flake checks pass, including the real converter/SVG checks.
- The working tree contains only the intended source/test changes plus the existing internal research/spec/plan notes.

- [x] **Step 1: Run the focused suites**

```bash
nix develop path:. --command python -m unittest tests.test_keymap tests.test_backup
```

- [x] **Step 2: Run all flake checks**

```bash
nix flake check --print-build-logs
```

- [x] **Step 3: Inspect the final diff and status**

```bash
git diff --check
git diff --stat
git status -sb
```

Expected: no whitespace errors, the macro helper and focused tests are the
only implementation changes, and no generated render output is left in the
repository.
