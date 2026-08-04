from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Sequence
import unittest
from unittest.mock import patch
import warnings
import xml.etree.ElementTree as ET

from keyball_config.backup import CommandResult
from keyball_config.cli import main
from keyball_config.devices import load_registry
from keyball_config.keymap import RenderTools
from keyball_config.site import (
    SiteCleanupWarning,
    SiteError,
    _KEYMAP_LEGEND,
    _site_html,
    build_site,
    validate_site,
)


FIXTURES = Path(__file__).parent / "fixtures" / "converter"


class FakeRenderRunner:
    def __call__(self, args: Sequence[str], cwd: Path) -> CommandResult:
        command = tuple(str(arg) for arg in args)
        if command[0].endswith("vial-converter"):
            source = Path(command[command.index("--input") + 1])
            output = Path(command[command.index("--output") + 1])
            vil = json.loads(source.read_text())
            lines = ['layout: {"qmk_info_json":"unused"}', "layers:"]
            for layer_index, layer in enumerate(vil["layout"]):
                lines.append(f"  L{layer_index}:")
                for keycode in (key for row in layer for key in row):
                    lines.append("    - " + json.dumps(keycode))
            if len(vil["layout"][0][0]) == 7:
                lines.extend(("combos:", '  - {"k":"Mouse1","l":["L0"],"p":[46,45]}'))
            output.write_text("\n".join(lines) + "\n")
            return CommandResult(0, "converted\n", "")
        if command[0].endswith("keymap"):
            output = Path(command[command.index("-o") + 1])
            output.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"><text>keys</text></svg>\n')
            return CommandResult(0, "", "")
        raise AssertionError(command)


class SiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.models = load_registry(Path("config/models.json"))
        self.tools = RenderTools(
            converter=Path("/tools/vial-converter"),
            keymap=Path("/tools/keymap"),
            geometry_root=FIXTURES,
        )

    def _repo(self, root: Path, *slugs: str) -> Path:
        repo = root / "repo"
        repo.mkdir()
        for slug in slugs:
            (repo / f"{slug}.vil").write_bytes((FIXTURES / f"{slug}.vil").read_bytes())
        return repo

    def test_zero_backups_fails_without_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repo(root)
            output = root / "site"

            with self.assertRaisesRegex(SiteError, "no supported backups"):
                build_site(repo, output, self.models, self.tools, FakeRenderRunner())

            self.assertFalse(output.exists())

    def test_output_cannot_be_repository_or_an_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repo(root, "keyball39")
            sentinel = repo / "sentinel"
            sentinel.write_text("keep")

            for output in (repo, root):
                with self.subTest(output=output):
                    with self.assertRaisesRegex(SiteError, "contain.*repository"):
                        build_site(
                            repo,
                            output,
                            self.models,
                            self.tools,
                            FakeRenderRunner(),
                        )
                    self.assertEqual(sentinel.read_text(), "keep")

    def test_existing_output_symlink_resolves_before_repository_safety_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repo(root, "keyball39")
            alias = root / "repo-alias"
            alias.symlink_to(repo, target_is_directory=True)

            with self.assertRaisesRegex(SiteError, "contain.*repository"):
                build_site(
                    repo, alias, self.models, self.tools, FakeRenderRunner()
                )
            self.assertTrue(alias.is_symlink())
            self.assertTrue((repo / "keyball39.vil").is_file())

    def test_one_profile_has_one_embedded_diagram_and_direct_relative_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repo(root, "keyball44")
            output = root / "site"

            built = build_site(repo, output, self.models, self.tools, FakeRenderRunner())

            self.assertEqual(tuple(path.name for path in built), ("index.html", "keyball44.svg"))
            self.assertEqual(sorted(path.name for path in output.iterdir()), ["index.html", "keyball44.svg"])
            html = (output / "index.html").read_text()
            self.assertIn('src="keyball44.svg"', html)
            self.assertIn('href="keyball44.svg"', html)
            self.assertIn("download", html)
            self.assertNotIn('class="selector"', html)
            self.assertNotIn(str(repo), html)
            validate_site(output, ("keyball44",))

    def test_two_profiles_have_selector_and_both_diagrams(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repo(root, "keyball39", "keyball44")
            output = root / "site"

            build_site(repo, output, self.models, self.tools, FakeRenderRunner())

            html = (output / "index.html").read_text()
            self.assertIn('class="selector"', html)
            for slug in ("keyball39", "keyball44"):
                self.assertIn(f'href="#{slug}"', html)
                self.assertIn(f'src="{slug}.svg"', html)
                self.assertIn(f'href="{slug}.svg"', html)
            validate_site(output, ("keyball39", "keyball44"))

    def test_each_model_has_one_fixed_key_legend_after_its_links(self) -> None:
        one = _site_html((self.models["keyball44"],))
        both = _site_html((self.models["keyball39"], self.models["keyball44"]))

        self.assertEqual(one.count(_KEYMAP_LEGEND), 1)
        self.assertEqual(both.count(_KEYMAP_LEGEND), 2)
        self.assertLess(one.index("Download SVG"), one.index(_KEYMAP_LEGEND))
        for text in (
            "Center = tap",
            "bottom = hold",
            "2×",
            "T+H",
            "Mouse",
            "raw keycode",
        ):
            with self.subTest(text=text):
                self.assertIn(text, _KEYMAP_LEGEND)

    def test_invalid_second_profile_preserves_absent_or_exact_prior_output(self) -> None:
        for with_prior in (False, True):
            with self.subTest(with_prior=with_prior), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                repo = self._repo(root, "keyball39")
                (repo / "keyball44.vil").write_text("not json")
                output = root / "site"
                if with_prior:
                    output.mkdir()
                    (output / "index.html").write_bytes(b"prior\n")
                    (output / "old.svg").write_bytes(b"old\n")
                before = self._tree(output)

                with self.assertRaises(SiteError):
                    build_site(repo, output, self.models, self.tools, FakeRenderRunner())

                self.assertEqual(self._tree(output), before)

    def test_successful_rebuild_removes_stale_prior_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repo(root, "keyball39")
            output = root / "site"
            output.mkdir()
            (output / "stale.svg").write_text("stale")

            build_site(repo, output, self.models, self.tools, FakeRenderRunner())

            self.assertEqual(sorted(path.name for path in output.iterdir()), ["index.html", "keyball39.svg"])

    def test_final_directory_replacement_failure_restores_exact_prior_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repo(root, "keyball39")
            output = root / "site"
            output.mkdir()
            (output / "index.html").write_bytes(b"prior index\n")
            (output / "prior.svg").write_bytes(b"prior svg\n")
            before = self._tree(output)
            real_replace = os.replace
            calls = 0

            def fail_publication(source: Path, target: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected final rename failure")
                real_replace(source, target)

            with patch("keyball_config.site.os.replace", side_effect=fail_publication):
                with self.assertRaisesRegex(SiteError, "injected final rename failure"):
                    build_site(
                        repo, output, self.models, self.tools, FakeRenderRunner()
                    )

            self.assertEqual(self._tree(output), before)
            self.assertEqual(
                list(root.glob(".site-prior-*")),
                [],
                "rollback must not leave a retired prior site behind",
            )

    def test_site_cli_builds_all_present_and_validate_requires_expected_models(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repo(root, "keyball39")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    ("site", "--output", "public"),
                    repo=repo,
                    registry_path=Path("config/models.json"),
                    runner=FakeRenderRunner(),
                    render_tools=self.tools,
                )
                validated = main(
                    ("validate-site", "public"),
                    repo=repo,
                    registry_path=Path("config/models.json"),
                )

            self.assertEqual((result, validated), (0, 0))
            self.assertTrue((repo / "public" / "keyball39.svg").is_file())
            with self.assertRaises(SystemExit):
                main(("site", "--model", "keyball39"), repo=repo)

    def test_cli_rejects_repository_as_relative_site_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self._repo(Path(directory), "keyball39")
            with self.assertRaises(SystemExit):
                main(
                    ("site", "--output", "."),
                    repo=repo,
                    registry_path=Path("config/models.json"),
                    runner=FakeRenderRunner(),
                    render_tools=self.tools,
                )
            self.assertTrue((repo / "keyball39.vil").is_file())

    def test_validate_site_cli_derives_complete_present_model_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repo(root, "keyball39")
            output = root / "site"
            build_site(repo, output, self.models, self.tools, FakeRenderRunner())
            (repo / "keyball44.vil").write_bytes(
                (FIXTURES / "keyball44.vil").read_bytes()
            )

            with self.assertRaises(SystemExit):
                main(
                    ("validate-site", str(output)),
                    repo=repo,
                    registry_path=Path("config/models.json"),
                )

            empty_repo = root / "empty"
            empty_repo.mkdir()
            with self.assertRaises(SystemExit):
                main(
                    ("validate-site", str(output)),
                    repo=empty_repo,
                    registry_path=Path("config/models.json"),
                )

    def test_cleanup_failure_is_post_commit_and_reported_without_false_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repo(root, "keyball39")
            output = root / "site"
            output.mkdir()
            (output / "prior.txt").write_text("prior")

            real_rmtree = shutil.rmtree

            def fail_retired(path: str | os.PathLike[str], *args: object, **kwargs: object) -> None:
                if Path(path).name.startswith(".site-prior-"):
                    raise OSError("injected persistent cleanup failure")
                real_rmtree(path, *args, **kwargs)

            stderr = io.StringIO()
            with patch(
                "keyball_config.site.shutil.rmtree", side_effect=fail_retired
            ), warnings.catch_warnings(), redirect_stderr(stderr):
                warnings.simplefilter("error", SiteCleanupWarning)
                built = build_site(repo, output, self.models, self.tools, FakeRenderRunner())

            self.assertEqual(tuple(path.name for path in built), ("index.html", "keyball39.svg"))
            validate_site(output, ("keyball39",))
            retired = list(root.glob(".site-prior-*"))
            self.assertEqual(len(retired), 1)
            self.assertEqual((retired[0] / "prior.txt").read_text(), "prior")
            self.assertIn(
                "committed but prior-output cleanup failed", stderr.getvalue()
            )

    def test_transient_post_commit_cleanup_failure_is_retried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repo(root, "keyball39")
            output = root / "site"
            output.mkdir()
            (output / "prior.txt").write_text("prior")
            real_rmtree = shutil.rmtree
            retired_attempts = 0

            def fail_once(path: str | os.PathLike[str], *args: object, **kwargs: object) -> None:
                nonlocal retired_attempts
                if Path(path).name.startswith(".site-prior-"):
                    retired_attempts += 1
                    if retired_attempts == 1:
                        raise OSError("injected transient cleanup failure")
                real_rmtree(path, *args, **kwargs)

            with patch(
                "keyball_config.site.shutil.rmtree", side_effect=fail_once
            ), warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter("always")
                build_site(repo, output, self.models, self.tools, FakeRenderRunner())

            validate_site(output, ("keyball39",))
            self.assertEqual(retired_attempts, 2)
            self.assertEqual(list(root.glob(".site-prior-*")), [])
            self.assertEqual(captured, [])

    @staticmethod
    def _tree(path: Path) -> object:
        if not path.exists() and not path.is_symlink():
            return None
        return tuple(
            sorted(
                (entry.relative_to(path).as_posix(), entry.read_bytes())
                for entry in path.rglob("*")
                if entry.is_file()
            )
        )


class SiteValidationTests(unittest.TestCase):
    def _valid_site(self, root: Path) -> Path:
        site = root / "site"
        site.mkdir()
        model = load_registry(Path("config/models.json"))["keyball44"]
        (site / "index.html").write_text(_site_html((model,)))
        (site / "keyball44.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>\n')
        return site

    def test_rejects_missing_and_unexpected_top_level_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = self._valid_site(root)
            (site / "keyball44.svg").unlink()
            with self.assertRaisesRegex(SiteError, "missing"):
                validate_site(site, ("keyball44",))

            (site / "keyball44.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            for name in ("backup.vil", "map.yaml", "map.yml", "extra.txt"):
                with self.subTest(name=name):
                    path = site / name
                    path.write_text("unexpected")
                    with self.assertRaisesRegex(SiteError, "unexpected"):
                        validate_site(site, ("keyball44",))
                    path.unlink()

    def test_rejects_nested_files_symlinks_and_hardlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = self._valid_site(root)
            nested = site / "assets"
            nested.mkdir()
            (nested / "thing.svg").write_text("nested")
            with self.assertRaisesRegex(SiteError, "nested|unexpected"):
                validate_site(site, ("keyball44",))
            (nested / "thing.svg").unlink()
            nested.rmdir()

            link = site / "extra.svg"
            link.symlink_to("keyball44.svg")
            with self.assertRaisesRegex(SiteError, "symbolic link"):
                validate_site(site, ("keyball44",))
            link.unlink()

            hardlink = site / "extra.svg"
            os.link(site / "keyball44.svg", hardlink)
            with self.assertRaisesRegex(SiteError, "hard link"):
                validate_site(site, ("keyball44",))

    def test_rejects_external_absolute_parent_and_unexpected_html_links(self) -> None:
        bad_links = (
            "https://example.com/keyball44.svg",
            "//example.com/keyball44.svg",
            "/keyball44.svg",
            "../keyball44.svg",
            "file:///repo/keyball44.svg",
            "/home/alexander/hacking/keyball44.svg",
            "other.svg",
        )
        for link in bad_links:
            with self.subTest(link=link), tempfile.TemporaryDirectory() as directory:
                site = self._valid_site(Path(directory))
                html = (site / "index.html").read_text()
                (site / "index.html").write_text(
                    html.replace('src="keyball44.svg"', f'src="{link}"')
                )
                with self.assertRaises(SiteError):
                    validate_site(site, ("keyball44",))

    def test_rejects_external_svg_links_as_site_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            site = self._valid_site(Path(directory))
            (site / "keyball44.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg">'
                '<image href="https://example.com/keymap.png"/></svg>'
            )

            with self.assertRaisesRegex(
                SiteError, "external|absolute|vocabulary"
            ):
                validate_site(site, ("keyball44",))

    def test_accepts_pinned_internal_layer_activator_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            site = self._valid_site(Path(directory))
            (site / "keyball44.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg">'
                '<a href="#L3"><text class="key tap layer-activator" '
                'x="0" y="0">L3</text></a>'
                '<text id="L3" x="0" y="28">L3:</text>'
                '<text id="L4" x="0" y="56">L4:</text>'
                '<a href="#L4"><text class="key tap layer-activator" '
                'x="0" y="84">L4</text></a></svg>'
            )

            validate_site(site, ("keyball44",))

    def test_rejects_missing_or_duplicate_svg_anchor_targets(self) -> None:
        documents = (
            '<a href="#L3"><text x="0" y="0">L3</text></a>',
            '<text id="L3" x="0" y="0">L3:</text>'
            '<text id="L3" x="0" y="28">duplicate</text>'
            '<a href="#L3"><text x="0" y="56">L3</text></a>',
        )
        for document in documents:
            with self.subTest(document=document), tempfile.TemporaryDirectory() as directory:
                site = self._valid_site(Path(directory))
                (site / "keyball44.svg").write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg">'
                    + document
                    + "</svg>"
                )

                with self.assertRaisesRegex(SiteError, "exactly one local element"):
                    validate_site(site, ("keyball44",))

    def test_rejects_other_svg_anchor_targets_and_attributes(self) -> None:
        anchors = (
            '<a href="#keyball44"/>',
            '<a href="#L"/>',
            '<a href="#L-1"/>',
            '<a href="#L3/other"/>',
            '<a href="https://example.com/#L3"/>',
            '<a href="file:///tmp/keymap.svg#L3"/>',
            '<a href="../keymap.svg#L3"/>',
            '<a href="keymap.svg#L3"/>',
            '<a href="#L3" target="_blank"/>',
            '<a xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="#L3"/>',
            "<a/>",
        )
        for anchor in anchors:
            with self.subTest(anchor=anchor), tempfile.TemporaryDirectory() as directory:
                site = self._valid_site(Path(directory))
                (site / "keyball44.svg").write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg">'
                    + anchor
                    + "</svg>"
                )

                with self.assertRaises(SiteError):
                    validate_site(site, ("keyball44",))

    def test_rejects_active_content_and_external_css(self) -> None:
        attacks = (
            '<script>alert(1)</script>',
            '<form action="https://example.com/upload"></form>',
            '<style>body{background:url(https://example.com/x)}</style>',
            '<p>/home/alexander/hacking/aleadag/keyball44</p>',
        )
        for attack in attacks:
            with self.subTest(attack=attack), tempfile.TemporaryDirectory() as directory:
                site = self._valid_site(Path(directory))
                html = (site / "index.html").read_text()
                (site / "index.html").write_text(html.replace("</body>", attack + "</body>"))
                with self.assertRaises(SiteError):
                    validate_site(site, ("keyball44",))

    def test_rejects_external_svg_style_content(self) -> None:
        styles = (
            ".key{fill:url(https://example.com/fill.svg)}",
            '@import "relative-theme.css";',
            '.key{fill:image-set("relative.png" 1x)}',
        )
        for style in styles:
            with self.subTest(style=style), tempfile.TemporaryDirectory() as directory:
                site = self._valid_site(Path(directory))
                (site / "keyball44.svg").write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg"><style>'
                    f"{style}</style></svg>"
                )
                with self.assertRaisesRegex(
                    SiteError, "external|absolute|vocabulary"
                ):
                    validate_site(site, ("keyball44",))

    def test_rejects_tspan_styles_outside_pinned_font_size_form(self) -> None:
        styles = (
            r"cursor:\75rl(\68ttps\3a\2f\2f evil.example/x),auto",
            r"cursor:\75rl(\68ttps\3a\2f\2f evil.example/x),auto; font-size: 64%",
            "font-size: 64%;",
            "FONT-SIZE: 64%",
            "font-size:64%",
            "font-size:  64%",
            "font-size: 64 %",
            "font-size: 0%",
            "font-size: 101%",
        )
        for style in styles:
            with self.subTest(style=style), tempfile.TemporaryDirectory() as directory:
                site = self._valid_site(Path(directory))
                (site / "keyball44.svg").write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg"><text>'
                    f'<tspan style="{style}">key</tspan></text></svg>'
                )
                with self.assertRaisesRegex(SiteError, "tspan.*style"):
                    validate_site(site, ("keyball44",))

    def test_accepts_pinned_tspan_font_size_values_and_bounds(self) -> None:
        for percentage in (1, 64, 70, 78, 88, 100):
            with self.subTest(percentage=percentage), tempfile.TemporaryDirectory() as directory:
                site = self._valid_site(Path(directory))
                (site / "keyball44.svg").write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg"><text>'
                    f'<tspan style="font-size: {percentage}%">key</tspan>'
                    "</text></svg>"
                )
                validate_site(site, ("keyball44",))

    def test_rejects_svg_active_and_resource_elements(self) -> None:
        elements = (
            "script",
            "foreignObject",
            "animate",
            "set",
            "image",
            "use",
        )
        for element in elements:
            with self.subTest(element=element), tempfile.TemporaryDirectory() as directory:
                site = self._valid_site(Path(directory))
                (site / "keyball44.svg").write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg">'
                    f'<{element} href="#safe"/></svg>'
                )
                with self.assertRaisesRegex(SiteError, "element|vocabulary"):
                    validate_site(site, ("keyball44",))

    def test_rejects_svg_event_attributes_case_and_namespace_bypasses(self) -> None:
        attributes = (
            'onload="alert(1)"',
            'OnLoAd="alert(1)"',
            'evil:onload="alert(1)" xmlns:evil="urn:evil"',
        )
        for attribute in attributes:
            with self.subTest(attribute=attribute), tempfile.TemporaryDirectory() as directory:
                site = self._valid_site(Path(directory))
                (site / "keyball44.svg").write_text(
                    f'<svg xmlns="http://www.w3.org/2000/svg" {attribute}/>'
                )
                with self.assertRaisesRegex(
                    SiteError, "attribute|vocabulary|namespace"
                ):
                    validate_site(site, ("keyball44",))

        with tempfile.TemporaryDirectory() as directory:
            site = self._valid_site(Path(directory))
            (site / "keyball44.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" xmlns:evil="urn:evil">'
                '<evil:g/></svg>'
            )
            with self.assertRaisesRegex(SiteError, "namespace|element|vocabulary"):
                validate_site(site, ("keyball44",))

    def test_rejects_svg_processing_instructions(self) -> None:
        instructions = (
            '<?xml-stylesheet href="relative.css"?>',
            '<?evil data="value"?>',
        )
        for instruction in instructions:
            with self.subTest(instruction=instruction), tempfile.TemporaryDirectory() as directory:
                site = self._valid_site(Path(directory))
                (site / "keyball44.svg").write_text(
                    instruction + '<svg xmlns="http://www.w3.org/2000/svg"/>'
                )
                with self.assertRaisesRegex(SiteError, "processing instruction"):
                    validate_site(site, ("keyball44",))

    def test_enforces_one_and_two_model_presentation_contract(self) -> None:
        mutations = (
            ('<nav class="selector"><a href="#keyball44">Keyball44</a></nav>', ("keyball44",)),
            ('', ("keyball44",)),
        )
        for inserted, expected in mutations:
            with self.subTest(inserted=inserted), tempfile.TemporaryDirectory() as directory:
                site = self._valid_site(Path(directory))
                html = (site / "index.html").read_text()
                if inserted.startswith("<nav"):
                    html = html.replace("<body>", "<body>" + inserted)
                else:
                    html = html.replace(
                        '<a href="keyball44.svg">Open SVG</a> · ', inserted
                    )
                (site / "index.html").write_text(html)
                with self.assertRaises(SiteError):
                    validate_site(site, expected)

        with tempfile.TemporaryDirectory() as directory:
            site = self._valid_site(Path(directory))
            html = (site / "index.html").read_text()
            (site / "index.html").write_text(html.replace(_KEYMAP_LEGEND, ""))
            with self.assertRaises(SiteError):
                validate_site(site, ("keyball44",))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "site"
            site.mkdir()
            models = load_registry(Path("config/models.json"))
            (site / "keyball39.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            (site / "keyball44.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            (site / "index.html").write_text(
                _site_html((models["keyball39"], models["keyball44"]))
                .replace(
                    '<nav class="selector" aria-label="Keymap selector">'
                    '<a href="#keyball39">Keyball39</a>'
                    '<a href="#keyball44">Keyball44</a></nav>',
                    "",
                )
            )
            with self.assertRaises(SiteError):
                validate_site(site, ("keyball39", "keyball44"))

    def test_rejects_missing_html_references_and_invalid_svg(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = self._valid_site(root)
            html = (site / "index.html").read_text()
            (site / "index.html").write_text(
                html.replace(
                    '<img src="keyball44.svg" alt="Keyball44 keymap">', ""
                )
            )
            with self.assertRaises(SiteError):
                validate_site(site, ("keyball44",))

            (site / "index.html").write_text(html)
            (site / "keyball44.svg").write_text("not svg")
            with self.assertRaisesRegex(SiteError, "SVG"):
                validate_site(site, ("keyball44",))

    def test_rejects_asset_references_without_an_html_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            site = self._valid_site(Path(directory))
            (site / "index.html").write_text(
                '<img src="keyball44.svg"><a href="keyball44.svg">SVG</a>'
            )

            with self.assertRaises(SiteError):
                validate_site(site, ("keyball44",))


class RealSiteIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("vial-converter") and shutil.which("keymap"),
        "pinned render tools are not on PATH",
    )
    def test_pinned_tools_build_and_validate_complete_two_model_site(self) -> None:
        converter = Path(shutil.which("vial-converter") or "")
        geometry_root = converter.resolve().parent.parent / "share" / "keyball-geometry"
        if not geometry_root.is_dir():
            self.skipTest("packaged Keyball geometry is not available")
        from keyball_config.backup import run_command

        models = load_registry(Path("config/models.json"))
        tools = RenderTools(
            converter=converter,
            keymap=Path(shutil.which("keymap") or ""),
            geometry_root=geometry_root,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            for slug in ("keyball39", "keyball44"):
                (repo / f"{slug}.vil").write_bytes(
                    (FIXTURES / f"{slug}.vil").read_bytes()
                )

            built = build_site(repo, root / "site", models, tools, run_command)

            self.assertEqual(
                tuple(path.name for path in built),
                ("index.html", "keyball39.svg", "keyball44.svg"),
            )
            self.assertEqual(
                (root / "site" / "index.html").read_text().count(_KEYMAP_LEGEND),
                2,
            )
            validate_site(root / "site", ("keyball39", "keyball44"))
            vocabulary: dict[str, set[str]] = {}
            tspan_styles: set[str] = set()
            for slug in ("keyball39", "keyball44"):
                for element in ET.parse(root / "site" / f"{slug}.svg").getroot().iter():
                    tag = element.tag.rsplit("}", 1)[-1]
                    vocabulary.setdefault(tag, set()).update(
                        attribute.rsplit("}", 1)[-1]
                        for attribute in element.attrib
                    )
                    if tag == "tspan" and "style" in element.attrib:
                        tspan_styles.add(element.attrib["style"])
            self.assertEqual(
                vocabulary,
                {
                    "svg": {"class", "height", "viewBox", "width"},
                    "style": set(),
                    "g": {"class", "transform"},
                    "a": {"href"},
                    "rect": {"class", "height", "rx", "ry", "width", "x", "y"},
                    "text": {"class", "id", "x", "y"},
                    "tspan": {"dy", "x"},
                },
            )
            self.assertEqual(tspan_styles, set())


if __name__ == "__main__":
    unittest.main()
