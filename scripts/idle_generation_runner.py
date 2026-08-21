"""Background Idle Generator Runner.

Monitors system CPU utilization using `psutil`. When the system CPU has been
continuously idle (<15% utilization) for 15 minutes, it triggers a single batch
pass of `spoin.scan_and_generate` to generate cards for the next incomplete topic.

Usage:
    python scripts/idle_generation_runner.py [--idle-minutes 15] [--cpu-threshold 15] [--limit 1]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime

import psutil

# Ensure apps/api/src is on the Python path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_SRC = os.path.join(REPO_ROOT, "apps", "api", "src")
if API_SRC not in sys.path:
    sys.path.insert(0, API_SRC)

# Default to spoin_db if not set
if "SPOIN_DATABASE_URL" not in os.environ:
    os.environ["SPOIN_DATABASE_URL"] = "postgresql+asyncpg://spoin:spoin@localhost:5432/spoin_db"

from spoin.core.config import get_settings
from spoin.scan_and_generate import process_incomplete_topics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("spoin.idle_runner")


class IdleMonitor:
    def __init__(
        self,
        *,
        idle_minutes: int = 15,
        cpu_threshold: float = 15.0,
        sample_interval: float = 30.0,
        cooldown_minutes: int = 30,
        limit_per_pass: int = 1,
    ) -> None:
        self.required_idle_seconds = idle_minutes * 60.0
        self.cpu_threshold = cpu_threshold
        self.sample_interval = sample_interval
        self.cooldown_seconds = cooldown_minutes * 60.0
        self.limit_per_pass = limit_per_pass

        self.consecutive_idle_seconds = 0.0
        self.last_run_timestamp = 0.0

    async def run(self) -> None:
        logger.info(
            "Starting CPU Idle Generation Monitor: trigger after %.0fm of CPU < %.1f%% (sample every %.0fs, limit=%d/pass, cooldown=%.0fm)",
            self.required_idle_seconds / 60.0,
            self.cpu_threshold,
            self.sample_interval,
            self.limit_per_pass,
            self.cooldown_seconds / 60.0,
        )

        while True:
            # Measure CPU utilization over a 1-second sample
            cpu_usage = await asyncio.to_thread(psutil.cpu_percent, interval=1.0)
            now = time.time()
            time_since_last_run = now - self.last_run_timestamp

            if time_since_last_run < self.cooldown_seconds:
                remaining_cooldown = int((self.cooldown_seconds - time_since_last_run) / 60.0)
                logger.debug(
                    "In post-run cooldown (%dm remaining). CPU: %.1f%%",
                    remaining_cooldown,
                    cpu_usage,
                )
                self.consecutive_idle_seconds = 0.0
                await asyncio.sleep(self.sample_interval)
                continue

            if cpu_usage <= self.cpu_threshold:
                self.consecutive_idle_seconds += self.sample_interval + 1.0
                idle_mins = self.consecutive_idle_seconds / 60.0
                target_mins = self.required_idle_seconds / 60.0
                logger.info(
                    "System IDLE: CPU is %.1f%% (threshold <= %.1f%%) -- Idle for %.1f / %.1f mins",
                    cpu_usage,
                    self.cpu_threshold,
                    idle_mins,
                    target_mins,
                )

                if self.consecutive_idle_seconds >= self.required_idle_seconds:
                    logger.info(
                        "15 minutes of continuous CPU idle reached! Triggering incomplete topic scan & generation..."
                    )
                    try:
                        results = await process_incomplete_topics(limit=self.limit_per_pass)
                        logger.info("Generation pass completed with %d topic result(s).", len(results))
                    except Exception as exc:
                        logger.exception("Error executing generation pass: %s", exc)

                    self.last_run_timestamp = time.time()
                    self.consecutive_idle_seconds = 0.0
            else:
                if self.consecutive_idle_seconds > 0.0:
                    logger.info(
                        "System ACTIVE: CPU jumped to %.1f%% (> %.1f%% threshold). Resetting idle timer (was %.1fm).",
                        cpu_usage,
                        self.cpu_threshold,
                        self.consecutive_idle_seconds / 60.0,
                    )
                self.consecutive_idle_seconds = 0.0

            await asyncio.sleep(self.sample_interval)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monitor CPU idle state and trigger generation pipeline for incomplete topics."
    )
    parser.add_argument(
        "--idle-minutes",
        type=int,
        default=15,
        help="Consecutive minutes CPU must be idle to trigger generation (default: 15)",
    )
    parser.add_argument(
        "--cpu-threshold",
        type=float,
        default=15.0,
        help="Maximum CPU usage percentage to be considered idle (default: 15.0)",
    )
    parser.add_argument(
        "--sample-interval",
        type=float,
        default=30.0,
        help="Seconds between CPU samples (default: 30.0)",
    )
    parser.add_argument(
        "--cooldown-minutes",
        type=int,
        default=30,
        help="Minutes to wait after a run before resuming idle countdown (default: 30)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Maximum number of incomplete topics to process per trigger (default: 1)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    monitor = IdleMonitor(
        idle_minutes=args.idle_minutes,
        cpu_threshold=args.cpu_threshold,
        sample_interval=args.sample_interval,
        cooldown_minutes=args.cooldown_minutes,
        limit_per_pass=args.limit,
    )
    try:
        asyncio.run(monitor.run())
    except KeyboardInterrupt:
        logger.info("Idle runner stopped by user.")
