"""Centralized user-visible response templates."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from src.conversation.option_resolver import render_option_set
from src.conversation.options import OptionSet


class ResponseComposer:
    """Render short Feishu-friendly replies from deterministic state."""

    def __init__(self, skills: Callable[[], Iterable[object]] | Iterable[object] | None = None) -> None:
        self._skills = skills

    def out_of_scope(self) -> str:
        skills = list(self._iter_skills())
        if not skills:
            return "我目前还没有可用的工具。"
        lines = ["我目前可以帮你做这些事："]
        for skill in skills:
            description = getattr(skill, "description", None)
            if description:
                lines.append(f"- {description}")
        lines.append("\n请告诉我你想做哪个？")
        return "\n".join(lines)

    def completed_followup(self) -> str:
        return "已完成。要继续这个任务、调整哪里，还是换别的需求？"

    def completed_capability(self) -> str:
        return f"{self.completed_followup()}\n\n{self.out_of_scope()}"

    def completed_boundary(self) -> str:
        return f"我主要处理 AIGC 工具任务。\n\n{self.completed_followup()}\n\n{self.out_of_scope()}"

    def skill_chitchat(self, *, completed: bool) -> str:
        if completed:
            return "我还在上一个任务里。要继续这个任务、再做一张相同的、调整哪里，还是换别的需求？"
        return "我还在当前任务里。要继续、调整参数，还是换别的需求？"

    def local_cancel(self) -> str:
        return "我已停止等待这次结果，后续即使完成也不会再发送。"

    def render_options(self, option_set: OptionSet) -> str:
        return render_option_set(option_set)

    def _iter_skills(self) -> Iterable[object]:
        if self._skills is None:
            return []
        if callable(self._skills):
            return self._skills()
        return self._skills
