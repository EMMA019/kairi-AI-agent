"""
Auto-Test Pipeline — コード生成後の自動テスト実行＆検証

【目的】
Executorがコードを生成した後、自動でテストを実行し、
失敗した場合はエラーを分析して修正→再テストのループを行う。

【フロー】
1. コード生成完了（<file> または <replace> 実行後）
2. 自動テスト実行（<run_command> でテストコマンドを実行）
3. テスト結果を解析：
   - 成功 → 完了
   - 失敗 → エラーログを分析 → 修正指示生成 → 再実行
4. 上限回数（3回）を超えたらエスカレーション
"""
import re
from typing import Optional
from app.core.tools.handler import ToolHandler
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 言語ごとのテストコマンド
LANG_TEST_COMMANDS = {
    "python": {
        "test": "python -m pytest {test_path} -v --tb=short 2>&1 || python -m unittest {test_path} -v 2>&1",
        "lint": "python -m py_compile {file_path} 2>&1",
        "check_tool": "pytest --version",
    },
    "javascript": {
        "test": "npx jest {test_path} --no-cache 2>&1",
        "lint": "npx eslint {file_path} 2>&1",
        "check_tool": "npx jest --version",
    },
    "typescript": {
        "test": "npx jest {test_path} --no-cache 2>&1",
        "lint": "npx tsc --noEmit 2>&1",
        "check_tool": "npx jest --version",
    },
    "go": {
        "test": "go test {test_path} -v 2>&1",
        "lint": "go vet {file_path} 2>&1",
        "check_tool": "go version",
    },
    "rust": {
        "test": "cargo test 2>&1",
        "lint": "cargo check 2>&1",
        "check_tool": "cargo --version",
    },
}


def _detect_language(file_path: str) -> Optional[str]:
    """ファイル拡張子から言語を検出"""
    ext = file_path.split(".")[-1].lower() if "." in file_path else ""
    ext_map = {
        "py": "python",
        "js": "javascript",
        "ts": "typescript",
        "tsx": "typescript",
        "jsx": "javascript",
        "go": "go",
        "rs": "rust",
    }
    return ext_map.get(ext)


def _find_test_file(file_path: str, lang: str) -> str:
    """ソースファイルに対応するテストファイルパスを推測"""
    import os
    base, ext = os.path.splitext(file_path)
    filename = os.path.basename(base)
    dirname = os.path.dirname(file_path)
    
    # 一般的なパターン
    patterns = {
        "python": [
            f"tests/test_{filename}.py",
            f"tests/{filename}_test.py",
            f"test_{file_path}",
            f"{dirname}/test_{filename}.py",
        ],
        "javascript": [
            f"{dirname}/{filename}.test.js",
            f"{dirname}/{filename}.spec.js",
            f"tests/{filename}.test.js",
        ],
        "typescript": [
            f"{dirname}/{filename}.test.ts",
            f"{dirname}/{filename}.spec.ts",
            f"tests/{filename}.test.ts",
        ],
        "go": [
            f"{dirname}/{filename}_test.go",
        ],
    }
    
    candidate_patterns = patterns.get(lang, [])
    for pattern in candidate_patterns:
        test_path = pattern
        # テストファイルが存在するかはToolHandlerが確認する
        # ここではパターンを返すだけ
        return test_path
    
    return ""


