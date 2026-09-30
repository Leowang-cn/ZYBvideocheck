from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv


DEFAULT_SHEET_URL = (
    "https://alidocs.dingtalk.com/i/nodes/"
    "kDnRL6jAJM3A0k6ycqAAwXAXWyMoPYe1"
)
DEFAULT_SHEET_TITLE = "生产表"
DEFAULT_COLUMN_HEADER = "视频（一稿）"
HISTORY_FILENAME = ".dingtalk-video-downloads.sqlite3"
TASK_SPACE_NAME = "download DingTalk sheet videos"


@dataclass(frozen=True)
class SheetAttachment:
    attachment_id: str
    name: str
    size: int
    mime: str
    row: int
    column: int
    download_url: str


def _browser_script(sheet_url: str, sheet_title: str, column_header: str) -> str:
    return f"""
const task = await useOrCreateTaskSpace({json.dumps(TASK_SPACE_NAME)})
await openOrReuseTab({json.dumps(sheet_url)}, {{ wait: true, timeout: 30 }})

let ready = false
for (let attempt = 0; attempt < 120; attempt++) {{
  ready = await js(String.raw`(() => {{
    const frame = document.querySelector('iframe')
    const page = frame?.contentWindow || window
        const docData = page.rawDataStore?.docData
        return docData?.status === 'resolved' &&
            Boolean(docData.value?.documentContent?.checkpoint)
  }})()`)
  if (ready) break
  await wait(0.5)
}}
if (!ready) throw new Error('等待钉钉表格数据超时，请确认 Ego 浏览器已登录且有表格访问权限')

const result = await js(String.raw`(async () => {{
  const frame = document.querySelector('iframe')
  const page = frame?.contentWindow || window
  const store = page.rawDataStore?.docData?.value
    if (!store?.documentContent?.checkpoint) {{
    throw new Error('未找到钉钉表格的结构化数据')
  }}

    let checkpointContent = store.documentContent.checkpoint.content
    if (!checkpointContent) {{
        if (!page.__videoDownloadWebpackRequire) {{
            page.webpackChunkflex_table_app.push([
                [Math.floor(Math.random() * 1e9)],
                {{}},
                require => {{ page.__videoDownloadWebpackRequire = require }},
            ])
        }}
        const require = page.__videoDownloadWebpackRequire
        const networkModuleId = Object.keys(require.m || {{}}).find(moduleId => {{
            const factory = require.m[moduleId]
            if (typeof factory !== 'function') return false
            const source = Function.prototype.toString.call(factory)
            return source.includes('getOssClient') &&
                source.includes('[NetworkServiceImpl]') &&
                source.includes('getDocConfigRepository')
        }})
        const createNetwork = networkModuleId
            ? require(networkModuleId).i
            : null
        const loadCheckpoint = require(506656)?.U
        if (typeof createNetwork !== 'function' || typeof loadCheckpoint !== 'function') {{
            throw new Error('未找到钉钉外置表格加载接口，可能是页面版本已变更')
        }}
        const network = createNetwork({{accessToken: store.accessToken, appName: 'sheet'}})
        try {{
            const docKey = store.fileMetaInfo.docKey
            checkpointContent = await loadCheckpoint({{
                res: store.documentContent,
                ossClient: network.getOssClient({{docKey, refreshDynamicConfig: false}}),
                category: 'sheet',
                logger: network.getLogger(),
                docKey: {{docKey}},
            }})
        }} finally {{
            network.destroy()
        }}
    }}
    if (!checkpointContent) throw new Error('钉钉表格内容加载失败')
    const root = JSON.parse(checkpointContent)
  const wantedSheetTitle = {json.dumps(sheet_title)}
    const wantedHeader = {json.dumps(column_header)}
    const columnLetters = wantedHeader.match(/^[A-Za-z]+$/)
    const wantedColumn = columnLetters
        ? [...columnLetters[0].toUpperCase()].reduce((value, letter) => value * 26 + letter.charCodeAt(0) - 64, 0) - 1
        : -1
  const sheetMeta = (root.sheetsMeta || []).find(item => item.title === wantedSheetTitle)
  if (!sheetMeta) throw new Error('未找到工作表：' + wantedSheetTitle)
  const sheetId = sheetMeta.id
  const rows = root.content?.[sheetId]?.rows || []
  const cells = new Map()

  const putCheckpointRows = () => {{
    rows.forEach((rowData, rowIndex) => {{
      const rowCells = Array.isArray(rowData) ? rowData[2] : null
      if (!Array.isArray(rowCells)) return
      rowCells.forEach((entry, fallbackColumn) => {{
        if (!entry) return
        const column = Number.isInteger(entry[0]) ? entry[0] : fallbackColumn
        const cell = entry[1] ?? entry
        cells.set(rowIndex + ':' + column, cell)
      }})
    }})
  }}
  putCheckpointRows()

  const setRange = (range, cell) => {{
    if (!Array.isArray(range) || range[0] !== sheetId) return
    const startRow = Number(range[1])
    const startColumn = Number(range[2])
    const rowCount = Math.max(1, Number(range[3]) || 1)
    const columnCount = Math.max(1, Number(range[4]) || 1)
    for (let r = 0; r < rowCount; r++) {{
      for (let c = 0; c < columnCount; c++) {{
        const key = (startRow + r) + ':' + (startColumn + c)
        if (cell == null) cells.delete(key)
        else cells.set(key, cell)
      }}
    }}
  }}

  const deltas = [...(store.documentContent.deltas?.list || [])]
    .sort((a, b) => Number(a.version || 0) - Number(b.version || 0))
  for (const delta of deltas) {{
    let operations = delta.operations
    if (typeof operations === 'string') {{
      try {{ operations = JSON.parse(operations) }} catch {{ operations = [] }}
    }}
    for (const operation of operations || []) {{
      const payload = operation?.payload || {{}}
      if (operation.action === 'fillRange') setRange(payload.range, payload.cell)
      if (operation.action === 'clearRange') setRange(payload.range, null)
    }}
  }}

  const collectText = value => {{
    const parts = []
    const visit = item => {{
      if (typeof item === 'string') parts.push(item)
      else if (Array.isArray(item)) item.forEach(visit)
      else if (item && typeof item === 'object') Object.values(item).forEach(visit)
    }}
    visit(value)
    return parts.join('').trim()
  }}

  let headerRow = -1
    let videoColumn = wantedColumn
    if (videoColumn < 0) {{
        for (const [key, cell] of cells) {{
            if (collectText(cell?.value) !== wantedHeader) continue
            const [row, column] = key.split(':').map(Number)
            headerRow = row
            videoColumn = column
            break
        }}
  }}
    if (videoColumn < 0) throw new Error('未找到列标题或列字母：' + wantedHeader)

  const attachments = []
  const seen = new Set()
  const findAttachments = (item, row, column) => {{
    if (!item) return
    if (Array.isArray(item)) {{
      item.forEach(child => findAttachments(child, row, column))
      return
    }}
    if (typeof item !== 'object') return
    const isAttachment = item['data-type'] === 'attach' || item.type === 'attach'
    const attachmentId = item.srcId || (isAttachment ? item.resourceId : '')
    if (isAttachment && attachmentId && item.name && !seen.has(attachmentId)) {{
      seen.add(attachmentId)
      attachments.push({{
        attachmentId: String(attachmentId),
        name: String(item.name),
        size: Number(item.size || 0),
        mime: String(item.mime || item.contentType || ''),
        row: row + 1,
        column: column + 1,
      }})
    }}
    Object.values(item).forEach(child => findAttachments(child, row, column))
  }}

  for (const [key, cell] of cells) {{
    const [row, column] = key.split(':').map(Number)
    if ((headerRow >= 0 && row <= headerRow) || column !== videoColumn) continue
    findAttachments(cell, row, column)
  }}

  if (!page.__videoDownloadWebpackRequire) {{
    page.webpackChunkflex_table_app.push([
      [Math.floor(Math.random() * 1e9)],
      {{}},
      require => {{ page.__videoDownloadWebpackRequire = require }},
    ])
  }}
  const require = page.__videoDownloadWebpackRequire
  // The attachment adapter is split into a lazy chunk in the current DingTalk
  // sheet application. Loading an already-loaded chunk is a no-op.
  try {{ await require.e(97240) }} catch {{}}
  let getDownloadUrl = null
    try {{
        const fileManager = require(683822)?.b
        const resourceType = require(551443)?.Wz?.EMBED
        if (fileManager && typeof fileManager.getDownloadUrl === 'function' && resourceType) {{
            getDownloadUrl = (resourceId, name) => fileManager.getDownloadUrl({{
                resourceId,
                resourceType,
                name,
            }})
        }}
    }} catch {{}}
    for (const moduleId of Object.keys(require.m || {{}})) {{
        if (getDownloadUrl) break
        const factory = require.m[moduleId]
        if (typeof factory !== 'function') continue
        const source = Function.prototype.toString.call(factory)
    // Only initialize the small file-service adapter. Requiring arbitrary modules
    // while searching can start unrelated UI components with missing context.
    if (
      !source.includes('getDownloadUrl({{resourceId') ||
      !source.includes('copyFilesToAnotherDoc') ||
      !source.includes('getAttachmentUrl')
    ) continue
    let exports
    try {{ exports = require(moduleId) }} catch {{ continue }}
    for (const value of Object.values(exports || {{}})) {{
      if (typeof value !== 'function') continue
      const fnSource = Function.prototype.toString.call(value)
      if (fnSource.includes('.getDownloadUrl') && fnSource.includes('resourceId')) {{
        getDownloadUrl = value
        break
      }}
    }}
    if (getDownloadUrl) break
  }}
  // Stable fallback for the current adapter; the source scan above remains the
  // preferred path so minor export-name changes do not matter.
    if (!getDownloadUrl) {{
    try {{
      const exports = require(641028)
            if (typeof exports?.km === 'function') getDownloadUrl = exports.km
    }} catch {{}}
  }}
  if (!getDownloadUrl) throw new Error('未找到钉钉附件下载接口，可能是页面版本已变更')

  for (const attachment of attachments) {{
    attachment.downloadUrl = await getDownloadUrl(attachment.attachmentId, attachment.name)
  }}
  return {{
    taskId: {{}},
    docKey: store.fileMetaInfo?.docKey || '',
    sheetTitle: wantedSheetTitle,
    columnHeader: wantedHeader,
    attachments,
  }}
}})()`)
result.taskId = task.id
cliLog('DINGTALK_VIDEO_RESULT=' + JSON.stringify(result))
"""


