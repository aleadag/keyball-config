from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from keyball_config.backup import BackupError, Runner, backup, run_command


def main(
    argv: Sequence[str] | None = None,
    *,
    repo: Path | None = None,
    registry_path: Path | None = None,
    runner: Runner = run_command,
) -> int:
    parser = argparse.ArgumentParser(prog="keyball-config")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup", help="safely back up the connected Keyball")
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
    raise AssertionError(f"unhandled command: {arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())
