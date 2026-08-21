#!/bin/zsh

set -u
cd "${0:A:h}"

if [[ ! -x .venv/bin/python ]]; then
    print "未找到项目虚拟环境 .venv，请先按照 README.md 完成首次配置。"
    read -r "?按回车键关闭..."
    exit 1
fi

read -r "batch?请输入批次名称（直接回车使用当天日期）："
if [[ -n "$batch" ]]; then
    ./.venv/bin/python -m video_review.cli --batch "$batch"
else
    ./.venv/bin/python -m video_review.cli
fi
exit_code=$?

print
read -r "?运行结束，按回车键关闭..."
exit "$exit_code"
