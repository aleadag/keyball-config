# GitHub Pages URL Discoverability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use beads-superpowers:subagent-driven-development (recommended) or beads-superpowers:executing-plans to implement this plan task-by-task. Each Task becomes a bead (`bd create -t task --parent <epic-id>`). Steps within tasks use checkbox (`- [ ]`) syntax for human readability.

**Goal:** Make the rendered keymaps directly discoverable from the repository README and GitHub repository metadata.

**Architecture:** Add one prominent Markdown link to the existing README, then publish that commit and set the repository description and website through GitHub's API. Read back both the local/public content and remote metadata so the result is verified at every user-facing surface.

**Tech Stack:** Markdown, Git, GitHub CLI/API, GitHub Pages, curl

## Global Constraints

- Use the exact repository description: `Back up and visualize Keyball Vial configurations with Nix and GitHub Pages.`
- Use the exact Pages URL: `https://aleadag.github.io/keyball-config/`.
- Add `[View the rendered keymaps](https://aleadag.github.io/keyball-config/)` immediately below the README title.
- Do not add a badge, duplicate deployment instructions, change the Pages workflow or generated site, or introduce redirects.
- Do not change or commit generated files.

---

### Task 1: Add the README link

**Files:**
- Modify: `README.md:1`

**Interfaces:**
- Consumes: The deployed Pages URL `https://aleadag.github.io/keyball-config/`.
- Produces: A documentation-only commit whose README exposes the rendered keymaps immediately below its title.

**Acceptance Criteria:**
- `README.md` contains the exact Markdown link `[View the rendered keymaps](https://aleadag.github.io/keyball-config/)` immediately below the H1 title, separated by one blank line on each side.
- No other README content or repository file changes.
- The committed diff contains only `README.md`.

- [ ] **Step 1: Verify the starting position and clean scope**

Run:

```bash
sed -n '1,8p' README.md
git status --short
```

Expected: the first line is `# Keyball configuration backup and keymap site`, the link is absent, and the worktree has no unrelated changes.

- [ ] **Step 2: Add the exact link**

Change the opening of `README.md` to:

```markdown
# Keyball configuration backup and keymap site

[View the rendered keymaps](https://aleadag.github.io/keyball-config/)

This repository keeps canonical Vial settings for supported Keyball keyboards
```

- [ ] **Step 3: Verify placement and diff hygiene**

Run:

```bash
sed -n '1,8p' README.md
git diff --check
git diff -- README.md
git status --short
```

Expected: the exact link appears immediately below the title; `git diff --check` prints nothing; the diff is a two-line README insertion; only `README.md` is modified.

- [ ] **Step 4: Commit the README change**

Run:

```bash
git add README.md
git diff --cached --check
git diff --cached --stat
git commit -m "📝 docs: link rendered keymaps"
```

Expected: the staged diff contains only `README.md`, and Git creates one documentation commit.

### Task 2: Publish and verify repository discoverability

**Files:**
- Modify: GitHub repository metadata for `aleadag/keyball-config` (`description` and `homepage` fields)
- Publish: the Task 1 commit to `origin/main`

**Interfaces:**
- Consumes: The documentation-only commit produced by Task 1 and an authenticated GitHub CLI session with write access to `aleadag/keyball-config`.
- Produces: A public repository landing page whose README, description, and website expose the rendered keymaps.

**Acceptance Criteria:**
- `origin/main` contains the Task 1 README commit.
- The GitHub description is exactly `Back up and visualize Keyball Vial configurations with Nix and GitHub Pages.`
- The GitHub homepage is exactly `https://aleadag.github.io/keyball-config/`.
- The Pages URL responds successfully, and the public README contains the exact rendered-keymaps link.
- The local worktree is clean after publication.

- [ ] **Step 1: Record current remote state and verify the Pages site**

Run:

```bash
gh api repos/aleadag/keyball-config --jq '{description, homepage}'
curl --fail --silent --show-error --location --output /dev/null --write-out '%{http_code}\n' https://aleadag.github.io/keyball-config/
```

Expected before mutation: GitHub reports `null` for both metadata fields, and curl prints `200`.

- [ ] **Step 2: Publish the README commit**

Run:

```bash
git push origin main
```

Expected: Git reports that `main` was updated on `origin` without a force push.

- [ ] **Step 3: Set the exact repository metadata**

Run:

```bash
gh api --method PATCH repos/aleadag/keyball-config \
  -f description='Back up and visualize Keyball Vial configurations with Nix and GitHub Pages.' \
  -f homepage='https://aleadag.github.io/keyball-config/' \
  --jq '{description, homepage}'
```

Expected: the returned object contains the exact description and homepage from the global constraints.

- [ ] **Step 4: Verify all public surfaces and local state**

Run:

```bash
gh api repos/aleadag/keyball-config --jq '{description, homepage}'
gh api repos/aleadag/keyball-config/readme -H 'Accept: application/vnd.github.raw+json' | rg -F '[View the rendered keymaps](https://aleadag.github.io/keyball-config/)'
curl --fail --silent --show-error --location --output /dev/null --write-out '%{http_code}\n' https://aleadag.github.io/keyball-config/
git status --short
git rev-parse HEAD
git rev-parse origin/main
```

Expected: metadata matches exactly; `rg` prints the README link; curl prints `200`; status prints nothing; and the two revision hashes are identical.

- [ ] **Step 5: Record rollback commands in the handoff**

If rollback is requested, revert the README commit and publish the revert, then restore the prior metadata values recorded in Step 1. For the currently empty fields, use:

```bash
gh api --method PATCH repos/aleadag/keyball-config -f description= -f homepage=
```

Expected: GitHub returns repository metadata with empty description and homepage fields; no rollback is performed unless explicitly requested.
