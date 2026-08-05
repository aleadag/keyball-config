# Live Vial Definition Backup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use beads-superpowers:subagent-driven-development (recommended) or beads-superpowers:executing-plans to implement this plan task-by-task. Each Task becomes a bead (`bd create -t task --parent <epic-id>`); Steps within tasks use checkbox (`- [ ]`) syntax for human readability.

**Goal:** Capture the live Vial definition beside each `.vil` backup and use its KLE geometry for faithful Keyball drawings.

**Architecture:** The pinned Vitaly source gains an optional definition output on its existing `save` command, so the metadata fetched during a save is written once and stays consistent with the exported keymap. Python keeps both outputs private until they validate, then replaces the model backup and companion definition with rollback protection. Rendering prefers the companion definition, converts its active KLE keys into the QMK geometry shape already consumed by keymap-drawer, and retains the pinned `info.json` path for legacy backups.

**Tech Stack:** Rust patch applied by Nix, Python 3 standard library, JSON/KLE parsing, unittest, Nix flake checks, keymap-drawer 0.23.0.

## Global Constraints

- Keep the existing `.vil` format unchanged; store live metadata in `<slug>.vial.json`.
- Preserve all existing dirty-target, inode, symlink, and atomic single-file backup protections.
- Never query or mutate the keyboard outside the existing Vitaly backup workflow.
- Do not add Python runtime dependencies; use the standard library for KLE parsing.
- Preserve rendering of repositories that have `.vil` files but no companion definition.
- A malformed existing companion must fail rendering rather than silently use stale geometry.

---

### Task 1: Export the live Vial definition from pinned Vitaly

**Files:**
- Create: `nix/vitaly-save-definition.patch`
- Modify: `nix/vitaly.nix`
- Test: `tests/test_backup.py`

**Interfaces:**
- Adds `vitaly save -d <definition-file>` to the pinned CLI.
- Keeps the existing `vitaly save -f <vil-file>` output and success transcript unchanged.

**Acceptance Criteria:**
- Vitaly writes the parsed Vial definition it already loads to the requested path.
- A non-Vial device rejects definition export clearly.
- The Python backup invokes `save` with both `-f` and `-d` paths.

- [ ] **Step 1: Add a failing command-contract test.** Extend `FakeRunner` so it can distinguish `-f` and `-d`, then assert the backup call contains a definition path and that the definition output is required.
- [ ] **Step 2: Run the focused backup test and confirm it fails because no definition path is requested.**

  Run: `nix develop --command python -m unittest tests.test_backup.BackupTests.test_initial_backup_creates_detected_model_target -v`

- [ ] **Step 3: Patch the pinned Rust source.** Add an optional `definition` field to `CommandSave`, pass it through `save_run`, and serialize `meta` with `serde_json::to_string_pretty` after all device reads succeed. Add `patches = [ ./vitaly-save-definition.patch ];` to `nix/vitaly.nix`.
- [ ] **Step 4: Run the focused test and verify the patched command contract passes.**
- [ ] **Step 5: Run `nix build .#vitaly --print-build-logs` to verify the Rust patch compiles.**

### Task 2: Capture and safely publish the companion definition

**Files:**
- Modify: `keyball_config/backup.py`
- Modify: `tests/test_backup.py`
- Modify: `keyball_config/keymap.py`

**Interfaces:**
- Add `_canonical_definition_name(model) -> str` returning `<slug>.vial.json`.
- Add `load_and_validate_vial_definition(path, model, matrix_shape) -> dict[str, object]` for shared backup/render validation.
- Extend `backup(...)` to validate and publish the companion definition.

**Acceptance Criteria:**
- Existing and companion targets are both inspected for Git dirtiness and concurrent changes.
- The definition JSON must contain a valid KLE `layouts.keymap`, a matrix matching the `.vil`, and valid layout labels when present.
- Temporary outputs are removed on every success and failure path.
- If publishing the companion fails after `.vil` replacement, the previous `.vil`/companion state is restored.

- [ ] **Step 1: Add failing tests for the companion target, malformed definition, cleanup, and replacement rollback.** Use a minimal valid Vial definition fixture value in the test module; do not depend on a connected device.
- [ ] **Step 2: Run `nix develop --command python -m unittest tests.test_backup -v` and verify the new tests fail for missing companion handling.
- [ ] **Step 3: Implement the companion filename, validation, dual target inspection, private output path, and rollback publication using the existing file-descriptor safeguards.**
- [ ] **Step 4: Run the focused backup tests again and confirm all backup tests pass.**

### Task 3: Render saved KLE geometry

**Files:**
- Modify: `keyball_config/keymap.py`
- Modify: `tests/test_keymap.py`

**Interfaces:**
- Add a standard-library KLE parser that returns active keys keyed by `(matrix-row, matrix-column)`.
- Add a geometry builder that emits the existing `layouts.LAYOUT_no_ball.layout` QMK JSON shape with `x`, `y`, `w`, `h`, `r`, `rx`, and `ry` values.
- `render_backup(...)` selects `<source stem>.vial.json` when present and otherwise uses `_filtered_geometry(...)` unchanged.

**Acceptance Criteria:**
- Active layout-option variants are selected from the `.vil` layout option state.
- KLE offsets and rotations survive conversion.
- Duplicate, missing, malformed, or out-of-matrix keys raise `RenderError` before keymap-drawer runs.
- Existing rendering tests and legacy fallback behavior remain green.

- [ ] **Step 1: Add failing geometry tests for a rotated KLE key, layout-option selection, malformed JSON, and missing companion fallback.**
- [ ] **Step 2: Run the focused rendering tests and verify the new tests fail before conversion exists.**
- [ ] **Step 3: Implement KLE state handling matching Vitaly: row `x/y` offsets, persistent rotation origin, per-key width/height reset, wire-label parsing, and active option filtering.**
- [ ] **Step 4: Feed the generated QMK geometry JSON to keymap-drawer and run all `tests.test_keymap` tests.**

### Task 4: Include snapshots in builds and document the workflow

**Files:**
- Modify: `flake.nix`
- Modify: `README.md`
- Test: `tests/test_site.py`

**Interfaces:**
- Nix source filtering includes `keyball39.vial.json` and `keyball44.vial.json` when present.
- README explains that backup updates both the `.vil` and companion definition, and that the companion drives curved geometry.

**Acceptance Criteria:**
- Site builds with legacy `.vil` inputs and with companion snapshots.
- Site output still contains only the documented generated files.
- Documentation names the exact companion files and review commands.

- [ ] **Step 1: Add a site test proving a companion input is consumed but never copied to generated output.**
- [ ] **Step 2: Update the Nix source allowlist and README backup instructions.**
- [ ] **Step 3: Run the complete verification gates: `nix flake check --print-build-logs` and `git diff --check`.**
- [ ] **Step 4: Record evidence on `keyball44-dx2.1` and leave Git changes uncommitted unless the user separately authorizes a commit.**
