# memory_guardian.py
# pip install psutil
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil


DEFAULT_TASK_NAME = "MemoryBoost"
DEFAULT_THRESHOLD = 90.0      # 内存占用率 >= 90% 时触发
DEFAULT_RELEASE = 80.0        # 低于这个值后，允许下一次触发
DEFAULT_INTERVAL = 5          # 轮询间隔（秒）
DEFAULT_COOLDOWN = 120        # 触发后冷却（秒）

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "memory_guardian.log"


def setup_logging() -> None:
    logging.basicConfig(
        filename=str(LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        encoding="utf-8",
    )


def memory_percent() -> float:
    return float(psutil.virtual_memory().percent)


def run_task(task_name: str) -> bool:
    """
    Run scheduled task.
    Return True if schtasks exited successfully.
    """
    try:
        result = subprocess.run(
            ["schtasks", "/run", "/tn", task_name],
            capture_output=True,
            text=True,
            shell=False,
        )
        if result.returncode == 0:
            logging.info("Triggered task: %s", task_name)
            return True

        logging.warning(
            "Failed to trigger task=%s rc=%s stdout=%r stderr=%r",
            task_name,
            result.returncode,
            result.stdout.strip(),
            result.stderr.strip(),
        )
        return False
    except Exception as e:
        logging.exception("Exception when triggering task %s: %s", task_name, e)
        return False


def main() -> int:
    if os.name != "nt":
        print("This script is Windows-only.")
        return 2

    parser = argparse.ArgumentParser(description="Memory guardian daemon")
    parser.add_argument("--task", default=DEFAULT_TASK_NAME, help="Scheduled task name")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="Trigger threshold")
    parser.add_argument("--release", type=float, default=DEFAULT_RELEASE, help="Release threshold")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="Polling interval seconds")
    parser.add_argument("--cooldown", type=int, default=DEFAULT_COOLDOWN, help="Cooldown seconds")
    args = parser.parse_args()

    setup_logging()
    logging.info(
        "Started memory guardian: task=%s threshold=%.1f release=%.1f interval=%ss cooldown=%ss",
        args.task, args.threshold, args.release, args.interval, args.cooldown
    )

    armed = True
    last_trigger_ts = 0.0

    while True:
        try:
            mem = memory_percent()
            now = time.time()

            # 允许重新布防：内存回落到 release 以下后，下一次再触发
            if mem <= args.release:
                if not armed:
                    logging.info("Re-armed at memory=%.1f%%", mem)
                armed = True

            # 触发条件：超过阈值 + 已布防 + 不在冷却期
            if armed and mem >= args.threshold and (now - last_trigger_ts) >= args.cooldown:
                logging.info("Threshold reached: memory=%.1f%% >= %.1f%%", mem, args.threshold)
                ok = run_task(args.task)
                if ok:
                    last_trigger_ts = now
                    armed = False
                else:
                    # 触发失败时也稍微冷却一下，避免疯狂刷日志
                    last_trigger_ts = now

            time.sleep(args.interval)

        except KeyboardInterrupt:
            logging.info("Stopped by user.")
            return 0
        except Exception as e:
            logging.exception("Loop error: %s", e)
            time.sleep(max(1, args.interval))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())