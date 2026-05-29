from src.conversation.classifier import TurnIntent
from src.conversation.session import ConversationPhase
from src.conversation.state_machine import SideEffect, StateMachine


def test_completed_capability_stays_completed_and_replies():
    transition = StateMachine().transition(ConversationPhase.completed, TurnIntent.ask_capability)

    assert transition.next_phase == ConversationPhase.completed
    assert transition.side_effects == [SideEffect.reply_capability]
    assert not transition.allow_skill_runtime


def test_completed_runtime_question_stays_completed_and_replies_runtime_context():
    transition = StateMachine().transition(ConversationPhase.completed, TurnIntent.ask_runtime)

    assert transition.next_phase == ConversationPhase.completed
    assert transition.side_effects == [SideEffect.reply_runtime]
    assert not transition.allow_skill_runtime


def test_completed_modify_returns_to_collecting_and_allows_runtime():
    transition = StateMachine().transition(ConversationPhase.completed, TurnIntent.modify_param)

    assert transition.next_phase == ConversationPhase.collecting
    assert transition.side_effects == [SideEffect.invoke_skill_runtime]
    assert transition.allow_skill_runtime


def test_collecting_cancel_clears_context():
    transition = StateMachine().transition(ConversationPhase.collecting, TurnIntent.cancel)

    assert transition.next_phase == ConversationPhase.idle
    assert transition.side_effects == [SideEffect.clear_context, SideEffect.reply_cancelled]


def test_awaiting_confirmation_confirm_submits_job():
    transition = StateMachine().transition(ConversationPhase.awaiting_confirmation, TurnIntent.confirm)

    assert transition.next_phase == ConversationPhase.running_job
    assert transition.side_effects == [SideEffect.submit_job]


def test_awaiting_confirmation_unrelated_does_not_invoke_runtime():
    transition = StateMachine().transition(ConversationPhase.awaiting_confirmation, TurnIntent.unrelated)

    assert transition.next_phase == ConversationPhase.awaiting_confirmation
    assert transition.side_effects == [SideEffect.reply_boundary]
    assert not transition.allow_skill_runtime


def test_awaiting_confirmation_modify_allows_runtime():
    transition = StateMachine().transition(ConversationPhase.awaiting_confirmation, TurnIntent.modify_param)

    assert transition.next_phase == ConversationPhase.collecting
    assert transition.side_effects == [SideEffect.invoke_skill_runtime]
    assert transition.allow_skill_runtime


def test_running_job_unrelated_keeps_user_in_running_job():
    transition = StateMachine().transition(ConversationPhase.running_job, TurnIntent.unrelated)

    assert transition.next_phase == ConversationPhase.running_job
    assert transition.side_effects == [SideEffect.reply_running_job]


def test_selecting_skill_option_moves_to_collecting():
    transition = StateMachine().transition(ConversationPhase.selecting_skill, TurnIntent.answer_option)

    assert transition.next_phase == ConversationPhase.collecting
    assert transition.side_effects == [SideEffect.clear_last_options, SideEffect.invoke_skill_runtime]
    assert transition.allow_skill_runtime


def test_cancelled_start_skill_reenters_selection():
    transition = StateMachine().transition(ConversationPhase.cancelled, TurnIntent.start_skill)

    assert transition.next_phase == ConversationPhase.selecting_skill
    assert transition.side_effects == [SideEffect.invoke_skill_runtime]
    assert transition.allow_skill_runtime


def test_failed_retry_resubmits_job():
    transition = StateMachine().transition(ConversationPhase.failed, TurnIntent.retry)

    assert transition.next_phase == ConversationPhase.running_job
    assert transition.side_effects == [SideEffect.submit_job]


def test_failed_cancel_clears_context():
    transition = StateMachine().transition(ConversationPhase.failed, TurnIntent.cancel)

    assert transition.next_phase == ConversationPhase.idle
    assert transition.side_effects == [SideEffect.clear_context]