def _cleanup_browser_task() -> None:
    script = f"""
const result = await completeTaskSpace({json.dumps(TASK_SPACE_NAME)}, {{keep:false}})
cliLog(JSON.stringify(result))
"""
    subprocess.run(
        ["ego-browser", "nodejs"],
        input=script,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def extract_attachments(
    sheet_url: str,
    sheet_title: str = DEFAULT_SHEET_TITLE,
    column_header: str = DEFAULT_COLUMN_HEADER,
) -> tuple[str, list[SheetAttachment]]:
    try:
        completed = subprocess.run(
            ["ego-browser", "nodejs"],
            input=_browser_script(sheet_url, sheet_title, column_header),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(detail or "Ego 浏览器读取失败")
        marker = "DINGTALK_VIDEO_RESULT="
        browser_output = "\n".join((completed.stdout, completed.stderr))
        result_line = next(
            (line for line in reversed(browser_output.splitlines()) if line.startswith(marker)),
            "",
        )
        if not result_line:
            raise RuntimeError("Ego 浏览器未返回可解析的附件数据")
        payload = json.loads(result_line[len(marker) :])
        attachments = [
            SheetAttachment(
                attachment_id=item["attachmentId"],
                name=item["name"],
                size=int(item["size"]),
                mime=item.get("mime", ""),
                row=int(item["row"]),
                column=int(item["column"]),
                download_url=item["downloadUrl"],
            )
            for item in payload.get("attachments", [])
        ]
        return payload.get("docKey", ""), attachments
    except FileNotFoundError as error:
        raise RuntimeError("未找到 ego-browser，请确认 Ego 浏览器已安装") from error
    finally:
        _cleanup_browser_task()


def _open_history(output_dir: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(output_dir / HISTORY_FILENAME)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS downloads (
            attachment_id TEXT PRIMARY KEY,
            doc_key TEXT NOT NULL,
            sheet_row INTEGER NOT NULL,
            filename TEXT NOT NULL,
            expected_size INTEGER NOT NULL,
            downloaded_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def _safe_filename(name: str) -> str:
    cleaned = name.replace("/", "／").replace("\0", "").strip()
    return cleaned or "unnamed-video.mp4"


def _available_path(output_dir: Path, filename: str) -> Path:
    candidate = output_dir / _safe_filename(filename)
    if not candidate.exists():
        return candidate

    suffix = candidate.suffix
    stem = candidate.stem
    number = 2
    while True:
        alternate = candidate.with_name(f"{stem} ({number}){suffix}")
        if not alternate.exists():
            return alternate
        number += 1


def _record_download(
    connection: sqlite3.Connection,
    doc_key: str,
    attachment: SheetAttachment,
    filename: str,
) -> None:
    connection.execute(
        """
        INSERT INTO downloads (
            attachment_id, doc_key, sheet_row, filename, expected_size, downloaded_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(attachment_id) DO UPDATE SET
            doc_key=excluded.doc_key,
            sheet_row=excluded.sheet_row,
            filename=excluded.filename,
            expected_size=excluded.expected_size,
            downloaded_at=excluded.downloaded_at
        """,
        (
            attachment.attachment_id,
            doc_key,
            attachment.row,
            filename,
            attachment.size,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    connection.commit()


def _recorded_file(
    connection: sqlite3.Connection,
    output_dir: Path,
    attachment: SheetAttachment,
) -> Path | None:
    row = connection.execute(
        "SELECT filename, expected_size FROM downloads WHERE attachment_id = ?",
        (attachment.attachment_id,),
    ).fetchone()
    if not row:
        return None
    path = output_dir / row[0]
    expected_size = attachment.size or int(row[1])
    if path.is_file() and (not expected_size or path.stat().st_size == expected_size):
        return path
    return None


def _download(attachment: SheetAttachment, destination: Path) -> None:
    for attempt in range(1, 13):
        try:
            _download_attempt(attachment, destination)
            return
        except urllib.error.HTTPError as error:
            if error.code not in (408, 429, 500, 502, 503, 504):
                raise
            failure = error
        except (OSError, urllib.error.URLError, http.client.HTTPException, RuntimeError) as error:
            failure = error
        if attempt == 12:
            raise RuntimeError(f"已尝试 12 次，仍未下载完成：{failure}") from failure
        print(f"    传输未完成：{failure}；即将重试 {attempt}/11（保留已下载部分）", flush=True)
        time.sleep(min(attempt * 2, 10))


def _download_attempt(attachment: SheetAttachment, destination: Path) -> None:
    partial = destination.with_name(destination.name + ".part")
    downloaded = partial.stat().st_size if partial.exists() else 0
    if attachment.size and downloaded == attachment.size:
        os.replace(partial, destination)
        return
    if attachment.size and downloaded > attachment.size:
        partial.unlink()
        downloaded = 0

    headers = {"User-Agent": "Mozilla/5.0 DingTalkVideoDownloader/1.0"}
    if downloaded:
        headers["Range"] = f"bytes={downloaded}-"
    request = urllib.request.Request(attachment.download_url, headers=headers)

    with urllib.request.urlopen(request, timeout=60) as response:
        status = getattr(response, "status", 200)
        if status == 206:
            content_range = re.fullmatch(
                r"bytes (\d+)-(\d+)/(\d+|\*)", response.headers.get("Content-Range", "")
            )
            if (
                not content_range
                or int(content_range[1]) != downloaded
                or int(content_range[2]) < downloaded
                or (attachment.size and content_range[3] != str(attachment.size))
            ):
                raise RuntimeError("服务器返回的续传字节范围不匹配，未写入本次响应")
        elif status != 200:
            raise RuntimeError(f"非预期的下载响应状态：{status}")
        append = downloaded > 0 and status == 206
        if downloaded and not append:
            downloaded = 0
        mode = "ab" if append else "wb"
        last_report = -1
        with partial.open(mode) as target:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                target.write(block)
                downloaded += len(block)
                if attachment.size:
                    percent = min(100, int(downloaded * 100 / attachment.size))
                    if percent >= last_report + 5 or percent == 100:
                        print(f"    {percent:3d}%  {downloaded / 1024 / 1024:.1f} MB", flush=True)
                        last_report = percent

    actual_size = partial.stat().st_size
    if attachment.size and actual_size != attachment.size:
        raise RuntimeError(
            f"文件大小不匹配：期望 {attachment.size}，实际 {actual_size}"
        )
    os.replace(partial, destination)


def download_all(
    output_dir: Path,
    doc_key: str,
    attachments: list[SheetAttachment],
    *,
    dry_run: bool = False,
) -> tuple[int, int, list[str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    connection = _open_history(output_dir)
    downloaded_count = 0
    skipped_count = 0
    errors: list[str] = []
    try:
        for index, attachment in enumerate(attachments, start=1):
            recorded = _recorded_file(connection, output_dir, attachment)
            if recorded:
                print(f"[{index}/{len(attachments)}] 跳过已下载：{recorded.name}")
                skipped_count += 1
                continue

            destination = _available_path(output_dir, attachment.name)

            print(
                f"[{index}/{len(attachments)}] {'将下载' if dry_run else '正在下载'}："
                f"{destination.name} ({attachment.size / 1024 / 1024:.1f} MB)"
            )
            if dry_run:
                continue
            try:
                _download(attachment, destination)
                _record_download(connection, doc_key, attachment, destination.name)
                downloaded_count += 1
            except (OSError, urllib.error.URLError, RuntimeError) as error:
                errors.append(f"{attachment.name}：{error}")
                print(f"    下载失败：{error}", file=sys.stderr)
    finally:
        connection.close()
    return downloaded_count, skipped_count, errors


def configured_sources() -> list[tuple[str, str, str]]:
    sources = [
        (
            os.getenv("DINGTALK_SHEET_URL", DEFAULT_SHEET_URL).strip(),
            os.getenv("DINGTALK_SHEET_TITLE", DEFAULT_SHEET_TITLE).strip(),
            os.getenv("DINGTALK_VIDEO_COLUMN", DEFAULT_COLUMN_HEADER).strip(),
        )
    ]
    index = 2
    while url := os.getenv(f"DINGTALK_SHEET_URL_{index}", "").strip():
        sources.append(
            (
                url,
                os.getenv(f"DINGTALK_SHEET_TITLE_{index}", DEFAULT_SHEET_TITLE).strip(),
                os.getenv(f"DINGTALK_VIDEO_COLUMN_{index}", DEFAULT_COLUMN_HEADER).strip(),
            )
        )
        index += 1
    return sources


def main() -> int:
    root_dir = Path(__file__).resolve().parent.parent
    load_dotenv(root_dir / ".env")
    parser = argparse.ArgumentParser(
        description="从钉钉在线表格批量下载指定列中的视频附件"
    )
    parser.add_argument("--output", required=True, help="视频保存目录")
    parser.add_argument(
        "--url",
        default=None,
        help="钉钉表格地址",
    )
    parser.add_argument(
        "--sheet-title",
        default=None,
        help="工作表名称",
    )
    parser.add_argument(
        "--column-header",
        default=None,
        help="视频列的表头文字或 Excel 列字母，例如 E",
    )
    parser.add_argument("--dry-run", action="store_true", help="只列出本次需要下载的文件")
    args = parser.parse_args()

    output_dir = Path(args.output).expanduser().resolve()
    sources = (
        [
            (
                args.url,
                args.sheet_title or DEFAULT_SHEET_TITLE,
                args.column_header or DEFAULT_COLUMN_HEADER,
            )
        ]
        if args.url
        else configured_sources()
    )
    print(f"保存目录：{output_dir}")
    try:
        downloaded = skipped = 0
        errors: list[str] = []
        for index, (sheet_url, sheet_title, column_header) in enumerate(sources, start=1):
            print(f"正在读取钉钉表格 {index}/{len(sources)}：{sheet_title}…")
            try:
                doc_key, attachments = extract_attachments(
                    sheet_url, sheet_title, column_header
                )
                total_size = sum(item.size for item in attachments)
                print(
                    f"表格中共找到 {len(attachments)} 个视频，"
                    f"合计 {total_size / 1024 / 1024:.1f} MB。"
                )
                source_downloaded, source_skipped, source_errors = download_all(
                    output_dir, doc_key, attachments, dry_run=args.dry_run
                )
                downloaded += source_downloaded
                skipped += source_skipped
                errors.extend(source_errors)
            except Exception as error:
                message = f"{sheet_title}：{error}"
                errors.append(message)
                print(f"表格处理失败：{error}", file=sys.stderr)
    except Exception as error:
        print(f"运行失败：{error}", file=sys.stderr)
        return 1

    print()
    if args.dry_run:
        print("检查完成，没有下载文件。")
    else:
        print(f"处理完成：新下载 {downloaded} 个，跳过 {skipped} 个。")
    if errors:
        print(f"失败 {len(errors)} 个，下次执行会自动重试。", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