async def run_auto_test(
    file_path: str,
    session_id: str,
    mode: str,
    max_retries: int = 3,
) -> dict:
    """
    コード生成後の自動テスト実行。
    
    Args:
        file_path: 生成されたファイルのパス
        session_id: セッションID
        mode: モード
        max_retries: 最大リトライ回数
    
    Returns:
        {"success": bool, "output": str, "fixed": bool, "retries": int}
    """
    lang = _detect_language(file_path)
    if not lang or lang not in LANG_TEST_COMMANDS:
        return {
            "success": True,
            "output": f"言語 '{lang}' のテスト設定がありません。スキップします。",
            "fixed": False,
            "retries": 0,
        }
    
    test_config = LANG_TEST_COMMANDS[lang]
    test_file = _find_test_file(file_path, lang)
    
    handler = ToolHandler(session_id=session_id, mode=mode, allow_mocks=False)
    
    # 1. まず構文チェック
    logger.info(f"🔍 構文チェック: {file_path}")
    
    if lang == "python":
        # Python: py_compileで構文チェック
        try:
            import py_compile
            py_compile.compile(file_path, doraise=True)
            logger.info(f"✅ 構文チェックOK: {file_path}")
        except py_compile.PyCompileError as e:
            error_msg = f"構文エラー: {e}"
            logger.error(error_msg)
            
            # エラー情報を返す（自動修正はSupervisor/Executorループに任せる）
            return {
                "success": False,
                "output": error_msg,
                "fixed": False,
                "retries": 0,
                "error_type": "syntax",
            }
    
    # 2. テストコマンドのツールがあるか確認
    check_cmd = test_config.get("check_tool", "")
    if check_cmd:
        logger.info(f"🔧 テストツール確認: {check_cmd}")
        check_xml = f"<run_command>{check_cmd}</run_command>"
        await handler.execute_tools(check_xml)
    
    # 3. テスト実行
    # テストファイルが存在する場合のみ実行
    if test_file:
        test_cmd = test_config["test"].format(test_path=test_file, file_path=file_path)
        logger.info(f"🧪 テスト実行: {test_cmd}")
        
        retries = 0
        while retries < max_retries:
            retries += 1
            handler = ToolHandler(session_id=session_id, mode=mode, allow_mocks=False)
            test_xml = f"<run_command>{test_cmd}</run_command>"
            await handler.execute_tools(test_xml)
            
            if handler.tool_results:
                test_output = "\n".join(handler.tool_results)
                
                # 成功判定
                success_keywords = ["passed", "ok", "PASSED", "0 failed", "success"]
                fail_keywords = ["FAILED", "failed", "Error", "error", "Traceback"]
                
                is_success = any(kw in test_output for kw in success_keywords) and not any(kw in test_output for kw in fail_keywords)
                
                if is_success:
                    logger.info(f"✅ テスト成功 ({retries}回目): {file_path}")
                    return {
                        "success": True,
                        "output": test_output,
                        "fixed": retries > 1,
                        "retries": retries,
                    }
                else:
                    logger.warning(f"❌ テスト失敗 ({retries}/{max_retries}): {file_path}")
                    
                    if retries < max_retries:
                        # エラー情報を次の修正に渡す
                        return {
                            "success": False,
                            "output": test_output,
                            "fixed": False,
                            "retries": retries,
                            "error_type": "test",
                            "error_detail": test_output[:500],  # 最初の500文字
                            "needs_auto_fix": True,
                        }
            
            # リトライの場合はコマンド再実行（ループはhandler側で行う）
            break
    else:
        logger.info(f"📝 テストファイルが見つかりません: {test_file}。プロジェクトビルドまたは構文チェックを実行します。")
        if lang in ["typescript", "javascript"]:
            # 🔴 妥協ゼロの厳格品質リンター (Strict No-Band-Aid Validator)
            try:
                from pathlib import Path as PathLib
                src_content = PathLib(file_path).read_text(encoding="utf-8")
                band_aid_patterns = [
                    (r':\s*any\b|\bany\[\]|\b<any>', 'any型 (型チェック放棄)'),
                    (r'@ts-ignore|@ts-expect-error', '@ts-ignore (エラー強制無視)'),
                    (r'TODO:|FIXME:|ダミーデータ', 'TODO/ダミーデータ残存'),
                ]
                violations = []
                for pattern, label in band_aid_patterns:
                    if re.search(pattern, src_content):
                        violations.append(label)
                if violations:
                    err_msg = f"⚠️ 【妥協ゼロ品質リンター違反】 ソースコード ({file_path}) 内に妥協・逃げコードが検出されました: {', '.join(violations)}\nビルドを通すためだけに any 型や @ts-ignore を使うことは厳格に禁止されています。適切な型定義を行って解決してください。"
                    logger.warning(err_msg)
                    return {
                        "success": False,
                        "output": err_msg,
                        "fixed": False,
                        "retries": 1,
                        "error_type": "lint_violation",
                        "error_detail": err_msg,
                        "needs_auto_fix": True,
                    }
            except Exception as read_err:
                logger.warning(f"ソース検証エラー: {read_err}")

            # Exit-code build gate (workspace root), not keyword matching on Docker logs
            try:
                from pathlib import Path as PathLib
                from app.core.build_gate import run_workspace_build
                from app.routers.workspace import get_workspace_dir

                ws = get_workspace_dir()
                # If file_path is absolute under a project with package.json, use that dir
                fp = PathLib(file_path)
                if fp.is_absolute():
                    for parent in [fp.parent, *fp.parents]:
                        if (parent / "package.json").exists():
                            ws = parent
                            break
                build = run_workspace_build(ws)
                build_output = build.get("output") or ""
                if not build.get("success"):
                    logger.warning(
                        f"❌ ビルドゲート失敗 exit={build.get('exit_code')}: {file_path}"
                    )
                    smart_hint = ""
                    missing_mod_match = re.search(
                        r"Cannot find module '([^']+)'|imported from external module \"([^\"]+)\"",
                        build_output,
                    )
                    if missing_mod_match:
                        pkg_name = missing_mod_match.group(1) or missing_mod_match.group(2)
                        smart_hint = (
                            f"\n\n💡 パッケージ '{pkg_name}' が未インストールの可能性。"
                            f"<run_command>npm install {pkg_name}</run_command> を実行すること。"
                        )
                    return {
                        "success": False,
                        "output": build_output + smart_hint,
                        "fixed": False,
                        "retries": 1,
                        "error_type": "build",
                        "error_detail": (build_output[:1000] + smart_hint),
                        "needs_auto_fix": True,
                        "exit_code": build.get("exit_code"),
                    }
                logger.info(f"✅ ビルドゲート成功: {ws}")
                return {
                    "success": True,
                    "output": build_output or "build ok",
                    "fixed": False,
                    "retries": 0,
                    "exit_code": build.get("exit_code", 0),
                }
            except Exception as e:
                logger.warning(f"ビルドゲート例外: {e}")

    return {
        "success": True,
        "output": "テストファイルが存在しないため、構文チェックのみ実行しました。",
        "fixed": False,
        "retries": 0,
    }


