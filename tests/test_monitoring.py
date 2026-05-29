import logging

from src.monitoring import metric_user_key, record_metric


def test_record_metric_logs_sorted_structured_fields(caplog):
    caplog.set_level(logging.INFO, logger="src.monitoring")

    record_metric("duplicate_submit", skill_name="xd-poster-gen", job_status="running")

    assert "[METRIC] name=duplicate_submit job_status=running skill_name=xd-poster-gen" in caplog.text


def test_metric_user_key_is_stable_and_does_not_expose_raw_id():
    user_id = "ou_real_user_id"

    assert metric_user_key(user_id) == metric_user_key(user_id)
    assert metric_user_key(user_id) != user_id
    assert "ou_" not in metric_user_key(user_id)
