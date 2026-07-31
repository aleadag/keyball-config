# Keyball configuration backup and visualization design

> **Date:** 2026-07-31
> **Brainstorming bead:** keyball44-ily
> **Intended repository:** `aleadag/keyball-config`
> **Status:** Approved and stress-tested

## Objective

Use this repository to preserve restorable Vial configurations for Keyball39 and Keyball44 keyboards and publish readable keymap diagrams through GitHub Pages. Nix provides the reproducible local and CI environment.

## Scope

The repository supports two independent configuration profiles:

- `keyball39.vil`
- `keyball44.vil`

Each existing `.vil` file is canonical, tracked backup data. Generated keymap-drawer YAML, SVG, and HTML are build artifacts and are not committed.

The workflow supports local device backup, local visualization, deterministic site builds, pull-request validation, and default-branch Pages deployment. It does not load configurations back onto a keyboard, edit keymaps, manage firmware, or publish the raw `.vil` files through Pages.

## Architecture

### Nix flake

The flake pins nixpkgs and initially exposes these outputs for `x86_64-linux`:

- `devShells.<system>.default`: Vitaly, the Vial-to-keymap-drawer converter and its runtime, keymap-drawer, Python, workflow linting, and project commands.
- `apps.<system>.backup`: detect one supported connected keyboard and update only its model-specific `.vil` file.
- `apps.<system>.render`: render all supported backups present into a gitignored local output directory.
- `packages.<system>.site`: build the complete static Pages site as an immutable Nix output.
- `checks.<system>`: unit tests, fixture rendering, site-contract checks, Nix evaluation, and workflow linting.

Vitaly v0.1.32 is packaged locally because current nixpkgs does not provide it. The Vial converter, Keyball geometry source, keymap-drawer, and GitHub Actions are pinned to reviewed immutable revisions. Other platforms are not advertised until both their Nix build and physical-device workflow have been verified.

### Project helper

A small Python standard-library helper owns structured project logic:

- Parse the version-pinned human-readable output of `vitaly devices`.
- Normalize supported product names to `keyball39` or `keyball44`.
- Validate exported `.vil` JSON and model-specific keymap data against reviewed Vial/QMK metadata or fixtures.
- Derive layers reachable from layer 0 through QMK layer-switch keycodes in every Vial keycode-emitting structure.
- Select model-specific conversion settings and physical geometry.
- Assemble and validate the static-site directory.

Shell wrappers are limited to process invocation, temporary-file management, and atomic replacement.

### Model registry

One explicit model registry maps each stable slug to:

- Canonical backup filename.
- Conservative product-name recognition rule.
- Pinned upstream geometry path.
- Converter layout/order settings.
- An optional reviewed, additive `include_layers` list for layers that cannot be discovered statically.
- Page title and display label.

Product-name matching is case-insensitive and requires both:

1. The word `keyball` or `trackball`.
2. A standalone model number, `39` or `44`.

Names that match neither model or both models are rejected. The installed firmware's VID/PID is not used to infer the model because the observed `trackball 44 V3` firmware identity differs from upstream QMK metadata.

Supporting a future Keyball model requires a reviewed registry entry, identity and geometry metadata, and detection, conversion, and rendering fixtures. Keyball59 and Keyball61 are explicitly deferred.

## Backup workflow

`nix run .#backup` performs these steps:

1. Run the pinned `vitaly devices` command and capture its output.
2. Parse every compatible-device record.
3. Require exactly one compatible device overall and reject any other enumerated device that collides with its Vitaly selector ID.
4. Normalize its product name to exactly one supported model.
5. If the target already exists, refuse to replace it when that exact file has uncommitted Git changes. Initial creation is allowed.
6. Create a fresh temporary output path beside the target backup.
7. Run `vitaly -i <observed-product-id> save -f <temporary-file>` and capture its diagnostics.
8. Require a successful exit, no reported export error, and a newly created, non-empty temporary file.
9. Validate JSON syntax, required Vial fields, non-empty layout data, and model-specific keymap data against reviewed Vial/QMK metadata or fixtures.
10. Atomically replace only the detected model's canonical `.vil` file.

The one-device invariant is required because Vitaly's `-i` selector matches USB product ID rather than a globally unique device identity.

