# Keyball configuration backup and visualization implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use beads-superpowers:subagent-driven-development (recommended) or beads-superpowers:executing-plans to implement this plan task-by-task. Each Task becomes a Beads child of the implementation epic; checkbox steps are human-readable execution detail.
>
> **Date:** 2026-07-31
> **Design:** [2026-07-31-keyball-config-design.md](../specs/2026-07-31-keyball-config-design.md)
> **Status:** Approved
> **Tracking:** Implementation epic `keyball44-fq7`; Beads is authoritative.

**Goal:** Deliver a reproducible `x86_64-linux` workflow that safely backs up the sole connected supported Keyball39 or Keyball44 into its canonical `.vil` file, renders all present backups into deterministic keymap diagrams, and publishes only the generated static site through GitHub Pages.

**Architecture:** A small standard-library Python package owns detection, safety checks, keymap analysis, conversion orchestration, and static-site assembly. A Nix flake pins all native tools and exposes backup, render, site, and check outputs; GitHub Actions publishes only the realized site artifact.

**Tech Stack:** Python 3 standard library, Nix flakes, Vitaly 0.1.32, Neko, YAL Vial-to-keymap-drawer, keymap-drawer 0.23.0, `unittest`, actionlint/PyYAML policy checks, and GitHub Pages Actions.

## Global constraints

- Preserve `keyball39.vil` and `keyball44.vil` as the only canonical configuration artifacts.
- Do not commit generated YAML, SVG, or HTML.
- Never replace a dirty existing backup, guess a model, partially publish a multi-model site, or rely on Vitaly's exit code alone.
- Keep Vial/QMK keymap validation independent from physical drawing geometry.
- Pin nixpkgs, Vitaly, the converter, Keyball geometry, and every GitHub Action to immutable revisions.
- Support only `x86_64-linux` initially.
- Do not commit, push, configure Pages, or otherwise mutate GitHub without separate user authorization.

---

## Planned repository shape

```text
.
├── .github/workflows/pages.yml
├── .gitignore
├── README.md
├── config/models.json
├── flake.lock
├── flake.nix
├── keyball44.vil
├── keyball_config/
│   ├── __init__.py
│   ├── backup.py
│   ├── cli.py
│   ├── devices.py
│   ├── keymap.py
│   └── site.py
├── nix/
│   ├── vitaly.nix
│   └── vial-converter.nix
└── tests/
    ├── fixtures/
    │   ├── devices/
    │   ├── vial/
    │   └── converter/
    ├── test_backup.py
    ├── test_devices.py
    ├── test_keymap.py
    └── test_site.py
```

The modules are divided only at process and data boundaries: device parsing, backup mutation, keymap analysis/conversion, and site assembly. No plugin framework or speculative model class hierarchy is planned.

## Task 1: Establish the pinned Nix toolchain (`keyball44-n4x`)

**Files:** `flake.nix`, `flake.lock`, `nix/vitaly.nix`, `nix/vial-converter.nix`

**Interfaces:** Produces the commands `vitaly`, `keymap`, and `vial-converter`; later tasks consume their absolute paths through the flake.

**Acceptance criteria:**

- The flake evaluates only `x86_64-linux` outputs.
- Vitaly reports 0.1.32 and keymap-drawer reports 0.23.0.
- Converter and geometry sources are immutable pins.
- The toolchain realizes successfully and can run offline afterward.

- [ ] **Step 1: Add the flake and local package skeletons.** Use this output contract:

  ```nix
  {
    devShells.x86_64-linux.default = pkgs.mkShell {
      packages = [ vitaly vialConverter pkgs.keymap-drawer pkgs.python3 ];
    };
    packages.x86_64-linux = {
      inherit vitaly vialConverter;
      default = vialConverter;
    };
  }
  ```

- [ ] **Step 2: Package Vitaly v0.1.32.** Use `rustPlatform.buildRustPackage`, the upstream `Cargo.lock`, `pkg-config`, and `udev`; obtain and replace fixed-output hashes through the normal failed-hash Nix build cycle.

- [ ] **Step 3: Package the reviewed YAL converter commit and wrap its Neko entry point behind this stable local interface:**

   ```text
   vial-converter --model <slug> --geometry <path> --input <vil> --output <yaml>
   ```

- [ ] **Step 4: Pin the official Keyball source at the reviewed commit and expose its Keyball39/44 geometry paths to the wrapper.**

- [ ] **Step 5: Run the verification commands and correct only packaging defects until they pass.**

**Verification:**

