from __future__ import annotations

import hashlib
from html import escape
import io
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from typing import Mapping, Sequence
import xml.etree.ElementTree as ET

from keyball_config.devices import ModelConfig
from keyball_config.keymap import RenderError, RenderTools, render_present


class SiteError(RuntimeError):
    """A complete, safe static site could not be produced or validated."""


class SiteCleanupWarning(UserWarning):
    """Compatibility category that cleanup reporting must never emit."""


_SLUG = re.compile(r"[a-z0-9][a-z0-9_-]*")
_EXTERNAL_REFERENCE = re.compile(r"(?i)(?:https?|file|ftp):|(?<!:)//")
_ABSOLUTE_PATH = re.compile(
    r"(?:^|[\s\"'=(:])(?:/[A-Za-z0-9_.-]+(?:/|\b)|[A-Za-z]:[\\/])"
)
_CSS_URL = re.compile(r"(?i)url\(\s*(['\"]?)(?P<target>.*?)\1\s*\)")
_CSS_IMPORT = re.compile(r"(?i)@import\b")
_TSPAN_STYLE = re.compile(r"font-size: (?:[1-9]|[1-9][0-9]|100)%")
_LAYER_FRAGMENT = re.compile(r"#L[0-9]+")
_SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"
_SVG_VOCABULARY = {
    "svg": {"class", "height", "viewBox", "width"},
    "style": set(),
    "g": {"class", "transform"},
    "a": {"href"},
    "path": {"class", "d"},
    "rect": {"class", "height", "rx", "ry", "width", "x", "y"},
    "text": {"class", "id", "x", "y"},
    "tspan": {"dy", "style", "x"},
}
# SHA-256 of the style text emitted for both pinned model fixtures by
# keymap-drawer 0.23.0.
_SVG_STYLE_SHA256 = "6f11938aa03d808d44c27e8519f60ab252a4f3e13ed4b630c6a29fd20a2b1062"
_SITE_CSS = """:root { color-scheme: light dark; font-family: system-ui, sans-serif; }
body { max-width: 96rem; margin: auto; padding: 1rem; }
.selector { display: flex; flex-wrap: wrap; gap: 1rem; }
section { margin-block: 2rem; }
img { display: block; width: 100%; height: auto; }
a { color: inherit; }
.legend { max-width: 60rem; }"""
_KEYMAP_LEGEND = """<aside class="legend" aria-label="Key legend">
<strong>Legend:</strong> Center = tap; bottom = hold; <code>2×</code> = double tap;
<code>T+H</code> = tap-hold. <code>L</code>/<code>R</code> preserve modifier side.
<code>M</code> in the top-right marks a macro; <code>…</code> means its text was
shortened to six characters.
Mouse arrows show movement and Mouse numbers show buttons. Named Keyball actions
control trackball or saved configuration behavior; a raw keycode means no
authoritative friendly name is available.
</aside>"""


def build_site(
    repo: Path,
    output: Path,
    models: Mapping[str, ModelConfig],
    tools: RenderTools,
    runner,
) -> tuple[Path, ...]:
    try:
        _require_safe_output(repo, output)
        present = tuple(
            model
            for slug, model in sorted(models.items())
            if (repo / model.backup_filename).is_file()
        )
        if not present:
            raise SiteError("no supported backups are present")
        _require_replaceable_output(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f".{output.name}-site-", dir=output.parent
        ) as directory:
            staging = Path(directory)
            render_present(repo, staging, models, tools, runner)
            (staging / "index.html").write_text(
                _site_html(present), encoding="utf-8"
            )
            expected = tuple(model.slug for model in present)
            validate_site(staging, expected)
            _replace_directory(staging, output)
    except SiteError:
        raise
    except (OSError, ValueError, RenderError) as error:
        raise SiteError(str(error)) from error

    return tuple(
        output / name
        for name in ("index.html", *(f"{model.slug}.svg" for model in present))
    )


