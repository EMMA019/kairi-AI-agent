"""Track B: acceptance checker + incomplete done.ok + lab heuristics."""
from pathlib import Path

from app.core.acceptance_checker import (
    detect_project_hint,
    format_incomplete_banner,
    parse_acceptance_markdown,
    programming_lab_items,
    response_marks_incomplete,
    run_acceptance_checks,
)
from app.core.completion_status import build_done_payload, response_ok


def test_parse_acceptance_checkboxes():
    md = """
## Acceptance
- [ ] スター永続化
- [x] already done
- [ ] ミッションが3本以上
"""
    items = parse_acceptance_markdown(md)
    assert len(items) >= 2
    assert any("star" in i.id or "スター" in i.description for i in items)


def test_programming_lab_heuristics_fail_on_current_lab(tmp_path: Path):
    """Current MVP without stars/missions/sandbox fails lab acceptance."""
    root = tmp_path / "programming-lab"
    (root / "src").mkdir(parents=True)
    (root / "package.json").write_text(
        '{"name":"programming-lab","version":"0.0.0"}', encoding="utf-8"
    )
    (root / "src" / "App.tsx").write_text(
        'export default function App(){ setMission(DEFAULT_MISSION); return <div>たのしいプログラミングラボ</div> }',
        encoding="utf-8",
    )
    (root / "src" / "missions.ts").write_text(
        'export const DEFAULT_MISSION = { id: "m1", title: "a", gridSize: 6, '
        'start:{x:0,y:0}, goal:{x:1,y:1}, obstacles:[{x:2,y:2}] };\n',
        encoding="utf-8",
    )
    (root / "src" / "engine.ts").write_text("export function executeBlocks(){}", encoding="utf-8")

    assert detect_project_hint(root) == "programming-lab"
    report = run_acceptance_checks(root)
    assert report.results
    assert not report.passed
    failed = {r.id for r in report.failed}
    assert "stars_persist_or_increment" in failed
    assert "missions_gte_3" in failed
    assert "sandbox_distinct" in failed
    assert "engine_exists" not in failed  # engine.ts present


def test_programming_lab_heuristics_pass_when_wired(tmp_path: Path):
    root = tmp_path / "lab"
    (root / "src").mkdir(parents=True)
    (root / "package.json").write_text('{"name":"programming-lab"}', encoding="utf-8")
    (root / "src" / "App.tsx").write_text(
        "const SANDBOX_MISSION = { obstacles: [] };\n"
        "localStorage.setItem('stars', String(stars + 1));\n"
        "setStars(starCount);\n",
        encoding="utf-8",
    )
    (root / "src" / "missions.ts").write_text(
        "export const MISSIONS = [\n"
        " { id: 'm1', title: 'a', gridSize: 6 },\n"
        " { id: 'm2', title: 'b', gridSize: 6 },\n"
        " { id: 'm3', title: 'c', gridSize: 6 },\n"
        "];\n",
        encoding="utf-8",
    )
    (root / "src" / "engine.ts").write_text("// ok", encoding="utf-8")
    report = run_acceptance_checks(root)
    assert report.passed, report.to_dict()


def test_incomplete_marker_forces_done_not_ok():
    text = "途中までできました\n\n*(⚠️ 完了ゲート未達・Acceptance NG: stars)*"
    assert response_marks_incomplete(text)
    assert response_ok(text) is False
    payload = build_done_payload(text, "作って")
    assert payload["ok"] is False
    assert payload.get("incomplete") is True


def test_format_incomplete_banner():
    from app.core.acceptance_checker import AcceptanceReport, AcceptanceResult

    rep = AcceptanceReport(
        results=[
            AcceptanceResult("stars", "stars", False, "missing"),
        ]
    )
    banner = format_incomplete_banner(rep, {"success": False, "exit_code": 1}, hit_loop_cap=True)
    assert "完了ゲート未達" in banner
    assert "続きを作成して" in banner


def test_lab_builtin_item_count():
    assert len(programming_lab_items()) >= 3


