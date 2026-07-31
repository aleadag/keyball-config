from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from typing import Callable, Sequence

from keyball_config.devices import (
    DeviceRecord,
    ModelConfig,
    load_registry,
    parse_devices,
    select_device,
)
from keyball_config.keymap import load_and_validate_vil


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str], Path], CommandResult]


class BackupError(RuntimeError):
    """A safe backup could not be completed."""


@dataclass(frozen=True)
class _TargetSnapshot:
    exists: bool
    device: int | None = None
    inode: int | None = None
    digest: bytes | None = None


_ERROR_LINE = re.compile(r"^\s*Error:", re.MULTILINE)
_FAILURE_LINE = re.compile(
    r"^\s*(?:unable|exception|aborted)\b", re.IGNORECASE | re.MULTILINE
)
_NO_MATCHING_DEVICES = "No matching devices found"


def run_command(args: Sequence[str], cwd: Path) -> CommandResult:
    environment = os.environ.copy()
    environment.update(
        {
            "LC_ALL": "C.UTF-8",
            "LANG": "C.UTF-8",
            "SOURCE_DATE_EPOCH": "0",
            "TZ": "UTC",
        }
    )
    completed = subprocess.run(
        args,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def backup(repo: Path, registry_path: Path, runner: Runner) -> Path:
    try:
        models = load_registry(registry_path)
        devices_result = runner(("vitaly", "devices"), repo)
    except (OSError, ValueError) as error:
        raise BackupError(f"cannot inspect supported devices: {error}") from error
    _require_success("vitaly devices", devices_result)

    try:
        device, model = select_device(parse_devices(devices_result.stdout), models)
    except ValueError as error:
        raise BackupError(str(error)) from error

    filename = _canonical_target_name(model)
    target = repo / filename
    initial = _snapshot_target(target)
    _inspect_git_target(repo, filename, initial.exists, runner)
    if _snapshot_target(target) != initial:
        raise BackupError(f"target {filename} changed during initial safety inspection")

    private_dir, temporary = _fresh_private_output(target)
    primary_failure: BaseException | None = None
    try:
        save_args = (
            "vitaly",
            "-i",
            str(device.product_id),
            "save",
            "-f",
            str(temporary),
        )
        try:
            save_result = runner(save_args, repo)
        except OSError as error:
            raise BackupError(f"cannot run Vitaly export: {error}") from error
        _validate_save_result(save_result, temporary, device)

        export_fd = _open_export(temporary)
        try:
            try:
                load_and_validate_vil(Path(f"/proc/self/fd/{export_fd}"), model)
                os.fsync(export_fd)
            except (OSError, ValueError) as error:
                raise BackupError(f"invalid Vitaly export: {error}") from error
            _inspect_git_target(repo, filename, initial.exists, runner)
            if _snapshot_target(target) != initial:
                raise BackupError(f"target {filename} changed while backup was running")

            _require_same_export_inode(temporary, export_fd)
            _replace_from_private_dir(repo, private_dir, temporary.name, filename)
        finally:
            os.close(export_fd)
        return target
    except BaseException as error:
        primary_failure = error
        raise
    finally:
        _cleanup_private_dir(private_dir, primary_failure)


def _canonical_target_name(model: ModelConfig) -> str:
    expected = f"{model.slug}.vil"
    filename = model.backup_filename
    if (
        re.fullmatch(r"[a-z0-9][a-z0-9_-]*", model.slug) is None
        or filename != expected
        or Path(filename).is_absolute()
        or Path(filename).name != filename
        or "/" in filename
        or "\\" in filename
        or filename.startswith(":")
    ):
        raise BackupError("model registry contains an unsafe backup_filename")
    return filename


def _inspect_git_target(
    repo: Path, filename: str, target_exists: bool, runner: Runner
) -> None:
    status_args = (
        "git",
        "--literal-pathspecs",
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        filename,
    )
    try:
        status_result = runner(status_args, repo)
    except OSError as error:
        raise BackupError(f"cannot inspect Git status for {filename}: {error}") from error
    if status_result.returncode != 0 or status_result.stderr:
        raise BackupError(_command_failure(f"cannot inspect Git status for {filename}", status_result))
    if status_result.stdout:
        raise BackupError(f"refusing to replace changed target {filename}")

    if not target_exists:
        return
    tracked_args = (
        "git",
        "--literal-pathspecs",
        "ls-files",
        "--error-unmatch",
        "--",
        filename,
    )
    try:
        tracked_result = runner(tracked_args, repo)
    except OSError as error:
        raise BackupError(f"cannot verify tracked target {filename}: {error}") from error
    if (
        tracked_result.returncode != 0
        or tracked_result.stderr
        or tracked_result.stdout.splitlines() != [filename]
    ):
        raise BackupError(
            _command_failure(f"target {filename} is not exactly tracked", tracked_result)
        )


def _snapshot_target(target: Path) -> _TargetSnapshot:
    try:
        path_metadata = target.lstat()
    except FileNotFoundError:
        return _TargetSnapshot(False)
    except OSError as error:
        raise BackupError(f"cannot inspect target {target.name}: {error}") from error
    if not stat.S_ISREG(path_metadata.st_mode):
        raise BackupError(f"target {target.name} is not a regular file")

    descriptor = _open_readonly_nofollow(target, "target")
    try:
        opened_metadata = os.fstat(descriptor)
        if (
            opened_metadata.st_dev != path_metadata.st_dev
            or opened_metadata.st_ino != path_metadata.st_ino
            or not stat.S_ISREG(opened_metadata.st_mode)
        ):
            raise BackupError(f"target {target.name} changed while being inspected")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        final_metadata = os.fstat(descriptor)
        if (
            final_metadata.st_dev != opened_metadata.st_dev
            or final_metadata.st_ino != opened_metadata.st_ino
            or final_metadata.st_size != opened_metadata.st_size
            or final_metadata.st_mtime_ns != opened_metadata.st_mtime_ns
            or final_metadata.st_ctime_ns != opened_metadata.st_ctime_ns
        ):
            raise BackupError(f"target {target.name} changed while being read")
        return _TargetSnapshot(
            True,
            final_metadata.st_dev,
            final_metadata.st_ino,
            digest.digest(),
        )
    except OSError as error:
        raise BackupError(f"cannot read target {target.name}: {error}") from error
    finally:
        os.close(descriptor)


def _fresh_private_output(target: Path) -> tuple[Path, Path]:
    try:
        private_dir = Path(
            tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent)
        )
    except OSError as error:
        raise BackupError(f"cannot create private export directory: {error}") from error

    try:
        descriptor, name = tempfile.mkstemp(
            prefix="export-", suffix=".vil", dir=private_dir
        )
        try:
            os.close(descriptor)
        except OSError as error:
            raise BackupError(f"cannot close export placeholder: {error}") from error
        temporary = Path(name)
        try:
            temporary.unlink()
        except OSError as error:
            raise BackupError(f"cannot remove export placeholder: {error}") from error
        return private_dir, temporary
    except BaseException as error:
        _cleanup_private_dir(private_dir, error)
        raise