```bash
nix flake show
nix develop --command vitaly --version
nix develop --command keymap --version
nix develop --command vial-converter --help
```

Expected: every command resolves from the flake without network access after realization; Vitaly reports 0.1.32 and keymap-drawer reports the pinned version.

## Task 2: Define and validate the model registry (`keyball44-d8m`)

**Files:** `config/models.json`, `keyball_config/__init__.py`, `keyball_config/devices.py`, `tests/test_devices.py`, `tests/fixtures/devices/*`

**Interfaces:**

```python
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

def load_registry(path: Path) -> dict[str, ModelConfig]: ...
def parse_devices(output: str) -> tuple[DeviceRecord, ...]: ...
def select_device(records: Sequence[DeviceRecord], models: Mapping[str, ModelConfig]) -> tuple[DeviceRecord, ModelConfig]: ...
```

**Acceptance criteria:**

- The observed `trackball 44 V3` normalizes to `keyball44`.
- Conservative Keyball39 names normalize to `keyball39`.
- Zero, multiple, malformed, unsupported, ambiguous, or selector-colliding records fail closed with actionable diagnostics.

- [ ] **Step 1: Write failing registry and parser tests** covering:

   - zero records;
   - the observed `trackball 44 V3` record;
   - a conservative Keyball39 name fixture;
   - unsupported, ambiguous, malformed, and multiple records;
   - another record sharing the selected product ID.

  ```python
  def test_observed_keyball44_is_selected(tmp_path: Path) -> None:
      models = load_registry(Path("config/models.json"))
      records = parse_devices((FIXTURES / "trackball-44-v3.txt").read_text())
      device, model = select_device(records, models)
      assert device.product_id == 16718
      assert model.slug == "keyball44"
  ```

- [ ] **Step 2: Run the focused test and verify it fails because the package does not exist.**

  ```bash
  nix develop --command python -m unittest tests.test_devices -v
  ```

- [ ] **Step 3: Implement the two registry records and exact interfaces above.** Parse complete three-line records, retain every diagnostic field, and require `keyball|trackball` plus a standalone `39|44`.

- [ ] **Step 4: Run the focused suite until every fail-closed case passes.**

**Red:**

```bash
nix develop --command python -m unittest tests.test_devices -v
```

Expected before implementation: missing module/tests fail.

**Green:** rerun the same command; all parser and registry cases pass.

## Task 3: Implement safe backup replacement (`keyball44-b6s`)

**Files:** `keyball_config/backup.py`, `keyball_config/cli.py`, `tests/test_backup.py`, `tests/fixtures/vial/*`

**Interfaces:**

```python
@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str

Runner = Callable[[Sequence[str], Path], CommandResult]

def backup(repo: Path, registry_path: Path, runner: Runner) -> Path: ...
```

**Acceptance criteria:**

- Initial creation and clean replacement update only the detected model target.
- Every dirty-state, selection, process, diagnostic, freshness, or validation failure preserves the previous bytes.
- The implementation provides neither a force option nor any Git mutation.

- [ ] **Step 1: Write failing tests with injected command results and temporary directories** for:

   - initial backup creation;
   - replacement of a clean existing target;
   - refusal for modified, staged, deleted, or untracked existing targets;
   - zero/nonzero Vitaly failures and error diagnostics;
   - missing, unchanged, empty, malformed, or model-invalid temporary output;
   - preservation of the old file for every failure;
   - replacement of only the detected model.

  ```python
  def test_error_diagnostic_preserves_existing_backup(tmp_path: Path) -> None:
      target = tmp_path / "keyball44.vil"
      target.write_bytes(b'{"old":true}')
      runner = FakeRunner(save=CommandResult(0, "", "Error: export failed"))
      with self.assertRaises(BackupError):
          backup(tmp_path, REGISTRY, runner)
      self.assertEqual(target.read_bytes(), b'{"old":true}')
  ```

- [ ] **Step 2: Run `nix develop --command python -m unittest tests.test_backup -v` and verify a missing implementation failure.**

- [ ] **Step 3: Implement exact-target dirty-state checking with porcelain Git status.** Existing files with any status fail; inability to inspect Git fails closed; a missing target is initial creation.

- [ ] **Step 4: Implement fresh sibling output and Vitaly invocation:**

   ```text
   vitaly -i <observed-product-id> save -f <temporary-path>
   ```

- [ ] **Step 5: Implement the success predicate.** Require zero exit, no recognized export-error diagnostic, and a newly created non-empty regular file containing valid model-specific Vial JSON.

