from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
from typing import Sequence

from keyball_config.backup import BackupError, Runner, backup, run_command
from keyball_config.devices import load_registry
from keyball_config.keymap import RenderError, RenderTools, render_present
from keyball_config.site import SiteError, build_site, validate_site


def main(
    argv: Sequence[str] | None = None,
    *,
    repo: Path | None = None,
    registry_path: Path | None = None,
    runner: Runner = run_command,
    render_tools: RenderTools | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog="keyball-config")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup", help="safely back up the connected Keyball")
    render = commands.add_parser("render", help="render backed-up Keyball keymaps")
    render.add_argument("--output", type=Path, default=Path("build"))
    render.add_argument("--model", help="render only one model for diagnosis")
    site = commands.add_parser("site", help="build the complete static keymap site")
    site.add_argument("--output", type=Path, default=Path("build/site"))
    site_validation = commands.add_parser(
        "validate-site", help="validate an exact static site artifact"
    )
    site_validation.add_argument("path", type=Path)
    arguments = parser.parse_args(argv)

    root = repo or Path.cwd()
    registry = registry_path or root / "config" / "models.json"
    if arguments.command == "backup":
        try:
            target = backup(root, registry, runner)
        except BackupError as error:
            parser.exit(1, f"backup failed: {error}\n")
        print(target)
        return 0
    if arguments.command == "render":
        try:
            models = load_registry(registry)
            tools = render_tools or _default_render_tools()
            output = arguments.output
            if not output.is_absolute():
                output = root / output
            rendered = render_present(
                root,
                output,
                models,
                tools,
                runner,
                only_model=arguments.model,
            )
        except (OSError, ValueError, RenderError) as error:
            parser.exit(1, f"render failed: {error}\n")
        for path in rendered:
            print(path)
        return 0
    if arguments.command == "site":
        try:
            models = load_registry(registry)
            tools = render_tools or _default_render_tools()
            output = arguments.output
            if not output.is_absolute():
                output = root / output
            built = build_site(root, output, models, tools, runner)
        except (OSError, ValueError, RenderError, SiteError) as error:
            parser.exit(1, f"site build failed: {error}\n")
        for path in built:
            print(path)
        return 0
    if arguments.command == "validate-site":
        try:
            models = load_registry(registry)
            expected = tuple(
                slug
                for slug, model in sorted(models.items())
                if (root / model.backup_filename).is_file()
            )
            site_path = arguments.path
            if not site_path.is_absolute():
                site_path = root / site_path
            validate_site(site_path, expected)
        except (OSError, ValueError, SiteError) as error:
            parser.exit(1, f"site validation failed: {error}\n")
        print(site_path)
        return 0
    raise AssertionError(f"unhandled command: {arguments.command}")


def _default_render_tools() -> RenderTools:
    converter = Path(
        os.environ.get("KEYBALL_CONVERTER")
        or shutil.which("vial-converter")
        or "vial-converter"
    )
    keymap = Path(
        os.environ.get("KEYBALL_KEYMAP") or shutil.which("keymap") or "keymap"
    )
    geometry_override = os.environ.get("KEYBALL_GEOMETRY_ROOT")
    if geometry_override:
        geometry_root = Path(geometry_override)
    else:
        geometry_root = (
            converter.resolve().parent.parent / "share" / "keyball-geometry"
        )
    return RenderTools(converter, keymap, geometry_root)


if __name__ == "__main__":
    raise SystemExit(main())
