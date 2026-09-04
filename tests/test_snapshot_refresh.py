import unittest

from video_review.snapshot_refresh import _input_transfer


class SnapshotRefreshTests(unittest.TestCase):
    def test_accepts_bt709_limited_video(self) -> None:
        self.assertEqual(
            _input_transfer(
                {
                    "color_range": "tv",
                    "color_space": "bt709",
                    "color_transfer": "bt709",
                    "color_primaries": "bt709",
                }
            ),
            "bt709",
        )

    def test_preserves_srgb_input_transfer(self) -> None:
        self.assertEqual(
            _input_transfer(
                {
                    "color_range": "tv",
                    "color_space": "bt709",
                    "color_transfer": "iec61966-2-1",
                    "color_primaries": "bt709",
                }
            ),
            "srgb",
        )

    def test_untagged_sdr_uses_bt709_fallback(self) -> None:
        self.assertEqual(_input_transfer({}), "bt709")

    def test_rejects_hdr_metadata(self) -> None:
        with self.assertRaises(ValueError):
            _input_transfer(
                {
                    "color_range": "tv",
                    "color_space": "bt2020nc",
                    "color_transfer": "smpte2084",
                    "color_primaries": "bt2020",
                }
            )


if __name__ == "__main__":
    unittest.main()
