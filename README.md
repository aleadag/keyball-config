# Keyball configuration backup and keymap site

[View the rendered keymaps](https://aleadag.github.io/keyball-config/)

This repository keeps canonical Vial settings for supported Keyball keyboards
and renders their keymaps as a static site. The current registry supports
Keyball39 and Keyball44 on `x86_64-linux`.

The root `keyball39.vil` and `keyball44.vil` files are the canonical backups.
Rendered SVG, converter YAML, and HTML are generated artifacts; they belong in
`build/` or a Nix result and must not be committed.

## Quick start

Run these commands from the repository root:

```bash
nix develop
vitaly devices
nix run .#backup
nix run .#render -- --output build
nix build .#site
```

`nix develop` provides the pinned Vitaly, converter, keymap-drawer, Python, and
workflow-checking tools. The flake currently exposes only `x86_64-linux`.

## Back up a connected keyboard

First inspect what the pinned Vitaly reports:

```bash
vitaly devices
```

Then make sure the existing canonical backup is clean before exporting:

```bash
git status --short -- keyball39.vil keyball44.vil
nix run .#backup
```

The backup command recognizes a sole connected Keyball39 or Keyball44 from its
Vitaly product name and prints the canonical file it updated. It refuses to
guess when device output is missing, malformed, unsupported, ambiguous, or has
multiple records or a colliding Vitaly selector ID. An existing target must be
tracked and unchanged. Vitaly's status, diagnostics, output freshness, JSON,
and model-specific Vial data must all pass validation before an atomic
replacement occurs. There is no force option. A failure before replacement
preserves the previous backup, and replacement itself is atomic.

Review and stage only the file printed by the backup command, for example:

```bash
git diff -- keyball44.vil
git add keyball44.vil
```

The command does not commit or push. It also never changes the other model's
backup.

## Render keymaps locally

Render every canonical backup currently present:

```bash
nix run .#render -- --output build
```

This writes `build/keyball39.svg`, `build/keyball44.svg`, or both, depending on
which canonical files exist. The renderer validates all present backups and
fails the complete render if any one is invalid. To diagnose one existing
profile without changing the complete-site contract, use `--model`:

```bash
nix run .#render -- --output build --model keyball44
```

The diagrams include layers reachable from layer 0 plus any reviewed additive
`include_layers` entries in `config/models.json`.

## Build and inspect the site

Build the immutable site output:

```bash
nix build .#site
```

Open `result/index.html` in a browser. The realized site contains only
`index.html` and one SVG for each canonical backup present; it excludes `.vil`
files, intermediate YAML, nested directories, symlinks, and external
resources. Nix validates the site while building it. Because `result` is a
symlink into the Nix store, use a local mutable site when running the explicit
validator:

```bash
nix run .#site -- --output build/site
nix run .#validate-site -- build/site
```

Site generation is all-or-nothing across the present backups. It stages and
validates a complete replacement before publishing it, rejects an output path
that is the repository or one of its ancestors, and preserves the previous
site when a pre-publication step fails.

Run all local checks with:

```bash
nix flake check --print-build-logs
```

## Publish with GitHub Pages

The workflow in `.github/workflows/pages.yml` checks pull requests and builds
the site on `main`. Only a trusted `main` push or a manual run on `main` uploads
and deploys the generated `_site/` artifact.

After hosting the repository on GitHub:

1. Open **Settings → Pages**.
2. Under **Build and deployment**, set **Source** to **GitHub Actions**.
3. Open or create **Settings → Environments → github-pages**.
4. Under **Deployment branches and tags**, allow only the `main` branch.
5. Push an approved change to `main`, or run **Build and deploy keymaps** from
   the Actions tab with `main` selected.

Pages uses the Actions artifact directly. This repository does not create or
maintain a `gh-pages` branch, and the workflow never publishes the canonical
`.vil` files.

## Roll back a publication

Revert the commit that changed a canonical backup, model configuration, pinned
tool, or generator, then push the revert to `main`:

```bash
git revert <commit>
git push
```

The new `main` run rebuilds and redeploys from canonical inputs. If a build or
deployment fails, GitHub Pages keeps the previous successful deployment live;
there is no generated branch to repair or roll back.

## Add another Keyball model

Keyball59 and Keyball61 are not implemented. Adding a model requires a reviewed
change that includes all of the following:

- a canonical `<slug>.vil` filename and registry entry in
  `config/models.json`;
- conservative Vitaly product-name identity rules and device-output fixtures;
- independently reviewed Vial/QMK matrix metadata;
- pinned physical geometry and converter settings;
- valid and invalid Vial fixtures, conversion tests, SVG rendering tests, and
  complete-site tests;
- an update to the current one-or-two-model site validation contract before a
  third model can be published;
- physical-device and Nix verification before claiming support on a platform.

Do not infer electrical matrix dimensions from the drawing geometry or add a
runtime model override; detection remains registry-driven and fail closed.

## Verification status

- Keyball44's canonical backup, fixtures, rendering, site build, and local
  automated checks are covered by the repository.
- Keyball39 parsing, validation, conversion, geometry, and site behavior are
  covered by fixtures, but physical Keyball39 hardware has not been verified;
  see the [device fixture note](tests/fixtures/devices/README.md).
- The GitHub Actions workflow is linted and policy-tested locally, but an actual
  GitHub Pages deployment has not been verified from this repository.
