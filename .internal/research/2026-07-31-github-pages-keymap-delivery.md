# Research: GitHub Pages delivery for the generated Keyball44 keymap

> **Date:** 2026-07-31
> **Bead:** keyball44-rq2
> **Status:** Complete

## Summary

GitHub Pages is a good publication target when the repository tracks the canonical `keyball44.vil` but not generated YAML or SVG. A custom Actions workflow can build and validate the site for pull requests, then deploy the same Pages artifact only for the default branch or a manual dispatch.

## Key Findings

### Pages supports generated output without a generated branch

> **Confidence:** high — current official GitHub Pages documentation directly recommends a custom Actions workflow when compiled output should not live on a dedicated branch.

The workflow should use separate `build` and `deploy` jobs. The build job checks out the repository, installs Nix, realizes the static-site flake output, copies it to `_site/`, configures Pages, and uploads `_site/` with `actions/upload-pages-artifact`. The deploy job depends on that build and uses `actions/deploy-pages`. [S1] [S2]

GitHub documents build-only pull-request validation: the workflow may run for pull requests, while `deploy-pages` runs only for pushes to the default branch. This matches the desired no-generated-files-in-Git model. [S1]

### The static-site artifact has a small, explicit contract

> **Confidence:** high — the artifact and site requirements are stated directly in current official documentation; an independent verifier confirmed the wording after rejecting an earlier overstatement about symlinks.

The uploaded directory must contain its entry file at the top level, so the Nix site output should contain `_site/index.html` and `_site/keyball44.svg`. The Pages artifact documentation says its tar should not contain symbolic or hard links. Because `nix build` commonly exposes an output through a symlink, CI should copy the realized output into a plain `_site/` tree before upload. [S2] [S3]

Only `_site/` should be uploaded. The workflow must not publish the repository root, the intermediate YAML, or `keyball44.vil` as Pages content.

### Deployment permissions can remain narrowly scoped

> **Confidence:** high — the official Pages documentation and action README agree, and the claim was independently verified.

The build job needs only `contents: read`. The deploy job needs `pages: write` and `id-token: write`, targets the `github-pages` environment, and exposes the resulting page URL from the deployment action. The environment should restrict deployment to the default branch. No repository or environment secrets are needed. [S1] [S4]

Use `pull_request`, not `pull_request_target`, for validation of pull-request code. GitHub warns against privileged triggers that check out untrusted pull-request content. [S5]

### Action dependencies should be immutable

> **Confidence:** high — GitHub's security reference directly states that a full commit SHA is the only immutable action reference; an independent verifier confirmed the claim.

Pin every action, including the Nix installer, to a verified full-length commit SHA and leave the human-readable major version in a comment. As checked on 2026-07-31, the coordinated Pages documentation uses `checkout@v6`, `configure-pages@v5`, `upload-pages-artifact@v4`, and `deploy-pages@v4`; resolve and review their full SHAs during implementation. [S1] [S5]

## Comparisons

| Approach | Generated files in Git | Viewing experience | Security/maintenance |
|---|---:|---|---|
| Custom Actions → Pages artifact | None | Stable project URL | Recommended; narrow deploy job and pinned actions |
| Actions build artifact only | None | Must open a workflow run and download | Simpler permissions, poor discoverability |
| Commit to `gh-pages` branch | Yes, on generated branch | Stable project URL | Extra branch/state and write-capable automation |

## Codebase Context

The repository currently has no configured Git remote, GitHub workflow, flake, static-site source, or generated site. It tracks `keyball44.vil`, while the earlier toolchain research established that CI must convert `.vil` to keymap-drawer YAML before rendering SVG. The repository's eventual GitHub owner, default branch, Pages URL, and visibility therefore cannot yet be confirmed locally.

## Recommendations

1. Use a custom GitHub Pages Actions workflow rather than a generated branch.
2. Trigger builds on pull requests, default-branch pushes, and manual dispatch; deploy only for the latter two trusted cases.
3. Define `packages.<system>.site` in the flake so local and CI rendering execute the same conversion and validation.
4. Copy the realized site to `_site/`, require top-level `index.html` and `keyball44.svg`, and upload only that directory.
5. Give Pages permissions only to the deploy job, protect the `github-pages` environment, and pin all actions to reviewed full SHAs.
6. Configure **Settings → Pages → Build and deployment → Source** as **GitHub Actions** after the repository has a GitHub remote.

## Open Questions

- Which layers should the default SVG expose: every Vial layer, only non-empty layers, or a named subset?
- Will the GitHub repository be public? GitHub Free supports Pages for public repositories; private-repository availability depends on the account plan, and Pages is generally public unless enterprise access control is configured.

## Refuted / Discarded Claims

- **Discarded:** “GitHub rejects every Pages artifact containing a symlink.” The cited documentation says the tar *should not* contain symbolic or hard links; it does not directly support the stronger rejection claim. The design still creates a plain `_site/` tree to satisfy the documented format.

## Sources

- [Configuring a publishing source for GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site) — Primary/Official — 2026-07-31 — build/deploy flow and PR behavior.
- [Using custom workflows with GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) — Primary/Official — 2026-07-31 — action versions, job linkage, permissions, and artifact format.
- [Creating a GitHub Pages site](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site) — Primary/Official — 2026-07-31 — top-level entry file, visibility, and plan availability.
- [actions/deploy-pages](https://github.com/actions/deploy-pages/blob/main/README.md) — Primary/Official — 2026-07-31 — deployment permissions and environment contract.
- [GitHub Actions secure-use reference](https://docs.github.com/en/actions/reference/security/secure-use) — Primary/Official — 2026-07-31 — immutable SHA pins and untrusted workflow guidance.
- [Official static Pages starter workflow](https://github.com/actions/starter-workflows/blob/main/pages/static.yml) — Primary/Official — 2026-07-31 — deployment concurrency pattern.
- [Continuous integration with GitHub Actions](https://nix.dev/guides/recipes/continuous-integration-github-actions.html) — Primary/Official — 2026-07-31 — installing Nix in GitHub Actions.
