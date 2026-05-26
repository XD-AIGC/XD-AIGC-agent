"""SKILLS_DIR 文件 watcher — 同事 push skill 后 cron 拉到本地，watcher 检测变化 reload registry。

对话不中断（只是后台重建 _registry dict）。

启动方式：在 src/main.py 启动时 start_skills_watcher()。
"""
import logging
import threading
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from src.config import SKILLS_DIR
from src.skill.registry import reload_registry

log = logging.getLogger(__name__)

# 防抖：短时间内多次事件（如 git pull 一次性 update 多个文件）合并成一次 reload
_DEBOUNCE_SEC = 2.0


class _SkillsChangeHandler(FileSystemEventHandler):
    def __init__(self) -> None:
        self._last_event_time = 0.0
        self._lock = threading.Lock()
        self._pending = False

    def _should_handle(self, src_path: str) -> bool:
        lower = src_path.lower()
        return lower.endswith((".yaml", ".yml", ".md", ".tsv"))

    def _schedule_reload(self):
        with self._lock:
            self._last_event_time = time.time()
            if self._pending:
                return
            self._pending = True

        def _debounced():
            # 等到没有新事件再 reload
            while True:
                time.sleep(_DEBOUNCE_SEC)
                with self._lock:
                    if time.time() - self._last_event_time >= _DEBOUNCE_SEC:
                        self._pending = False
                        break
            try:
                reload_registry()
            except Exception:
                log.exception("[WATCHER] reload_registry failed")

        threading.Thread(target=_debounced, daemon=True).start()

    _WRITE_EVENTS = {"modified", "created", "deleted", "moved"}

    def on_any_event(self, event):
        if event.is_directory:
            return
        if event.event_type not in self._WRITE_EVENTS:
            return
        if not self._should_handle(event.src_path):
            return
        log.info(f"[WATCHER] {event.event_type} {event.src_path}")
        self._schedule_reload()


_observer: Observer | None = None


def start_skills_watcher() -> None:
    """启动文件 watcher，监听 SKILLS_DIR 变化自动 reload registry。"""
    global _observer
    if _observer is not None:
        log.warning("[WATCHER] already started")
        return
    handler = _SkillsChangeHandler()
    _observer = Observer()
    _observer.schedule(handler, SKILLS_DIR, recursive=True)
    _observer.start()
    log.info(f"[WATCHER] watching {SKILLS_DIR}（debounce={_DEBOUNCE_SEC}s）")


def stop_skills_watcher() -> None:
    global _observer
    if _observer is None:
        return
    _observer.stop()
    _observer.join(timeout=5)
    _observer = None
