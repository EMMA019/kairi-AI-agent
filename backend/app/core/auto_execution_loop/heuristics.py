import json
import re
import asyncio
import uuid
import time
from typing import AsyncGenerator, Optional
from datetime import datetime
from pathlib import Path
from app.utils.logger import get_logger

logger = get_logger(__name__)

# エラーパターン検出用の正規表現
ERROR_PATTERNS = [
    re.compile(r'(Error|Exception|Traceback|Failed|SyntaxError|ImportError|ModuleNotFoundError)', re.IGNORECASE),
    re.compile(r'(errno|exit code [1-9]|non-zero|returned 1)', re.IGNORECASE),
    re.compile(r'(not found|No such|does not exist|cannot find|unable to resolve)', re.IGNORECASE),
    re.compile(r'(permission denied|access denied|EACCES|EACCESS)', re.IGNORECASE),
    re.compile(r'(timeout|timed out|connection refused|connection reset)', re.IGNORECASE),
]

# 誤検出（偽陽性）を除外するためのパターン
IGNORE_ERROR_PATTERNS = [
    re.compile(r'(npm warn|npm notice|deprecation|deprecated|SKIPPING|skipped|nothing to commit|0 vulnerabilities|no such file or directory, open \'.*package-lock\.json\')', re.IGNORECASE),
    re.compile(r'(\b0 failed\b)', re.IGNORECASE),
]

# 成功パターン（明示的に成功を示す）
SUCCESS_PATTERNS = [
    re.compile(r'(success|completed|installed|created|updated|deleted)', re.IGNORECASE),
    re.compile(r'(\b[1-9]\d*\s+passed\b|100%|all good|build success)', re.IGNORECASE),
]

def _detect_test_failure(tool_result: str) -> Optional[dict]:
    """テスト結果を構造化して解析（pytest, jest, go test, npm test等対応）"""
    if not tool_result:
        return None
        
    # pytest / unittest
    if "passed" in tool_result.lower() or "failed" in tool_result.lower() or "error" in tool_result.lower():
        passed_m = re.search(r'(\d+)\s+passed', tool_result, re.IGNORECASE)
        failed_m = re.search(r'(\d+)\s+failed', tool_result, re.IGNORECASE)
        error_m = re.search(r'(\d+)\s+error', tool_result, re.IGNORECASE)
        
        passed = int(passed_m.group(1)) if passed_m else 0
        failed = int(failed_m.group(1)) if failed_m else 0
        errors = int(error_m.group(1)) if error_m else 0
        
        if passed > 0 or failed > 0 or errors > 0:
            success = (failed == 0 and errors == 0 and passed > 0)
            return {
                "framework": "pytest",
                "passed": passed,
                "failed": failed + errors,
                "success": success,
                "summary": f"Pytest: {passed} passed, {failed+errors} failed/error"
            }
            
    # Jest / Vitest
    m = re.search(r'Tests:\s*(?:(\d+)\s+failed,\s*)?(\d+)\s+passed', tool_result, re.IGNORECASE)
    if m:
        failed = int(m.group(1) or 0)
        passed = int(m.group(2))
        return {"framework": "jest", "passed": passed, "failed": failed, "success": failed == 0, "summary": f"Jest: {passed} passed, {failed} failed"}
        
    # Go test
    if "--- FAIL:" in tool_result or "FAIL\t" in tool_result:
        return {"framework": "gotest", "passed": 0, "failed": 1, "success": False, "summary": "Go test: FAIL detected"}
    if "--- PASS:" in tool_result or "ok\t" in tool_result:
        return {"framework": "gotest", "passed": 1, "failed": 0, "success": True, "summary": "Go test: PASS detected"}
        
    return None


def _detect_error(tool_result: str) -> Optional[str]:
    """ツール実行結果からエラーを検出"""
    if not tool_result or len(tool_result.strip()) < 5:
        return None
        
    # テスト失敗の専用チェック
    test_info = _detect_test_failure(tool_result)
    if test_info and not test_info["success"]:
        return f"【テスト失敗】{test_info['summary']}\n" + tool_result[-1500:]
    
    # 除外パターンのチェック（警告や正常な情報メッセージなど）
    # 全体が除外パターンだけにマッチする場合はエラーとしない
    lines = tool_result.split('\n')
    error_lines = []
    
    for i, line in enumerate(lines):
        # 除外パターンが含まれている行はエラー判定をスキップ
        if any(ignore_p.search(line) for ignore_p in IGNORE_ERROR_PATTERNS):
            continue
        for pattern in ERROR_PATTERNS:
            if pattern.search(line):
                start = max(0, i - 3)
                end = min(len(lines), i + 4)
                error_lines.extend(lines[start:end])
                error_lines.append('---')
                break
                
    if error_lines:
        context = '\n'.join(error_lines[-50:])  # 最大50行
        return context
    
    return None


def _detect_success(tool_result: str) -> bool:
    """ツール実行結果が成功を示しているかチェック"""
    if not tool_result:
        return False
        
    test_info = _detect_test_failure(tool_result)
    if test_info:
        return test_info["success"]
    
    # 明らかなエラーがある場合は成功とみなさない
    if _detect_error(tool_result):
        if 'warning' in tool_result.lower() and not any(k in tool_result.lower() for k in ['error', 'failed', 'exception']):
            pass
        else:
            return False
    
    # 成功パターンをチェック
    for pattern in SUCCESS_PATTERNS:
        if pattern.search(tool_result):
            return True
    
    return True  # エラーがなければ一応成功扱い