def validate_site(path: Path, expected_models: Sequence[str]) -> None:
    expected = tuple(expected_models)
    if not expected:
        raise SiteError("expected_models must contain at least one model")
    if len(expected) > 2:
        raise SiteError("site supports one or two expected models")
    if len(set(expected)) != len(expected) or any(
        _SLUG.fullmatch(slug) is None for slug in expected
    ):
        raise SiteError("expected_models contains an invalid or duplicate model slug")
    expected = tuple(sorted(expected))
    expected_names = {"index.html", *(f"{slug}.svg" for slug in expected)}

    try:
        root = path.lstat()
    except OSError as error:
        raise SiteError(f"site directory is missing: {path}") from error
    if stat.S_ISLNK(root.st_mode):
        raise SiteError("site directory must not be a symbolic link")
    if not stat.S_ISDIR(root.st_mode):
        raise SiteError("site path must be a directory")

    entries: dict[str, os.DirEntry[str]] = {}
    try:
        with os.scandir(path) as iterator:
            for entry in iterator:
                entries[entry.name] = entry
    except OSError as error:
        raise SiteError(f"cannot inspect site directory: {error}") from error

    for name, entry in entries.items():
        info = entry.stat(follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode):
            raise SiteError(f"site contains a symbolic link: {name}")
        if stat.S_ISDIR(info.st_mode):
            raise SiteError(f"site contains a nested directory: {name}")
        if not stat.S_ISREG(info.st_mode):
            raise SiteError(f"site contains a non-regular file: {name}")
        if info.st_nlink != 1:
            raise SiteError(f"site contains a hard link: {name}")

    actual_names = set(entries)
    missing = sorted(expected_names - actual_names)
    if missing:
        raise SiteError("site is missing required files: " + ", ".join(missing))
    unexpected = sorted(actual_names - expected_names)
    if unexpected:
        raise SiteError("site contains unexpected files: " + ", ".join(unexpected))

    for slug in expected:
        svg = path / f"{slug}.svg"
        try:
            svg_text = svg.read_text(encoding="utf-8")
            if "<?" in svg_text:
                raise SiteError(f"invalid SVG for {slug}: processing instructions are forbidden")
            if "<!DOCTYPE" in svg_text.upper():
                raise SiteError(f"invalid SVG for {slug}: document types are forbidden")
            namespaces = {
                declaration
                for _, declaration in ET.iterparse(
                    io.StringIO(svg_text), events=("start-ns",)
                )
            }
            if ("", _SVG_NAMESPACE) not in namespaces or not namespaces.issubset(
                {("", _SVG_NAMESPACE), ("xlink", _XLINK_NAMESPACE)}
            ):
                raise SiteError(f"invalid SVG for {slug}: unexpected namespace declaration")
            parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
            root_element = ET.fromstring(svg_text, parser=parser)
        except (OSError, UnicodeError, ET.ParseError) as error:
            raise SiteError(f"invalid SVG for {slug}: {error}") from error
        if root_element.tag.rsplit("}", 1)[-1] != "svg":
            raise SiteError(f"invalid SVG for {slug}: root element is not svg")
        id_counts: dict[str, int] = {}
        layer_targets: list[str] = []
        for element in root_element.iter():
            local_tag = _require_svg_name(element.tag, kind="element")
            allowed_attributes = _SVG_VOCABULARY.get(local_tag)
            if allowed_attributes is None:
                raise SiteError(f"site SVG contains an element outside the pinned vocabulary: {local_tag}")
            for attribute, value in element.attrib.items():
                local_attribute = _require_svg_name(attribute, kind="attribute")
                if local_attribute not in allowed_attributes:
                    raise SiteError(
                        "site SVG contains an attribute outside the pinned vocabulary: "
                        f"{local_tag}.{local_attribute}"
                    )
                if (
                    local_tag == "tspan"
                    and local_attribute == "style"
                    and _TSPAN_STYLE.fullmatch(value) is None
                ):
                    raise SiteError("site SVG tspan style is outside the pinned vocabulary")
                _require_safe_content(value)
                if local_attribute == "id":
                    id_counts[value] = id_counts.get(value, 0) + 1
            if local_tag == "a" and (
                set(element.attrib) != {"href"}
                or _LAYER_FRAGMENT.fullmatch(element.attrib["href"]) is None
            ):
                raise SiteError("site SVG link is not a pinned layer fragment")
            if local_tag == "a":
                layer_targets.append(element.attrib["href"][1:])
            if local_tag == "style" and hashlib.sha256(
                (element.text or "").encode("utf-8")
            ).hexdigest() != _SVG_STYLE_SHA256:
                raise SiteError("site SVG style is outside the pinned vocabulary")
            _require_safe_content(element.text or "")
            _require_safe_content(element.tail or "")
        if any(id_counts.get(target, 0) != 1 for target in layer_targets):
            raise SiteError(
                "site SVG link target must identify exactly one local element"
            )

    try:
        html = (path / "index.html").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise SiteError(f"invalid index.html: {error}") from error
    entries = tuple((slug, _label_for_slug(slug)) for slug in expected)
    if html != _site_html_entries(entries):
        raise SiteError("index.html does not exactly match the authored site document")


