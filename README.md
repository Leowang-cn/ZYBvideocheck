# 视频走查工具

批量读取本地视频或 OpenList 中的百度个人网盘视频，按规则截取多张画面，将原视频和截图上传腾讯 COS，并更新带内嵌截图的离线 HTML 总表。也可以将结构化记录推送到公司内网的视频走查服务器。

## 首次配置

1. 确认本机已安装 `ffmpeg` 和 `ffprobe`。
2. 在终端执行 `./.venv/bin/python -m pip install -r requirements.txt`。
3. 将 `.env.example` 复制为 `.env`。
4. 在 `.env` 中填写 `COS_PREFIX`、`COS_SECRET_ID` 和 `COS_SECRET_KEY`。
5. 确认 COS 对象可通过配置的公共域名长期访问；私有桶的临时签名链接不适合写入离线 HTML。

密钥只保存在本机 `.env`，该文件已被 Git 忽略。

服务器部署完成后，在 `.env` 中填写 `VIDEO_REVIEW_SERVER_URL` 和 `VIDEO_REVIEW_IMPORT_TOKEN`。本地脚本会在 COS 上传完成后自动推送记录；服务器地址留空时完全保持原有离线 HTML 工作方式。技术部署步骤见 [服务器部署说明.md](服务器部署说明.md)。

## 日常使用

1. 把本次视频放入 `待处理视频`，可以包含子文件夹。
2. 双击 `运行视频走查.command`。
3. 输入批次名称；直接回车则使用当天日期。
4. 等待终端显示完成，在 `输出/视频走查.html` 中获取累计 HTML 总表。
5. 使用浏览器打开 HTML，可按一级地址、二级地址、视频名称、批次、创建日期和评级筛选；也可以将 HTML 文件发送给其他人查看。

后续批次会追加到同一个固定报告中：脚本只处理和上传新增视频，然后根据本地历史重建总表，既有记录不会重复上传。唯一 ID 根据文件内容生成，改名不会导致重复导入；视频内容发生变化会作为新视频处理。

### 从钉钉表格下载视频

双击 `下载表格视频.command`，在弹出窗口中选择本地保存目录。脚本会复用 Ego 浏览器的钉钉登录状态，读取“生产表”中“视频（一稿）”列的附件并下载到该目录。

下载记录保存在所选目录中的隐藏文件 `.dingtalk-video-downloads.sqlite3`。下次仍选择同一目录时，已完整下载的附件会自动跳过；如果文件被删除或大小不符，会重新下载。下载中断后会保留 `.part` 文件，再次执行时会尝试续传。

命令行也可直接指定目录：

```sh
./.venv/bin/python -m video_review.dingtalk_video_download --output "/Users/leo/Downloads/待上传视频"
```

更换表格、工作表名或视频列名时，可在 `.env` 中设置 `DINGTALK_SHEET_URL`、`DINGTALK_SHEET_TITLE` 和 `DINGTALK_VIDEO_COLUMN`。

### OpenList 远程输入

百度个人网盘可通过 OpenList 直接作为输入源。企业网盘当前兼容性测试未通过，因此这一模式只建议用于个人网盘。

1. 在 OpenList 中挂载百度个人网盘，并确认文件状态正常。
2. 在 `.env` 中填写 `OPENLIST_URL`、`OPENLIST_TOKEN` 和 `OPENLIST_PATH`。脚本默认将路径首段识别为百度个人网盘挂载点，例如从 `/baidu-test/初化` 推断 `/baidu-test`；只有路径结构特殊时才需要用 `BAIDU_PAN_MOUNT_PATH` 覆盖。Token 需要具备 `/api/fs/list` 和 `/api/fs/get` 的访问权限，不要把它提交到版本库。
3. 正常运行脚本。配置 `OPENLIST_PATH` 后，脚本会递归处理该路径下的视频，同时仍会处理本地 `待处理视频` 中的文件。

远程模式先通过 OpenList 的实时下载 URL 读取媒体信息和生成截图，再将完整原片流式下载到临时文件。文件大小与 OpenList 元数据一致后，原片通过 COS SDK 可恢复分片上传，整个过程不转码；上传完成或失败后都会删除临时文件。截图保持源视频分辨率并上传 COS，表格中的“原视频链接”指向 COS 原片。远程唯一 ID 根据路径、文件大小和修改时间生成，这些元数据变化时会作为新视频重新处理。

总表前两列分别记录视频相对 `待处理视频` 的第一级和第二级文件夹，层级不存在时留空，随后按日期记录首次创建该条数据的时间。一级和二级地址均可单独筛选，包括筛选空地址。点击“导出 CSV”会导出当前筛选条件下的可见数据，视频与截图仅写入 COS URL，不包含媒体文件或 Base64 图片。点击截图会在当前页面打开图片查看器，可使用“上一张”“下一张”按钮或键盘左右方向键切换；“原图”链接仍可用于访问 COS 文件。

支持 `.mp4`、`.mov`、`.mkv`、`.avi`、`.m4v`、`.webm`。每个视频截取第 3 秒和倒数第 3 秒；视频严格大于 6 秒时，再截取中间位置，共生成 2 至 3 张截图。极短视频的时间点会自动限制在有效范围内。截图使用无损 PNG，将 BT.709 有限范围视频画面显式转换为 sRGB 全范围图片，并保留源视频分辨率，包括 4K；HTML 表格中仅缩小显示，点击后按原图分辨率查看。

已导入的旧 JPEG 截图可使用 `./.venv/bin/python -m video_review.snapshot_refresh` 刷新。脚本会先将旧图备份到同一 COS 目录的 `snapshot-v1-N.jpg`，再用新 PNG 覆盖原对象地址，因此不需要登录或改动内网服务器，也不会影响评级与备注。迁移按视频记录检查点，中断后重新运行即可续传。

## 命令行使用

```sh
./.venv/bin/python -m video_review.cli --batch "2026年第34周"
```

运行记录保存在 `数据/import-history.sqlite`。若部分文件失败，成功文件仍会生成 HTML，失败原因会显示在终端中。

## 服务器功能

服务器代码位于 `server/`，提供内网页面、幂等批量导入、筛选分页、质检保存、并发修改保护和 CSV 导出。推荐使用根目录的 `compose.yaml` 部署 FastAPI、PostgreSQL 和 Nginx；服务器不保存媒体文件，浏览器通过 COS URL 读取视频和截图。

服务器端百度原视频自动转存使用 [deploy/video-review-worker.service](deploy/video-review-worker.service) 和 [deploy/video-review-worker.timer](deploy/video-review-worker.timer)，完整安装与验收步骤见 [服务器部署说明.md](服务器部署说明.md)。
