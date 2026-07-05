from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PROGRAM_PATHS = [
    "nvidia_probe",
    "scripts",
    "pyproject.toml",
    "requirements.txt",
    "README.md",
    ".venv",
    ".git",
    "build",
    "dist",
    "__pycache__",
]
PROGRAM_GLOBS = ["*.egg-info"]


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
            "任务已完成。是否保留程序文件？\n\n"
            "删除程序文件只会卸载工具本体，不会删除刚刚生成的检测结果。\n"
            "测试结果文件会继续保留在结果目录。\n"
            "默认操作是删除程序本体，仅保留测试结果文件。\n"
            "只有选择“是”才会保留程序文件；选择“否”或关闭窗口都会删除程序本体。",
            default=messagebox.NO,
        )
        root.destroy()
        return bool(keep)
    except Exception:  # noqa: BLE001 - headless servers usually fail here
        return None


def _ask_tkinter_delete_after_interrupt() -> bool | None:
    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception:  # noqa: BLE001 - tkinter may not exist on remote servers
        return None

    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        delete = messagebox.askyesno(
            "NVIDIA Model Probe",
            "检测已被 Ctrl+C 中断。是否删除程序文件？\n\n"
            "删除程序文件只会卸载工具本体，不会删除已经生成的检测结果。\n"
            "默认操作是不删除程序，方便稍后继续运行或断点续跑。\n"
            "只有选择“是”才会删除程序文件；选择“否”或关闭窗口都会保留程序本体。",
            default=messagebox.NO,
        )
        root.destroy()
        return bool(delete)
    except Exception:  # noqa: BLE001 - headless servers usually fail here
        return None


def _ask_console() -> bool:
    if not sys.stdin.isatty():
        print("当前不是交互式终端，无法输入 y，默认删除程序本体，仅保留测试结果文件。")
        return False
    print("\n任务已完成。是否保留程序文件？")
    print("删除程序文件只会卸载工具本体，不会删除刚刚生成的检测结果。")
    print("测试结果文件会继续保留在结果目录。")
    print("默认操作：直接回车或 Ctrl+C 将删除程序本体，仅保留测试结果文件。")
    print("只有输入 y 或 yes 才会保留程序文件。")
    while True:
        try:
            answer = input("保留程序文件？输入 y 保留，直接回车删除 [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n未输入 y，默认删除程序本体；不会删除检测结果，测试结果文件会继续保留。")
            return False
        if answer in ("y", "yes"):
            return True
        if answer in ("", "n", "no"):
            return False
        print("请输入 y 保留，或直接回车删除。")


def _ask_console_delete_after_interrupt() -> bool:
    if not sys.stdin.isatty():
        print("检测已被 Ctrl+C 中断；当前不是交互式终端，默认不删除程序文件。")
        return False
    print("\n检测已被 Ctrl+C 中断。是否删除程序文件？")
    print("删除程序文件只会卸载工具本体，不会删除已经生成的检测结果。")
    print("默认操作：直接回车或再次 Ctrl+C 将不删除程序，方便稍后继续运行或断点续跑。")
    print("只有输入 y 或 yes 才会删除程序文件。")
    while True:
        try:
            answer = input("删除程序文件？输入 y 删除，直接回车保留 [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n未输入 y，默认不删除程序文件；检测结果和程序本体都会保留。")
            return False
        if answer in ("y", "yes"):
            return True
        if answer in ("", "n", "no"):
            return False
        print("请输入 y 删除，或直接回车保留。")


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


def should_delete_program_after_interrupt(cleanup_prompt: str) -> bool:
    if cleanup_prompt == "never":
        return False
    if cleanup_prompt == "always":
        delete = _ask_tkinter_delete_after_interrupt()
        if delete is not None:
            return delete
        return _ask_console_delete_after_interrupt()
    if cleanup_prompt == "auto":
        delete = _ask_tkinter_delete_after_interrupt()
        if delete is not None:
            return delete
        return _ask_console_delete_after_interrupt()
    return False


def _iter_cleanup_targets(project_root: Path):
    seen: set[Path] = set()
    for relative in PROGRAM_PATHS:
        target = (project_root / relative).resolve()
        if target in seen:
            continue
        seen.add(target)
        yield target
    for pattern in PROGRAM_GLOBS:
        for target in project_root.glob(pattern):
            resolved = target.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield resolved


def _contains_protected_path(target: Path, protected: set[Path]) -> bool:
    for protected_path in protected:
        if target == protected_path:
            return True
        try:
            protected_path.relative_to(target)
        except ValueError:
            continue
        return True
    return False


def _write_cleanup_marker(project_root: Path, protected: set[Path]) -> bool:
    marker = os.getenv("NVIDIA_PROBE_CLEANUP_MARKER")
    if not marker:
        return False

    resolved_root = project_root.resolve()
    if _contains_protected_path(resolved_root, protected):
        return False

    marker_path = Path(marker).expanduser().resolve()
    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(str(resolved_root), encoding="utf-8")
    except OSError as exc:
        print(f"无法写入卸载标记文件 {marker_path}: {exc}")
        return False
    return True


def _delete_target(target: Path) -> None:
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()


def cleanup_program_files(project_root: Path, result_paths: list[Path]) -> tuple[list[Path], list[tuple[Path, str]], Path | None]:
    deleted: list[Path] = []
    failures: list[tuple[Path, str]] = []
    protected = {path.resolve() for path in result_paths if path.exists()}
    resolved_root = project_root.resolve()
    deferred_root = resolved_root if _write_cleanup_marker(project_root, protected) else None
    if deferred_root is not None:
        return deleted, failures, deferred_root

    for target in _iter_cleanup_targets(project_root):
        if _contains_protected_path(target, protected):
            continue
        if not target.exists():
            continue
        try:
            _delete_target(target)
        except OSError as exc:
            failures.append((target, str(exc)))
            continue
        deleted.append(target)

    if resolved_root.exists() and not _contains_protected_path(resolved_root, protected):
        try:
            _delete_target(resolved_root)
        except OSError as exc:
            failures.append((resolved_root, str(exc)))
        else:
            deleted.append(resolved_root)
    return deleted, failures, deferred_root


def maybe_cleanup_program(cleanup_prompt: str, project_root: Path, result_paths: list[Path]) -> None:
    keep = should_keep_program(cleanup_prompt)
    if keep:
        print("已选择保留程序文件。")
        return
    _cleanup_and_print_result(project_root, result_paths)


def maybe_cleanup_program_after_interrupt(cleanup_prompt: str, project_root: Path, result_paths: list[Path]) -> None:
    delete = should_delete_program_after_interrupt(cleanup_prompt)
    if not delete:
        print("已保留程序文件。")
        return
    _cleanup_and_print_result(project_root, result_paths)


def _cleanup_and_print_result(project_root: Path, result_paths: list[Path]) -> None:
    deleted, failures, deferred_root = cleanup_program_files(project_root, result_paths)
    if deleted:
        print("已删除程序文件：")
        for path in deleted:
            print(f"- {path}")
    if deferred_root is not None:
        print("已安排在当前 Python 进程退出后删除程序目录：")
        print(f"- {deferred_root}")
    if not deleted and deferred_root is None:
        print("没有发现可删除的程序文件。")
    existing_results = [path for path in result_paths if path.exists()]
    if existing_results:
        print("已保留测试结果文件：")
        for path in existing_results:
            print(f"- {path}")
    if failures:
        print("以下程序文件未能删除，可稍后手动删除：")
        for path, error in failures:
            print(f"- {path}: {error}")
