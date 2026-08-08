"""In-memory workspace change / activity log for IDE panels."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Deque, List, Optional

_lock = Lock()
_MAX = 80


@dataclass
class WorkspaceChange:
    path: str
    before: str
    after: str
    op: str
    ts: float


@dataclass
class WorkspaceActivity:
    kind: str
    detail: str
    ts: float


_changes: Deque[WorkspaceChange] = deque(maxlen=_MAX)
_activity: Deque[WorkspaceActivity] = deque(maxlen=_MAX)


def record_change(path: str, before: str, after: str, op: str = "write") -> None:
    with _lock:
        # replace older entry for same path
        existing = [c for c in _changes if c.path != path]
        _changes.clear()
        _changes.extend(existing)
        _changes.append(
            WorkspaceChange(
                path=path,
                before=before or "",
                after=after or "",
                op=op,
                ts=time.time(),
            )
        )
    record_activity(op, path)


def record_activity(kind: str, detail: str) -> None:
    with _lock:
        _activity.append(WorkspaceActivity(kind=kind, detail=detail, ts=time.time()))


def list_changes() -> List[dict]:
    with _lock:
        return [asdict(c) for c in list(_changes)]


def list_activity(limit: int = 40) -> List[dict]:
    with _lock:
        items = list(_activity)[-limit:]
        return [asdict(a) for a in items]


def pop_change(path: str) -> Optional[WorkspaceChange]:
    with _lock:
        found = None
        kept: List[WorkspaceChange] = []
        for c in _changes:
            if c.path == path and found is None:
                found = c
            else:
                kept.append(c)
        _changes.clear()
        _changes.extend(kept)
        return found


def clear_change(path: str) -> bool:
    return pop_change(path) is not None


def clear_all_changes() -> None:
    with _lock:
        _changes.clear()
