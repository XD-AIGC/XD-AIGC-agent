"""State transitions for conversation boundary decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.conversation.classifier import TurnIntent
from src.conversation.session import ConversationPhase


class SideEffect(str, Enum):
    clear_context = "clear_context"
    clear_last_options = "clear_last_options"
    invoke_skill_runtime = "invoke_skill_runtime"
    no_op = "no_op"
    reply_boundary = "reply_boundary"
    reply_cancelled = "reply_cancelled"
    reply_capability = "reply_capability"
    reply_chitchat = "reply_chitchat"
    reply_runtime = "reply_runtime"
    reply_running_job = "reply_running_job"
    submit_job = "submit_job"


@dataclass(frozen=True)
class Transition:
    next_phase: ConversationPhase
    side_effects: list[SideEffect]
    allow_skill_runtime: bool = False


class StateMachine:
    """Map `(phase, intent)` to the next phase and runtime side effects."""

    def transition(self, phase: ConversationPhase | str, intent: TurnIntent | str) -> Transition:
        phase = _coerce_phase(phase)
        intent = _coerce_intent(intent)
        if phase == ConversationPhase.completed:
            return self._completed(intent)
        if phase == ConversationPhase.collecting:
            return self._collecting(intent)
        if phase == ConversationPhase.awaiting_confirmation:
            return self._awaiting_confirmation(intent)
        if phase == ConversationPhase.running_job:
            return self._running_job(intent)
        if phase == ConversationPhase.selecting_skill:
            return self._selecting_skill(intent)
        if phase == ConversationPhase.cancelled:
            return self._cancelled(intent)
        if phase == ConversationPhase.failed:
            return self._failed(intent)
        if phase == ConversationPhase.idle:
            return self._idle(intent)
        return Transition(phase, [SideEffect.no_op])

    def _idle(self, intent: TurnIntent) -> Transition:
        if intent == TurnIntent.ask_capability:
            return Transition(ConversationPhase.idle, [SideEffect.reply_capability])
        if intent == TurnIntent.start_skill:
            return Transition(ConversationPhase.selecting_skill, [SideEffect.invoke_skill_runtime], True)
        return Transition(ConversationPhase.idle, [SideEffect.reply_boundary])

    def _collecting(self, intent: TurnIntent) -> Transition:
        if intent == TurnIntent.cancel:
            return Transition(ConversationPhase.idle, [SideEffect.clear_context, SideEffect.reply_cancelled])
        if intent == TurnIntent.chitchat:
            return Transition(ConversationPhase.collecting, [SideEffect.reply_chitchat])
        return Transition(ConversationPhase.collecting, [SideEffect.invoke_skill_runtime], True)

    def _awaiting_confirmation(self, intent: TurnIntent) -> Transition:
        if intent == TurnIntent.confirm:
            return Transition(ConversationPhase.running_job, [SideEffect.submit_job])
        if intent == TurnIntent.cancel:
            return Transition(ConversationPhase.idle, [SideEffect.clear_context, SideEffect.reply_cancelled])
        if intent == TurnIntent.modify_param:
            return Transition(ConversationPhase.collecting, [SideEffect.invoke_skill_runtime], True)
        if intent == TurnIntent.ask_capability:
            return Transition(ConversationPhase.awaiting_confirmation, [SideEffect.reply_capability])
        if intent == TurnIntent.chitchat:
            return Transition(ConversationPhase.awaiting_confirmation, [SideEffect.reply_chitchat])
        return Transition(ConversationPhase.awaiting_confirmation, [SideEffect.reply_boundary])

    def _running_job(self, intent: TurnIntent) -> Transition:
        if intent == TurnIntent.cancel:
            return Transition(ConversationPhase.completed, [SideEffect.reply_cancelled])
        if intent == TurnIntent.continue_wait:
            return Transition(ConversationPhase.running_job, [SideEffect.no_op])
        if intent == TurnIntent.ask_status:
            return Transition(ConversationPhase.running_job, [SideEffect.reply_running_job])
        return Transition(ConversationPhase.running_job, [SideEffect.reply_running_job])

    def _completed(self, intent: TurnIntent) -> Transition:
        if intent == TurnIntent.retry:
            return Transition(ConversationPhase.running_job, [SideEffect.submit_job])
        if intent == TurnIntent.modify_param:
            return Transition(ConversationPhase.collecting, [SideEffect.invoke_skill_runtime], True)
        if intent in {TurnIntent.needs_llm, TurnIntent.start_skill}:
            return Transition(ConversationPhase.selecting_skill, [SideEffect.invoke_skill_runtime], True)
        if intent == TurnIntent.ask_capability:
            return Transition(ConversationPhase.completed, [SideEffect.reply_capability])
        if intent == TurnIntent.ask_runtime:
            return Transition(ConversationPhase.completed, [SideEffect.reply_runtime])
        if intent == TurnIntent.chitchat:
            return Transition(ConversationPhase.completed, [SideEffect.reply_chitchat])
        return Transition(ConversationPhase.completed, [SideEffect.reply_boundary])

    def _selecting_skill(self, intent: TurnIntent) -> Transition:
        if intent == TurnIntent.answer_option:
            return Transition(
                ConversationPhase.collecting,
                [SideEffect.clear_last_options, SideEffect.invoke_skill_runtime],
                True,
            )
        if intent == TurnIntent.cancel:
            return Transition(ConversationPhase.idle, [SideEffect.clear_context, SideEffect.reply_cancelled])
        return Transition(ConversationPhase.selecting_skill, [SideEffect.invoke_skill_runtime], True)

    def _cancelled(self, intent: TurnIntent) -> Transition:
        if intent == TurnIntent.start_skill:
            return Transition(ConversationPhase.selecting_skill, [SideEffect.invoke_skill_runtime], True)
        if intent == TurnIntent.ask_capability:
            return Transition(ConversationPhase.cancelled, [SideEffect.reply_capability])
        return Transition(ConversationPhase.cancelled, [SideEffect.reply_boundary])

    def _failed(self, intent: TurnIntent) -> Transition:
        if intent == TurnIntent.retry:
            return Transition(ConversationPhase.running_job, [SideEffect.submit_job])
        if intent == TurnIntent.modify_param:
            return Transition(ConversationPhase.collecting, [SideEffect.invoke_skill_runtime], True)
        if intent == TurnIntent.cancel:
            return Transition(ConversationPhase.idle, [SideEffect.clear_context])
        return Transition(ConversationPhase.failed, [SideEffect.reply_boundary])


def _coerce_phase(value: ConversationPhase | str) -> ConversationPhase:
    return value if isinstance(value, ConversationPhase) else ConversationPhase(value)


def _coerce_intent(value: TurnIntent | str) -> TurnIntent:
    return value if isinstance(value, TurnIntent) else TurnIntent(value)
