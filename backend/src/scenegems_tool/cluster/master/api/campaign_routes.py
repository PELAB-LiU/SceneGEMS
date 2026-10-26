"""The operator's campaign routes: create, read and control campaigns (Phase 4).

Like the job and node routes (operator_routes.py) they have no authentication yet and are
served on the operator listener only. They are a thin layer on the AssuranceStores; the
pipeline engine in the master (P4.4) converges a campaign onto the desired state these
routes set. Without Postgres stores the master mounts unavailable_router instead.

    POST CAMPAIGNS_PATH/validate           the same body as create, nothing is created: 200 with {"valid": true, "name", "config_hash",
                                           "classes" (id, content hash, counts, quota, failure budget), "cases_planned" (the quotas' sum),
                                           "runs" (index, name, repeatability tier, warnings)}, or the 422 create answers
    POST CAMPAIGNS_PATH?name=&start=       create from a config; 201 with the campaign. The body is the config as
                                           YAML text (Content-Type application/yaml, text/yaml or application/x-yaml;
                                           JSON is YAML too) or a JSON object {"config": {...}, "name": "...",
                                           "start": false} (application/json). The campaign waits paused unless
                                           start is true. 422 with {"message", "reasons"} for a config that does
                                           not load or that the catalog or the vessel stack resolver refuses
    GET  CAMPAIGNS_PATH?state=&limit=&offset=      campaigns, newest first; state is an actual state, repeatable
    GET  <id>                              the campaign with its classes (counts, state, verdicts per run and state) and totals
    GET  <id>/classes                      the classes alone
    GET  <id>/cases?class_id=&state=&stage=&limit=&offset=      cases by class and index
    GET  <id>/cases/<case id>              the case with its jobs, run records and verdicts
    GET  <id>/verdicts?class_id=&state=&run_index=&sensitive=&limit=&offset=&format=       verdicts by class, case and run;
                                           format=csv answers every matching verdict as a CSV stream (limit and offset still apply when given)
    GET  <id>/run-records?class_id=&run_index=&limit=&offset=
    GET  <id>/events?after=&limit=         the audit trail after an event id, oldest first
    GET  <id>/config                       the current config and every config version
    POST <id>/start | resume               desired state running
    POST <id>/pause                        desired state paused: queued jobs held, no new cases
    POST <id>/drain                        desired state draining: started cases finish, no new ones
    POST <id>/stop                         desired state stopped; final. 409 for any change of a stopped or finished campaign

The lists (campaigns, cases, verdicts, run records, events) answer the number of entries that match their filters without the
page in the X-Total-Count header. Verdicts and run records carry the case's index in its class (case_index).

Control routes answer 200 with the campaign. The actual state follows when the engine has converged.
"""

import csv
import io
import json
from functools import partial
from typing import Any, Callable, Iterator, List, Optional

import anyio
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from scenegems_tool.cluster.master.api.campaign_views import (
    VERDICT_COLUMNS,
    campaign_detail_view,
    campaign_view,
    case_job_view,
    case_view,
    classes_view,
    config_version_view,
    event_view,
    run_record_view,
    validated_campaign_view,
    verdict_row,
    verdict_view,
)
from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.protocol.routes import CAMPAIGNS_PATH
from scenegems_tool.persistence.schema import CampaignActualState, CampaignDesiredState, CaseState, PipelineStage, VerdictState
from scenegems_tool.persistence.stores import AssuranceStores, CampaignRecord, CampaignStateConflict, UnknownCampaign

MAX_LISTED = 1000
TOTAL_COUNT_HEADER = "X-Total-Count"
CSV_PAGE = 1000
YAML_TYPES = ("application/yaml", "text/yaml", "application/x-yaml", "text/x-yaml")
CONTROLS = {
    "start": CampaignDesiredState.RUNNING,
    "resume": CampaignDesiredState.RUNNING,
    "pause": CampaignDesiredState.PAUSED,
    "drain": CampaignDesiredState.DRAINING,
    "stop": CampaignDesiredState.STOPPED,
}


