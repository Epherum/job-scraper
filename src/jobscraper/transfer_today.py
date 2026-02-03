from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import List


@dataclass
class TransferConfig:
    sheet_id: str
    from_tab: str = "Jobs_Today"
    to_tab: str = "Jobs"
    account: str = "wassimfekih2@gmail.com"
    # Keep range wide enough for our current Jobs schema (A:I)
    range_cols: str = "A:I"


def _run_gog(args: List[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"gog failed: {' '.join(args)}\n{proc.stderr}\n{proc.stdout}")
    return proc.stdout


def fetch_rows(cfg: TransferConfig) -> list[list[str]]:
    out = _run_gog(
        [
            "gog",
            "sheets",
            "get",
            cfg.sheet_id,
            f"{cfg.from_tab}!{cfg.range_cols}",
            "--account",
            cfg.account,
            "--json",
        ]
    )
    data = json.loads(out)
    values = data.get("values") or []

    # values includes header row at index 0 if present
    if not values or len(values) <= 1:
        return []

    rows = values[1:]
    # normalize row length to 9 cols
    norm: list[list[str]] = []
    for r in rows:
        r = list(r)
        if len(r) < 9:
            r = r + [""] * (9 - len(r))
        norm.append(r[:9])
    return norm


def _fetch_preview(cfg: TransferConfig, tab: str, n_rows: int = 3) -> list[list[str]]:
    out = _run_gog(
        [
            "gog",
            "sheets",
            "get",
            cfg.sheet_id,
            f"{tab}!A1:I{n_rows}",
            "--account",
            cfg.account,
            "--json",
        ]
    )
    data = json.loads(out)
    return data.get("values") or []


def _looks_like_source(v: str) -> bool:
    return (v or "").strip().lower() in {
        "keejob",
        "welcometothejungle",
        "weworkremotely",
        "remoteok",
        "remotive",
        "tanitjobs",
        "aneti",
        "rss",
        "test",
    }


def _to_tab_expects_legacy_order(cfg: TransferConfig) -> bool:
    """Detect whether the destination tab (Jobs) uses the legacy column order.

    Current source tab (Jobs_Today) schema is:
      [date_added, source, title, company, location, url, labels, decision, notes]

    Older Jobs tab in your sheet historically used:
      [source, labels, title, company, location, date_added, url, decision, notes]

    We infer this from the first data row, since the header row may be stale.
    """

    preview = _fetch_preview(cfg, cfg.to_tab, n_rows=3)
    if len(preview) < 2:
        return False

    first = preview[1]
    first = first + [""] * (9 - len(first))

    # If the first cell of the first data row looks like a source name,
    # then the tab is in legacy order.
    return _looks_like_source(first[0])


def _reorder_for_legacy(rows: list[list[str]]) -> list[list[str]]:
    out: list[list[str]] = []
    for r in rows:
        r = r + [""] * (9 - len(r))
        date_added, source, title, company, location, url, labels, decision, notes = r[:9]
        out.append([source, labels, title, company, location, date_added, url, decision, notes])
    return out


def append_rows(cfg: TransferConfig, rows: list[list[str]]) -> int:
    if not rows:
        return 0

    # Best effort compatibility: if Jobs is in legacy order, map rows before append.
    if _to_tab_expects_legacy_order(cfg):
        rows = _reorder_for_legacy(rows)

    _run_gog(
        [
            "gog",
            "sheets",
            "append",
            cfg.sheet_id,
            f"{cfg.to_tab}!{cfg.range_cols}",
            "--account",
            cfg.account,
            "--values-json",
            json.dumps(rows, ensure_ascii=False),
            "--insert",
            "INSERT_ROWS",
        ]
    )
    return len(rows)


def clear_from(cfg: TransferConfig) -> None:
    _run_gog(["gog", "sheets", "clear", cfg.sheet_id, f"{cfg.from_tab}!A2:Z", "--account", cfg.account])


def transfer_today(cfg: TransferConfig) -> int:
    rows = fetch_rows(cfg)
    n = append_rows(cfg, rows)
    if n:
        clear_from(cfg)
    return n
