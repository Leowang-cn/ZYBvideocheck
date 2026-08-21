from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from video_review.config import Settings
from video_review.cos_storage import CosUploader
from video_review.pipeline import run


def main() -> int:
    parser = argparse.ArgumentParser(description="批量截取视频画面、上传 COS 并生成走查 HTML")
    parser.add_argument(
        "--batch",
        default=date.today().isoformat(),
        help="写入 HTML 的批次名称，默认使用当天日期",
    )
    args = parser.parse_args()
    root_dir = Path(__file__).resolve().parent.parent
    load_dotenv(root_dir / ".env")

    try:
        settings = Settings.from_env(root_dir)
        settings.input_dir.mkdir(parents=True, exist_ok=True)
        uploader = CosUploader(settings)
        report_path, errors = run(settings, uploader, args.batch)
    except Exception as error:
        print(f"运行失败：{error}", file=sys.stderr)
        return 1

    for error in errors:
        print(f"处理失败：{error}", file=sys.stderr)
    if report_path:
        print(f"处理完成：{report_path}")
    elif errors:
        print("没有成功生成新的 HTML。", file=sys.stderr)
    else:
        print("没有发现需要处理的新视频。")
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
