import os
import unittest
from pathlib import Path
from unittest.mock import patch

from video_review.config import Settings


class SettingsTests(unittest.TestCase):
    def test_requires_cos_prefix(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "COS_PREFIX"):
                Settings.from_env(Path("/tmp/video-review"))

    def test_normalizes_prefix_and_builds_default_url(self) -> None:
        with patch.dict(os.environ, {"COS_PREFIX": "/fixed/folder/"}, clear=True):
            settings = Settings.from_env(Path("/tmp/video-review"))

        object_key = settings.object_key("2026-W34/id/video.mp4")
        self.assertEqual(object_key, "fixed/folder/2026-W34/id/video.mp4")
        self.assertEqual(
            settings.public_url(object_key),
            "https://zyb-cxyj-content1-1253445850.cos.ap-beijing.myqcloud.com/"
            "fixed/folder/2026-W34/id/video.mp4",
        )

    def test_infers_baidu_mount_from_openlist_path(self) -> None:
        with patch.dict(
            os.environ,
            {"COS_PREFIX": "fixed/folder", "OPENLIST_PATH": "/baidu-test/初化"},
            clear=True,
        ):
            settings = Settings.from_env(Path("/tmp/video-review"))

        self.assertEqual(settings.effective_baidu_pan_mount_path(), "/baidu-test")


if __name__ == "__main__":
    unittest.main()