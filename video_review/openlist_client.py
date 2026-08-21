from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from video_review.media import VIDEO_EXTENSIONS


@dataclass(frozen=True)
class OpenListFile:
    path: str
    name: str
    size: int
    modified: str = ""


class OpenListClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def find_videos(self, root_path: str) -> list[OpenListFile]:
        return sorted(self._walk(root_path), key=lambda item: item.path)

    def download_url(self, path: str) -> str:
        data = self._post("/api/fs/get", {"path": path, "password": ""})
        raw_url = str(data.get("raw_url") or "")
        if not raw_url:
            raise RuntimeError(f"OpenList 未返回下载地址：{path}")
        return raw_url

    def page_url(self, path: str) -> str:
        encoded_path = quote(path, safe="/")
        return f"{self.base_url}{encoded_path}"

    @staticmethod
    def baidu_pan_page_url(path: str, mount_path: str) -> str:
        file_path = PurePosixPath(path)
        mount = PurePosixPath(mount_path)
        try:
            baidu_path = file_path.relative_to(mount)
        except ValueError as error:
            raise ValueError(f"文件路径不在百度网盘挂载点下：{path}") from error
        directory = PurePosixPath("/") / baidu_path.parent
        query = urlencode({"path": str(directory)})
        return f"https://pan.baidu.com/disk/main#/index?category=all&{query}"

    def _walk(self, directory: str) -> Iterator[OpenListFile]:
        data = self._post(
            "/api/fs/list",
            {
                "path": directory,
                "password": "",
                "page": 1,
                "per_page": 0,
                "refresh": False,
            },
        )
        for item in data.get("content") or []:
            name = str(item.get("name") or "")
            path = str(PurePosixPath(directory) / name)
            if item.get("is_dir"):
                yield from self._walk(path)
            elif PurePosixPath(name).suffix.lower() in VIDEO_EXTENSIONS:
                yield OpenListFile(
                    path=path,
                    name=name,
                    size=int(item.get("size") or 0),
                    modified=str(item.get("modified") or ""),
                )

    def _post(self, endpoint: str, payload: dict[str, object]) -> dict[str, object]:
        request = Request(
            f"{self.base_url}{endpoint}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": self.token,
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenList 请求失败（HTTP {error.code}）：{detail}") from error
        except URLError as error:
            raise RuntimeError(f"无法连接 OpenList：{error.reason}") from error
        if result.get("code") != 200:
            raise RuntimeError(f"OpenList 请求失败：{result.get('message') or '未知错误'}")
        data = result.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("OpenList 返回了无效数据")
        return data