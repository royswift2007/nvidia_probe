#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${NVIDIA_PROBE_REPO_URL:-https://github.com/royswift2007/nvidia_probe.git}"
BRANCH="${NVIDIA_PROBE_BRANCH:-main}"
INSTALL_DIR="${NVIDIA_PROBE_INSTALL_DIR:-${PWD}/.nvidia_probe}"
PYTHON_BIN="${PYTHON:-python3}"

log() {
  printf '[nvidia-probe] %s\n' "$*"
}

ensure_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "缺少命令: $1"
    log "请先安装 $1 后重试。Ubuntu/Debian 可执行: sudo apt update && sudo apt install -y $1"
    exit 1
  fi
}

ensure_command git
ensure_command "$PYTHON_BIN"

if ! "$PYTHON_BIN" -m venv --help >/dev/null 2>&1; then
  log "当前 Python 不支持 venv。Ubuntu/Debian 可执行: sudo apt update && sudo apt install -y python3-venv"
  exit 1
fi

mkdir -p "$INSTALL_DIR"

if [ -d "$INSTALL_DIR/.git" ]; then
  log "更新项目: $INSTALL_DIR"
  git -C "$INSTALL_DIR" fetch --depth 1 origin "$BRANCH"
  git -C "$INSTALL_DIR" checkout "$BRANCH"
  git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"
else
  if [ -n "$(find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | head -n 1)" ]; then
    log "安装目录非空且不是 git 仓库: $INSTALL_DIR"
    log "请设置 NVIDIA_PROBE_INSTALL_DIR 指向空目录，或删除该目录后重试。"
    exit 1
  fi
  log "克隆项目到: $INSTALL_DIR"
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

log "创建/更新虚拟环境"
"$PYTHON_BIN" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

log "安装依赖"
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -e .

log "启动检测。如果未设置 NVIDIA_API_KEY，将提示隐藏输入 API Key。"
log "默认参数: --cleanup-prompt auto；运行结束后会询问是否卸载程序，只保留测试结果。"
python -m nvidia_probe run --cleanup-prompt auto "$@"
