#!/bin/zsh
set -euo pipefail

VERSION="v4.2.5"
ARCHIVE="openlist-darwin-arm64.tar.gz"
EXPECTED_SHA256="95071c3b5b63ffc683bcb36b36d7f1359ba81d7650ec8e13336daa4124ec1cf6"
DOWNLOAD_URL="https://github.com/OpenListTeam/OpenList/releases/download/${VERSION}/${ARCHIVE}"
SCRIPT_DIR="${0:A:h}"

cd "${SCRIPT_DIR}"
mkdir -p data logs

if [[ ! -x ./openlist ]]; then
  curl --fail --location --continue-at - --retry 10 --retry-all-errors --output "${ARCHIVE}" "${DOWNLOAD_URL}"
  ACTUAL_SHA256="$(shasum -a 256 "${ARCHIVE}" | awk '{print $1}')"
  if [[ "${ACTUAL_SHA256}" != "${EXPECTED_SHA256}" ]]; then
    print -u2 "SHA-256 mismatch: expected ${EXPECTED_SHA256}, got ${ACTUAL_SHA256}"
    exit 1
  fi
  tar -xzf "${ARCHIVE}"
  chmod +x ./openlist
fi

exec ./openlist server --data ./data