def _site_html(models: Sequence[ModelConfig]) -> str:
    return _site_html_entries(
        tuple((model.slug, model.page_label) for model in models)
    )


def _site_html_entries(entries: Sequence[tuple[str, str]]) -> str:
    selector = ""
    if len(entries) > 1:
        links = "".join(
            f'<a href="#{escape(slug)}">{escape(label)}</a>'
            for slug, label in entries
        )
        selector = f'<nav class="selector" aria-label="Keymap selector">{links}</nav>'
    diagrams = "".join(
        f'''<section id="{escape(slug)}">
<h2>{escape(label)}</h2>
<img src="{escape(slug)}.svg" alt="{escape(label)} keymap">
<p><a href="{escape(slug)}.svg">Open SVG</a> · <a href="{escape(slug)}.svg" download>Download SVG</a></p>
{_KEYMAP_LEGEND}
</section>'''
        for slug, label in entries
    )
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Keyball keymaps</title>
<style>
{_SITE_CSS}
</style>
</head>
<body>
<h1>Keyball keymaps</h1>
{selector}
{diagrams}
</body>
</html>
'''


def _label_for_slug(slug: str) -> str:
    match = re.fullmatch(r"keyball(?P<number>[0-9]+)", slug)
    if match is None:
        raise SiteError(f"cannot derive page label for expected model: {slug}")
    return "Keyball" + match["number"]


def _require_safe_content(value: str) -> None:
    if (
        _EXTERNAL_REFERENCE.search(value)
        or _ABSOLUTE_PATH.search(value)
        or _CSS_IMPORT.search(value)
    ):
        raise SiteError("site contains external content or an absolute filesystem path")
    for match in _CSS_URL.finditer(value):
        if not match["target"].strip().startswith("#"):
            raise SiteError("site contains an external or non-fragment CSS URL")


def _require_svg_name(name: object, *, kind: str) -> str:
    if not isinstance(name, str):
        raise SiteError(f"site SVG contains an invalid {kind}")
    if kind == "attribute" and not name.startswith("{"):
        return name
    if not name.startswith("{") or "}" not in name:
        raise SiteError(f"site SVG contains an unnamespaced {kind}")
    namespace, local_name = name[1:].split("}", 1)
    if kind == "element":
        if namespace != _SVG_NAMESPACE:
            raise SiteError(f"site SVG contains an element in an unexpected namespace: {namespace}")
    elif namespace:
        raise SiteError(f"site SVG contains a namespaced attribute: {local_name}")
    return local_name


def _require_replaceable_output(output: Path) -> None:
    try:
        info = output.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode):
        raise SiteError("site output must not be a symbolic link")
    if not stat.S_ISDIR(info.st_mode):
        raise SiteError("site output must be a directory or absent")


def _require_safe_output(repo: Path, output: Path) -> None:
    try:
        resolved_repo = repo.resolve(strict=True)
        resolved_output = output.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise SiteError(f"cannot resolve repository and site output paths: {error}") from error
    if resolved_repo == resolved_output or resolved_repo.is_relative_to(resolved_output):
        raise SiteError("site output must not contain the repository")


def _replace_directory(staging: Path, output: Path) -> None:
    retired: Path | None = None
    if output.exists():
        retired = Path(
            tempfile.mkdtemp(prefix=f".{output.name}-prior-", dir=output.parent)
        )
        retired.rmdir()
        try:
            os.replace(output, retired)
        except OSError as error:
            raise SiteError(f"cannot retire existing site output: {error}") from error
    try:
        os.replace(staging, output)
    except OSError as error:
        if retired is not None:
            try:
                os.replace(retired, output)
            except OSError as rollback_error:
                raise SiteError(
                    "cannot publish staged site and cannot restore prior output: "
                    f"{error}; rollback failed: {rollback_error}"
                ) from rollback_error
        raise SiteError(f"cannot publish staged site: {error}") from error
    if retired is not None:
        _cleanup_retired(retired)


def _cleanup_retired(retired: Path) -> None:
    last_error: OSError | None = None
    for _ in range(2):
        try:
            shutil.rmtree(retired)
            return
        except OSError as error:
            last_error = error
    _report_cleanup_failure(
        "site publication committed but prior-output cleanup failed; "
        f"retired output remains at {retired}: {last_error}"
    )


def _report_cleanup_failure(message: str) -> None:
    try:
        sys.stderr.write(f"site cleanup warning: {message}\n")
    except Exception:
        pass