def unavailable_router() -> APIRouter:
    """The campaign routes of a master without Postgres stores: every one answers 503."""
    router = APIRouter()

    @router.api_route(CAMPAIGNS_PATH, methods=["GET", "POST"])
    @router.api_route(CAMPAIGNS_PATH + "/{rest:path}", methods=["GET", "POST"])
    async def unavailable(rest: str = "") -> None:
        raise HTTPException(status_code=503, detail="this master runs without the campaign stores")

    return router


def _page(limit: int) -> int:
    return max(1, min(limit, MAX_LISTED))


async def _run(function: Callable[..., Any], *arguments: Any, **keywords: Any) -> Any:
    return await anyio.to_thread.run_sync(partial(function, *arguments, **keywords))


def _with_total(response: Response, total: int) -> None:
    response.headers[TOTAL_COUNT_HEADER] = str(total)


def _config_problem(reasons: List[str]) -> HTTPException:
    return HTTPException(status_code=422, detail={"message": "the campaign config is not valid", "reasons": list(reasons)})


def _json_body(text: str, name: Optional[str], start: Optional[bool]) -> tuple:
    """The config text, name and start flag of a JSON create body: {"config": object or YAML text, "name", "start"}."""
    try:
        document = json.loads(text)
    except ValueError as error:
        raise _config_problem([f"not valid JSON: {error}"])
    if not isinstance(document, dict) or "config" not in document:
        raise _config_problem(['the body is an object with the config under "config", and optionally "name" and "start"'])
    unknown = sorted(set(document) - {"config", "name", "start"})
    if unknown:
        raise _config_problem([f"unknown fields in the body: {unknown}"])
    config = json.dumps(document["config"]) if isinstance(document["config"], dict) else document["config"]
    if not isinstance(config, str):
        raise _config_problem(['"config" is a config object or YAML text'])
    chosen_name = name if name is not None else document.get("name")
    if chosen_name is not None and (not isinstance(chosen_name, str) or not chosen_name.strip()):
        raise _config_problem(['"name" is a non-empty string'])
    chosen_start = start if start is not None else document.get("start", False)
    if not isinstance(chosen_start, bool):
        raise _config_problem(['"start" is true or false'])
    return config, chosen_name, chosen_start


async def _request_config(request: Request, name: Optional[str], start: Optional[bool]) -> tuple:
    """The config text, name and start flag of a create request, from either body form."""
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    try:
        text = (await request.body()).decode("utf-8")
    except UnicodeDecodeError:
        raise _config_problem(["the body is not UTF-8 text"])
    if content_type in YAML_TYPES:
        return text, name, bool(start)
    if content_type != "application/json":
        raise HTTPException(status_code=415, detail=f"send the config as application/yaml or application/json, not {content_type or 'no content type'}")
    return _json_body(text, name, start)


def _validated_config(text: str) -> Any:
    """The config text checked against the catalog and the resolver (a ValidatedCampaign); 422 with every reason when it does not pass."""
    # Imported here: the config model pulls in numpy and the job type modules, which the master keeps out of its startup
    from scenegems_tool.assurance.campaign import CampaignConfigError, parse_campaign_config, validate_campaign_config

    try:
        return validate_campaign_config(parse_campaign_config(text))
    except CampaignConfigError as error:
        raise _config_problem(error.reasons)


async def _campaign_or_404(stores: AssuranceStores, campaign_id: str) -> CampaignRecord:
    campaign = await _run(stores.campaigns.get_campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail=f"no campaign {campaign_id}")
    return campaign


def _classes_of(stores: AssuranceStores, campaign_id: str) -> List[dict]:
    return classes_view(stores.cases.list_classes(campaign_id), stores.results.coverage(campaign_id))


def campaign_router(stores: AssuranceStores, plane: ControlPlane) -> APIRouter:
    router = APIRouter()
    router.include_router(_campaign_routes(stores, plane))
    router.include_router(_case_routes(stores, plane))
    router.include_router(_result_routes(stores))
    router.include_router(_control_routes(stores))
    return router


