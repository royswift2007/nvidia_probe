#!/usr/bin/env bash
set -Eeuo pipefail

REPO_URL="${NVIDIA_PROBE_REPO_URL:-https://github.com/royswift2007/nvidia_probe.git}"
BRANCH="${NVIDIA_PROBE_BRANCH:-main}"
ORIGINAL_DIR="${PWD}"
INSTALL_DIR="${NVIDIA_PROBE_INSTALL_DIR:-${ORIGINAL_DIR}/.nvidia_probe}"
RESULT_DIR="${NVIDIA_PROBE_RESULT_DIR:-${ORIGINAL_DIR}/nvidia_probe_results}"
CLEANUP_MARKER="${NVIDIA_PROBE_CLEANUP_MARKER:-${ORIGINAL_DIR}/.nvidia_probe_cleanup_marker}"
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

cleanup_dir_safely() {
  local target="$1"
  if [ -z "$target" ] || [ "$target" = "/" ] || [ "$target" = "$ORIGINAL_DIR" ]; then
    log "拒绝删除不安全目录: $target"
    return 1
  fi
  rm -rf "$target"
}

preserve_old_results_if_needed() {
  if [ ! -d "$INSTALL_DIR/results" ]; then
    return 0
  fi

  local destination="$RESULT_DIR"
  if [ -e "$destination" ]; then
    destination="${RESULT_DIR}_previous_$(date -u +%Y%m%d_%H%M%S)"
  fi
  mkdir -p "$(dirname "$destination")"
  mv "$INSTALL_DIR/results" "$destination"
  log "已保留旧结果目录: $destination"
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
    log "发现旧的非 git 安装目录: $INSTALL_DIR"
    preserve_old_results_if_needed
    cleanup_dir_safely "$INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
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

mkdir -p "$RESULT_DIR"
rm -f "$CLEANUP_MARKER"
export NVIDIA_PROBE_CLEANUP_MARKER="$CLEANUP_MARKER"

log "启动检测。如果未设置 NVIDIA_API_KEY，将提示隐藏输入 API Key。"
log "结果目录: $RESULT_DIR"
log "默认参数: --cleanup-prompt auto；运行结束后会询问是否卸载程序，只保留测试结果。"
set +e
python -m nvidia_probe run --cleanup-prompt auto --output-dir "$RESULT_DIR" "$@"
status=$?
set -e

cd "$ORIGINAL_DIR"
if [ -f "$CLEANUP_MARKER" ]; then
  cleanup_target="$(cat "$CLEANUP_MARKER" 2>/dev/null || true)"
  rm -f "$CLEANUP_MARKER"
  if [ -n "$cleanup_target" ] && [ -d "$cleanup_target" ]; then
    cleanup_dir_safely "$cleanup_target" || true
    if [ -d "$cleanup_target" ]; then
      log "程序目录仍未完全删除，可手动删除: $cleanup_target"
    else
      log "已卸载程序目录: $cleanup_target"
    fi
  fi
fi

log "测试结果保留在: $RESULT_DIR"
exit "$status"
