from __future__ import annotations

from pathlib import Path
import unittest

from keyball_config.devices import load_registry, parse_devices, select_device


FIXTURES = Path(__file__).parent / "fixtures" / "devices"


class DeviceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.models = load_registry(Path("config/models.json"))

    def test_registry_contains_relative_geometry_for_each_supported_model(self) -> None:
        self.assertEqual(set(self.models), {"keyball39", "keyball44"})
        for model in self.models.values():
            self.assertFalse(Path(model.geometry_path).is_absolute())
            self.assertNotIn("/nix/store/", model.geometry_path)

    def test_zero_records_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "no compatible devices"):
            select_device(parse_devices(""), self.models)

    def test_observed_keyball44_is_selected(self) -> None:
        records = parse_devices((FIXTURES / "trackball-44-v3.txt").read_text())

        device, model = select_device(records, self.models)

        self.assertEqual(device.product_id, 16718)
        self.assertEqual(device.vendor_id, 16717)
        self.assertEqual(device.release, 1)
        self.assertEqual(device.serial, "vial:f64c2b3c")
        self.assertEqual(device.path, "/dev/hidraw3")
        self.assertEqual(model.slug, "keyball44")

    def test_vitaly_record_separator_is_accepted(self) -> None:
        transcript = (FIXTURES / "trackball-44-v3.txt").read_text() + "\n"

        records = parse_devices(transcript)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].product_name, "trackball 44 V3")

    def test_vitaly_separators_between_records_are_accepted(self) -> None:
        transcript = (FIXTURES / "multiple.txt").read_text()
        transcript = transcript.replace("\nProduct name:", "\n\nProduct name:") + "\n"

        self.assertEqual(len(parse_devices(transcript)), 2)

    def test_blank_line_inside_record_fails_closed(self) -> None:
        transcript = (FIXTURES / "trackball-44-v3.txt").read_text()
        transcript = transcript.replace(
            "\nManufacturer name:", "\n\nManufacturer name:"
        )

        with self.assertRaisesRegex(ValueError, "complete three-line"):
            parse_devices(transcript)

    def test_repeated_record_separator_fails_closed(self) -> None:
        transcript = (FIXTURES / "trackball-44-v3.txt").read_text() + "\n\n"

        with self.assertRaisesRegex(ValueError, "complete three-line"):
            parse_devices(transcript)

    def test_case_insensitive_keyball39_is_selected(self) -> None:
        records = parse_devices((FIXTURES / "keyball-39.txt").read_text())

        _, model = select_device(records, self.models)

        self.assertEqual(model.slug, "keyball39")

    def test_unsupported_name_fails_closed(self) -> None:
        records = parse_devices((FIXTURES / "unsupported.txt").read_text())

        with self.assertRaisesRegex(ValueError, "unsupported product name"):
            select_device(records, self.models)

    def test_ambiguous_name_fails_closed(self) -> None:
        records = parse_devices((FIXTURES / "ambiguous.txt").read_text())

        with self.assertRaisesRegex(ValueError, "ambiguous product name"):
            select_device(records, self.models)

    def test_malformed_record_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "complete three-line"):
            parse_devices((FIXTURES / "malformed.txt").read_text())

    def test_multiple_records_fail_closed(self) -> None:
        records = parse_devices((FIXTURES / "multiple.txt").read_text())

        with self.assertRaisesRegex(ValueError, "exactly one compatible device"):
            select_device(records, self.models)

    def test_product_id_collision_fails_closed(self) -> None:
        records = parse_devices((FIXTURES / "selector-collision.txt").read_text())

        with self.assertRaisesRegex(ValueError, "selector collision.*16718"):
            select_device(records, self.models)


if __name__ == "__main__":
    unittest.main()