The command fails before replacement when there are zero devices, multiple compatible devices, a selector collision, an unsupported or ambiguous product name, a dirty existing target, a Vitaly failure or error diagnostic, missing or stale output, malformed output, or invalid exported configuration. A Keyball39 backup never removes or rewrites `keyball44.vil`, and vice versa. The workflow neither commits changes nor provides a force flag.

## Rendering workflow

`nix run .#render` and `nix build .#site` share the same rendering implementation:

1. Discover `keyball39.vil` and `keyball44.vil` in the source tree.
2. Require at least one supported backup.
3. Validate every supported backup that exists.
4. Starting from layer 0, follow recognized QMK layer actions—including `MO`, `LT`, `TG`, `TO`, `DF`, and one-shot layer forms—across all Vial keycode-emitting structures to calculate a conservative reachable layer set.
5. Add any reviewed model-specific `include_layers`; there is no exclusion override. Diagnose unknown custom keycodes that prevent static reachability analysis.
6. Convert only the resulting layers from `.vil` to normalized temporary keymap-drawer YAML through a replaceable helper interface.
7. Render each model with its matching pinned Keyball geometry.
8. Validate that each SVG is non-empty and structurally valid.
9. Generate the static page and copy only publication assets into the site output.

An error in any existing profile fails the whole build. The renderer does not silently publish a partial site or reuse stale output.

Conversion is hermetic: it uses only pinned local inputs, never a network or live API fallback. Repeated conversion of the same normalized inputs must be byte-stable. A model-specific local render mode may aid diagnosis, but `packages.x86_64-linux.site` always validates and renders every present backup.

## Pages presentation

The generated artifact contains top-level `index.html` and one SVG per available model. It never contains `.vil` backups or intermediate YAML.

With one backup, the page displays one responsive embedded diagram. With both backups, it adds a small Keyball39/Keyball44 selector and displays both diagrams. Each diagram has a direct open/download link. The presentation remains static and minimal; it has no client-side keymap editor, history browser, or application framework.

The HTML and asset paths are relative and do not hard-code the current repository name. Renaming the repository to `aleadag/keyball-config` therefore affects only the eventual Pages project URL.

## GitHub Actions and Pages

One workflow responds to:

- Pull requests targeting the default branch.
- Pushes to the default branch.
- Manual dispatch.

The build job has `contents: read`, installs Nix through a full-SHA-pinned action, builds `.#site`, copies the realized output into a plain `_site/` directory, validates the site contract, configures Pages, and uploads only `_site/` as the Pages artifact.

The deploy job:

- Is skipped for pull requests.
- Depends on a successful build.
- Has only `pages: write` and `id-token: write` elevated permissions.
- Uses the protected `github-pages` environment.
- Uses deployment-only concurrency so validation builds cannot interfere with production publication.
- Deploys through a full-SHA-pinned `actions/deploy-pages` revision.

After the repository is hosted on GitHub, its Pages publishing source must be configured as **GitHub Actions**, and the `github-pages` environment must restrict deployment to the default branch.

A failed build or deployment leaves the previous successful Pages deployment live. Rollback is performed by reverting the offending canonical backup, configuration, or generator change on the default branch and redeploying; generated files are not retained on a `gh-pages` branch.

## Error handling and security

- Existing backups survive every failed detection, export, validation, conversion, rendering, or deployment attempt.
- Temporary backups are created beside their target so atomic replacement remains on one filesystem.
- Device detection rejects ambiguity rather than guessing.
- CI never receives USB/device access and never executes backup operations.
- Pull-request code runs through `pull_request`, not privileged `pull_request_target`.
- Pull-request builds have no secrets or write permissions and cannot deploy or write shared caches.
- No secrets are required.
- Only the generated `_site/` tree is uploaded.
- Every third-party GitHub Action and converter source is pinned to a reviewed full commit SHA with its readable release version in a comment and an explicit update procedure.
- The Pages environment limits trusted deployment refs.
- The Pages artifact is a plain directory tree with a top-level entry file and no symlink dependency.

## Verification

### Unit tests

Device-output fixtures cover:

- Zero devices.
- One recognized Keyball39 variant.
- The observed `trackball 44 V3` record.
- Unsupported product names.
- Ambiguous product names.
- Multiple compatible devices.
- Malformed Vitaly output.

Layer-graph tests cover direct and nested references, cycles, unreachable non-empty layers, empty reachable layers, and the supported QMK layer-switch keycode forms.

