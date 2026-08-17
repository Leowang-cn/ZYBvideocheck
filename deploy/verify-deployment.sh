#!/bin/sh
set -eu

BASE_URL=${1:-}
IMPORT_TOKEN=${2:-}

if [ -z "$BASE_URL" ] || [ -z "$IMPORT_TOKEN" ]; then
    echo "用法: $0 http://服务器内网IP:端口 IMPORT_TOKEN" >&2
    exit 2
fi

BASE_URL=${BASE_URL%/}
VIDEO_ID=3a6e302acbb24eca9df31d7cfe2a137e13cbd696c8c7aebfc7b1c7341936fd2c
PAYLOAD=$(cat <<EOF
{"videos":[{"video_id":"$VIDEO_ID","level_1":"部署验收","level_2":"接口测试","batch":"deployment-check","created_date":"$(date +%F)","file_name":"部署验收记录.mp4","file_size":0,"duration":1,"width":16,"height":16,"video_url":"https://example.invalid/video.mp4","snapshots":[{"sequence":1,"second":0,"url":"https://example.invalid/snapshot.jpg"}]}]}
EOF
)

echo "[1/4] 检查健康接口"
curl --fail --silent --show-error "$BASE_URL/api/health"
echo

echo "[2/4] 检查错误 Token 被拒绝"
UNAUTHORIZED_STATUS=$(curl --silent --output /dev/null --write-out '%{http_code}' \
    -X POST "$BASE_URL/api/videos/import" \
    -H 'Authorization: Bearer invalid-token' \
    -H 'Content-Type: application/json' \
    --data "$PAYLOAD")
if [ "$UNAUTHORIZED_STATUS" != "401" ]; then
    echo "预期 HTTP 401，实际为 $UNAUTHORIZED_STATUS" >&2
    exit 1
fi

echo "[3/4] 导入验收记录并重复提交"
curl --fail --silent --show-error -X POST "$BASE_URL/api/videos/import" \
    -H "Authorization: Bearer $IMPORT_TOKEN" \
    -H 'Content-Type: application/json' \
    --data "$PAYLOAD"
echo
curl --fail --silent --show-error -X POST "$BASE_URL/api/videos/import" \
    -H "Authorization: Bearer $IMPORT_TOKEN" \
    -H 'Content-Type: application/json' \
    --data "$PAYLOAD"
echo

echo "[4/4] 查询验收记录"
curl --fail --silent --show-error \
    "$BASE_URL/api/videos?level_1=%E9%83%A8%E7%BD%B2%E9%AA%8C%E6%94%B6&keyword=%E9%83%A8%E7%BD%B2%E9%AA%8C%E6%94%B6"
echo
echo "部署接口验收完成。请在页面确认 deployment-check 批次仅有一条记录。"