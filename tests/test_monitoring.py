import logging

from src.monitoring import record_metric


def test_record_metric_logs_sorted_structured_fields(caplog):
    caplog.set_level(logging.INFO, logger="src.monitoring")

    record_metric("duplicate_submit", skill_name="xd-poster-gen", job_status="running")

    assert "[METRIC] name=duplicate_submit job_status=running skill_name=xd-poster-gen" in caplog.text
