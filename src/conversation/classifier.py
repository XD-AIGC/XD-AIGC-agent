"""Deterministic turn classification for conversation boundary handling."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from src.conversation.session import ConversationPhase


RETRY_PHRASES = {
    "再来一张", "再来一个", "再来", "再生成", "再画一张", "再做一张",
    "重新生成", "重做", "again",
}

SKILL_CHITCHAT_PHRASES = {
    "你好", "您好", "hi", "hello", "哈喽", "嗨", "在吗",
    "好", "好的", "嗯", "嗯嗯", "ok", "收到",
    "谢谢", "感谢", "辛苦了", "这张不错", "不错",
}

CONFIRM_PHRASES = {"确认", "确定", "可以", "没问题", "就这样"}
CANCEL_PHRASES = {"取消", "算了", "不要了", "停止"}
CONTINUE_WAIT_PHRASES = {"继续等", "继续等待", "等一下", "再等等"}
ASK_STATUS_PHRASES = {"还在吗", "好了没", "进度", "什么状态", "生成好了吗"}
ASK_STATUS_SUFFIXES = {"还在吗", "好了没", "什么状态", "生成好了吗", "进度怎么样", "进度如何"}
SENTENCE_PARTICLES = ("吧", "啊", "呀", "啦", "哦", "喔", "呢")


class TurnIntent(str, Enum):
    answer_option = "answer_option"
    ask_capability = "ask_capability"
    ask_status = "ask_status"
    cancel = "cancel"
    chitchat = "chitchat"
    confirm = "confirm"
    continue_wait = "continue_wait"
    modify_param = "modify_param"
    needs_llm = "needs_llm"
    retry = "retry"
    start_skill = "start_skill"
    unrelated = "unrelated"


@dataclass(frozen=True)
class ClassifiedTurn:
    intent: TurnIntent
    source: str = "deterministic"
    reason: str = ""


class TurnClassifier:
    """Classify high-confidence boundary turns before invoking the LLM."""

    def classify(
        self,
        text: str,
        *,
        phase: ConversationPhase | str | None = None,
        has_last_options: bool = False,
    ) -> ClassifiedTurn:
        normalized_phase = _coerce_phase(phase)
        if has_last_options and _is_numbered_reply(text):
            return ClassifiedTurn(TurnIntent.answer_option, reason="numbered option")
        if is_capability_question(text):
            return ClassifiedTurn(TurnIntent.ask_capability, reason="capability question")
        if normalized_phase == ConversationPhase.awaiting_confirmation and _matches_phrase(text, CONFIRM_PHRASES):
            return ClassifiedTurn(TurnIntent.confirm, reason="confirmation phrase")
        if is_retry(text):
            return ClassifiedTurn(TurnIntent.retry, reason="retry phrase")
        if (
            normalized_phase in {ConversationPhase.awaiting_confirmation, ConversationPhase.completed}
            and is_completed_skill_continuation(text)
        ):
            return ClassifiedTurn(TurnIntent.modify_param, reason="completed continuation")
        running = self._classify_running_control(text, normalized_phase)
        if running is not None:
            return running
        cancel = self._classify_cancel(text)
        if cancel is not None:
            return cancel
        if is_skill_chitchat(text):
            return ClassifiedTurn(TurnIntent.chitchat, reason="short chitchat")
        if normalized_phase in {ConversationPhase.completed, ConversationPhase.running_job}:
            return ClassifiedTurn(TurnIntent.unrelated, reason="boundary turn")
        return ClassifiedTurn(TurnIntent.needs_llm, source="llm", reason="no deterministic match")

    def _classify_running_control(
        self,
        text: str,
        phase: ConversationPhase | None,
    ) -> ClassifiedTurn | None:
        if phase != ConversationPhase.running_job:
            return None
        if _matches_phrase(text, CONTINUE_WAIT_PHRASES):
            return ClassifiedTurn(TurnIntent.continue_wait, reason="running job control")
        if _matches_status_question(text):
            return ClassifiedTurn(TurnIntent.ask_status, reason="running job status")
        return None

    def _classify_cancel(self, text: str) -> ClassifiedTurn | None:
        if _matches_phrase(text, CANCEL_PHRASES):
            return ClassifiedTurn(TurnIntent.cancel, reason="bare cancel")
        compact = compact_text(text)
        if _strip_sentence_particles(compact) in {compact_text(phrase) for phrase in CANCEL_PHRASES}:
            return ClassifiedTurn(TurnIntent.cancel, reason="cancel with sentence particle")
        if any(compact.startswith(compact_text(phrase)) for phrase in CANCEL_PHRASES):
            return ClassifiedTurn(TurnIntent.needs_llm, source="llm", reason="cancel has object")
        return None


def is_retry(text: str) -> bool:
    return _matches_phrase(text, RETRY_PHRASES)


def is_skill_chitchat(text: str) -> bool:
    return _matches_phrase(text, SKILL_CHITCHAT_PHRASES)


def is_capability_question(text: str) -> bool:
    text = compact_text(text)
    if not text:
        return False
    explicit = (
        "你能做什么",
        "能做什么",
        "可以做什么",
        "有什么功能",
        "哪些功能",
        "支持什么",
        "能帮我什么",
        "还能帮我什么",
    )
    if any(phrase in text for phrase in explicit):
        return True
    return ("还能" in text or "还可以" in text) and (
        "做什么" in text or "什么事" in text or "哪些" in text or "啥" in text
    )


def is_completed_skill_continuation(text: str) -> bool:
    text = compact_text(text)
    if not text:
        return False
    markers = (
        "再来", "再生成", "再做", "再画", "重新生成", "重做",
        "改", "换", "调整", "变成", "设成",
        "标题", "主标题", "副标题", "文案", "比例", "构图",
        "角色", "动作", "颜色", "色调", "风格", "尺寸",
        "横版", "竖版", "方图", "手机",
    )
    return any(marker in text for marker in markers)


def compact_text(text: str) -> str:
    return re.sub(r"[\s，,。.!！?？~～]", "", text).lower().replace("其它", "其他")


def _matches_phrase(text: str, phrases: set[str]) -> bool:
    cleaned = text.strip().rstrip("。.!！?？ ").lower()
    return cleaned in {phrase.lower() for phrase in phrases}


def _matches_status_question(text: str) -> bool:
    compact = compact_text(text)
    if compact in {compact_text(phrase) for phrase in ASK_STATUS_PHRASES}:
        return True
    return any(compact.endswith(suffix) for suffix in ASK_STATUS_SUFFIXES)


def _strip_sentence_particles(text: str) -> str:
    while text.endswith(SENTENCE_PARTICLES):
        text = text[:-1]
    return text


def _is_numbered_reply(text: str) -> bool:
    return bool(re.match(r"^\s*(?:选|选择|第)?\s*(\d{1,2})\s*(?:号|个)?\s*[。.!！?？]?\s*$", text))


def _coerce_phase(phase: ConversationPhase | str | None) -> ConversationPhase | None:
    if phase is None or isinstance(phase, ConversationPhase):
        return phase
    try:
        return ConversationPhase(phase)
    except ValueError:
        return None
