from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Callable, Sequence
import unittest
from unittest.mock import patch

from keyball_config.backup import BackupError, CommandResult, backup, run_command
from keyball_config.cli import main


FIXTURES = Path(__file__).parent / "fixtures"
REGISTRY = Path("config/models.json").resolve()
VALID_KEYBALL39 = (FIXTURES / "vial" / "valid-keyball39.vil").read_bytes()
VALID_KEYBALL44 = (FIXTURES / "vial" / "valid-keyball44.vil").read_bytes()
OBSERVED_KEYBALL44 = Path("keyball44.vil").read_bytes()
KEYBALL44_DEVICES = (FIXTURES / "devices" / "trackball-44-v3.txt").read_text()
KEYBALL39_DEVICES = (FIXTURES / "devices" / "keyball-39.txt").read_text()


def definition_bytes(rows: int = 8, columns: int = 6) -> bytes:
    return (
        json.dumps(
            {
                "matrix": {"rows": rows, "cols": columns},
                "layouts": {
                    "keymap": [
                        [f"{row},{column}" for column in range(columns)]
                        for row in range(rows)
                    ]
                },
            },
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


VALID_KEYBALL44_DEFINITION = definition_bytes()
VALID_KEYBALL39_DEFINITION = definition_bytes()


OutputAction = Callable[[Path], None]


class FakeRunner:
    def __init__(
        self,
        *,
        devices: CommandResult | None = None,
        status: CommandResult | Sequence[CommandResult] | None = None,
        tracked: CommandResult | Sequence[CommandResult] | None = None,
        save: CommandResult | None = None,
        save_devices: str | None = None,
        save_success_markers: int = 1,
        save_trailing: str = "",
        output: bytes | None = VALID_KEYBALL44,
        definition: bytes | None = VALID_KEYBALL44_DEFINITION,
        output_action: OutputAction | None = None,
        after_save: OutputAction | None = None,
        during_final_status: OutputAction | None = None,
        save_error: OSError | None = None,
    ) -> None:
        self.devices = devices if devices is not None else CommandResult(
            0, KEYBALL44_DEVICES, ""
        )
        self.status = self._results(status, CommandResult(0, "", ""))
        self.tracked = self._results(tracked, None)
        self.save = save
        self.save_devices = save_devices
        self.save_success_markers = save_success_markers
        self.save_trailing = save_trailing
        self.output = output
        self.definition = definition
        self.output_action = output_action
        self.after_save = after_save
        self.during_final_status = during_final_status
        self.save_error = save_error
        self.calls: list[tuple[tuple[str, ...], Path]] = []
        self.save_paths: list[Path] = []
        self.definition_paths: list[Path] = []
        self.save_dirs: list[Path] = []
        self.save_dir_modes: list[int] = []
        self.save_path_existed: bool | None = None
        self._status_index = 0
        self._tracked_index = 0
        self._during_final_status_called = False
        self._save_has_definition = False

    @staticmethod
    def _results(
        value: CommandResult | Sequence[CommandResult] | None,
        default: CommandResult | None,
    ) -> list[CommandResult] | None:
        if value is None:
            return None if default is None else [default]
        if isinstance(value, CommandResult):
            return [value]
        return list(value)

    @staticmethod
    def _next(results: list[CommandResult], index: int) -> CommandResult:
        return results[min(index, len(results) - 1)]

    def __call__(self, args: Sequence[str], cwd: Path) -> CommandResult:
        command = tuple(args)
        self.calls.append((command, cwd))
        if command == ("vitaly", "devices"):
            return self.devices
        if command[:3] == ("git", "--literal-pathspecs", "status"):
            assert self.status is not None
            if (
                self._status_index >= (2 if self._save_has_definition else 1)
                and not self._during_final_status_called
                and self.during_final_status is not None
                and self.save_paths
            ):
                self.during_final_status(self.save_paths[-1])
                self._during_final_status_called = True
            result = self._next(self.status, self._status_index)
            self._status_index += 1
            return result
        if command[:3] == ("git", "--literal-pathspecs", "ls-files"):
            if self.tracked is None:
                return CommandResult(0, f"{command[-1]}\n", "")
            result = self._next(self.tracked, self._tracked_index)
            self._tracked_index += 1
            return result
        if len(command) >= 6 and command[:2] == ("vitaly", "-i"):
            if self.save_error is not None:
                raise self.save_error
            self._save_has_definition = "-d" in command
            vil_path = Path(command[command.index("-f") + 1])
            definition_path = (
                Path(command[command.index("-d") + 1])
                if "-d" in command
                else None
            )
            self.save_paths.append(vil_path)
            if definition_path is not None:
                self.definition_paths.append(definition_path)
            self.save_dirs.append(vil_path.parent)
            self.save_dir_modes.append(
                stat.S_IMODE(vil_path.parent.stat().st_mode)
            )
            self.save_path_existed = vil_path.exists() or vil_path.is_symlink()
            if self.output_action is not None:
                self.output_action(vil_path)
            elif self.output is not None:
                vil_path.write_bytes(self.output)
            if definition_path is not None and self.definition is not None:
                definition_path.write_bytes(self.definition)
            if self.after_save is not None:
                self.after_save(vil_path)
            if self.save is not None:
                return self.save
            save_devices = (
                self.devices.stdout
                if self.save_devices is None
                else self.save_devices
            )
            success = f"Configuration saved to file {vil_path}\n"
            stdout = (
                save_devices
                + "\n"
                + success * self.save_success_markers
                + self.save_trailing
            )
            return CommandResult(0, stdout, "")
        raise AssertionError(f"unexpected command: {command!r}")


class CommandEnvironmentTests(unittest.TestCase):
    def test_runner_sets_complete_deterministic_locale_and_time_environment(self) -> None:
        ambient = {
            "LANG": "zh_CN.UTF-8",
            "LC_ALL": "fr_FR.UTF-8",
            "TZ": "Asia/Shanghai",
            "SOURCE_DATE_EPOCH": "1234",
        }
        with patch.dict(os.environ, ambient), patch(
            "keyball_config.backup.subprocess.run",
            return_value=CommandResult(0, "", ""),
        ) as invoked:
            run_command(("example",), Path("."))

        environment = invoked.call_args.kwargs["env"]
        self.assertEqual(environment["LC_ALL"], "C.UTF-8")
        self.assertEqual(environment["LANG"], "C.UTF-8")
        self.assertEqual(environment["TZ"], "UTC")
        self.assertEqual(environment["SOURCE_DATE_EPOCH"], "0")


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.repo = Path(self.directory.name)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def assert_temporary_paths_removed(self, runner: FakeRunner) -> None:
        for save_path in runner.save_paths:
            self.assertFalse(save_path.exists())
            self.assertFalse(save_path.is_symlink())
        for definition_path in runner.definition_paths:
            self.assertFalse(definition_path.exists())
            self.assertFalse(definition_path.is_symlink())
        for save_dir in runner.save_dirs:
            self.assertFalse(save_dir.exists())

    def assert_preserved(self, target: Path, old: bytes, runner: FakeRunner) -> None:
        with self.assertRaises(BackupError):
            backup(self.repo, REGISTRY, runner)
        self.assertEqual(target.read_bytes(), old)
        self.assert_temporary_paths_removed(runner)

    def test_initial_backup_creates_detected_model_target(self) -> None:
        runner = FakeRunner()

        result = backup(self.repo, REGISTRY, runner)

        target = self.repo / "keyball44.vil"
        self.assertEqual(result, target)
        self.assertEqual(target.read_bytes(), VALID_KEYBALL44)
        self.assertEqual(
            (self.repo / "keyball44.vial.json").read_bytes(),
            VALID_KEYBALL44_DEFINITION,
        )
        self.assertFalse((self.repo / "keyball39.vil").exists())
        status_command = (
            "git",
            "--literal-pathspecs",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            "keyball44.vil",
        )
        self.assertEqual([call[0] for call in runner.calls].count(status_command), 2)
        self.assertFalse(any("ls-files" in call[0] for call in runner.calls))
        self.assertTrue(
            any(
                call[0][:5] == ("vitaly", "-i", "16718", "save", "-f")
                for call in runner.calls
            )
        )
        self.assertTrue(
            any(
                "-d" in call[0]
                for call in runner.calls
                if call[0][:2] == ("vitaly", "-i")
            )
        )
        self.assertEqual(runner.save_paths[0].parent.parent, self.repo)
        self.assertEqual(runner.save_dir_modes, [0o700])
        self.assertFalse(runner.save_path_existed)
        self.assert_temporary_paths_removed(runner)

    def test_dirty_companion_target_is_refused_before_export(self) -> None:
        companion = self.repo / "keyball44.vial.json"
        runner = FakeRunner(
            status=(
                CommandResult(0, "", ""),
                CommandResult(0, "?? keyball44.vial.json\n", ""),
            )
        )

        with self.assertRaisesRegex(BackupError, "changed target keyball44.vial.json"):
            backup(self.repo, REGISTRY, runner)

        self.assertFalse(runner.save_paths)
        self.assertFalse(companion.exists())

    def test_malformed_companion_preserves_existing_pair(self) -> None:
        target = self.repo / "keyball44.vil"
        companion = self.repo / "keyball44.vial.json"
        old_vil = b"old backup"
        old_definition = b"old definition"
        target.write_bytes(old_vil)
        companion.write_bytes(old_definition)
        runner = FakeRunner(definition=b"{}")

        with self.assertRaisesRegex(BackupError, "invalid Vial definition"):
            backup(self.repo, REGISTRY, runner)

        self.assertEqual(target.read_bytes(), old_vil)
        self.assertEqual(companion.read_bytes(), old_definition)
        self.assert_temporary_paths_removed(runner)

    def test_companion_created_during_export_is_refused(self) -> None:
        companion = self.repo / "keyball44.vial.json"

        def create_companion(_: Path) -> None:
            companion.write_bytes(b"concurrent definition")

        runner = FakeRunner(after_save=create_companion)

        with self.assertRaisesRegex(BackupError, "target keyball44.vial.json changed"):
            backup(self.repo, REGISTRY, runner)

        self.assertEqual(companion.read_bytes(), b"concurrent definition")
        self.assert_temporary_paths_removed(runner)

    def test_failed_pair_replacement_rolls_back_both_targets(self) -> None:
        target = self.repo / "keyball44.vil"
        companion = self.repo / "keyball44.vial.json"
        old_vil = b"old backup"
        old_definition = b"old definition"
        target.write_bytes(old_vil)
        companion.write_bytes(old_definition)
        runner = FakeRunner()
        real_replace = os.replace
        replace_calls = 0

        def fail_on_companion_install(*args, **kwargs):
            nonlocal replace_calls
            replace_calls += 1
            if replace_calls == 4:
                raise OSError("simulated companion replacement failure")
            return real_replace(*args, **kwargs)

        with patch("keyball_config.backup.os.replace", side_effect=fail_on_companion_install):
            with self.assertRaisesRegex(BackupError, "atomically replace backup pair"):
                backup(self.repo, REGISTRY, runner)

        self.assertEqual(target.read_bytes(), old_vil)
        self.assertEqual(companion.read_bytes(), old_definition)
        self.assert_temporary_paths_removed(runner)

    def test_clean_tracked_existing_backup_is_replaced(self) -> None:
        target = self.repo / "keyball44.vil"
        target.write_bytes(b"old backup")
        runner = FakeRunner()

        result = backup(self.repo, REGISTRY, runner)

        self.assertEqual(result, target)
        self.assertEqual(target.read_bytes(), VALID_KEYBALL44)
        self.assertEqual(
            sum("ls-files" in call[0] for call in runner.calls),
            2,
        )

    def test_only_detected_model_is_replaced_with_its_valid_shape(self) -> None:
        old_39 = b"old keyball39"
        old_44 = b"old keyball44"
        target = self.repo / "keyball39.vil"
        target.write_bytes(old_39)
        other = self.repo / "keyball44.vil"
        other.write_bytes(old_44)
        runner = FakeRunner(
            devices=CommandResult(0, KEYBALL39_DEVICES, ""),
            output=VALID_KEYBALL39,
        )

        result = backup(self.repo, REGISTRY, runner)

        self.assertEqual(result, target)
        self.assertEqual(target.read_bytes(), VALID_KEYBALL39)
        self.assertEqual(other.read_bytes(), old_44)

    def test_keyball44_eight_by_seven_export_is_rejected_for_keyball39(self) -> None:
        target = self.repo / "keyball39.vil"
        old = b"old keyball39"
        target.write_bytes(old)
        runner = FakeRunner(
            devices=CommandResult(0, KEYBALL39_DEVICES, ""),
            output=OBSERVED_KEYBALL44,
        )

        self.assert_preserved(target, old, runner)

    def test_existing_target_with_any_porcelain_status_is_refused(self) -> None:
        old = b"old backup"
        statuses = (" M keyball44.vil\n", "M  keyball44.vil\n", "?? keyball44.vil\n")
        for status in statuses:
            with self.subTest(status=status):
                target = self.repo / "keyball44.vil"
                target.write_bytes(old)
                runner = FakeRunner(status=CommandResult(0, status, ""))

                self.assert_preserved(target, old, runner)
                self.assertFalse(any("save" in call[0] for call in runner.calls))

    def test_blank_status_existing_untracked_or_ignored_target_is_refused(self) -> None:
        target = self.repo / "keyball44.vil"
        old = b"untracked or ignored"
        target.write_bytes(old)
        runner = FakeRunner(tracked=CommandResult(1, "", "not tracked"))

        self.assert_preserved(target, old, runner)
        self.assertFalse(any("save" in call[0] for call in runner.calls))

    def test_deleted_target_with_porcelain_status_is_not_recreated(self) -> None:
        for status in (" D keyball44.vil\n", "D  keyball44.vil\n"):
            with self.subTest(status=status):
                target = self.repo / "keyball44.vil"
                runner = FakeRunner(status=CommandResult(0, status, ""))

                with self.assertRaises(BackupError):
                    backup(self.repo, REGISTRY, runner)

                self.assertFalse(target.exists())
                self.assertFalse(any("save" in call[0] for call in runner.calls))

    def test_git_status_or_tracked_inspection_failure_preserves_backup(self) -> None:
        target = self.repo / "keyball44.vil"
        old = b"old backup"
        target.write_bytes(old)
        runners = (
            FakeRunner(status=CommandResult(128, "", "fatal")),
            FakeRunner(tracked=CommandResult(128, "", "fatal")),
        )
        for runner in runners:
            with self.subTest(runner=runner):
                self.assert_preserved(target, old, runner)

    def test_existing_target_modified_during_save_is_preserved_and_refused(self) -> None:
        target = self.repo / "keyball44.vil"
        target.write_bytes(b"old backup")
        new = b"new concurrent bytes"

        def mutate_target(_: Path) -> None:
            target.write_bytes(new)

        runner = FakeRunner(after_save=mutate_target)

        with self.assertRaises(BackupError):
            backup(self.repo, REGISTRY, runner)

        self.assertEqual(target.read_bytes(), new)
        self.assert_temporary_paths_removed(runner)

    def test_existing_target_inode_replaced_during_save_is_refused(self) -> None:
        target = self.repo / "keyball44.vil"
        old = b"old backup"
        target.write_bytes(old)

        def replace_target(_: Path) -> None:
            replacement = self.repo / "replacement"
            replacement.write_bytes(old)
            os.replace(replacement, target)

        runner = FakeRunner(after_save=replace_target)

        with self.assertRaises(BackupError):
            backup(self.repo, REGISTRY, runner)

        self.assertEqual(target.read_bytes(), old)
        self.assert_temporary_paths_removed(runner)

    def test_absent_target_created_during_save_is_preserved_and_refused(self) -> None:
        target = self.repo / "keyball44.vil"
        new = b"new concurrent file"

        def create_target(_: Path) -> None:
            target.write_bytes(new)

        runner = FakeRunner(after_save=create_target)

        with self.assertRaises(BackupError):
            backup(self.repo, REGISTRY, runner)

        self.assertEqual(target.read_bytes(), new)
        self.assert_temporary_paths_removed(runner)

    def test_selection_failures_preserve_existing_backup(self) -> None:
        target = self.repo / "keyball44.vil"
        old = b"old backup"
        target.write_bytes(old)
        outputs = (
            "",
            (FIXTURES / "devices" / "multiple.txt").read_text(),
            (FIXTURES / "devices" / "selector-collision.txt").read_text(),
            (FIXTURES / "devices" / "unsupported.txt").read_text(),
            (FIXTURES / "devices" / "malformed.txt").read_text(),
        )
        for output in outputs:
            with self.subTest(output=output):
                runner = FakeRunner(devices=CommandResult(0, output, ""))

                self.assert_preserved(target, old, runner)
                self.assertEqual(len(runner.calls), 1)

    def test_device_listing_requires_zero_status_and_empty_stderr(self) -> None:
        target = self.repo / "keyball44.vil"
        old = b"old backup"
        target.write_bytes(old)
        results = (
            CommandResult(1, KEYBALL44_DEVICES, "Error: device failure"),
            CommandResult(0, KEYBALL44_DEVICES, "Error: device failure"),
            CommandResult(0, KEYBALL44_DEVICES, "error count: 0"),
            CommandResult(0, "", "No matching devices found"),
        )
        for result in results:
            with self.subTest(result=result):
                self.assert_preserved(
                    target, old, FakeRunner(devices=result)
                )

    def test_nonzero_export_preserves_existing_backup(self) -> None:
        target = self.repo / "keyball44.vil"
        old = b"old backup"
        target.write_bytes(old)
        runner = FakeRunner(save=CommandResult(1, "", "Error: failed"))

        self.assert_preserved(target, old, runner)

    def test_export_requires_empty_stderr_exact_success_and_no_errors(self) -> None:
        target = self.repo / "keyball44.vil"
        old = b"old backup"
        target.write_bytes(old)
        results = (
            CommandResult(0, "Configuration saved to another file", ""),
            CommandResult(0, "", "Error: export failed"),
            CommandResult(0, "", "No matching devices found"),
            CommandResult(0, "Error: export failed", ""),
            CommandResult(0, "Unable to save", ""),
            CommandResult(0, "Exception while saving", ""),
            CommandResult(0, "Export aborted", ""),
        )
        for result in results:
            with self.subTest(result=result):
                self.assert_preserved(target, old, FakeRunner(save=result))

    def test_save_time_device_identity_and_transcript_failures_preserve_backup(self) -> None:
        target = self.repo / "keyball44.vil"
        old = b"old backup"
        target.write_bytes(old)
        collision = (FIXTURES / "devices" / "selector-collision.txt").read_text()
        replacement = "\n".join(collision.splitlines()[3:]) + "\n"
        same_pid_changed_endpoint = KEYBALL44_DEVICES.replace(
            'Serial: "vial:f64c2b3c", Path: "/dev/hidraw3"',
            'Serial: "vial:replacement", Path: "/dev/hidraw9"',
        )
        incomplete = "\n".join(KEYBALL44_DEVICES.splitlines()[:2]) + "\n"
        cases = (
            ("second same-PID record", FakeRunner(save_devices=collision)),
            ("replaced same-PID record", FakeRunner(save_devices=replacement)),
            (
                "same name/PID with changed endpoint",
                FakeRunner(save_devices=same_pid_changed_endpoint),
            ),
            ("missing record", FakeRunner(save_devices="")),
            ("incomplete record", FakeRunner(save_devices=incomplete)),
            ("duplicate success marker", FakeRunner(save_success_markers=2)),
            (
                "nonblank trailing output",
                FakeRunner(save_trailing="unexpected trailing output\n"),
            ),
        )

        for name, runner in cases:
            with self.subTest(name=name):
                self.assert_preserved(target, old, runner)

    def test_missing_output_preserves_backup_and_cleans_private_directory(self) -> None:
        target = self.repo / "keyball44.vil"
        old = b"old backup"
        target.write_bytes(old)
        runner = FakeRunner(output=None)

        self.assert_preserved(target, old, runner)
        self.assertFalse(runner.save_path_existed)

    def test_invalid_output_preserves_backup_and_cleans_private_directory(self) -> None:
        invalid_model = json.loads(VALID_KEYBALL44)
        invalid_model["vial_protocol"] = 99
        invalid_outputs = (
            b"",
            (FIXTURES / "vial" / "malformed.vil").read_bytes(),
            json.dumps(invalid_model).encode(),
        )
        for output in invalid_outputs:
            with self.subTest(output=output):
                target = self.repo / "keyball44.vil"
                old = b"old backup"
                target.write_bytes(old)

                self.assert_preserved(target, old, FakeRunner(output=output))

    def test_directory_or_symlink_output_preserves_existing_backup(self) -> None:
        target = self.repo / "keyball44.vil"
        old = b"old backup"
        target.write_bytes(old)
        source = self.repo / "export-source.vil"
        source.write_bytes(VALID_KEYBALL44)

        def create_directory(path: Path) -> None:
            path.mkdir()

        def create_symlink(path: Path) -> None:
            os.symlink(source, path)

        for action in (create_directory, create_symlink):
            with self.subTest(action=action):
                self.assert_preserved(
                    target, old, FakeRunner(output_action=action)
                )

    def test_hardlinked_output_preserves_existing_backup(self) -> None:
        target = self.repo / "keyball44.vil"
        old = b"old backup"
        target.write_bytes(old)
        source = self.repo / "hardlink-source.vil"
        source.write_bytes(VALID_KEYBALL44)

        def create_hardlink(path: Path) -> None:
            os.link(source, path)

        self.assert_preserved(
            target, old, FakeRunner(output_action=create_hardlink)
        )

    def test_swapped_invalid_output_preserves_existing_backup(self) -> None:
        target = self.repo / "keyball44.vil"
        old = b"old backup"
        target.write_bytes(old)

        def swap_output(path: Path) -> None:
            path.write_bytes(VALID_KEYBALL44)
            replacement = path.parent / "replacement.vil"
            replacement.write_bytes(b"not json")
            os.replace(replacement, path)

        self.assert_preserved(
            target, old, FakeRunner(output_action=swap_output)
        )

    def test_output_swapped_during_final_git_check_is_refused(self) -> None:
        target = self.repo / "keyball44.vil"
        old = b"old backup"
        target.write_bytes(old)

        def swap_output(path: Path) -> None:
            replacement = path.parent / "late-replacement.vil"
            replacement.write_bytes(VALID_KEYBALL44.replace(b"KC_A", b"KC_C"))
            os.replace(replacement, path)

        runner = FakeRunner(during_final_status=swap_output)

        self.assert_preserved(target, old, runner)

    def test_export_runner_error_preserves_existing_backup(self) -> None:
        target = self.repo / "keyball44.vil"
        old = b"old backup"
        target.write_bytes(old)
        runner = FakeRunner(save_error=OSError("cannot execute vitaly"))

        self.assert_preserved(target, old, runner)

    def test_backup_cli_exposes_only_safe_backup_arguments(self) -> None:
        runner = FakeRunner()
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            self.assertEqual(
                main(
                    ["backup"],
                    repo=self.repo,
                    registry_path=REGISTRY,
                    runner=runner,
                ),
                0,
            )
        self.assertEqual((self.repo / "keyball44.vil").read_bytes(), VALID_KEYBALL44)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(
                ["backup", "--force"],
                repo=self.repo,
                registry_path=REGISTRY,
                runner=runner,
            )


if __name__ == "__main__":
    unittest.main()
