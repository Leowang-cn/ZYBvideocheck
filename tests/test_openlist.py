import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from video_review.config import Settings
from video_review.media import VideoInfo
from video_review.openlist_client import OpenListClient, OpenListFile
from video_review.pipeline import run


class FakeUploader:
    def __init__(self) -> None:
        self.uploads = []

    def upload(self, local_path: Path, object_key: str) -> None:
        self.uploads.append((local_path, object_key))


class OpenListTests(unittest.TestCase):
    def test_client_recursively_lists_videos_and_gets_download_url(self) -> None:
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append((self.path, self.headers.get("Authorization"), payload))
                if self.path == "/api/fs/get":
                    data = {"raw_url": "https://download.test/video.mp4"}
                elif payload["path"] == "/root":
                    data = {"content": [{"name": "folder", "is_dir": True}]}
                else:
                    data = {"content": [{"name": "video.mp4", "is_dir": False, "size": 123, "modified": "now"}]}
                body = json.dumps({"code": 200, "message": "success", "data": data}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = OpenListClient(f"http://127.0.0.1:{server.server_port}", "secret-token")
            files = client.find_videos("/root")
            url = client.download_url(files[0].path)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

        self.assertEqual(files[0].path, "/root/folder/video.mp4")
        self.assertEqual(files[0].size, 123)
        self.assertEqual(files[0].modified, "now")
        self.assertEqual(url, "https://download.test/video.mp4")
        self.assertTrue(all(request[1] == "secret-token" for request in requests))

    @patch("video_review.pipeline.create_snapshot")
    @patch("video_review.pipeline.probe_video")
    @patch("video_review.pipeline.OpenListClient")
    def test_remote_pipeline_links_baidu_page_and_only_uploads_snapshots(
        self, client_class, probe_video, create_snapshot
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            remote_file = OpenListFile("/remote/W34/course/video.mp4", "video.mp4", 123, "now")
            client = client_class.return_value
            client.find_videos.return_value = [remote_file]
            client.download_url.return_value = "https://download.test/video.mp4"
            client.baidu_pan_page_url.return_value = (
                "https://pan.baidu.com/disk/main#/index?category=all&path=%2FW34%2Fcourse"
            )
            probe_video.return_value = VideoInfo(10.0, 3840, 2160, "h264")
            def write_snapshot(source, output, second):
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"jpg")

            create_snapshot.side_effect = write_snapshot
            settings = Settings(
                input_dir=root / "input",
                output_dir=root / "output",
                data_dir=root / "data",
                cos_bucket="bucket",
                cos_region="region",
                cos_prefix="prefix",
                cos_public_base_url="https://cos.test",
                secret_id="",
                secret_key="",
                openlist_url="http://openlist.test",
                openlist_token="token",
                openlist_path="/remote/W34",
                baidu_pan_mount_path="/remote",
            )
            uploader = FakeUploader()

            report_path, errors = run(settings, uploader, "remote")

            self.assertEqual(errors, [])
            self.assertIsNotNone(report_path)
            self.assertEqual(len(uploader.uploads), 3)
            self.assertEqual(probe_video.call_args.args[0], "https://download.test/video.mp4")
            self.assertTrue(all(call.args[0] == "https://download.test/video.mp4" for call in create_snapshot.call_args_list))
            html = report_path.read_text(encoding="utf-8")
            self.assertIn("3840 × 2160", html)
            self.assertIn('<td class="source">W34</td>', html)
            self.assertIn('<td class="source">course</td>', html)
            self.assertIn("https://pan.baidu.com/disk/main#/index?category=all&amp;path=%2FW34%2Fcourse", html)
            self.assertIn("打开原视频", html)

            second_report_path, second_errors = run(settings, uploader, "remote-2")

            self.assertIsNone(second_report_path)
            self.assertEqual(second_errors, [])
            self.assertEqual(len(uploader.uploads), 3)
            self.assertEqual(probe_video.call_count, 1)

    def test_baidu_page_url_removes_openlist_mount_path(self) -> None:
        url = OpenListClient.baidu_pan_page_url(
            "/baidu-test/初化/课程/video.mp4", "/baidu-test"
        )

        self.assertEqual(
            url,
            "https://pan.baidu.com/disk/main#/index?category=all&"
            "path=%2F%E5%88%9D%E5%8C%96%2F%E8%AF%BE%E7%A8%8B",
        )


if __name__ == "__main__":
    unittest.main()