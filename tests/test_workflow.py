from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

import yaml


WORKFLOWS_DIR = Path(".github/workflows")
WORKFLOW_PATH = WORKFLOWS_DIR / "pages.yml"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
TRUSTED_MAIN = (
    "github.ref == 'refs/heads/main' && "
    "(github.event_name == 'push' || github.event_name == 'workflow_dispatch')"
)
EXPECTED_ACTIONS = {
    "actions/checkout": ("3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
    "DeterminateSystems/nix-installer-action": (
        "ef8a148080ab6020fd15196c2084a2eea5ff2d25",
        "v22",
    ),
    "actions/configure-pages": (
        "45bfe0192ca1faeb007ade9deae92b16b8254a0d",
        "v6.0.0",
    ),
    "actions/upload-pages-artifact": (
        "fc324d3547104276b827a68afc52ff2a11cc49c9",
        "v5.0.0",
    ),
    "actions/deploy-pages": (
        "cd2ce8fcbc39b97be8ca5fce6e763baed58fa128",
        "v5.0.0",
    ),
}
EXPECTED_ACTION_REFS = [
    f"{action}@{sha}"
    for action, (sha, _tag) in (
        ("actions/checkout", EXPECTED_ACTIONS["actions/checkout"]),
        (
            "DeterminateSystems/nix-installer-action",
            EXPECTED_ACTIONS["DeterminateSystems/nix-installer-action"],
        ),
        (
            "actions/upload-pages-artifact",
            EXPECTED_ACTIONS["actions/upload-pages-artifact"],
        ),
        ("actions/configure-pages", EXPECTED_ACTIONS["actions/configure-pages"]),
        ("actions/deploy-pages", EXPECTED_ACTIONS["actions/deploy-pages"]),
    )
]
EXPECTED_WORKFLOW = {
    "name": "Build and deploy keymaps",
    "on": {
        "pull_request": {"branches": ["main"]},
        "push": {"branches": ["main"]},
        "workflow_dispatch": None,
    },
    "jobs": {
        "build": {
            "permissions": {"contents": "read"},
            "runs-on": "ubuntu-latest",
            "steps": [
                {
                    "name": "Check out repository",
                    "uses": EXPECTED_ACTION_REFS[0],
                    "with": {"persist-credentials": False},
                },
                {
                    "name": "Install Nix",
                    "uses": EXPECTED_ACTION_REFS[1],
                    "with": {"determinate": False, "github-token": ""},
                },
                {
                    "name": "Check flake",
                    "run": "nix flake check --print-build-logs",
                },
                {"name": "Build site", "run": "nix build .#site"},
                {
                    "name": "Copy realized site",
                    "run": "rm -rf _site\nmkdir _site\ncp -aL result/. _site/\n",
                },
                {
                    "name": "Validate publication artifact",
                    "run": "nix run .#validate-site -- _site",
                },
                {
                    "name": "Upload Pages artifact",
                    "if": TRUSTED_MAIN,
                    "uses": EXPECTED_ACTION_REFS[2],
                    "with": {"path": "_site"},
                },
            ],
        },
        "deploy": {
            "needs": "build",
            "if": TRUSTED_MAIN,
            "permissions": {"pages": "write", "id-token": "write"},
            "environment": {
                "name": "github-pages",
                "url": "${{ steps.deployment.outputs.page_url }}",
            },
            "runs-on": "ubuntu-latest",
            "concurrency": {"group": "pages", "cancel-in-progress": False},
            "steps": [
                {
                    "name": "Configure Pages",
                    "uses": EXPECTED_ACTION_REFS[3],
                },
                {
                    "name": "Deploy to GitHub Pages",
                    "id": "deployment",
                    "uses": EXPECTED_ACTION_REFS[4],
                },
            ],
        },
    },
}


def load_workflow(path: Path) -> dict[str, object]:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(workflow, dict):
        raise AssertionError("workflow must parse as a mapping")
    # PyYAML follows YAML 1.1 and treats the workflow key `on` as a boolean.
    if True in workflow and "on" not in workflow:
        workflow["on"] = workflow.pop(True)
    return workflow


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _uses_values(value: object) -> list[str]:
    if isinstance(value, dict):
        found: list[str] = []
        for key, nested in value.items():
            if key == "uses":
                _require(isinstance(nested, str), "every uses value must be a string")
                found.append(nested)
            found.extend(_uses_values(nested))
        return found
    if isinstance(value, list):
        found = []
        for nested in value:
            found.extend(_uses_values(nested))
        return found
    return []


def assert_workflow_policy(workflows_dir: Path) -> None:
    entries = sorted(workflows_dir.iterdir(), key=lambda path: path.name)
    _require(
        [entry.name for entry in entries] == ["pages.yml"],
        "workflow directory must contain only pages.yml",
    )
    workflow_path = entries[0]
    _require(
        workflow_path.is_file() and not workflow_path.is_symlink(),
        "pages.yml must be a regular non-symlink file",
    )

    raw = workflow_path.read_text(encoding="utf-8")
    workflow = load_workflow(workflow_path)
    _require(
        workflow == EXPECTED_WORKFLOW,
        "parsed workflow graph differs from the reviewed policy",
    )

    uses_values = _uses_values(workflow)
    _require(
        uses_values == EXPECTED_ACTION_REFS,
        "workflow action graph differs from the reviewed action list",
    )
    for action_ref in uses_values:
        action, separator, sha = action_ref.rpartition("@")
        _require(bool(action) and separator == "@", f"invalid action ref: {action_ref}")
        _require(bool(FULL_SHA.fullmatch(sha)), f"action is not full-SHA pinned: {action_ref}")

    for action, (sha, tag) in EXPECTED_ACTIONS.items():
        tag_line = re.compile(
            rf"^\s+uses:\s+{re.escape(action)}@{sha}\s+#\s+{re.escape(tag)}\s*$",
            flags=re.MULTILINE,
        )
        _require(
            len(tag_line.findall(raw)) == 1,
            f"{action} must have exactly one reviewed tag comment",
        )


class PagesWorkflowPolicyTests(unittest.TestCase):
    def test_repository_workflow_matches_exact_reviewed_policy(self) -> None:
        assert_workflow_policy(WORKFLOWS_DIR)


class PagesWorkflowMutationTests(unittest.TestCase):
    canonical = WORKFLOW_PATH.read_text(encoding="utf-8")

    def assert_rejected(self, raw: str, extras: dict[str, str] | None = None) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workflows = Path(temporary) / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (workflows / "pages.yml").write_text(raw, encoding="utf-8")
            for name, contents in (extras or {}).items():
                (workflows / name).write_text(contents, encoding="utf-8")
            with self.assertRaises(AssertionError):
                assert_workflow_policy(workflows)

    def assert_mutations_rejected(self, mutations: dict[str, str]) -> None:
        for name, mutated in mutations.items():
            with self.subTest(name=name):
                self.assertNotEqual(mutated, self.canonical)
                self.assert_rejected(mutated)

    def test_extra_workflow_entries_are_rejected(self) -> None:
        extra_workflow = "name: bypass\non: workflow_dispatch\njobs: {}\n"
        for name in ("evil.yml", "evil.yaml", "README"):
            with self.subTest(name=name):
                self.assert_rejected(self.canonical, {name: extra_workflow})

    def test_symlinked_pages_workflow_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True)
            target = root / "pages.yml"
            target.write_text(self.canonical, encoding="utf-8")
            (workflows / "pages.yml").symlink_to(target)
            with self.assertRaises(AssertionError):
                assert_workflow_policy(workflows)

    def test_extra_job_and_flow_style_mutable_action_are_rejected(self) -> None:
        mutated = self.canonical + (
            "\n  bypass:\n"
            "    permissions: write-all\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - {uses: evil/example@main}\n"
        )
        self.assert_rejected(mutated)

    def test_extra_run_cache_or_upload_steps_are_rejected(self) -> None:
        self.assert_mutations_rejected(
            {
                "run step": self.canonical.replace(
                    "\n  deploy:\n",
                    "\n      - run: echo bypass\n\n  deploy:\n",
                ),
                "cache action": self.canonical.replace(
                    "\n  deploy:\n",
                    "\n      - {uses: actions/cache@main}\n\n  deploy:\n",
                ),
                "extra upload": self.canonical.replace(
                    "\n  deploy:\n",
                    "\n      - uses: actions/upload-pages-artifact@"
                    f"{EXPECTED_ACTIONS['actions/upload-pages-artifact'][0]}\n"
                    "        with: {path: .}\n\n  deploy:\n",
                ),
            }
        )

    def test_extra_job_secrets_or_environment_are_rejected(self) -> None:
        self.assert_mutations_rejected(
            {
                "job secrets": self.canonical.replace(
                    "  build:\n", "  build:\n    secrets: inherit\n", 1
                ),
                "job env": self.canonical.replace(
                    "  build:\n", "  build:\n    env: {BYPASS: enabled}\n", 1
                ),
            }
        )

    def test_extra_token_or_continue_on_error_is_rejected(self) -> None:
        self.assert_mutations_rejected(
            {
                "step token": self.canonical.replace(
                    "          persist-credentials: false\n",
                    "          persist-credentials: false\n          token: bypass\n",
                    1,
                ),
                "continue on error": self.canonical.replace(
                    "      - name: Check flake\n",
                    "      - name: Check flake\n        continue-on-error: true\n",
                    1,
                ),
            }
        )


if __name__ == "__main__":
    unittest.main()
