from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import List, Sequence

from .models import Job
from .filtering import decision_for_title, match_labels


@dataclass
class SheetsConfig:
    sheet_id: str
    tab: str = "Jobs"
    account: str = "wassimfekih2@gmail.com"


def _run_gog(args: List[str]) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"gog failed: {' '.join(args)}\n{proc.stderr}\n{proc.stdout}")


def ensure_jobs_header(cfg: SheetsConfig) -> None:
    # Legacy sheet schema (kept for compatibility with existing Jobs tab data):
    # A: source
    # B: labels
    # C: title
    # D: company
    # E: location
    # F: date_added
    # G: url
    # H: decision
    # I: notes
    values = [[
        "source",
        "labels",
        "title",
        "company",
        "location",
        "date_added",
        "url",
        "decision",
        "notes",
    ]]
    _run_gog(
        [
            "gog",
            "sheets",
            "update",
            cfg.sheet_id,
            f"{cfg.tab}!A1:I1",
            "--account",
            cfg.account,
            "--values-json",
            json.dumps(values, ensure_ascii=False),
            "--input",
            "USER_ENTERED",
        ]
    )


def append_jobs(cfg: SheetsConfig, jobs: Sequence[Job], date_label: str) -> None:
    if not jobs:
        return

    rows = []
    for j in jobs:
        labels = ",".join(match_labels(j.title))
        decision = decision_for_title(j.title)
        rows.append([j.source, labels, j.title, j.company, j.location, date_label, j.url, decision, ""]) 

    _run_gog(
        [
            "gog",
            "sheets",
            "append",
            cfg.sheet_id,
            f"{cfg.tab}!A:I",
            "--account",
            cfg.account,
            "--values-json",
            json.dumps(rows, ensure_ascii=False),
            "--insert",
            "INSERT_ROWS",
        ]
    )