Validation tests cover malformed JSON, missing required fields, empty layouts, invalid model-specific keymap data, and valid model-specific exports. They do not infer electrical matrix dimensions from physical drawing geometry.

Backup tests cover a dirty existing target, initial creation, selector-ID collisions, zero-status failures with diagnostics, missing output, empty output, malformed output, and preservation of the previous file for every failure.

### Integration and build tests

- Test-only Keyball39 and Keyball44 `.vil` fixtures pass through conversion and SVG rendering.
- A single-profile fixture produces a one-model site.
- A two-profile fixture produces the selector and both SVGs.
- Any invalid present profile fails the complete site build.
- A model-specific diagnostic render cannot weaken the complete-site validation contract.
- Repeated conversion of identical normalized fixtures is byte-identical and requires no network access.
- The site has top-level `index.html`, expected SVG files, relative links, no published `.vil` or YAML, and no symlink dependency.
- Workflow YAML passes the pinned linter.
- `nix flake check` runs the automated test and fixture matrix.
- `nix build .#site` succeeds against the repository's real tracked backups.

### Live verification

During implementation, run device discovery against the connected Keyball44 and confirm it normalizes `trackball 44 V3` to `keyball44`. Run the backup workflow and verify the resulting file is valid and renderable while preserving the previous file until atomic replacement. Keyball39 hardware validation remains optional until such a device is available; its parser, fixture, conversion, and geometry paths remain required CI checks.

## Acceptance criteria

1. `nix develop` provides all backup, conversion, rendering, testing, and linting tools.
2. `nix run .#backup` safely updates only the sole detected supported model's canonical backup.
3. The repository can retain Keyball39 and Keyball44 backups simultaneously.
4. `nix run .#render` generates diagrams for every supported backup present without tracking generated files.
5. Generated diagrams contain layers reachable from layer 0 plus only explicitly reviewed additive `include_layers` entries.
6. `nix build .#site` produces a minimal responsive site for one or both models.
7. Pull requests build and validate but cannot deploy.
8. Trusted default-branch and manual runs deploy only the generated site through GitHub Pages.
9. Failures preserve prior backups and prevent partial publication.
10. Automated checks cover both models even when only one physical keyboard is available.
11. The documented supported platform is `x86_64-linux`; additional platforms are claimed only after Nix and physical-device verification.

## Stress Test Results

### Resolved decisions

1. Device identification is registry-driven and fail-closed, with no runtime model override.
2. An existing backup with uncommitted changes is never replaced; initial creation is allowed, with no force or automatic commit behavior.
3. Reachability traverses standard QMK layer actions across Vial keycode-emitting structures and permits only reviewed additive layer inclusions.
4. Conversion is a pinned, hermetic, byte-stable, replaceable adapter with no network fallback.
5. Production site publication is atomic across all present model backups; per-model rendering is diagnostic only.
6. Initial platform support is explicitly `x86_64-linux`.
7. Pages uses Actions artifacts without a generated branch; rollback reverts canonical inputs and redeploys.
8. Pull requests are unprivileged and deployment permissions exist only in the protected deploy job.
9. Vial/QMK keymap validation and physical drawing geometry are separate contracts.
10. Export success requires unambiguous selection and fresh, valid output rather than relying on process status alone.

### Changes made

The design now specifies dirty-target protection, selector-collision checks, robust Vitaly output validation, conservative layer traversal, optional additive layer metadata, hermetic conversion, atomic multi-model publication, an explicit platform boundary, artifact-based rollback, and narrower CI permissions. Its earlier geometry-derived matrix check was replaced with independent model-keymap and physical-render validation.

### Deferred and parking lot

- Keyball59 and Keyball61 support.
- macOS, ARM Linux, and other platforms pending build and hardware verification.
- Loading backups onto devices, editing keymaps, firmware management, and keymap history browsing.

### Confidence

All ten decision branches were agreed without modification. The remaining uncertainty is implementation-level integration with pinned upstream formats, which must be resolved through the specified fixtures, tests, and live Keyball44 verification.

## References

- [Toolchain research](../research/2026-07-31-keyball44-backup-visualization-toolchain.md)
- [GitHub Pages research](../research/2026-07-31-github-pages-keymap-delivery.md)
- [Device-driven model research](../research/2026-07-31-device-driven-keyball-models.md)
