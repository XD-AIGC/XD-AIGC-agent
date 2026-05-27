from src.conversation.classifier import TurnClassifier, TurnIntent
from src.conversation.session import ConversationPhase


def test_classifier_prioritizes_capability_question_over_chitchat_prefix():
    result = TurnClassifier().classify("好的，你还能做其它什么事情?", phase=ConversationPhase.completed)

    assert result.intent == TurnIntent.ask_capability


def test_classifier_keeps_completed_edits_in_skill_runtime_path():
    result = TurnClassifier().classify("换成横版", phase=ConversationPhase.completed)

    assert result.intent == TurnIntent.modify_param


def test_classifier_treats_completed_date_question_as_unrelated():
    result = TurnClassifier().classify("hello, 今天是周几啊", phase=ConversationPhase.completed)

    assert result.intent == TurnIntent.unrelated


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
