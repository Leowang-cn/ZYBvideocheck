import subprocess
import tempfile
import unittest
from pathlib import Path

from video_review.media import create_proxy_video, create_snapshot, probe_video, snapshot_seconds


class SnapshotSecondsTests(unittest.TestCase):
    def test_six_second_video_has_two_snapshots(self) -> None:
        self.assertEqual(snapshot_seconds(6.0), (3.0, 3.0))

    def test_long_video_adds_middle_snapshot(self) -> None:
        self.assertEqual(snapshot_seconds(10.0), (3.0, 5.0, 7.0))

    def test_short_video_stays_within_duration(self) -> None:
        self.assertEqual(snapshot_seconds(2.0), (2.0, 0.0))

    def test_snapshot_preserves_4k_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            video_path = root / "4k.mp4"
            snapshot_path = root / "snapshot.jpg"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=3840x2160:d=0.1",
                    "-frames:v",
                    "1",
                    "-c:v",
                    "libx264",
                    str(video_path),
                ],
                check=True,
                capture_output=True,
            )

            create_snapshot(video_path, snapshot_path, 0.0)

            snapshot_info = probe_video(snapshot_path)
            self.assertEqual((snapshot_info.width, snapshot_info.height), (3840, 2160))

    def test_proxy_limits_4k_video_to_1080p(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            video_path = root / "4k.mp4"
            proxy_path = root / "proxy.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=3840x2160:d=0.1",
                    "-frames:v",
                    "1",
                    "-c:v",
                    "libx264",
                    str(video_path),
                ],
                check=True,
                capture_output=True,
            )

            create_proxy_video(video_path, proxy_path)

            proxy_info = probe_video(proxy_path)
            self.assertEqual((proxy_info.width, proxy_info.height), (1920, 1080))


if __name__ == "__main__":
    unittest.main()