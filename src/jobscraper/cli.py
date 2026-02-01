from __future__ import annotations

import csv
import datetime as dt
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import typer
from rich.console import Console
from rich.live import Live
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table


app = typer.Typer(add_completion=False)
console = Console()


DEFAULT_SHEET_ID = ""  # pass explicitly
DEFAULT_LOG = Path("data/run_log.csv")


@dataclass
class Task:
    name: str
    kind: str  # run|watch
    interval_s: int
    cmd: List[str]
    last_run_ts: Optional[float] = None
    last_exit: Optional[int] = None
    last_summary: str = ""


STAT_RE = re.compile(r"^(?P<source>\w+):\s+scraped=(?P<scraped>\d+)\s+new=(?P<new>\d+)\s+relevant_new=(?P<relevant>\d+)", re.M)
WATCH_RE = re.compile(r"NEW relevant=(?P<count>\d+)")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _ensure_log(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "ts_utc",
                "task",
                "kind",
                "exit_code",
                "duration_s",
                "summary",
            ])


def _append_log(path: Path, row: List[str]) -> None:
    _ensure_log(path)
    with path.open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)


def _run(cmd: List[str], timeout_s: int = 600) -> Tuple[int, str]:
    """Run command and return (exit_code, stdout+stderr)."""
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, out


def _parse_summary(task: Task, output: str) -> str:
    # Try to parse main stats from run.py
    m = STAT_RE.search(output)
    if m:
        return f"scraped={m.group('scraped')} new={m.group('new')} relevant_new={m.group('relevant')}"

    # Watchers
    mw = WATCH_RE.search(output)
    if mw:
        return f"new_relevant={mw.group('count')}"

    # Otherwise short fallback
    out = " ".join((output or "").strip().split())
    return out[:160]


def _task_next_run(task: Task, now_ts: float) -> float:
    if task.last_run_ts is None:
        return now_ts
    return task.last_run_ts + task.interval_s


def _build_table(tasks: List[Task], now_ts: float) -> Table:
    table = Table(title="JobScraper Dashboard", expand=True)
    table.add_column("Task", no_wrap=True)
    table.add_column("Kind", width=6)
    table.add_column("Interval")
    table.add_column("Next")
    table.add_column("Progress")
    table.add_column("Last exit", justify="right")
    table.add_column("Last summary")

    for t in tasks:
        nxt = _task_next_run(t, now_ts)
        remaining = max(0, int(nxt - now_ts))
        interval = t.interval_s

        if interval <= 0:
            prog = 1.0
        elif t.last_run_ts is None:
            prog = 0.0
        else:
            prog = min(1.0, max(0.0, (now_ts - t.last_run_ts) / interval))

        def fmt_secs(s: int) -> str:
            if s >= 3600:
                return f"{s//3600}h{(s%3600)//60:02d}"
            if s >= 60:
                return f"{s//60}m{s%60:02d}"
            return f"{s}s"

        table.add_row(
            t.name,
            t.kind,
            fmt_secs(interval),
            "now" if remaining == 0 else fmt_secs(remaining),
            f"{int(prog*100):3d}%",
            "" if t.last_exit is None else str(t.last_exit),
            t.last_summary,
        )

    return table


@app.command()
def dashboard(
    sheet_id: str = typer.Option("", help="Google Sheet ID for Tier-1 runs (append)."),
    interval_tier1_min: int = typer.Option(20, help="Tier-1 scrape interval minutes."),
    interval_tier2_min: int = typer.Option(15, help="Tier-2 watch interval minutes."),
    log_csv: Path = typer.Option(DEFAULT_LOG, help="CSV log path."),
) -> None:
    """Live dashboard loop. Runs Tier-1 scrapers and Tier-2 watchers on schedule."""

    if not sheet_id:
        console.print("sheet_id is required (use your Jobs sheet id)")
        raise typer.Exit(2)

    tier1 = ["keejob", "welcometothejungle", "weworkremotely", "remoteok", "remotive"]
    tier2 = ["tanitjobs", "aneti"]

    # Build commands. We call modules so the CLI stays thin.
    tasks: List[Task] = []

    for s in tier1:
        tasks.append(
            Task(
                name=s,
                kind="run",
                interval_s=interval_tier1_min * 60,
                cmd=[
                    sys.executable,
                    "-m",
                    "jobscraper.run",
                    "--source",
                    s,
                    "--once",
                    "--notify",
                    "--sheet-id",
                    sheet_id,
                ],
            )
        )

    # Tier-2 watchers use CDP and ntfy directly.
    # CDP URL is currently hardcoded in run.py for ANETI run-mode; watchers take --cdp.
    cdp = os.getenv("CDP_URL", "http://172.25.192.1:9223")
    tasks.append(
        Task(
            name="tanitjobs",
            kind="watch",
            interval_s=interval_tier2_min * 60,
            cmd=[sys.executable, "-m", "jobscraper.tanitjobs_watch", "--cdp", cdp],
        )
    )
    tasks.append(
        Task(
            name="aneti",
            kind="watch",
            interval_s=interval_tier2_min * 60,
            cmd=[sys.executable, "-m", "jobscraper.aneti_watch", "--cdp", cdp],
        )
    )

    # Loop
    with Live(_build_table(tasks, time.time()), refresh_per_second=2, console=console) as live:
        while True:
            now_ts = time.time()
            ran_any = False

            for t in tasks:
                if now_ts >= _task_next_run(t, now_ts):
                    start = time.time()
                    try:
                        code, out = _run(t.cmd)
                    except subprocess.TimeoutExpired:
                        code, out = 124, "timeout"

                    dur = time.time() - start
                    t.last_run_ts = time.time()
                    t.last_exit = code
                    t.last_summary = _parse_summary(t, out)

                    _append_log(
                        log_csv,
                        [
                            _now().isoformat(timespec="seconds"),
                            t.name,
                            t.kind,
                            str(code),
                            f"{dur:.2f}",
                            t.last_summary,
                        ],
                    )

                    ran_any = True

            live.update(_build_table(tasks, time.time()))

            # Sleep lightly so the UI stays responsive.
            time.sleep(1 if ran_any else 2)


@app.command()
def run_all(sheet_id: str = typer.Argument(...), notify: bool = True) -> None:
    """Run Tier-1 sources once."""
    tier1 = ["keejob", "welcometothejungle", "weworkremotely", "remoteok", "remotive"]
    for s in tier1:
        cmd = [sys.executable, "-m", "jobscraper.run", "--source", s, "--once", "--sheet-id", sheet_id]
        if notify:
            cmd.append("--notify")
        code, out = _run(cmd)
        console.print(f"{s}: exit={code}")
        console.print(_parse_summary(Task(s, 'run', 0, []), out))


if __name__ == "__main__":
    app()