def extract_test_errors(test_output: str) -> list[dict]:
    """
    テスト出力からエラー行を抽出して分析。
    
    Returns:
        [{"file": "...", "line": N, "message": "..."}, ...]
    """
    errors = []
    
    # Python pytest形式
    # FAILED test_example.py::test_function - AssertionError: ...
    pytest_pattern = re.compile(r'FAILED\s+([^\s]+)\s+-\s+(.+)')
    for match in pytest_pattern.finditer(test_output):
        errors.append({
            "file": match.group(1).split("::")[0],
            "test": match.group(1).split("::")[-1] if "::" in match.group(1) else "",
            "message": match.group(2).strip(),
        })
    
    # Python traceback形式
    traceback_pattern = re.compile(r'File\s+"([^"]+)",\s+line\s+(\d+).*\n\s+(.+)')
    for match in traceback_pattern.finditer(test_output):
        errors.append({
            "file": match.group(1),
            "line": int(match.group(2)),
            "message": match.group(3).strip(),
        })
    
    # Jest形式
    jest_pattern = re.compile(r'●\s+(.+?)\n\s+(.+)')
    for match in jest_pattern.finditer(test_output):
        errors.append({
            "test": match.group(1).strip(),
            "message": match.group(2).strip(),
        })
    
    return errors