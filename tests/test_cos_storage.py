import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from video_review.config import Settings
from video_review.cos_storage import CosUploader


class CosUploaderTests(unittest.TestCase):
    @patch("qcloud_cos.CosS3Client")
    def test_upload_uses_resumable_multipart_with_md5(self, client_class: Mock) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_path = Path(temporary_directory) / "video.mp4"
            local_path.write_bytes(b"video")
            settings = Settings(
                input_dir=Path(temporary_directory),
                output_dir=Path(temporary_directory),
                data_dir=Path(temporary_directory),
                cos_bucket="bucket-123",
                cos_region="ap-beijing",
                cos_prefix="prefix",
                cos_public_base_url="https://cos.test",
                secret_id="secret-id",
                secret_key="secret-key",
            )

            client_class.return_value.head_object.return_value = {"Content-Length": "5"}
            uploader = CosUploader(settings)
            uploader.upload(local_path, "prefix/video.mp4")

            client_class.return_value.upload_file.assert_called_once_with(
                Bucket="bucket-123",
                Key="prefix/video.mp4",
                LocalFilePath=str(local_path),
                PartSize=8,
                MAXThread=4,
                EnableMD5=True,
                ACL="public-read",
            )
            client_class.return_value.head_object.assert_called_once_with(
                Bucket="bucket-123", Key="prefix/video.mp4"
            )

    @patch("qcloud_cos.CosS3Client")
    def test_upload_rejects_mismatched_cos_object_size(self, client_class: Mock) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            local_path = Path(temporary_directory) / "video.mp4"
            local_path.write_bytes(b"video")
            settings = Settings(
                input_dir=Path(temporary_directory),
                output_dir=Path(temporary_directory),
                data_dir=Path(temporary_directory),
                cos_bucket="bucket-123",
                cos_region="ap-beijing",
                cos_prefix="prefix",
                cos_public_base_url="https://cos.test",
                secret_id="secret-id",
                secret_key="secret-key",
            )
            client_class.return_value.head_object.return_value = {"Content-Length": "4"}

            with self.assertRaisesRegex(RuntimeError, "COS 对象大小不一致"):
                CosUploader(settings).upload(local_path, "prefix/video.mp4")


if __name__ == "__main__":
    unittest.main()