def test_japanese_acceptance_maps_to_code_evidence_not_prose_grep(tmp_path: Path):
    """日本語 Acceptance を原文 grep せず、コード証拠で判定する。"""
    root = tmp_path / "ibkr_autotrader"
    root.mkdir()
    (root / "config.yaml").write_text(
        "dry_run: true\nconnection:\n  host: 127.0.0.1\n  port: 7497\n"
        "scanner:\n  scan_code: TOP_PER_CENT_GAIN\n  location_code: STK.US\n"
        "order:\n  max_positions: 5\n  take_profit_dollars: 2.0\n  stop_loss_dollars: 1.0\n",
        encoding="utf-8",
    )
    (root / "main.py").write_text(
        "import sys\n"
        "from ib_insync import IB\n"
        "def connect(ib):\n"
        "    try:\n"
        "        ib.connect('127.0.0.1', 7497)\n"
        "    except Exception:\n"
        "        print('TWS/Gateway 接続できません')\n"
        "        sys.exit(1)\n"
        "    if not ib.isConnected():\n"
        "        sys.exit(1)\n",
        encoding="utf-8",
    )
    (root / "scanner.py").write_text(
        "from ib_insync import ScannerSubscription\n"
        "sub = ScannerSubscription()\n"
        "sub.scanCode = 'TOP_PER_CENT_GAIN'\n"
        "sub.locationCode = 'STK.US'\n"
        "ib.reqScannerData(sub)\n",
        encoding="utf-8",
    )
    (root / "strategy.py").write_text(
        "def filter_uptrend(ib, contracts):\n"
        "    sma_fast = 20\n"
        "    sma_slow = 50\n"
        "    return []\n"
        "def _sma(closes, period): return sum(closes[-period:]) / period\n",
        encoding="utf-8",
    )
    (root / "order_manager.py").write_text(
        "dry_run = True\n"
        "print('[DRY_RUN] 発注予定 Bracket')\n"
        "take_profit = 2.0\n"
        "stop_loss = 1.0\n"
        "max_positions = 5\n"
        "from ib_insync import MarketOrder, StopOrder\n",
        encoding="utf-8",
    )
    (root / "logger.py").write_text(
        "import json\n"
        "def log_event(event, data):\n"
        "    open('execution.jsonl','a').write(json.dumps({'event': event})+'\\n')\n",
        encoding="utf-8",
    )
    (root / "ACCEPTANCE.md").write_text(
        "## Acceptance\n"
        "- [ ] TWS/Gateway未接続時に明確なエラーメッセージを出して終了する\n"
        "- [ ] スキャナーで米国株上位50銘柄（STK.US / TOP_PER_CENT_GAIN）を取得できる\n"
        "- [ ] SMA20 > SMA50 の銘柄のみに絞り込める\n"
        "- [ ] dry_run=true 時は注文を一切出さず、発注予定ログのみ出力する\n"
        "- [ ] dry_run=false 時は成行買い+利確(+$2.00)/損切(-$1.00)のBracket注文を発注する\n"
        "- [ ] 同時ポジション数が max_positions を超えない\n"
        "- [ ] 全パラメータを config.yaml で変更できる\n"
        "- [ ] 実行ログが JSONL で出力される\n",
        encoding="utf-8",
    )

    assert detect_project_hint(root) == "ibkr-python"
    report = run_acceptance_checks(root)
    assert report.project_hint == "ibkr-python"
    # lab 混入なし
    assert "スター常時0" not in report.format_for_agent()
    assert "missions_gte_3" not in {r.id for r in report.results}
    assert report.passed, report.to_dict()


def test_lab_advice_not_injected_for_non_lab():
    from app.core.acceptance_checker import AcceptanceReport, AcceptanceResult

    rep = AcceptanceReport(
        project_hint="ibkr-python",
        results=[AcceptanceResult("x", "x", False, "missing")],
    )
    text = rep.format_for_agent()
    assert "未達項目" in text
    assert "スター常時0" not in text