def _campaign_routes(stores: AssuranceStores, plane: ControlPlane) -> APIRouter:
    router = APIRouter()

    def create(text: str, name: Optional[str], start: bool) -> CampaignRecord:
        validated = _validated_config(text)
        # Pin what this master expects now. Without a listing yet the campaign has none and the engine pins it at start
        pinned = plane.expected.current() or {}
        return stores.campaigns.create_campaign(
            name or validated.config.name,
            validated.config_json,
            validated.config_hash,
            validated.classes,
            pinned_fingerprints=pinned,
            desired_state=CampaignDesiredState.RUNNING if start else CampaignDesiredState.PAUSED,
        )

    @router.post(CAMPAIGNS_PATH + "/validate")
    async def validate_campaign(request: Request, name: Optional[str] = None, start: Optional[bool] = None) -> dict:
        text, _name, _start = await _request_config(request, name, start)
        return validated_campaign_view(await _run(_validated_config, text))

    @router.post(CAMPAIGNS_PATH)
    async def create_campaign(request: Request, response: Response, name: Optional[str] = None, start: Optional[bool] = None) -> dict:
        text, chosen_name, chosen_start = await _request_config(request, name, start)
        campaign = await _run(create, text, chosen_name, chosen_start)
        response.status_code = 201
        return campaign_detail_view(campaign, await _run(_classes_of, stores, campaign.campaign_id))

    @router.get(CAMPAIGNS_PATH)
    async def list_campaigns(response: Response, state: Optional[List[CampaignActualState]] = Query(None), limit: int = 100, offset: int = 0) -> list:
        campaigns = await _run(stores.campaigns.list_campaigns, state, _page(limit), max(0, offset))
        _with_total(response, await _run(stores.campaigns.count_campaigns, state))
        return [campaign_view(campaign) for campaign in campaigns]

    @router.get(CAMPAIGNS_PATH + "/{campaign_id}")
    async def get_campaign(campaign_id: str) -> dict:
        campaign = await _campaign_or_404(stores, campaign_id)
        return campaign_detail_view(campaign, await _run(_classes_of, stores, campaign_id))

    @router.get(CAMPAIGNS_PATH + "/{campaign_id}/classes")
    async def get_classes(campaign_id: str) -> list:
        await _campaign_or_404(stores, campaign_id)
        return await _run(_classes_of, stores, campaign_id)

    @router.get(CAMPAIGNS_PATH + "/{campaign_id}/events")
    async def list_events(response: Response, campaign_id: str, after: int = 0, limit: int = 100) -> list:
        await _campaign_or_404(stores, campaign_id)
        events = await _run(stores.campaigns.list_events, campaign_id, max(0, after), _page(limit))
        _with_total(response, await _run(stores.campaigns.count_events, campaign_id, max(0, after)))
        return [event_view(event) for event in events]

    @router.get(CAMPAIGNS_PATH + "/{campaign_id}/config")
    async def get_config(campaign_id: str) -> dict:
        campaign = await _campaign_or_404(stores, campaign_id)
        versions = await _run(stores.campaigns.config_versions, campaign_id)
        return {"current_version": campaign.config_version, "versions": [config_version_view(version) for version in versions]}

    return router


def _case_routes(stores: AssuranceStores, plane: ControlPlane) -> APIRouter:
    router = APIRouter()

    @router.get(CAMPAIGNS_PATH + "/{campaign_id}/cases")
    async def list_cases(
        response: Response,
        campaign_id: str,
        class_id: Optional[str] = None,
        state: Optional[List[CaseState]] = Query(None),
        stage: Optional[List[PipelineStage]] = Query(None),
        limit: int = 100,
        offset: int = 0,
    ) -> list:
        await _campaign_or_404(stores, campaign_id)
        cases = await _run(stores.cases.list_cases, campaign_id, class_id, state, stage, _page(limit), max(0, offset))
        _with_total(response, await _run(stores.cases.count_cases, campaign_id, state, class_id=class_id, stages=stage))
        return [case_view(case) for case in cases]

    @router.get(CAMPAIGNS_PATH + "/{campaign_id}/cases/{case_id}")
    async def get_case(campaign_id: str, case_id: int) -> dict:
        case = await _run(stores.cases.get_case, case_id)
        if case is None or case.campaign_id != campaign_id:
            raise HTTPException(status_code=404, detail=f"no case {case_id} in campaign {campaign_id}")

        def gather() -> dict:
            links = stores.pipeline.pipeline_jobs_of_case(case_id)
            return {
                **case_view(case),
                "progress": case.progress,
                "jobs": [case_job_view(link, None if link.job_id is None else plane.jobs.get(link.job_id)) for link in links],
                "run_records": [run_record_view(record) for record in stores.results.list_run_records(campaign_id, case_id=case_id, limit=None)],
                "verdicts": [verdict_view(verdict) for verdict in stores.results.list_verdicts(campaign_id, case_id=case_id, limit=None)],
            }

        return await _run(gather)

    return router


