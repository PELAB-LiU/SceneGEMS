from scenegems_tool.cluster.node.launchers.per_job.job_container_io import format_status_line, parse_status_line


def test_status_lines_round_trip():
    assert parse_status_line(format_status_line("monitored 100 of 200 scenes", 0.5)) == ("monitored 100 of 200 scenes", 0.5)
    assert parse_status_line(format_status_line("started")) == ("started", None)


def test_other_lines_are_log_lines():
    assert parse_status_line("Traceback (most recent call last):") is None
    assert parse_status_line("scenegems-status not json") is None
