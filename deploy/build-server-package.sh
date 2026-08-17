#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
OUTPUT_PATH=${1:-"$PROJECT_DIR/视频走查服务器交付包.tar.gz"}

cd "$PROJECT_DIR"
tar -czf "$OUTPUT_PATH" \
    server \
    tests/test_server.py \
    deploy/nginx.conf \
    deploy/server.env.example \
    deploy/video-review.service \
    deploy/verify-deployment.sh \
    deploy/backup-postgres.sh \
    deploy/build-server-package.sh \
    .dockerignore \
    Dockerfile \
    compose.yaml \
    requirements-server.txt \
    requirements-server-test.txt \
    服务器部署说明.md \
    技术交付清单.md

echo "交付包已生成：$OUTPUT_PATH"