- [ ] **Step 6: Flush and atomically replace with `os.replace`; clean temporary paths in `finally`; expose `python -m keyball_config.cli backup`.**

- [ ] **Step 7: Run the focused suite and verify all mutation-safety cases pass.**

**Red/Green:**

```bash
nix develop --command python -m unittest tests.test_backup -v
```

Expected final result: all destructive-edge fixtures pass and no failing case changes the canonical target bytes.

## Task 4: Analyze reachable layers without conflating geometry (`keyball44-l2r`)

**Files:** `keyball_config/keymap.py`, `tests/test_keymap.py`, `tests/fixtures/vial/*`

**Interfaces:**

```python
def load_and_validate_vil(path: Path, model: ModelConfig) -> dict[str, object]: ...
def reachable_layers(vil: Mapping[str, object], include_layers: Sequence[int] = ()) -> tuple[int, ...]: ...
def normalized_vil(vil: Mapping[str, object], layers: Sequence[int]) -> bytes: ...
```

**Acceptance criteria:**

- Reachability begins at layer 0, follows every supported QMK layer action, terminates on cycles, and returns sorted unique layers.
- Only reviewed additive `include_layers` may extend the result.
- Unknown custom keycodes that could conceal layer transitions are diagnosed.
- Vial/QMK validation never derives dimensions from drawing geometry.

- [ ] **Step 1: Write failing tests** for direct/nested references, cycles, unreachable non-empty layers, empty reachable layers, additive/invalid inclusions, and unknown custom keycodes.

  ```python
  def test_reachability_handles_nested_cycle() -> None:
      vil = fixture_vil({0: ["MO(2)"], 2: ["LT(3,KC_A)"], 3: ["TG(2)"]})
      self.assertEqual(reachable_layers(vil), (0, 2, 3))
  ```

- [ ] **Step 2: Run `nix develop --command python -m unittest tests.test_keymap -v` and verify the missing implementation failure.**

- [ ] **Step 3: Implement explicit traversal of layout, combos, tap dances, key overrides, macros, and alternate-repeat key data.** Recognize `MO`, `LT`, `TG`, `TO`, `DF`, and one-shot layer forms.

- [ ] **Step 4: Implement additive inclusions, diagnostics, model-specific validation, and stable normalized JSON bytes.**

- [ ] **Step 5: Rerun the focused suite and verify every graph and validation case passes.**

**Red/Green:**

```bash
nix develop --command python -m unittest tests.test_keymap -v
```

## Task 5: Build the hermetic conversion and SVG path (`keyball44-c9v`)

**Files:** `keyball_config/keymap.py`, `keyball_config/cli.py`, `tests/fixtures/converter/*`, `tests/test_keymap.py`, `.gitignore`

**Interfaces:**

```python
@dataclass(frozen=True)
class RenderTools:
    converter: Path
    keymap: Path
    geometry_root: Path

def render_backup(source: Path, output_svg: Path, model: ModelConfig, tools: RenderTools, runner: Runner) -> None: ...
def render_present(repo: Path, output: Path, models: Mapping[str, ModelConfig], tools: RenderTools, only_model: str | None = None) -> tuple[Path, ...]: ...
```

**Acceptance criteria:**

- Each model fixture converts and renders without network access.
- Two runs from identical normalized input produce byte-identical YAML and SVG.
- Missing, stale, empty, or malformed SVG fails.
- `render --model` is diagnostic only; the site path has no partial-model option.

- [ ] **Step 1: Add failing converter fixtures and integration tests for both models.**

  ```python
  def test_keyball44_render_is_byte_stable(tmp_path: Path) -> None:
      first = tmp_path / "first.svg"
      second = tmp_path / "second.svg"
      render_backup(KEYBALL44_FIXTURE, first, MODELS["keyball44"], TOOLS, run)
      render_backup(KEYBALL44_FIXTURE, second, MODELS["keyball44"], TOOLS, run)
      self.assertEqual(first.read_bytes(), second.read_bytes())
  ```

- [ ] **Step 2: Run the focused integration test and confirm failure before rendering exists.**

- [ ] **Step 3: Implement normalized temporary Vial input, fixed locale/timezone, converter invocation, normalized YAML, and keymap-drawer invocation.**

- [ ] **Step 4: Validate fresh SVG as non-empty XML with an `<svg>` root; reject stale output and clean temporary files.**

- [ ] **Step 5: Add diagnostic `render --model`, default all-present rendering, and a `build/` ignore rule that does not hide `.vil` files.**

