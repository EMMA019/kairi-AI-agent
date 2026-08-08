"""Workspace GUI strengthen: open/status/changes/discard/spec (unit, no auth)."""
import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core import workspace_state
from app.routers import workspace as ws


@pytest.fixture()
def proj(tmp_path: Path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "package.json").write_text('{"name":"demo"}', encoding="utf-8")
    (root / "hello.txt").write_text("hi\n", encoding="utf-8")

    monkeypatch.setattr(ws, "ROOT_OUTPUT_DIR", root)
    monkeypatch.setattr(ws, "_WORKSPACE_ROOT_FILE", tmp_path / "workspace_root.txt")
    ws.set_workspace_path(str(root), persist=False)
    workspace_state.clear_all_changes()
    return root


def test_workspace_status(proj: Path):
    data = ws._workspace_status()
    assert Path(data["root"]) == proj.resolve()
    assert "Node.js" in data["project_type"] or "JavaScript" in data["project_type"]


def test_workspace_open(proj: Path, tmp_path: Path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "requirements.txt").write_text("fastapi\n", encoding="utf-8")

    async def _run():
        return await ws.open_workspace(ws.OpenWorkspaceRequest(path=str(other)))

    data = asyncio.run(_run())
    assert Path(data["root"]) == other.resolve()
    assert "Python" in data["project_type"]
    assert (tmp_path / "workspace_root.txt").read_text(encoding="utf-8") == str(other.resolve())


def test_open_rejects_missing(proj: Path):
    with pytest.raises(HTTPException) as ei:
        ws._validate_open_path(str(proj / "missing-dir"))
    assert ei.value.status_code == 400


def test_changes_and_discard(proj: Path):
    workspace_state.record_change("hello.txt", "hi\n", "bye\n", "write")
    (proj / "hello.txt").write_text("bye\n", encoding="utf-8")
    assert len(workspace_state.list_changes()) == 1

    async def _run():
        return await ws.discard_change(ws.DiscardRequest(path="hello.txt"))

    data = asyncio.run(_run())
    assert data["action"] == "restored"
    assert (proj / "hello.txt").read_text(encoding="utf-8") == "hi\n"
    assert workspace_state.list_changes() == []


def test_save_spec(proj: Path):
    async def _run():
        return await ws.save_spec(ws.SaveSpecRequest(content="# Spec\n\nHello", filename="SPEC.md"))

    data = asyncio.run(_run())
    assert data["path"] == "SPEC.md"
    assert (proj / "SPEC.md").read_text(encoding="utf-8") == "# Spec\n\nHello"
