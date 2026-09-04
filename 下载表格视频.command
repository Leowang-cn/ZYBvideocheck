#!/bin/zsh

set -u
cd "${0:A:h}"

if [[ ! -x .venv/bin/python ]]; then
    print "未找到项目虚拟环境 .venv，请先按照 README.md 完成首次配置。"
    read -r "?按回车键关闭..."
    exit 1
fi

download_dir=$(osascript -e 'POSIX path of (choose folder with prompt "请选择表格视频的保存目录")' 2>/dev/null)
if [[ -z "$download_dir" ]]; then
    print "已取消。"
    exit 0
fi

./.venv/bin/python -m video_review.dingtalk_video_download --output "$download_dir"
exit_code=$?

print
read -r "?运行结束，按回车键关闭..."
exit "$exit_code"
