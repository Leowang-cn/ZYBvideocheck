import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from video_review import dingtalk_video_download as downloader

from video_review.dingtalk_video_download import (
    SheetAttachment,
    _available_path,
    _open_history,
    _record_download,
    _recorded_file,
)


class DingTalkVideoDownloadTests(unittest.TestCase):
    def test_browser_script_uses_current_attachment_api(self) -> None:
        script = downloader._browser_script("https://sheet.test", "生产表", "E")
        self.assertIn("fileManager.getDownloadUrl({", script)
        self.assertIn("resourceType", script)
        self.assertIn("typeof factory !== 'function'", script)

    def response(self, content: bytes, *, status: int = 200, content_range: str = ""):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = status
        response.headers = {"Content-Range": content_range}
        response.read.side_effect = io.BytesIO(content).read
        return response

    def test_truncated_response_is_resumed_in_same_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "lesson.mp4"
            responses = [self.response(b"vi"), self.response(b"deo", status=206, content_range="bytes 2-4/5")]
            with patch.object(downloader.urllib.request, "urlopen", side_effect=responses) as request, patch.object(downloader.time, "sleep"), patch("builtins.print"):
                downloader._download(self.attachment(), destination)
            self.assertEqual(destination.read_bytes(), b"video")
            self.assertEqual(request.call_args_list[1].args[0].get_header("Range"), "bytes=2-")
            self.assertFalse(destination.with_suffix(".mp4.part").exists())

    def test_timeout_resumes_existing_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "lesson.mp4"
            first = self.response(b"")
            first.read.side_effect = [b"vi", TimeoutError("timed out")]
            second = self.response(b"deo", status=206, content_range="bytes 2-4/5")
            with patch.object(downloader.urllib.request, "urlopen", side_effect=[first, second]), patch.object(downloader.time, "sleep"), patch("builtins.print"):
                downloader._download(self.attachment(), destination)
            self.assertEqual(destination.read_bytes(), b"video")

    def test_ignored_range_restarts_without_duplicate_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "lesson.mp4"
            destination.with_suffix(".mp4.part").write_bytes(b"vi")
            with patch.object(downloader.urllib.request, "urlopen", return_value=self.response(b"video")), patch("builtins.print"):
                downloader._download(self.attachment(), destination)
            self.assertEqual(destination.read_bytes(), b"video")

    def test_wrong_range_is_rejected_and_retries_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "lesson.mp4"
            partial = destination.with_suffix(".mp4.part")
            partial.write_bytes(b"vi")
            response = self.response(b"video", status=206, content_range="bytes 0-4/5")
            with patch.object(downloader.urllib.request, "urlopen", return_value=response) as request, patch.object(downloader.time, "sleep"), patch("builtins.print"):
                with self.assertRaisesRegex(RuntimeError, "12"):
                    downloader._download(self.attachment(), destination)
            self.assertEqual(request.call_count, 12)
            self.assertEqual(partial.read_bytes(), b"vi")
            self.assertFalse(destination.exists())

    def test_complete_partial_does_not_download_again(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "lesson.mp4"
            destination.with_suffix(".mp4.part").write_bytes(b"video")
            with patch.object(downloader.urllib.request, "urlopen") as request:
                downloader._download(self.attachment(), destination)
            request.assert_not_called()
            self.assertEqual(destination.read_bytes(), b"video")

    def test_source_failure_does_not_stop_next_source(self) -> None:
        sources = [("https://first.test", "first", "E"), ("https://second.test", "second", "E")]
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch.object(downloader, "load_dotenv"), patch.object(
                downloader, "configured_sources", return_value=sources
            ), patch.object(
                downloader, "extract_attachments",
                side_effect=[RuntimeError("checkpoint unavailable"), ("doc", [])],
            ) as extract, patch.object(
                downloader, "download_all", return_value=(0, 0, [])
            ) as download, patch(
                "sys.argv", ["download", "--output", temporary_directory]
            ), patch("builtins.print"):
                self.assertEqual(downloader.main(), 2)
                self.assertEqual(extract.call_args_list, [call(*source) for source in sources])
                download.assert_called_once_with(
                    Path(temporary_directory).resolve(), "doc", [], dry_run=False
                )

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
