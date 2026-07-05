from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PROGRAM_PATHS = [
    "nvidia_probe",
    "pyproject.toml",
    "requirements.txt",
    "README.md",
]


def _ask_tkinter() -> bool | None:
    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception:  # noqa: BLE001 - tkinter may not exist on remote servers
        return None

    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        keep = messagebox.askyesno(
            "NVIDIA Model Probe",
            "任务已完成。是否保留程序文件？\n\n选择“否”将删除程序本体，仅保留测试结果文件。",
        )
        root.destroy()
        return bool(keep)
    except Exception:  # noqa: BLE001 - headless servers usually fail here
        return None


def _ask_console() -> bool:
    if not sys.stdin.isatty():
        print("当前不是交互式终端，默认保留程序文件。")
        return True
    print("\n任务已完成。是否保留程序文件？")
    print("输入 y 保留；输入 n 删除程序本体，仅保留测试结果文件。")
    while True:
        answer = input("保留程序文件？[Y/n]: ").strip().lower()
        if answer in ("", "y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("请输入 y 或 n。")


def should_keep_program(cleanup_prompt: str) -> bool:
    if cleanup_prompt == "never":
        return True
    if cleanup_prompt == "always":
        keep = _ask_tkinter()
        if keep is not None:
            return keep
        return _ask_console()
    if cleanup_prompt == "auto":
        keep = _ask_tkinter()
        if keep is not None:
            return keep
        return _ask_console()
    return True


def cleanup_program_files(project_root: Path, result_paths: list[Path]) -> list[Path]:
    deleted: list[Path] = []
    protected = {path.resolve() for path in result_paths if path.exists()}
    for relative in PROGRAM_PATHS:
        target = (project_root / relative).resolve()
        if target in protected:
            continue
        if not target.exists():
            continue
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        deleted.append(target)
    return deleted


def maybe_cleanup_program(cleanup_prompt: str, project_root: Path, result_paths: list[Path]) -> None:
    keep = should_keep_program(cleanup_prompt)
    if keep:
        print("已选择保留程序文件。")
        return
    deleted = cleanup_program_files(project_root, result_paths)
    if deleted:
        print("已删除程序文件：")
        for path in deleted:
            print(f"- {path}")
    else:
        print("没有发现可删除的程序文件。")
