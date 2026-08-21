from __future__ import annotations

import base64
from datetime import datetime
from html import escape
from pathlib import Path, PurePosixPath

from video_review.config import Settings
from video_review.history import ImportRecord


def format_duration(seconds: float) -> str:
    total = round(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_size(size: int) -> str:
    return f"{size / (1024 * 1024):.1f} MB"


def image_data_url(image_path: str) -> str:
    encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def relative_source_path(source_path: str, input_dir: Path) -> str:
    try:
        return Path(source_path).resolve().relative_to(input_dir.resolve()).as_posix()
    except ValueError:
        return source_path


def source_levels(source_path: str, input_dir: Path) -> tuple[str, str]:
  relative_path = Path(relative_source_path(source_path, input_dir))
  folders = relative_path.parts[:-1]
  first_level = folders[0] if len(folders) >= 1 else ""
  second_level = folders[1] if len(folders) >= 2 else ""
  return first_level, second_level


def record_source_levels(record: ImportRecord, settings: Settings) -> tuple[str, str]:
  if settings.openlist_path and record.source_path.startswith("/"):
    try:
      relative_path = PurePosixPath(record.source_path).relative_to(
        PurePosixPath(settings.effective_baidu_pan_mount_path())
      )
    except ValueError:
      pass
    else:
      folders = relative_path.parts[:-1]
      return (
        folders[0] if len(folders) >= 1 else "",
        folders[1] if len(folders) >= 2 else "",
      )
  return source_levels(record.source_path, settings.input_dir)


def export_html(
    records: list[ImportRecord], settings: Settings, batch: str, output_path: Path
) -> None:
    imported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = "\n".join(_record_row(record, settings, imported_at) for record in records)
    source_level_pairs = [
        record_source_levels(record, settings) for record in records
    ]
    first_level_options = _source_level_options(level[0] for level in source_level_pairs)
    second_level_options = _source_level_options(level[1] for level in source_level_pairs)
    batches = sorted({record.batch or "未标记" for record in records})
    batch_options = "".join(
        f'<option value="{escape(value, quote=True)}">{escape(value)}</option>'
        for value in batches
    )
    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>视频走查</title>
  <style>
    :root {{ color-scheme: light; font-family: "PingFang SC", "Microsoft YaHei", sans-serif; }}
    body {{ margin: 0; background: #f5f7f8; color: #182026; }}
    header {{ padding: 20px 24px; background: #173f5f; color: white; }}
    h1 {{ margin: 0 0 6px; font-size: 22px; letter-spacing: 0; }}
    header p {{ margin: 0; color: #d8e6ef; font-size: 14px; }}
    main {{ padding: 20px; }}
    .toolbar {{ display: flex; align-items: end; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }}
    .toolbar label {{ display: grid; gap: 5px; color: #52616b; font-size: 12px; }}
    .toolbar input, .toolbar select, .toolbar button {{ width: 190px; min-height: 34px; padding: 8px 10px; border: 1px solid #b8c4cc; background: white; }}
    .toolbar button {{ width: auto; cursor: pointer; color: #173f5f; font-weight: 600; }}
    .count {{ margin-left: auto; color: #52616b; font-size: 13px; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; min-width: 1800px; border-collapse: collapse; background: white; }}
    th, td {{ border: 1px solid #d9e0e5; padding: 10px; text-align: left; vertical-align: top; }}
    th {{ position: sticky; top: 0; background: #e9f0f4; white-space: nowrap; }}
    td {{ font-size: 14px; }}
    .name {{ min-width: 220px; font-weight: 600; }}
    .source {{ min-width: 220px; overflow-wrap: anywhere; }}
    .snapshots {{ display: flex; gap: 10px; min-width: 540px; }}
    figure {{ width: 170px; margin: 0; }}
    .thumbnail {{ padding: 0; border: 0; background: transparent; cursor: zoom-in; }}
    .thumbnail img {{ display: block; width: 160px; height: 90px; object-fit: contain; background: #101820; }}
    figcaption {{ margin-top: 6px; font-size: 12px; color: #52616b; }}
    a {{ color: #075985; }}
    select, textarea {{ width: 100%; box-sizing: border-box; font: inherit; }}
    textarea {{ min-width: 180px; min-height: 90px; resize: vertical; }}
    .meta {{ white-space: nowrap; }}
    dialog {{ width: min(1100px, calc(100vw - 32px)); padding: 0; border: 0; background: #101820; color: white; }}
    dialog::backdrop {{ background: rgba(0, 0, 0, .82); }}
    .viewer {{ display: grid; grid-template-columns: 52px minmax(0, 1fr) 52px; align-items: center; min-height: 320px; }}
    .viewer img {{ width: 100%; max-height: calc(100vh - 120px); object-fit: contain; }}
    .viewer button {{ min-height: 52px; border: 0; background: transparent; color: white; font-size: 30px; cursor: pointer; }}
    .viewer-close {{ position: absolute; top: 8px; right: 10px; width: 44px; z-index: 1; }}
    .viewer-caption {{ position: absolute; left: 16px; bottom: 10px; padding: 5px 8px; background: rgba(0, 0, 0, .65); font-size: 13px; }}
    @media print {{ header {{ background: white; color: black; }} main {{ padding: 0; }} .toolbar {{ display: none; }} th {{ position: static; }} }}
  </style>
</head>
<body>
  <header>
    <h1>视频走查</h1>
    <p>累计 {len(records)} 条 · 本次新增批次：{escape(batch)} · 更新时间：{imported_at}</p>
  </header>
  <main>
    <div class="toolbar">
      <label>搜索视频名称<input id="search" type="search" placeholder="输入名称"></label>
      <label>筛选一级地址<select id="first-level-filter"><option value="">全部一级地址</option>{first_level_options}</select></label>
      <label>筛选二级地址<select id="second-level-filter"><option value="">全部二级地址</option>{second_level_options}</select></label>
      <label>筛选批次<select id="batch-filter"><option value="">全部批次</option>{batch_options}</select></label>
      <label>创建时间从<input id="created-from" type="date"></label>
      <label>创建时间至<input id="created-to" type="date"></label>
      <label>筛选评级<select id="rating-filter"><option value="">全部评级</option><option value="未评级">未评级</option><option>优秀</option><option>良好</option><option>合格</option><option>不合格</option><option>无需审核</option></select></label>
      <button id="export-csv" type="button">导出 CSV</button>
      <span class="count" id="count">显示 {len(records)} / {len(records)} 条</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>一级地址</th><th>二级地址</th><th>创建时间</th><th>视频名称</th><th>原视频链接</th><th>截图</th><th>文件信息</th><th>原片类型</th><th>评级</th><th>质检备注</th><th>补充</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </main>
  <dialog id="image-viewer">
    <button class="viewer-close" type="button" aria-label="关闭">×</button>
    <div class="viewer">
      <button id="viewer-prev" type="button" aria-label="上一张">‹</button>
      <img id="viewer-image" alt="截图预览">
      <button id="viewer-next" type="button" aria-label="下一张">›</button>
    </div>
    <span class="viewer-caption" id="viewer-caption"></span>
  </dialog>
  <script>
    const rows = [...document.querySelectorAll("tbody tr")];
    const search = document.querySelector("#search");
    const firstLevelFilter = document.querySelector("#first-level-filter");
    const secondLevelFilter = document.querySelector("#second-level-filter");
    const batchFilter = document.querySelector("#batch-filter");
    const createdFrom = document.querySelector("#created-from");
    const createdTo = document.querySelector("#created-to");
    const ratingFilter = document.querySelector("#rating-filter");
    const count = document.querySelector("#count");
    function filterRows() {{
      const query = search.value.trim().toLocaleLowerCase();
      let visible = 0;
      for (const row of rows) {{
        const matchesName = row.dataset.videoName.toLocaleLowerCase().includes(query);
        const selectedFirstLevel = firstLevelFilter.value === "__EMPTY__" ? "" : firstLevelFilter.value;
        const selectedSecondLevel = secondLevelFilter.value === "__EMPTY__" ? "" : secondLevelFilter.value;
        const matchesFirstLevel = !firstLevelFilter.value || row.dataset.firstLevel === selectedFirstLevel;
        const matchesSecondLevel = !secondLevelFilter.value || row.dataset.secondLevel === selectedSecondLevel;
        const matchesBatch = !batchFilter.value || row.dataset.batch === batchFilter.value;
        const createdDate = row.dataset.createdAt;
        const matchesFrom = !createdFrom.value || createdDate >= createdFrom.value;
        const matchesTo = !createdTo.value || createdDate <= createdTo.value;
        const rating = row.querySelector('[aria-label="评级"]').value || "未评级";
        const matchesRating = !ratingFilter.value || rating === ratingFilter.value;
        row.hidden = !(matchesName && matchesFirstLevel && matchesSecondLevel && matchesBatch && matchesFrom && matchesTo && matchesRating);
        if (!row.hidden) visible += 1;
      }}
      count.textContent = `显示 ${{visible}} / ${{rows.length}} 条`;
    }}
    search.addEventListener("input", filterRows);
    firstLevelFilter.addEventListener("change", filterRows);
    secondLevelFilter.addEventListener("change", filterRows);
    batchFilter.addEventListener("change", filterRows);
    createdFrom.addEventListener("change", filterRows);
    createdTo.addEventListener("change", filterRows);
    ratingFilter.addEventListener("change", filterRows);
    document.querySelectorAll('[aria-label="评级"]').forEach(select => select.addEventListener("change", filterRows));

    function csvCell(value) {{
      const text = String(value ?? "");
      const protectedText = /^[=+\-@]/.test(text) ? `'${{text}}` : text;
      return `"${{protectedText.replaceAll('"', '""')}}"`;
    }}
    document.querySelector("#export-csv").addEventListener("click", () => {{
      const header = ["一级地址", "二级地址", "创建日期", "批次", "视频名称", "视频 URL", "截图 URL", "文件大小", "时长", "分辨率", "原片类型", "评级", "质检备注", "补充"];
      const data = rows.filter(row => !row.hidden).map(row => [
        row.dataset.firstLevel,
        row.dataset.secondLevel,
        row.dataset.createdAt,
        row.dataset.batch,
        row.dataset.videoName,
        row.querySelector(".video-link").href,
        [...row.querySelectorAll(".snapshot-link")].map(link => link.href).join("\\n"),
        row.dataset.fileSize,
        row.dataset.duration,
        row.dataset.resolution,
        row.querySelector('[aria-label="原片类型"]').value,
        row.querySelector('[aria-label="评级"]').value || "未评级",
        row.querySelector('[aria-label="质检备注"]').value,
        row.querySelector('[aria-label="补充"]').value,
      ]);
      const content = [header, ...data].map(values => values.map(csvCell).join(",")).join("\\r\\n");
      const url = URL.createObjectURL(new Blob(["\ufeff", content], {{ type: "text/csv;charset=utf-8" }}));
      const link = document.createElement("a");
      link.href = url;
      link.download = `视频走查_${{new Date().toISOString().slice(0, 10)}}.csv`;
      link.click();
      URL.revokeObjectURL(url);
    }});

    const viewer = document.querySelector("#image-viewer");
    const viewerImage = document.querySelector("#viewer-image");
    const viewerCaption = document.querySelector("#viewer-caption");
    const thumbnails = [...document.querySelectorAll(".thumbnail")];
    let imageIndex = 0;
    function showImage(index) {{
      imageIndex = (index + thumbnails.length) % thumbnails.length;
      const thumbnail = thumbnails[imageIndex];
      viewerImage.src = thumbnail.querySelector("img").src;
      viewerCaption.textContent = `${{imageIndex + 1}} / ${{thumbnails.length}} · ${{thumbnail.dataset.caption}}`;
    }}
    thumbnails.forEach((thumbnail, index) => thumbnail.addEventListener("click", () => {{
      showImage(index);
      viewer.showModal();
    }}));
    document.querySelector(".viewer-close").addEventListener("click", () => viewer.close());
    document.querySelector("#viewer-prev").addEventListener("click", () => showImage(imageIndex - 1));
    document.querySelector("#viewer-next").addEventListener("click", () => showImage(imageIndex + 1));
    viewer.addEventListener("click", event => {{ if (event.target === viewer) viewer.close(); }});
    document.addEventListener("keydown", event => {{
      if (!viewer.open) return;
      if (event.key === "ArrowLeft") showImage(imageIndex - 1);
      if (event.key === "ArrowRight") showImage(imageIndex + 1);
    }});
  </script>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(document, encoding="utf-8")


def _record_row(
    record: ImportRecord, settings: Settings, imported_at: str
) -> str:
    video_url = settings.public_url(record.video_key)
    snapshots = []
    for index, (path, key, second) in enumerate(
        zip(record.snapshot_paths, record.snapshot_keys, record.snapshot_seconds), start=1
    ):
        snapshot_url = settings.public_url(key)
        caption = f"{record.file_name} · {format_duration(second)}"
        snapshots.append(
            f'<figure><button class="thumbnail" type="button" '
            f'data-caption="{escape(caption, quote=True)}">'
            f'<img src="{image_data_url(path)}" alt="截图 {index}"></button>'
            f'<figcaption>{format_duration(second)} · <a class="snapshot-link" href="{escape(snapshot_url, quote=True)}" '
            f'target="_blank">原图</a></figcaption></figure>'
        )
    first_level, second_level = record_source_levels(record, settings)
    created_at = record.created_at or imported_at
    created_date = created_at[:10]
    return f"""
<tr data-video-name="{escape(record.file_name, quote=True)}" data-first-level="{escape(first_level, quote=True)}" data-second-level="{escape(second_level, quote=True)}" data-batch="{escape(record.batch or '未标记', quote=True)}" data-created-at="{escape(created_date, quote=True)}" data-file-size="{format_size(record.file_size)}" data-duration="{format_duration(record.duration)}" data-resolution="{record.width} × {record.height}">
  <td class="source">{escape(first_level)}</td>
  <td class="source">{escape(second_level)}</td>
  <td class="meta">{escape(created_date)}</td>
  <td class="name">{escape(record.file_name)}<br><small>批次：{escape(record.batch or "未标记")}<br>报告更新：{imported_at}</small></td>
  <td><a class="video-link" href="{escape(video_url, quote=True)}" target="_blank">打开原视频</a></td>
  <td><div class="snapshots">{''.join(snapshots)}</div></td>
  <td class="meta">{format_size(record.file_size)}<br>{format_duration(record.duration)}<br>{record.width} × {record.height}</td>
  <td><select aria-label="原片类型"><option value=""></option><option>新片</option><option>旧片新剪</option><option>人像原片</option><option>屏幕原片</option></select></td>
  <td><select aria-label="评级"><option>未评级</option><option>优秀</option><option>良好</option><option>合格</option><option>不合格</option><option>无需审核</option></select></td>
  <td><textarea aria-label="质检备注"></textarea></td>
  <td><textarea aria-label="补充"></textarea></td>
</tr>"""


def _source_level_options(levels: object) -> str:
    values = sorted(set(levels))
    return "".join(
    '<option value="__EMPTY__">（空）</option>'
        if value == ""
        else f'<option value="{escape(value, quote=True)}">{escape(value)}</option>'
        for value in values
    )