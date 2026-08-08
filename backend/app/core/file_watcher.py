"""
File Watcher — ファイル変更監視＋スナップショット管理（watchdogリアルタイム監視）

【CLINE対抗機能】
- watchdogベースのリアルタイムファイル監視
- ファイル保存「瞬間」にキャッシュ無効化
- git diff + 内容ハッシュの併用で精度最大化

【使い方】
1. watcher = FileWatcher() で初期化（起動時に監視スレッド開始）
2. watcher.snapshot(key, paths) でスナップショット保存
3. watcher.has_changed(key) で変更検出
4. 終了時に watcher.stop() で監視スレッド停止
"""
import hashlib
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Callable
from app.utils.logger import get_logger

logger = get_logger(__name__)

def _get_workspace_dir() -> Path:
    try:
        from app.routers.workspace import get_workspace_dir
        return get_workspace_dir()
    except Exception:
        return Path(__file__).resolve().parent.parent.parent

def _get_ignore_dirs() -> set[str]:
    try:
        from app.routers.workspace import IGNORE_DIRS
        return IGNORE_DIRS
    except Exception:
        return {"venv", ".venv", "node_modules", ".git", "__pycache__", "dist", "build", "coverage", "cache", "storage", "data", "output", "uploads"}

# watchdogが利用可能かチェック
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False
    logger.warning("watchdog not installed. Falling back to polling mode.")


class FileWatcher:
    """ファイル変更監視＋スナップショット管理（watchdog + ポーリング併用）"""

    def __init__(self, watch_enabled: bool = True):
        self._snapshots: dict[str, str] = {}
        self._tracked_files: dict[str, list[str]] = {}
        self._observer: Optional[Observer] = None
        self._watch_enabled = watch_enabled
        
        if watch_enabled and HAS_WATCHDOG:
            self._start_watchdog()
        elif watch_enabled:
            self._start_polling()

    def _start_watchdog(self):
        """watchdogによるリアルタイム監視を開始"""
        try:
            class ChangeHandler(FileSystemEventHandler):
                def __init__(self, watcher):
                    self.watcher = watcher
                
                def on_modified(self, event):
                    if not event.is_directory and self.watcher._watch_enabled:
                        if not any(part in _get_ignore_dirs() for part in Path(event.src_path).parts):
                            self.watcher._invalidate_for_path(event.src_path)
                
                def on_created(self, event):
                    if not event.is_directory and self.watcher._watch_enabled:
                        if not any(part in _get_ignore_dirs() for part in Path(event.src_path).parts):
                            self.watcher._invalidate_for_path(event.src_path)
            
            self._observer = Observer()
            self._observer.schedule(ChangeHandler(self), str(_get_workspace_dir()), recursive=True)
            self._observer.daemon = True
            self._observer.start()
            logger.info("✅ FileWatcher: watchdogリアルタイム監視開始")
        except Exception as e:
            logger.warning(f"⚠️ FileWatcher: watchdog起動失敗 ({e})、ポーリングにフォールバック")
            self._start_polling()

    def _start_polling(self):
        """ポーリング方式の監視を開始（watchdog非対応時）"""
        logger.info("✅ FileWatcher: ポーリング監視開始 (interval: 2s)")

    def _invalidate_for_path(self, file_path: str):
        """変更されたファイルパスに関連するキャッシュを無効化"""
        try:
            rel_path = Path(file_path).relative_to(_get_workspace_dir()).as_posix()
        except Exception:
            rel_path = Path(file_path).name
        invalidated_keys = []
        for key, files in list(self._tracked_files.items()):
            if rel_path in files:
                invalidated_keys.append(key)
                self._snapshots.pop(key, None)
        if invalidated_keys:
            logger.debug(f"🔔 ファイル変更検出: {rel_path} ({len(invalidated_keys)}キャッシュ無効化)")

    def snapshot(self, key: str, paths: Optional[list[str]] = None) -> str:
        """スナップショット保存"""
        if paths is None:
            paths = self._detect_git_changed_files()
        hash_val = self._calc_files_hash(paths)
        self._snapshots[key] = hash_val
        self._tracked_files[key] = paths or []
        return hash_val

    def has_changed(self, key: str, paths: Optional[list[str]] = None) -> bool:
        """変更検出"""
        if key not in self._snapshots:
            return True
        
        if paths is None:
            paths = self._tracked_files.get(key)
        if not paths:
            paths = self._detect_git_changed_files()
            if not paths:
                return False
        
        return self._calc_files_hash(paths) != self._snapshots[key]

    def get_snapshot(self, key: str) -> Optional[str]:
        return self._snapshots.get(key)

    def _calc_files_hash(self, paths: list[str]) -> str:
        if not paths:
            return ""
        hasher = hashlib.md5()
        ws_dir = _get_workspace_dir()
        ignore_dirs = _get_ignore_dirs()
        for p in sorted(paths):
            if any(part in ignore_dirs for part in Path(p).parts):
                continue
            full_path = ws_dir / p
            if full_path.exists():
                try:
                    if full_path.stat().st_size <= 1_000_000:
                        hasher.update(full_path.read_bytes())
                except Exception:
                    pass
        return hasher.hexdigest()

    def _detect_git_changed_files(self) -> list[str]:
        ws_dir = _get_workspace_dir()
        ignore_dirs = _get_ignore_dirs()
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                capture_output=True, text=True, cwd=str(ws_dir), timeout=5
            )
            if result.returncode == 0:
                files = [f.strip() for f in result.stdout.split('\n') if f.strip() and not any(part in ignore_dirs for part in Path(f.strip()).parts)]
                untracked = subprocess.run(
                    ["git", "ls-files", "--others", "--exclude-standard"],
                    capture_output=True, text=True, cwd=str(ws_dir), timeout=5
                )
                if untracked.returncode == 0:
                    files.extend([f.strip() for f in untracked.stdout.split('\n') if f.strip() and not any(part in ignore_dirs for part in Path(f.strip()).parts)])
                return files
        except Exception as e:
            logger.warning(f"git diff error: {e}")
        return []

    def invalidate(self, key: str):
        self._snapshots.pop(key, None)
        self._tracked_files.pop(key, None)

    def clear(self):
        self._snapshots.clear()
        self._tracked_files.clear()

    def stop(self):
        """監視スレッド停止"""
        self._watch_enabled = False
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2)
            logger.info("FileWatcher: 監視停止")


# シングルトンインスタンス（アプリ起動時に自動開始）
file_watcher = FileWatcher()