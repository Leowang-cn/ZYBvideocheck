import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from server.app import create_app
from server.config import ServerSettings


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temporary_directory.name) / "server.sqlite"
        app = create_app(ServerSettings(f"sqlite:///{database_path}", "test-token"))
        self.client = TestClient(app)
        self.video_id = "a" * 64
        self.payload = {
            "videos": [
                {
                    "video_id": self.video_id,
                    "level_1": "W33",
                    "level_2": "小学数学",
                    "batch": "2026-08-17",
                    "created_date": "2026-08-17",
                    "file_name": "=测试视频.mp4",
                    "file_size": 123456,
                    "duration": 8.5,
                    "width": 1920,
                    "height": 1080,
                    "video_url": "https://example.test/video.mp4",
                    "snapshots": [
                        {
                            "sequence": 1,
                            "second": 3,
                            "url": "https://example.test/snapshot-1.jpg",
                        }
                    ],
                }
            ]
        }

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def import_video(self):
        return self.client.post(
            "/api/videos/import",
            json=self.payload,
            headers={"Authorization": "Bearer test-token"},
        )

    def test_health_page_and_import_authentication(self) -> None:
        self.assertEqual(self.client.get("/api/health").json(), {"status": "ok"})
        self.assertIn("视频走查", self.client.get("/").text)
        self.assertEqual(self.client.post("/api/videos/import", json=self.payload).status_code, 401)

    def test_import_is_idempotent_and_list_is_filterable(self) -> None:
        self.assertEqual(self.import_video().json()["created"], 1)
        duplicate = self.import_video().json()
        self.assertEqual(duplicate["created"], 0)
        self.assertEqual(duplicate["existing"], 1)

        result = self.client.get(
            "/api/videos", params={"level_1": "W33", "keyword": "测试"}
        ).json()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["review"]["version"], 0)
        self.assertEqual(
            self.client.get("/api/videos", params={"level_1": "其他"}).json()["total"],
            0,
        )

    def test_review_uses_optimistic_version_and_csv_is_safe(self) -> None:
        self.import_video()
        response = self.client.patch(
            f"/api/videos/{self.video_id}/review",
            json={
                "original_type": "旧片新剪",
                "rating": "合格",
                "review_note": "+备注",
                "supplement": "已确认",
                "reviewer": "测试员",
                "version": 0,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["version"], 1)
        self.assertEqual(response.json()["original_type"], "旧片新剪")
        conflict = self.client.patch(
            f"/api/videos/{self.video_id}/review",
            json={"rating": "优秀", "version": 0},
        )
        self.assertEqual(conflict.status_code, 409)

        response = self.client.patch(
            f"/api/videos/{self.video_id}/review",
            json={
                "original_type": "屏幕原片",
                "rating": "无需审核",
                "review_note": "+备注",
                "supplement": "已确认",
                "reviewer": "测试员",
                "version": 1,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["original_type"], "屏幕原片")
        self.assertEqual(
            self.client.get("/api/videos", params={"rating": "无需审核"}).json()["total"],
            1,
        )

        filtered = self.client.get("/api/videos", params={"rating": "无需审核"}).json()
        self.assertEqual(filtered["total"], 1)
        csv_text = self.client.get("/api/videos/export.csv").text
        self.assertIn("'=测试视频.mp4", csv_text)
        self.assertIn("'+备注", csv_text)
        self.assertIn("屏幕原片", csv_text)
        self.assertIn("https://example.test/snapshot-1.jpg", csv_text)

    def test_statistics_summarizes_review_progress_and_issues(self) -> None:
        self.import_video()
        second_video = dict(self.payload["videos"][0])
        second_video["video_id"] = "b" * 64
        second_video["file_name"] = "第二条视频.mp4"
        self.client.post(
            "/api/videos/import",
            json={"videos": [second_video]},
            headers={"Authorization": "Bearer test-token"},
        )
        self.client.patch(
            f"/api/videos/{self.video_id}/review",
            json={
                "original_type": "人像原片",
                "rating": "不合格",
                "review_note": "人像偏黄；人像模糊",
                "version": 0,
            },
        )

        self.assertIn("统计分析", self.client.get("/statistics").text)
        result = self.client.get("/api/statistics/overview").json()
        self.assertEqual(result["summary"]["total"], 2)
        self.assertEqual(result["summary"]["reviewed"], 1)
        self.assertEqual(result["summary"]["unreviewed"], 1)
        self.assertEqual(result["summary"]["completion_rate"], 50.0)
        self.assertEqual(result["batches"][0]["failed"], 1)
        ratings = {item["name"]: item["count"] for item in result["ratings"]}
        issues = {item["name"]: item["count"] for item in result["issues"]}
        self.assertEqual(ratings["不合格"], 1)
        self.assertEqual(ratings["未评级"], 1)
        self.assertEqual(issues["人像偏黄"], 1)
        self.assertEqual(issues["人像模糊"], 1)


if __name__ == "__main__":
    unittest.main()