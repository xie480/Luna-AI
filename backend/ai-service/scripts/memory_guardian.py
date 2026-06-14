"""
memory_guardian.py - 内存监控守护进程

做什么：监控系统内存使用率，当超过阈值时触发 Windows 计划任务（schtasks）执行内存清理。
        支持从 .env 读取配置，也支持作为模块被 app.main 生命周期导入并在线程中运行。

为什么这样做：AI 服务（Embedding/Rerank 模型）长时间运行后可能产生内存泄漏，
             需要守护进程定期检测并触发清理任务，防止系统因内存不足而卡顿。

输入输出：
    输入：从 dataclass GuardianConfig 或 CLI 参数读取配置
    输出：日志写入 backend/ai-service/scripts/memory_guardian.log

边界条件：
    - Windows-only（依赖 schtasks 命令）
    - 非 Windows 环境调用循环函数将直接返回，不会报错
    - 触发失败时进入冷却期，避免刷日志

异常行为：
    - 循环中任意异常被捕获并记录，不影响下一轮检测
    - 通过 threading.Event 实现优雅停止

依赖安装：pip install psutil
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


try:
    import psutil
except ImportError:
    print("请先安装依赖: pip install psutil")
    sys.exit(1)


# ============================================================
# 默认配置常量
# ============================================================
DEFAULT_TASK_NAME = "MemoryBoost"      # Windows 计划任务名称
DEFAULT_THRESHOLD = 90.0               # 内存占用率 >= 90% 时触发
DEFAULT_RELEASE = 80.0                 # 内存回落到 80% 以下后允许再次触发
DEFAULT_INTERVAL = 5                   # 轮询间隔（秒）
DEFAULT_COOLDOWN = 120                 # 触发后冷却时间（秒）


# 日志输出路径（与脚本同目录）
LOG_FILE = Path(__file__).resolve().parent / "memory_guardian.log"


@dataclass
class GuardianConfig:
    """
    内存守护进程配置数据类

    做什么：集中承载所有运行时参数，支持从 .env/Settings 或 CLI 参数构造。
    为什么这样做：作为 SSOT 传递给循环函数，避免依赖全局变量和环境变量。
    """
    task_name: str = DEFAULT_TASK_NAME
    threshold: float = DEFAULT_THRESHOLD
    release: float = DEFAULT_RELEASE
    interval: int = DEFAULT_INTERVAL
    cooldown: int = DEFAULT_COOLDOWN


def setup_logging() -> None:
    """初始化日志系统，日志写入与脚本同目录的 memory_guardian.log"""
    log_dir = LOG_FILE.parent
    if not log_dir.exists():
        log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        encoding="utf-8",
    )


def memory_percent() -> float:
    """返回当前系统内存使用率（百分比）"""
    return float(psutil.virtual_memory().percent)


def run_task(task_name: str) -> bool:
    """
    执行 Windows 计划任务。

    做什么：调用 schtasks /run 触发指定名称的计划任务。
    为什么这样做：利用 Windows 内置的计划任务机制执行高权限内存清理，
                 避免守护进程自身需要管理员权限。

    参数：
        task_name: Windows 计划任务名称

    返回：True 表示触发成功，False 表示失败
    """
    try:
        result = subprocess.run(
            ["schtasks", "/run", "/tn", task_name],
            capture_output=True,
            text=True,
            shell=False,
        )
        if result.returncode == 0:
            logging.info(f"计划任务触发成功: {task_name}")
            return True

        logging.warning(
            f"计划任务触发失败 task={task_name} "
            f"returncode={result.returncode} "
            f"stdout={result.stdout.strip()} "
            f"stderr={result.stderr.strip()}"
        )
        return False
    except Exception as e:
        logging.exception(f"计划任务触发异常 task={task_name}: {e}")
        return False


def run_guardian_loop(
    config: GuardianConfig,
    stop_event: threading.Event | None = None,
) -> None:
    """
    内存守护进程轮询循环，可在独立线程中运行。

    做什么：持续检测系统内存使用率，超过阈值且处于布防状态时触发计划任务。
            通过 stop_event 支持外部控制停止。

    参数：
        config: GuardianConfig 配置实例
        stop_event: 可选的 threading.Event，set() 后循环优雅退出

    谁创建：app.main lifespan 的启动阶段创建线程调用此函数
    谁取消：stop_event.set() 触发、或进程退出
    谁回收：线程自然结束
    超时策略：无（持续运行的后台守护）
    重试次数：触发失败后等待冷却期再重试
    降级方案：非 Windows 环境直接 return
    """
    # 非 Windows 系统直接返回，不做任何事
    if os.name != "nt":
        logging.info("非 Windows 系统，内存守护进程不启动")
        return

    armed = True              # 是否已"布防"（允许触发）
    last_trigger_ts = 0.0     # 上次触发时间戳

    logging.info(
        f"内存守护进程循环启动: "
        f"task={config.task_name} "
        f"threshold={config.threshold:.1f}% "
        f"release={config.release:.1f}% "
        f"interval={config.interval}s "
        f"cooldown={config.cooldown}s"
    )

    while True:
        # 检查外部停止信号
        if stop_event is not None and stop_event.is_set():
            logging.info("内存守护进程收到停止信号，循环退出")
            break

        try:
            mem = memory_percent()
            now = time.time()

            # 内存回落到释放阈值以下 → 重新布防
            if mem <= config.release:
                if not armed:
                    logging.info(f"重新布防: 内存已回落至 {mem:.1f}%")
                armed = True

            # 触发条件：超过阈值 + 已布防 + 不在冷却期
            if armed and mem >= config.threshold and (now - last_trigger_ts) >= config.cooldown:
                logging.info(
                    f"触发条件满足: 当前内存 {mem:.1f}% >= 阈值 {config.threshold:.1f}%"
                )
                ok = run_task(config.task_name)
                if ok:
                    last_trigger_ts = now
                    armed = False
                else:
                    # 触发失败也进入冷却，防止疯狂刷日志
                    last_trigger_ts = now

            time.sleep(config.interval)

        except Exception as e:
            logging.exception(f"主循环异常: {e}")
            time.sleep(max(1, config.interval))


# ============================================================
# CLI 入口（单独运行时使用）
# ============================================================


def parse_args() -> argparse.Namespace:
    """
    解析 CLI 参数。

    返回：解析后的参数命名空间
    """
    parser = argparse.ArgumentParser(
        description="Luna AI 内存监控守护进程 - 监控系统内存并在超阈值时触发清理任务"
    )
    parser.add_argument(
        "--task",
        default=DEFAULT_TASK_NAME,
        help=f"Windows 计划任务名称（默认: {DEFAULT_TASK_NAME}）",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"触发阈值，内存占用率百分比（默认: {DEFAULT_THRESHOLD}）",
    )
    parser.add_argument(
        "--release",
        type=float,
        default=DEFAULT_RELEASE,
        help=f"释放阈值，低于此值后允许再次触发（默认: {DEFAULT_RELEASE}）",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"轮询间隔（秒）（默认: {DEFAULT_INTERVAL}）",
    )
    parser.add_argument(
        "--cooldown",
        type=int,
        default=DEFAULT_COOLDOWN,
        help=f"触发后冷却时间（秒）（默认: {DEFAULT_COOLDOWN}）",
    )
    return parser.parse_args()


def main() -> int:
    """
    CLI 主入口。

    做什么：解析 CLI 参数 → 构造 GuardianConfig → 启动轮询循环。
    返回：0 正常退出，2 非 Windows 环境
    """
    if os.name != "nt":
        print("memory_guardian 仅支持 Windows 系统")
        return 2

    setup_logging()
    args = parse_args()

    config = GuardianConfig(
        task_name=args.task,
        threshold=args.threshold,
        release=args.release,
        interval=args.interval,
        cooldown=args.cooldown,
    )

    print(
        f"Luna AI 内存守护进程已启动\n"
        f"  计划任务: {config.task_name}\n"
        f"  触发阈值: {config.threshold:.1f}%\n"
        f"  释放阈值: {config.release:.1f}%\n"
        f"  轮询间隔: {config.interval}s\n"
        f"  冷却时间: {config.cooldown}s\n"
        f"  日志文件: {LOG_FILE}\n"
    )

    try:
        run_guardian_loop(config)
    except KeyboardInterrupt:
        logging.info("用户手动停止内存守护进程")
        print("\n内存守护进程已停止")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
