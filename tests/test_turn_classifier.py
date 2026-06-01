import pytest

from src.conversation.classifier import TurnClassifier, TurnIntent
from src.conversation.session import ConversationPhase


def test_classifier_prioritizes_capability_question_over_chitchat_prefix():
    result = TurnClassifier().classify("好的，你还能做其它什么事情?", phase=ConversationPhase.completed)

    assert result.intent == TurnIntent.ask_capability


def test_classifier_keeps_completed_edits_in_skill_runtime_path():
    result = TurnClassifier().classify("换成横版", phase=ConversationPhase.completed)

    assert result.intent == TurnIntent.modify_param


def test_classifier_keeps_awaiting_confirmation_edits_in_skill_runtime_path():
    result = TurnClassifier().classify("换成横版", phase=ConversationPhase.awaiting_confirmation)

    assert result.intent == TurnIntent.modify_param


@pytest.mark.parametrize("text", ["yes", "ok", "好的"])
def test_classifier_accepts_common_confirmation_phrases_when_awaiting_confirmation(text):
    result = TurnClassifier().classify(text, phase=ConversationPhase.awaiting_confirmation)

    assert result.intent == TurnIntent.confirm


def test_classifier_detects_completed_runtime_question():
    result = TurnClassifier().classify("刚刚生图，你没有调用 SKILL_TOKEN??", phase=ConversationPhase.completed)

    assert result.intent == TurnIntent.ask_runtime


def test_classifier_routes_completed_unknown_turns_to_llm_router():
    result = TurnClassifier().classify("hello, 今天是周几啊", phase=ConversationPhase.completed)

    assert result.intent == TurnIntent.needs_llm
    assert result.source == "llm"


def test_classifier_routes_completed_new_generation_request_to_llm_router():
    result = TurnClassifier().classify("心动小镇海报生成", phase=ConversationPhase.completed)

    assert result.intent == TurnIntent.needs_llm
    assert result.source == "llm"


def test_classifier_does_not_treat_cancel_with_object_as_cancel_command():
    result = TurnClassifier().classify("取消主标题", phase=ConversationPhase.collecting)

    assert result.intent == TurnIntent.needs_llm


def test_classifier_detects_bare_cancel_command():
    result = TurnClassifier().classify("取消", phase=ConversationPhase.collecting)

    assert result.intent == TurnIntent.cancel


def test_classifier_detects_running_job_controls():
    classifier = TurnClassifier()

    assert classifier.classify("继续等", phase=ConversationPhase.running_job).intent == TurnIntent.continue_wait
    assert classifier.classify("还在吗", phase=ConversationPhase.running_job).intent == TurnIntent.ask_status


def test_classifier_does_not_match_status_phrase_as_substring():
    result = TurnClassifier().classify("这张做得好了没意思", phase=ConversationPhase.running_job)

    assert result.intent == TurnIntent.unrelated


def test_classifier_allows_status_phrase_with_prefix():
    result = TurnClassifier().classify("现在好了没", phase=ConversationPhase.running_job)

    assert result.intent == TurnIntent.ask_status


def test_classifier_treats_cancel_with_sentence_particle_as_cancel():
    classifier = TurnClassifier()

    assert classifier.classify("停止吧", phase=ConversationPhase.collecting).intent == TurnIntent.cancel
    assert classifier.classify("取消啊", phase=ConversationPhase.collecting).intent == TurnIntent.cancel
    assert classifier.classify("算了吧", phase=ConversationPhase.collecting).intent == TurnIntent.cancel
