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

run_privileged() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    log "需要 root 权限或 sudo 才能自动安装系统依赖: $*"
    return 1
  fi
}

python_venv_packages() {
  "$PYTHON_BIN" - <<'PY'
import sys
major = sys.version_info.major
minor = sys.version_info.minor
print(f"python{major}.{minor}-venv")
print(f"python{major}-venv")
print("python3-venv")
PY
}

can_create_venv() {
  local tmp_dir
  tmp_dir="$(mktemp -d)"
  if "$PYTHON_BIN" -m venv "$tmp_dir/venv" >/dev/null 2>&1; then
    rm -rf "$tmp_dir"
    return 0
  fi
  rm -rf "$tmp_dir"
  return 1
}

install_python_venv_dependency() {
  if command -v apt-get >/dev/null 2>&1; then
    log "检测到 Python venv/ensurepip 不完整，尝试自动安装 venv 系统依赖。"
    run_privileged apt-get update
    while IFS= read -r package_name; do
      [ -n "$package_name" ] || continue
      log "尝试安装: $package_name"
      if run_privileged apt-get install -y "$package_name"; then
        return 0
      fi
    done < <(python_venv_packages)
  fi

  log "无法自动安装 Python venv 依赖。"
  log "Debian/Ubuntu 可手动执行: apt update && apt install -y $(python_venv_packages | head -n 1)"
  return 1
}

ensure_venv_ready() {
  if "$PYTHON_BIN" -m venv --help >/dev/null 2>&1 && can_create_venv; then
    return 0
  fi

  install_python_venv_dependency
  if "$PYTHON_BIN" -m venv --help >/dev/null 2>&1 && can_create_venv; then
    return 0
  fi

  log "安装 venv 依赖后仍无法创建虚拟环境，请检查 Python 安装。"
  exit 1
}

ensure_command git
ensure_command "$PYTHON_BIN"
ensure_venv_ready

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
if [ -d .venv ]; then
  rm -rf .venv
fi
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
