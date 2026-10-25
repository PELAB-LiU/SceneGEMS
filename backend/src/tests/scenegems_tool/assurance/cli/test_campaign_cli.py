"""The campaign CLI against a mocked httpx transport: requests it sends, what it prints, its exit codes."""

import hashlib
import io
from typing import Callable, List, Tuple

import httpx
import pytest

from scenegems_tool.assurance.cli.api_client import reasons_of
from scenegems_tool.assurance.cli.main import DEFAULT_OPERATOR_URL, OPERATOR_URL_VARIABLE, build_parser, main

CAMPAIGN = "1b7a9b3e-0000-4000-8000-000000000001"
CLASS_A = "2vessel_0obstacle_scenarios/functional_model0"


def campaign_json(**changes) -> dict:
    view = {
        "campaign_id": CAMPAIGN,
        "name": "smoke",
        "desired_state": "paused",
        "actual_state": "created",
        "state_reason": None,
        "config_version": 1,
        "pinned_fingerprints": {},
        "created_at": "2026-10-25T12:00:00+00:00",
        "updated_at": "2026-10-25T12:00:00+00:00",
        "started_at": None,
        "finished_at": None,
    }
    view.update(changes)
    return view


def detail_json(**changes) -> dict:
    classes = [
        {"class_id": CLASS_A, "state": "open", "quota": 5, "complete": 3, "dropped": 1, "in_flight": 2, "failure_budget_left": 4, "verdicts": {"0": {"passed": 2, "failed": 1}}},
        {
            "class_id": "3vessel_0obstacle_scenarios/functional_model2",
            "state": "complete",
            "quota": 5,
            "complete": 5,
            "dropped": 0,
            "in_flight": 0,
            "failure_budget_left": 5,
            "verdicts": {"0": {"passed": 5}},
        },
    ]
    view = campaign_json(**changes)
    view["classes"] = classes
    view["totals"] = {
        "classes": 2,
        "classes_open": 1,
        "classes_complete": 1,
        "classes_abandoned": 0,
        "quota": 10,
        "complete": 8,
        "dropped": 1,
        "in_flight": 2,
        "verdicts": {"passed": 7, "failed": 1},
    }
    return view


