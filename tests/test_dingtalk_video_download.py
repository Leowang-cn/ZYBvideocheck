import tempfile
import unittest
from pathlib import Path

from video_review.dingtalk_video_download import (
    SheetAttachment,
    _available_path,
    _open_history,
    _record_download,
    _recorded_file,
)


class DingTalkVideoDownloadTests(unittest.TestCase):
    def attachment(self, *, attachment_id: str = "file-1", size: int = 5) -> SheetAttachment:
        return SheetAttachment(
            attachment_id=attachment_id,
            name="lesson.mp4",
            size=size,
            mime="video/mp4",
            row=6,
            column=5,
            download_url="https://download.test/lesson.mp4",
        )

    def test_recorded_complete_file_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            (output / "lesson.mp4").write_bytes(b"video")
            connection = _open_history(output)
            attachment = self.attachment()
            _record_download(connection, "doc", attachment, "lesson.mp4")

            self.assertEqual(
                _recorded_file(connection, output, attachment), output / "lesson.mp4"
            )
            connection.close()

    def test_missing_or_incomplete_recorded_file_is_not_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            connection = _open_history(output)
            attachment = self.attachment()
            _record_download(connection, "doc", attachment, "lesson.mp4")
            (output / "lesson.mp4").write_bytes(b"bad")

            self.assertIsNone(_recorded_file(connection, output, attachment))
            connection.close()

    def test_name_collision_does_not_overwrite_different_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            (output / "lesson.mp4").write_bytes(b"old")

            path = _available_path(output, "lesson.mp4")

            self.assertEqual(path.name, "lesson (2).mp4")

    def test_unrecorded_matching_file_is_not_assumed_to_be_same_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            (output / "lesson.mp4").write_bytes(b"video")

            path = _available_path(output, "lesson.mp4")

            self.assertEqual(path.name, "lesson (2).mp4")


if __name__ == "__main__":
    unittest.main()