- [ ] **Step 6: Run both model fixtures twice and verify byte equality and absence of network-dependent behavior.**

**Verification:**

```bash
nix develop --command python -m unittest tests.test_keymap -v
nix develop --command python -m keyball_config.cli render --output build
test -s build/keyball44.svg
```

## Task 6: Generate and validate the complete Pages site (`keyball44-s3p`)

**Files:** `keyball_config/site.py`, `keyball_config/cli.py`, `tests/test_site.py`, `tests/fixtures/vial/*`

**Interfaces:**

```python
def build_site(repo: Path, output: Path, models: Mapping[str, ModelConfig], tools: RenderTools, runner: Runner) -> tuple[Path, ...]: ...
def validate_site(path: Path, expected_models: Sequence[str]) -> None: ...
```

**Acceptance criteria:**

- Zero backups fails; one backup produces one diagram; two produce a selector and both diagrams.
- Any invalid present backup fails the entire build without leaving mixed/stale output.
- Publication contains only top-level `index.html`, expected SVGs, and intentional authored assets, with relative paths and no links or symlinks.

- [ ] **Step 1: Write failing tests for zero, one, two, and mixed-validity source trees.**

  ```python
  def test_invalid_second_profile_prevents_partial_site(tmp_path: Path) -> None:
      repo = copy_fixture_tree(tmp_path, "one-valid-one-invalid")
      output = tmp_path / "site"
      with self.assertRaises(SiteError):
          build_site(repo, output, MODELS, TOOLS, run)
      self.assertFalse(output.exists())
  ```

- [ ] **Step 2: Run `nix develop --command python -m unittest tests.test_site -v` and confirm the missing implementation failure.**

- [ ] **Step 3: Implement staging-directory assembly that validates and renders all present models before a final directory replacement.**

- [ ] **Step 4: Generate minimal responsive HTML with one embedded diagram or a two-model selector and direct relative SVG links.**

- [ ] **Step 5: Implement `validate_site`; reject `.vil`, YAML, absolute repository paths, links, symlinks, and missing/unexpected files.**

- [ ] **Step 6: Rerun site tests and verify atomic all-or-nothing behavior.**

**Red/Green:**

```bash
nix develop --command python -m unittest tests.test_site -v
```

Expected final result: an invalid present profile fails before replacing a prior output directory, while one- and two-model sites satisfy the publication contract.

## Task 7: Wire applications, package output, and checks into the flake (`keyball44-f5w`)

**Files:** `flake.nix`, `flake.lock`

**Interfaces:** Consumes `python -m keyball_config.cli {backup,render,site,validate-site}` and produces the final flake outputs.

**Acceptance criteria:**

- `nix run .#backup`, `nix run .#render`, `nix build .#site`, and `nix flake check` resolve on `x86_64-linux`.
- The site derivation has no device or network dependency.
- The Nix source excludes repository metadata, internal planning, logs, and local output while including canonical backups.

- [ ] **Step 1: Add flake wrappers with this output contract:**

  ```nix
  apps.x86_64-linux = {
    backup.program = "${backupApp}/bin/keyball-backup";
    render.program = "${renderApp}/bin/keyball-render";
  };
  packages.x86_64-linux.site = site;
  checks.x86_64-linux = {
    unit = unitTests;
    conversion = conversionTests;
    site = siteContractTests;
    workflow = workflowChecks;
  };
  ```

  These outputs expose:

   - `apps.x86_64-linux.backup` for the mutating local backup command;
   - `apps.x86_64-linux.render` for local all-present rendering;
   - `packages.x86_64-linux.site` for the immutable complete site;
   - checks for unit tests, converter fixtures, byte stability, site contract, and workflow linting.

- [ ] **Step 2: Implement source filtering and the pure site derivation.** Pass only pinned tools, geometry, authored source, canonical backups, `LC_ALL=C.UTF-8`, `TZ=UTC`, and a fresh output path.

- [ ] **Step 3: Add the unit, conversion, site-contract, byte-stability, and workflow checks to `nix flake check`.**

- [ ] **Step 4: Run the verification commands; fix only integration defects until all outputs pass.**

**Verification:**

```bash
nix flake check --print-build-logs
nix build .#site
test -f result/index.html
test -s result/keyball44.svg
find -L result -type l
find result -type f \( -name '*.vil' -o -name '*.yaml' -o -name '*.yml' \)
```

Expected: checks and build pass; the two `find` commands produce no output.

## Task 8: Add least-privilege Pages automation (`keyball44-g7h`)

**Files:** `.github/workflows/pages.yml`, `tests/test_workflow.py`, `flake.nix`