class Server:
    """Records requests and answers from a route table: (method, path) to a response or a function of the request."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.requests: List[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            answer = self.routes.get((request.method, request.url.path))
            if answer is None:
                return httpx.Response(404, json={"detail": f"no route {request.url.path}"})
            return answer(request) if callable(answer) else answer

        return httpx.MockTransport(handle)


def run(server: Server, *argv: str, sleep: Callable = None) -> Tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = main(["--api", "http://master"] + list(argv), transport=server.transport(), out=out, err=err, sleep=sleep)
    return code, out.getvalue(), err.getvalue()


def json_response(body, status=200) -> httpx.Response:
    return httpx.Response(status, json=body)


def test_create_sends_the_yaml_with_its_content_type(tmp_path):
    config = tmp_path / "campaign.yaml"
    config.write_text("name: from file\nscope: []\n", encoding="utf-8")
    server = Server({("POST", "/cluster/campaigns"): json_response(detail_json(), 201)})
    code, out, err = run(server, "create", str(config), "--name", "my name", "--start")
    assert code == 0 and err == ""
    (request,) = server.requests
    assert request.headers["content-type"] == "application/yaml" and request.content == config.read_bytes()
    assert dict(request.url.params) == {"name": "my name", "start": "true"}
    assert f"campaign smoke ({CAMPAIGN})" in out and "classes 2: open 1, complete 1, abandoned 0" in out


def test_create_without_options_sends_no_query(tmp_path):
    config = tmp_path / "campaign.yaml"
    config.write_text("x: 1\n", encoding="utf-8")
    server = Server({("POST", "/cluster/campaigns"): json_response(detail_json(), 201)})
    assert run(server, "create", str(config))[0] == 0
    assert dict(server.requests[0].url.params) == {}


def test_create_prints_the_servers_reasons_and_fails_on_422(tmp_path):
    config = tmp_path / "campaign.yaml"
    config.write_text("x: 1\n", encoding="utf-8")
    reasons = {"message": "the campaign config is not valid", "reasons": ["scope.0: no class 'x'", "execution.runs.0: stack unavailable"]}
    server = Server({("POST", "/cluster/campaigns"): json_response({"detail": reasons}, 422)})
    code, out, err = run(server, "create", str(config))
    assert code == 1 and out == ""
    assert err.splitlines() == ["error: HTTP 422: scope.0: no class 'x'", "  execution.runs.0: stack unavailable"]


def test_create_with_a_missing_file_fails_without_a_request(tmp_path):
    server = Server({})
    code, _, err = run(server, "create", str(tmp_path / "missing.yaml"))
    assert code == 1 and "cannot read" in err and server.requests == []


def test_list_prints_a_table_and_sends_the_filters():
    other = campaign_json(campaign_id="2c8b0c4f-0000-4000-8000-000000000002", name="second", actual_state="running", desired_state="running")
    server = Server({("GET", "/cluster/campaigns"): json_response([campaign_json(), other])})
    code, out, _ = run(server, "list", "--state", "running", "--state", "paused", "--limit", "5", "--offset", "10")
    assert code == 0
    assert server.requests[0].url.params.get_list("state") == ["running", "paused"] and server.requests[0].url.params["limit"] == "5"
    lines = out.splitlines()
    assert lines[0].split() == ["id", "name", "desired", "actual", "created"] and len(lines) == 3
    assert "second" in lines[2] and "running" in lines[2]


def test_list_of_nothing():
    server = Server({("GET", "/cluster/campaigns"): json_response([])})
    assert run(server, "list")[1] == "no campaigns\n"


def test_show_prints_the_summary_and_a_coverage_table():
    server = Server({("GET", f"/cluster/campaigns/{CAMPAIGN}"): json_response(detail_json(actual_state="running", desired_state="running", started_at="2026-10-25T12:05:00+00:00"))})
    code, out, _ = run(server, "show", CAMPAIGN)
    assert code == 0
    assert "desired running, actual running" in out and "started 2026-10-25T12:05:00+00:00" in out
    assert "cases: 8 complete of quota 10, 1 dropped, 2 in flight" in out and "verdicts: failed 1, passed 7" in out
    table_lines = out.split("\n\n", 1)[1].splitlines()
    assert table_lines[0].split() == ["class", "state", "quota", "complete", "dropped", "in", "flight", "budget", "left", "failed", "passed"]
    assert table_lines[1].split() == [CLASS_A, "open", "5", "3", "1", "2", "4", "1", "2"]
    assert table_lines[2].split()[-2:] == ["0", "5"]


@pytest.mark.parametrize("control, path", [("start", "start"), ("pause", "pause"), ("drain", "drain"), ("resume", "resume"), ("stop", "stop")])
def test_controls_post_to_their_route(control, path):
    server = Server({("POST", f"/cluster/campaigns/{CAMPAIGN}/{path}"): json_response(campaign_json(desired_state="running"))})
    code, out, _ = run(server, control, CAMPAIGN)
    assert code == 0 and server.requests[0].method == "POST"
    assert out == f"campaign {CAMPAIGN}: desired running, actual created\n"


def test_a_conflict_prints_the_reason_and_fails():
    server = Server({("POST", f"/cluster/campaigns/{CAMPAIGN}/start"): json_response({"detail": f"campaign {CAMPAIGN} is stopping; a stop cannot be undone"}, 409)})
    code, out, err = run(server, "start", CAMPAIGN)
    assert (code, out) == (1, "") and err == f"error: HTTP 409: campaign {CAMPAIGN} is stopping; a stop cannot be undone\n"


def test_an_unknown_campaign_fails_with_the_404_text():
    code, _, err = run(Server({}), "show", "nope")
    assert code == 1 and err.startswith("error: HTTP 404: no route /cluster/campaigns/nope")


def test_cases_send_their_filters_and_print_a_table():
    cases = [{"class_id": CLASS_A, "case_index": 3, "case_id": 17, "stage": "simulate", "state": "active", "seed": 99, "reason": None}]
    server = Server({("GET", f"/cluster/campaigns/{CAMPAIGN}/cases"): json_response(cases)})
    code, out, _ = run(server, "cases", CAMPAIGN, "--class", CLASS_A, "--state", "active", "--stage", "simulate")
    assert code == 0
    params = server.requests[0].url.params
    assert (params["class_id"], params["state"], params["stage"]) == (CLASS_A, "active", "simulate")
    assert out.splitlines()[1].split() == [CLASS_A, "3", "17", "simulate", "active", "99", "-"]


def test_cases_refuse_an_unknown_state():
    with pytest.raises(SystemExit) as exit_info:
        run(Server({}), "cases", CAMPAIGN, "--state", "bogus")
    assert exit_info.value.code == 2


def test_verdicts_print_a_page():
    verdicts = [{"class_id": CLASS_A, "case_id": 17, "run_index": 0, "state": "failed", "failed_rules": ["rule_15", "rule_16"], "first_failure_time_s": 4.5, "sensitive": True}]
    server = Server({("GET", f"/cluster/campaigns/{CAMPAIGN}/verdicts"): json_response(verdicts)})
    code, out, _ = run(server, "verdicts", CAMPAIGN, "--state", "failed", "--run", "0", "--sensitive")
    assert code == 0
    params = server.requests[0].url.params
    assert (params["state"], params["run_index"], params["sensitive"]) == ("failed", "0", "true") and "format" not in params
    assert out.splitlines()[1].split() == [CLASS_A, "17", "0", "failed", "rule_15;rule_16", "4.5", "True"]


def test_verdicts_stream_into_a_csv_file(tmp_path):
    body = "verdict_id,class_id,state\n1,a,passed\n"
    server = Server({("GET", f"/cluster/campaigns/{CAMPAIGN}/verdicts"): httpx.Response(200, content=body.encode(), headers={"content-type": "text/csv"})})
    target = tmp_path / "out.csv"
    code, out, _ = run(server, "verdicts", CAMPAIGN, "--csv", str(target), "--class", CLASS_A)
    assert code == 0 and target.read_text() == body and f"wrote {len(body)} bytes" in out
    params = server.requests[0].url.params
    assert (params["format"], params["class_id"]) == ("csv", CLASS_A) and "limit" not in params


def test_a_failed_csv_download_leaves_no_file(tmp_path):
    server = Server({("GET", f"/cluster/campaigns/{CAMPAIGN}/verdicts"): json_response({"detail": "no campaign"}, 404)})
    target = tmp_path / "out.csv"
    code, _, err = run(server, "verdicts", CAMPAIGN, "--csv", str(target))
    assert code == 1 and "no campaign" in err and not target.exists()


def test_events_print_one_line_each():
    events = [
        {"event_id": 1, "at": "2026-10-25T12:00:00+00:00", "kind": "created", "class_id": None, "detail": {}},
        {"event_id": 2, "at": "2026-10-25T12:01:00+00:00", "kind": "class_complete", "class_id": CLASS_A, "detail": {"complete": 5}},
    ]
    server = Server({("GET", f"/cluster/campaigns/{CAMPAIGN}/events"): json_response(events)})
    code, out, _ = run(server, "events", CAMPAIGN, "--after", "0")
    lines = out.splitlines()
    assert code == 0 and lines[0].split()[:3] == ["1", "2026-10-25T12:00:00+00:00", "created"]
    assert lines[1].endswith(f"class_complete {CLASS_A} {{'complete': 5}}")
    assert server.requests[0].url.params["after"] == "0"


def test_events_follow_polls_after_the_last_event_until_the_campaign_is_final():
    batches = iter(
        [
            [{"event_id": 1, "at": "t1", "kind": "created", "class_id": None, "detail": {}}],
            [{"event_id": 2, "at": "t2", "kind": "started", "class_id": None, "detail": {}}],
            [],
            [{"event_id": 3, "at": "t3", "kind": "stopped", "class_id": None, "detail": {}}],
            [],
        ]
    )
    states = iter(["running", "stopped"])
    server = Server(
        {
            ("GET", f"/cluster/campaigns/{CAMPAIGN}/events"): lambda request: json_response(next(batches)),
            ("GET", f"/cluster/campaigns/{CAMPAIGN}"): lambda request: json_response(detail_json(actual_state=next(states))),
        }
    )
    sleeps: List[float] = []
    code, out, _ = run(server, "events", CAMPAIGN, "--follow", "--interval", "0.5", sleep=sleeps.append)
    assert code == 0 and [line.split()[0] for line in out.splitlines()] == ["1", "2", "3"]
    event_requests = [request for request in server.requests if request.url.path.endswith("/events")]
    assert [request.url.params["after"] for request in event_requests] == ["0", "1", "2", "2", "3"]
    assert sleeps == [0.5, 0.5, 0.5, 0.5]  # after the first two, the empty poll of a running campaign, and the third event


def test_events_follow_stops_on_interrupt():
    server = Server({("GET", f"/cluster/campaigns/{CAMPAIGN}/events"): json_response([])})

    def interrupt(_seconds):
        raise KeyboardInterrupt

    server.routes[("GET", f"/cluster/campaigns/{CAMPAIGN}")] = json_response(detail_json(actual_state="running"))
    assert run(server, "events", CAMPAIGN, "--follow", sleep=interrupt)[0] == 130


def test_artifact_downloads_and_checks_the_hash(tmp_path):
    data = b'{"scene": 1}'
    digest = hashlib.sha256(data).hexdigest()
    server = Server({("GET", f"/cluster/artifacts/{digest}"): httpx.Response(200, content=data)})
    target = tmp_path / "scene.json"
    code, out, _ = run(server, "artifact", digest, "--out", str(target))
    assert code == 0 and target.read_bytes() == data and f"wrote {len(data)} bytes" in out


def test_artifact_with_the_wrong_content_is_removed(tmp_path):
    digest = hashlib.sha256(b"expected").hexdigest()
    server = Server({("GET", f"/cluster/artifacts/{digest}"): httpx.Response(200, content=b"tampered")})
    target = tmp_path / "scene.json"
    code, _, err = run(server, "artifact", digest, "--out", str(target))
    assert code == 1 and "hash to" in err and not target.exists()


def test_artifact_not_found(tmp_path):
    digest = "a" * 64
    server = Server({("GET", f"/cluster/artifacts/{digest}"): json_response({"detail": "no artifact"}, 404)})
    target = tmp_path / "x"
    code, _, err = run(server, "artifact", digest, "--out", str(target))
    assert code == 1 and err == "error: HTTP 404: no artifact\n" and not target.exists()


def test_artifact_refuses_a_malformed_hash():
    with pytest.raises(SystemExit) as exit_info:
        run(Server({}), "artifact", "XYZ", "--out", "x")
    assert exit_info.value.code == 2


def test_an_unreachable_master_fails_with_a_message():
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    out, err = io.StringIO(), io.StringIO()
    code = main(["--api", "http://master", "list"], transport=httpx.MockTransport(refuse), out=out, err=err)
    assert code == 1 and err.getvalue().startswith("error: cannot reach http://master")


def test_the_api_default_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv(OPERATOR_URL_VARIABLE, raising=False)
    assert build_parser().parse_args(["list"]).api == DEFAULT_OPERATOR_URL
    monkeypatch.setenv(OPERATOR_URL_VARIABLE, "http://127.0.0.1:9999")
    assert build_parser().parse_args(["list"]).api == "http://127.0.0.1:9999"
    assert build_parser().parse_args(["--api", "http://other", "list"]).api == "http://other"


def test_the_help_says_the_operator_api_is_loopback_only(capsys):
    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(["--help"])
    assert exit_info.value.code == 0
    text = capsys.readouterr().out
    assert "loopback" in text and "ssh -L 5174:127.0.0.1:5174" in text and OPERATOR_URL_VARIABLE in text


@pytest.mark.parametrize(
    "detail, expected",
    [
        ("plain", ["plain"]),
        ({"message": "only a message"}, ["only a message"]),
        ({"message": "m", "reasons": ["a", "b"]}, ["a", "b"]),
        ({"message": "payload", "job_type": "x", "errors": [{"loc": ["trajectories", "inline"], "msg": "bad"}]}, ["payload", "trajectories.inline: bad"]),
        ([{"loc": ["query", "limit"], "msg": "not an integer"}], ["query.limit: not an integer"]),
    ],
)
def test_reasons_of_reads_every_error_shape(detail, expected):
    assert reasons_of(detail) == expected


def test_a_non_json_error_body_is_shown():
    server = Server({("GET", "/cluster/campaigns"): httpx.Response(502, text="bad gateway")})
    code, _, err = run(server, "list")
    assert code == 1 and err == "error: HTTP 502: bad gateway\n"