def _result_routes(stores: AssuranceStores) -> APIRouter:
    router = APIRouter()

    def csv_rows(campaign_id: str, filters: tuple, limit: Optional[int], offset: int) -> Iterator[str]:
        """The verdict CSV in pages, so a campaign of any size streams in constant memory."""
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(VERDICT_COLUMNS)
        position, remaining = offset, limit
        while remaining is None or remaining > 0:
            size = CSV_PAGE if remaining is None else min(CSV_PAGE, remaining)
            page = stores.results.list_verdicts(campaign_id, *filters, size, position)
            for verdict in page:
                writer.writerow(verdict_row(verdict))
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate()
            position += len(page)
            if remaining is not None:
                remaining -= len(page)
            if len(page) < size:
                return

    @router.get(CAMPAIGNS_PATH + "/{campaign_id}/verdicts")
    async def list_verdicts(
        response: Response,
        campaign_id: str,
        class_id: Optional[str] = None,
        state: Optional[VerdictState] = None,
        run_index: Optional[int] = None,
        sensitive: Optional[bool] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        format: str = "json",
    ):
        await _campaign_or_404(stores, campaign_id)
        if format not in ("json", "csv"):
            raise HTTPException(status_code=422, detail="format is json or csv")
        filters = (class_id, None, state, run_index, sensitive)  # class, case, state, run, sensitivity: the case filter is not offered here
        total = await _run(partial(stores.results.count_verdicts, campaign_id, state, class_id=class_id, run_index=run_index, sensitive=sensitive))
        _with_total(response, total)
        if format == "json":
            verdicts = await _run(stores.results.list_verdicts, campaign_id, *filters, _page(100 if limit is None else limit), max(0, offset))
            return [verdict_view(verdict) for verdict in verdicts]
        headers = {"Content-Disposition": f'attachment; filename="verdicts-{campaign_id}.csv"', TOTAL_COUNT_HEADER: str(total)}
        return StreamingResponse(csv_rows(campaign_id, filters, limit, max(0, offset)), media_type="text/csv", headers=headers)

    @router.get(CAMPAIGNS_PATH + "/{campaign_id}/run-records")
    async def list_run_records(response: Response, campaign_id: str, class_id: Optional[str] = None, run_index: Optional[int] = None, limit: int = 100, offset: int = 0) -> list:
        await _campaign_or_404(stores, campaign_id)
        records = await _run(stores.results.list_run_records, campaign_id, class_id, None, run_index, _page(limit), max(0, offset))
        _with_total(response, await _run(stores.results.count_run_records, campaign_id, class_id, None, run_index))
        return [run_record_view(record) for record in records]

    return router


def _control_routes(stores: AssuranceStores) -> APIRouter:
    router = APIRouter()

    @router.post(CAMPAIGNS_PATH + "/{campaign_id}/{control}")
    async def control_campaign(campaign_id: str, control: str) -> dict:
        state = CONTROLS.get(control)
        if state is None:
            raise HTTPException(status_code=404, detail=f"no control {control}; use {', '.join(CONTROLS)}")
        try:
            campaign = await _run(stores.campaigns.set_desired_state, campaign_id, state)
        except UnknownCampaign:
            raise HTTPException(status_code=404, detail=f"no campaign {campaign_id}")
        except CampaignStateConflict as error:
            raise HTTPException(status_code=409, detail=str(error))
        return campaign_view(campaign)

    return router
