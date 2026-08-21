import subprocess
import tempfile
import unittest
from pathlib import Path

from video_review.config import Settings
from video_review.pipeline import run


class FakeUploader:
    def __init__(self) -> None:
        self.uploads: list[tuple[Path, str]] = []

    def upload(self, local_path: Path, object_key: str) -> None:
        self.uploads.append((local_path, object_key))


class PipelineTests(unittest.TestCase):
    def test_generates_fixed_html_and_appends_new_batches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_dir = root / "待处理视频"
            input_dir.mkdir()
            video_path = input_dir / "W33" / "小学数学" / "测试视频.mp4"
            video_path.parent.mkdir(parents=True)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=640x360:d=8",
                    "-c:v",
                    "libx264",
                    str(video_path),
                ],
                check=True,
                capture_output=True,
            )
            settings = Settings(
                input_dir=input_dir,
                output_dir=root / "输出",
                data_dir=root / "数据",
                cos_bucket="bucket-123",
                cos_region="ap-beijing",
                cos_prefix="fixed/folder",
                cos_public_base_url="https://example.test",
                secret_id="",
                secret_key="",
            )
            uploader = FakeUploader()

            report_path, errors = run(settings, uploader, "测试批次")

            self.assertEqual(errors, [])
            self.assertIsNotNone(report_path)
            self.assertEqual(len(uploader.uploads), 4)
            self.assertTrue(uploader.uploads[1][0].is_file())
            html = report_path.read_text(encoding="utf-8")
            self.assertIn("测试视频.mp4", html)
            self.assertIn("一级地址", html)
            self.assertIn("二级地址", html)
            self.assertIn(
                '<td class="source">W33</td>\n  <td class="source">小学数学</td>',
                html,
            )
            self.assertIn("创建时间", html)
            self.assertIn("00:00:08", html)
            self.assertIn("640 × 360", html)
            self.assertIn("00:00:03", html)
            self.assertIn("00:00:04", html)
            self.assertIn("00:00:05", html)
            self.assertIn("https://example.test/fixed/folder/", html)
            self.assertEqual(html.count("data:image/jpeg;base64,"), 3)

            second_video_path = input_dir / "第二条视频.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=green:s=320x240:d=6",
                    "-c:v",
                    "libx264",
                    str(second_video_path),
                ],
                check=True,
                capture_output=True,
            )
            second_report, second_errors = run(settings, uploader, "第二批次")
            self.assertEqual(second_report, report_path)
            self.assertEqual(second_errors, [])
            self.assertEqual(len(uploader.uploads), 7)
            updated_html = second_report.read_text(encoding="utf-8")
            self.assertIn("测试视频.mp4", updated_html)
            self.assertIn("第二条视频.mp4", updated_html)
            self.assertIn(
                '<td class="source"></td>\n  <td class="source"></td>',
                updated_html,
            )
            self.assertIn("测试批次", updated_html)
            self.assertIn("第二批次", updated_html)
            self.assertEqual(updated_html.count("data:image/jpeg;base64,"), 5)
            self.assertIn('id="batch-filter"', updated_html)
            self.assertIn('id="first-level-filter"', updated_html)
            self.assertIn('id="second-level-filter"', updated_html)
            self.assertIn('<option value="__EMPTY__">（空）</option>', updated_html)
            self.assertIn('id="search"', updated_html)
            self.assertIn('id="created-from"', updated_html)
            self.assertIn('id="created-to"', updated_html)
            self.assertIn('id="rating-filter"', updated_html)
            self.assertIn('id="export-csv"', updated_html)
            self.assertNotIn("    }));\n\n    const viewer", updated_html)
            self.assertIn('row.dataset.firstLevel', updated_html)
            self.assertIn('row.dataset.secondLevel', updated_html)
            self.assertIn('firstLevelFilter.value === "__EMPTY__"', updated_html)
            self.assertIn('row => !row.hidden', updated_html)
            self.assertIn('class="video-link"', updated_html)
            self.assertEqual(updated_html.count('class="snapshot-link"'), 5)
            self.assertIn("视频 URL", updated_html)
            self.assertIn("截图 URL", updated_html)
            self.assertIn("<th>补充</th>", updated_html)
            self.assertNotIn("领导补充", updated_html)
            self.assertNotIn("视频唯一 ID", updated_html)
            self.assertNotIn('data-video-id=', updated_html)
            self.assertIn('id="image-viewer"', updated_html)
            self.assertIn('id="viewer-prev"', updated_html)
            self.assertIn('id="viewer-next"', updated_html)
            self.assertEqual(updated_html.count('class="thumbnail"'), 5)
            self.assertNotIn('<a href="https://example.test/fixed/folder/', updated_html.split('<td><div class="snapshots">', 1)[1].split('<figcaption>', 1)[0])
            self.assertIn('data-batch="测试批次"', updated_html)
            self.assertIn('data-batch="第二批次"', updated_html)
            self.assertIn("累计 2 条", updated_html)

            third_report, third_errors = run(settings, uploader, "第二批次")
            self.assertIsNone(third_report)
            self.assertEqual(third_errors, [])
            self.assertEqual(len(uploader.uploads), 7)


if __name__ == "__main__":
    unittest.main()