def _open_export(path: Path) -> int:
    descriptor = _open_readonly_nofollow(path, "Vitaly export")
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise BackupError("Vitaly export is not a regular file")
        if metadata.st_size == 0:
            raise BackupError("Vitaly export is empty")
        if metadata.st_nlink != 1:
            raise BackupError("Vitaly export must have exactly one link")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_readonly_nofollow(path: Path, context: str) -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        raise BackupError(f"{context} requires O_NOFOLLOW support")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        return os.open(path, flags)
    except OSError as error:
        raise BackupError(f"cannot safely open {context}: {error}") from error


def _require_same_export_inode(path: Path, descriptor: int) -> None:
    try:
        opened = os.fstat(descriptor)
        current = path.lstat()
    except OSError as error:
        raise BackupError(f"cannot recheck Vitaly export: {error}") from error
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(current.st_mode)
        or opened.st_dev != current.st_dev
        or opened.st_ino != current.st_ino
        or opened.st_nlink != 1
        or current.st_nlink != 1
    ):
        raise BackupError("Vitaly export path changed after validation")


def _replace_from_private_dir(
    repo: Path,
    private_dir: Path,
    temporary_name: str,
    target_name: str,
) -> None:
    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    try:
        source_dir_fd = os.open(private_dir, directory_flags)
        try:
            destination_dir_fd = os.open(repo, directory_flags)
            try:
                os.replace(
                    temporary_name,
                    target_name,
                    src_dir_fd=source_dir_fd,
                    dst_dir_fd=destination_dir_fd,
                )
            finally:
                os.close(destination_dir_fd)
        finally:
            os.close(source_dir_fd)
    except OSError as error:
        raise BackupError(f"cannot atomically replace {target_name}: {error}") from error


def _validate_save_result(
    result: CommandResult, temporary: Path, selected_device: DeviceRecord
) -> None:
    _require_success("Vitaly export", result)
    diagnostics = "\n".join((result.stdout, result.stderr))
    if (
        _ERROR_LINE.search(diagnostics)
        or any(line.strip() == _NO_MATCHING_DEVICES for line in diagnostics.splitlines())
        or _FAILURE_LINE.search(diagnostics)
    ):
        raise BackupError("Vitaly reported an export error")
    success_line = f"Configuration saved to file {temporary}"
    lines = result.stdout.splitlines()
    success_indices = [
        index for index, line in enumerate(lines) if line == success_line
    ]
    if len(success_indices) != 1:
        raise BackupError("Vitaly must report exactly one export success line")

    success_index = success_indices[0]
    device_lines = lines[:success_index]
    while device_lines and not device_lines[-1].strip():
        device_lines.pop()
    try:
        saved_devices = parse_devices("\n".join(device_lines))
    except ValueError as error:
        raise BackupError(f"invalid save-time device record: {error}") from error
    if len(saved_devices) != 1:
        raise BackupError("Vitaly must report exactly one save-time device")
    if saved_devices[0] != selected_device:
        raise BackupError("Vitaly save-time device changed after discovery")
    if any(line.strip() for line in lines[success_index + 1 :]):
        raise BackupError("Vitaly reported unexpected output after saving")


def _require_success(context: str, result: CommandResult) -> None:
    if result.returncode != 0 or result.stderr:
        raise BackupError(_command_failure(context, result))


def _cleanup_private_dir(
    private_dir: Path, primary_failure: BaseException | None
) -> None:
    try:
        shutil.rmtree(private_dir)
    except FileNotFoundError:
        return
    except OSError as cleanup_error:
        if primary_failure is not None:
            primary_failure.add_note(
                f"also failed to remove private export directory: {cleanup_error}"
            )
            return
        raise BackupError(
            f"failed to remove private export directory: {cleanup_error}"
        ) from cleanup_error


def _command_failure(context: str, result: CommandResult) -> str:
    diagnostic = result.stderr.strip() or result.stdout.strip()
    if diagnostic:
        return f"{context}: {diagnostic}"
    return f"{context}: exit status {result.returncode}"
