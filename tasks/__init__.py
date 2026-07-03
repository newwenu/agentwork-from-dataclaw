"""Tasks — 定时任务模块。

每个任务是一个独立的 .py 文件，包含：
- name: 任务名称
- interval: 执行间隔（秒）
- run(): 任务执行函数

修复 (2026-06-25):
1. 使用隔离的模块命名空间，避免污染 sys.modules
2. 验证 interval 必须为正数
3. 限制最大加载任务数量
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Callable, TypedDict


class TaskInfo(TypedDict):
    """任务信息结构。"""

    name: str
    interval: float
    description: str
    func: Callable


# 禁止与系统模块冲突的任务文件名
RESERVED_MODULE_NAMES = frozenset({
    "os", "sys", "json", "re", "pathlib", "typing", "asyncio",
    "subprocess", "socket", "urllib", "http", "ftplib", "pickle",
    "builtins", "importlib", "inspect", "warnings", "traceback",
})

MAX_TASKS = 50  # 限制最大加载任务数，防止资源耗尽
MIN_INTERVAL = 1.0  # 最小执行间隔 (秒)
MAX_INTERVAL = 86400.0  # 最大执行间隔 24 小时


def scan_tasks(tasks_dir: Path) -> list[TaskInfo]:
    """扫描 tasks 文件夹，加载所有可用任务。

    Args:
        tasks_dir: tasks 目录路径

    Returns:
        任务信息列表
    """
    tasks = []

    if not tasks_dir.exists():
        return tasks

    task_files = [f for f in tasks_dir.glob("*.py") if not f.name.startswith("_")]

    if len(task_files) > MAX_TASKS:
        print(f"[Tasks] 警告: 发现 {len(task_files)} 个任务文件，超过最大限制 {MAX_TASKS}，只加载前 {MAX_TASKS} 个")
        task_files = task_files[:MAX_TASKS]

    for task_file in task_files:
        stem = task_file.stem

        if stem in RESERVED_MODULE_NAMES:
            print(f"[Tasks] 跳过 {task_file.name}: 文件名与系统模块冲突")
            continue

        try:
            # 使用隔离的模块名，避免污染 sys.modules
            module_name = f"__dataclaw_task_{stem}__"
            spec = importlib.util.spec_from_file_location(
                module_name, task_file
            )
            if not spec or not spec.loader:
                continue

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # 检查必需的属性
            if not hasattr(module, "run"):
                print(f"[Tasks] 跳过 {task_file.name}: 缺少 run() 函数")
                continue

            interval = getattr(module, "interval", 60)
            # 验证 interval 范围
            if not (MIN_INTERVAL <= interval <= MAX_INTERVAL):
                print(f"[Tasks] 跳过 {task_file.name}: interval {interval} 不在允许范围 [{MIN_INTERVAL}, {MAX_INTERVAL}]")
                continue

            task_info: TaskInfo = {
                "name": getattr(module, "name", stem),
                "interval": interval,
                "description": getattr(module, "description", ""),
                "func": module.run,
            }
            tasks.append(task_info)
            print(f"[Tasks] 已加载任务: {task_info['name']} (间隔 {task_info['interval']}s)")

        except Exception as e:
            print(f"[Tasks] 加载 {task_file.name} 失败: {e}")

    return tasks
