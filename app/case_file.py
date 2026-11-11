"""The case file: Disha's working memory for one call, mirrored live to the UI."""

from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30), name="IST")

MAX_ACTIVITY_ITEMS = 60


def now_ist() -> datetime:
    return datetime.now(IST)


def new_reference(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(3).upper()}"


@dataclass
class CaseFile:
    case_id: str
    mode: str
    language: str
    started_at: str
    previous_case_id: str | None = None
    diagnosis: dict[str, Any] | None = None
    progress: dict[str, Any] | None = None
    restock_plan: dict[str, Any] | None = None
    insights: list[dict[str, Any]] = field(default_factory=list)
    action_plan: list[dict[str, Any]] = field(default_factory=list)
    kpi_targets: list[str] = field(default_factory=list)
    actions_taken: list[dict[str, Any]] = field(default_factory=list)
    follow_up: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    activity: list[dict[str, Any]] = field(default_factory=list)
    call_ending: bool = False

    @classmethod
    def open(cls, *, mode: str, language: str, previous_case_id: str | None = None) -> CaseFile:
        return cls(
            case_id=new_reference("CASE"),
            mode=mode,
            language=language,
            started_at=now_ist().isoformat(timespec="seconds"),
            previous_case_id=previous_case_id,
        )

    def log_activity(self, tool: str, label: str, args: dict[str, Any], ok: bool) -> None:
        self.activity.append(
            {
                "tool": tool,
                "label": label,
                "args": args,
                "ok": ok,
                "at": now_ist().strftime("%H:%M:%S"),
            }
        )
        del self.activity[:-MAX_ACTIVITY_ITEMS]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