**Interfaces:** The workflow consumes `nix flake check` and `nix build .#site`; it uploads `_site/` and exposes the URL returned by `actions/deploy-pages`.

**Acceptance criteria:**

- Pull requests build with `contents: read`, no secrets, no writes, no shared cache writes, and no deployment.
- Only trusted `main` pushes or manual runs of `main` reach the protected deploy job.
- Only the deploy job has `pages: write` and `id-token: write`.
- Every action uses a reviewed full 40-character SHA and only `_site/` is uploaded.

- [ ] **Step 1: Write a failing policy test that parses the workflow YAML.** Add PyYAML only to the test/check environment, not the runtime helper.

  ```python
  def test_deploy_permissions_are_job_scoped() -> None:
      workflow = load_workflow(Path(".github/workflows/pages.yml"))
      self.assertEqual(workflow["jobs"]["build"]["permissions"], {"contents": "read"})
      self.assertEqual(
          workflow["jobs"]["deploy"]["permissions"],
          {"pages": "write", "id-token": "write"},
      )
  ```

- [ ] **Step 2: Run the workflow test and confirm it fails because the workflow is absent.**

- [ ] **Step 3: Resolve and review full SHAs for checkout, the Nix installer, configure-pages, upload-pages-artifact, and deploy-pages; include readable release tags in comments.**

- [ ] **Step 4: Implement build triggers for pull requests, `main` pushes, and manual dispatch.** The build job runs checks/site build, copies the realized result with link dereferencing into `_site/`, validates it, and uploads only `_site/`.

- [ ] **Step 5: Implement a deploy job gated to `refs/heads/main`, dependent on build success, with protected `github-pages` environment, deployment-only concurrency, and only Pages/OIDC permissions.**

- [ ] **Step 6: Run actionlint, policy tests, and the aggregate flake check until all pass.**

**Verification:**

```bash
nix flake check --print-build-logs
```

Expected: workflow lint and security-contract checks pass locally. Actual Pages deployment remains unverified until the repository has a GitHub remote and the user authorizes publication/configuration.

## Task 9: Document operation and rollback (`keyball44-r4d`)

**Files:** `README.md`

**Interfaces:** Documents only commands and behavior verified by Tasks 1–8.

**Acceptance criteria:**

- A new user can back up, render, build, and configure Pages using exact commands.
- Safety behavior, canonical/generated boundaries, platform limitations, future-model extension, and rollback are explicit.
- Keyball39 hardware and GitHub deployment remain labeled unverified until evidence exists.

- [ ] **Step 1: Write README sections for the shipped commands and limitations:**

- enter the Nix environment;
- list/detect devices;
- run safe backup;
- render locally;
- build and inspect the site;
- add a future model through reviewed registry/identity/geometry/fixtures;
- initial `x86_64-linux` support;
- configure Pages source as GitHub Actions and protect the environment;
- roll back by reverting canonical input/tooling changes and redeploying;
- explain that failed deployments leave the previous site live and no `gh-pages` branch exists.

- [ ] **Step 2: Include this minimal quick-start contract, expanding it only with verified details:**

  ```bash
  nix develop
  vitaly devices
  nix run .#backup
  nix run .#render -- --output build
  nix build .#site
  ```

- [ ] **Step 3: Run every documented local command that does not require missing hardware or GitHub publication; correct documentation drift.**

- [ ] **Step 4: Mark Keyball39 hardware and actual Pages deployment as unverified, then run the documentation-audit workflow.**

## Final verification gate

Run fresh, in order:

```bash
nix flake check --print-build-logs
nix build .#site
nix run .#render -- --output build
cmp result/keyball44.svg build/keyball44.svg
nix run .#backup
```

The first four commands must pass. Run the last command only with the connected Keyball44 and after confirming `keyball44.vil` has no uncommitted change. Verify that detection reports `trackball 44 V3` as `keyball44`, the new backup validates and renders, and `keyball39.vil` is untouched if present.

After verification, run the documentation audit and code-review workflows. Report exact evidence, Beads status, and any unverified external deployment. Do not commit, push, or configure GitHub until separately authorized.

## Plan review checklist

- Every design acceptance criterion maps to a task and fresh verification command.
- Failure paths are tested before backup mutation or publication code is accepted.
- Generated artifacts stay out of Git and out of the uploaded artifact unless explicitly public.
- The plan adds no Keyball59/61, restore, editor, firmware, history, macOS, or ARM scope.
- Git and GitHub mutations remain outside current authorization.
