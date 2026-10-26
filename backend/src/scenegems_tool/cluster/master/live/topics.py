"""The producers of the live channel's topics, and the wiring of the channel into a master.

    nodes             NodesTopic: NodeRegistry.on_change, then the node's view when it differs
                      from the last one sent (a heartbeat that changes nothing but the time sends nothing)
    job:<id>          JobTopics: JobActivity's listener (status, log lines, state changes reported
                      by the lease manager, the scheduler and the control plane)
    campaign:<id>     CampaignTopics: PipelineEngine.on_change after each committed tick, then the
                      new events, the summary when it changed and the classes that changed
    instance:...      ObservationHub (observation_hub.py)

Every hook first checks LiveChannel.has_subscribers and returns when nobody listens. What a
hook needs from the database is read by a CoalescingWorker: one task per producer, which reads
in worker threads in the order the keys were marked and merges marks that arrive meanwhile, so
the event loop never waits on Postgres and a burst of changes costs one read per key.
"""

import asyncio
import logging
from functools import partial
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Set

import anyio
from sqlalchemy import func, select

from scenegems_tool.cluster.master.api.campaign_views import campaign_detail_view, campaign_view, classes_view, event_view
from scenegems_tool.cluster.master.api.views import job_view, node_view
from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.master.job_activity import JobProgress
from scenegems_tool.cluster.master.live.live_channel import LiveChannel, LiveSettings, UnknownTopic
from scenegems_tool.cluster.master.live.observation_hub import BrokerClientFactory, ObservationHub
from scenegems_tool.cluster.protocol.live import (
    NODES_TOPIC,
    CampaignChanged,
    CampaignClassesChanged,
    CampaignEventAdded,
    JobChanged,
    JobLogsAdded,
    JobProgressView,
    JobStatusChanged,
    NodeChanged,
    Topic,
    TopicKind,
    campaign_topic,
    job_topic,
)
from scenegems_tool.cluster.protocol.messages import LogLine
from scenegems_tool.persistence.schema import CampaignEventRow
from scenegems_tool.persistence.stores import AssuranceStores

logger = logging.getLogger(__name__)

# Fields of a view that change without anything an observer cares about
_NODE_NOISE = ("last_seen_at",)
_JOB_NOISE = ("progress", "lease_expires_at")


def _without(view: Dict[str, Any], keys: Iterable[str]) -> Dict[str, Any]:
    return {key: value for key, value in view.items() if key not in keys}


async def _run(function: Callable[..., Any], *arguments: Any) -> Any:
    return await anyio.to_thread.run_sync(partial(function, *arguments))


class CoalescingWorker:
    """Runs handle(keys) for marked keys, one call at a time; marks during a call are handled by the next."""

    def __init__(self, handle: Callable[[List[str]], Awaitable[None]], name: str):
        self._handle = handle
        self._name = name
        self._keys: Dict[str, None] = {}  # insertion ordered
        self._task: Optional[asyncio.Task] = None

    def mark(self, key: str) -> None:
        self._keys[key] = None
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run())

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    async def idle(self) -> None:
        """Waits until every marked key was handled (for tests)."""
        while self.busy:
            await asyncio.shield(self._task)

    async def _run(self) -> None:
        while self._keys:
            keys = list(self._keys)
            self._keys.clear()
            try:
                await self._handle(keys)
            except Exception:
                logger.exception("The live %s producer failed for %s", self._name, ", ".join(keys))

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)


class NodesTopic:
    """`nodes`: every node's view, then a node's view whenever it changes."""

    def __init__(self, channel: LiveChannel, plane: ControlPlane):
        self._channel = channel
        self._plane = plane
        self._sent: Dict[str, Dict[str, Any]] = {}
        self.worker = CoalescingWorker(self._refresh, "nodes")

    async def snapshot(self, topic: Topic) -> Any:
        records = await self._plane.registry.nodes()
        return [node_view(record, self._plane.registry.session(record.node_id)) for record in records]

    def activate(self, topic: Topic) -> None:
        self._sent.clear()

    def deactivate(self, topic: Topic) -> None:
        self._sent.clear()

    def node_changed(self, node_id: str) -> None:
        if self._channel.has_subscribers(NODES_TOPIC):
            self.worker.mark(node_id)

    async def _refresh(self, node_ids: List[str]) -> None:
        registry = self._plane.registry
        for node_id in node_ids:
            session = registry.session(node_id)
            record = session.record if session is not None and not session.closed else await registry.node(node_id)
            if record is None or not self._channel.has_subscribers(NODES_TOPIC):
                continue
            view = node_view(record, registry.session(node_id))
            key = _without(view, _NODE_NOISE)
            if self._sent.get(node_id) == key:
                continue
            self._sent[node_id] = key
            self._channel.publish(NODES_TOPIC, NodeChanged(node=view).model_dump())


class JobTopics:
    """`job:<id>`: the job with its progress and recent log lines, then status, log lines and state changes.

    It is JobActivity's listener and passes status and state on to the observation hub, whose
    job instances show them too.
    """

    def __init__(self, channel: LiveChannel, plane: ControlPlane, hub: Optional[ObservationHub] = None):
        self._channel = channel
        self._plane = plane
        self._hub = hub
        self._sent: Dict[str, Dict[str, Any]] = {}
        self.worker = CoalescingWorker(self._refresh, "job")

    async def snapshot(self, topic: Topic) -> Any:
        job_id = topic.key
        # In memory first, before any await: updates queued after the subscription are newer than these
        progress = self._plane.activity.progress(job_id)
        lines = self._plane.activity.lines(job_id)
        job = await _run(self._plane.jobs.get, job_id)
        if job is None:
            raise UnknownTopic(f"no job {job_id}")
        return {**job_view(job, progress), "logs": [line.model_dump(mode="json") for line in lines]}

    def activate(self, topic: Topic) -> None:
        self._sent.pop(topic.key, None)

    def deactivate(self, topic: Topic) -> None:
        self._sent.pop(topic.key, None)

    # ActivityListener

    def job_status(self, job_id: str, progress: JobProgress) -> None:
        topic = job_topic(job_id)
        if self._channel.has_subscribers(topic):
            self._channel.publish(topic, JobStatusChanged(status=JobProgressView(progress=progress.progress, message=progress.message, at=progress.at)).model_dump())
        if self._hub is not None:
            self._hub.job_progress(job_id, progress)

    def job_logs(self, job_id: str, lines: List[LogLine]) -> None:
        topic = job_topic(job_id)
        if lines and self._channel.has_subscribers(topic):
            self._channel.publish(topic, JobLogsAdded(logs=[line.model_dump(mode="json") for line in lines]).model_dump())

    def job_changed(self, job_id: str) -> None:
        if self._channel.has_subscribers(job_topic(job_id)) or (self._hub is not None and self._hub.observes_job(job_id)):
            self.worker.mark(job_id)

    async def _refresh(self, job_ids: List[str]) -> None:
        for job_id in job_ids:
            job = await _run(self._plane.jobs.get, job_id)
            if job is None:
                continue
            if self._hub is not None:
                self._hub.job_state(job)
            topic = job_topic(job_id)
            if not self._channel.has_subscribers(topic):
                continue
            view = job_view(job, self._plane.activity.progress(job_id))
            key = _without(view, _JOB_NOISE)
            if self._sent.get(job_id) == key:
                continue
            self._sent[job_id] = key
            self._channel.publish(topic, JobChanged(job=view).model_dump())


class _Watch:
    """What the subscribers of one campaign have been sent: up to which event, the summary, each class."""

    def __init__(self) -> None:
        self.primer_taken = False  # the activating subscriber's snapshot primes it, not a later one that may finish first
        self.primed = False
        self.last_event_id = 0
        self.summary: Optional[Dict[str, Any]] = None
        self.classes: Dict[str, Dict[str, Any]] = {}


class CampaignTopics:
    """`campaign:<id>`: the campaign detail, then new events, summary changes and changed classes.

    The first subscriber's snapshot primes what was sent; the engine's notifications then make the
    worker read, in a worker thread, the events after the last one sent, the campaign and its
    classes, and publish what differs. A later subscriber's snapshot may be newer than what was
    sent, so its event updates may repeat events up to its snapshot's last_event_id.
    """

    def __init__(self, channel: LiveChannel, stores: AssuranceStores):
        self._channel = channel
        self._stores = stores
        self._watches: Dict[str, _Watch] = {}
        self.worker = CoalescingWorker(self._refresh, "campaign")

    async def snapshot(self, topic: Topic) -> Any:
        campaign_id = topic.key
        watch = self._watches.get(campaign_id)
        primes = watch is not None and not watch.primer_taken
        if primes:
            watch.primer_taken = True
        campaign, classes, last_event_id = await _run(self._read_snapshot, campaign_id)
        if campaign is None:
            raise UnknownTopic(f"no campaign {campaign_id}")
        if primes and self._watches.get(campaign_id) is watch:
            watch.primed = True
            watch.last_event_id = last_event_id
            watch.summary = campaign_view(campaign)
            watch.classes = {entry["class_id"]: entry for entry in classes}
            self.worker.mark(campaign_id)  # what changed between this read and the priming
        return {**campaign_detail_view(campaign, classes), "last_event_id": last_event_id}

    def _read_snapshot(self, campaign_id: str) -> tuple:
        stores = self._stores
        with stores.transaction() as session:
            campaign = stores.campaigns.get_campaign(campaign_id, session=session)
            if campaign is None:
                return None, [], 0
            last_event_id = session.execute(select(func.max(CampaignEventRow.id)).where(CampaignEventRow.campaign_id == campaign_id)).scalar() or 0
            classes = classes_view(stores.cases.list_classes(campaign_id, session=session), stores.results.coverage(campaign_id, session=session))
            return campaign, classes, last_event_id

    def activate(self, topic: Topic) -> None:
        self._watches[topic.key] = _Watch()

    def deactivate(self, topic: Topic) -> None:
        self._watches.pop(topic.key, None)

    def campaigns_changed(self, campaign_ids: Set[str]) -> None:
        """The pipeline engine's notification after a committed transaction."""
        for campaign_id in sorted(campaign_ids):
            if self._channel.has_subscribers(campaign_topic(campaign_id)):
                self.worker.mark(campaign_id)

    async def _refresh(self, campaign_ids: List[str]) -> None:
        for campaign_id in campaign_ids:
            watch = self._watches.get(campaign_id)
            if watch is None or not watch.primed:
                continue  # the snapshot that primes it marks the campaign again
            campaign, events, classes = await _run(self._read_changes, campaign_id, watch.last_event_id)
            if self._watches.get(campaign_id) is not watch or campaign is None:
                continue
            topic = campaign_topic(campaign_id)
            for event in events:
                self._channel.publish(topic, CampaignEventAdded(event=event_view(event)).model_dump())
                watch.last_event_id = event.event_id
            summary = campaign_view(campaign)
            if summary != watch.summary:
                watch.summary = summary
                self._channel.publish(topic, CampaignChanged(campaign=summary).model_dump())
            changed = [entry for entry in classes if watch.classes.get(entry["class_id"]) != entry]
            if changed:
                watch.classes.update({entry["class_id"]: entry for entry in changed})
                self._channel.publish(topic, CampaignClassesChanged(classes=changed).model_dump())

    def _read_changes(self, campaign_id: str, after_event_id: int) -> tuple:
        stores = self._stores
        with stores.transaction() as session:
            campaign = stores.campaigns.get_campaign(campaign_id, session=session)
            if campaign is None:
                return None, [], []
            events = stores.campaigns.list_events(campaign_id, after_event_id, None, session=session)
            classes = classes_view(stores.cases.list_classes(campaign_id, session=session), stores.results.coverage(campaign_id, session=session))
            return campaign, events, classes


class LiveProducers:
    """The channel's producers of one master, kept for shutdown and for tests."""

    def __init__(self, nodes: NodesTopic, jobs: JobTopics, campaigns: Optional[CampaignTopics], hub: ObservationHub):
        self.nodes = nodes
        self.jobs = jobs
        self.campaigns = campaigns
        self.hub = hub

    async def idle(self) -> None:
        """Waits until every producer handled what it was told (for tests)."""
        for worker in self._workers():
            await worker.idle()

    async def close(self) -> None:
        for worker in self._workers():
            await worker.close()
        await self.hub.close()

    def _workers(self) -> List[CoalescingWorker]:
        workers = [self.nodes.worker, self.jobs.worker]
        if self.campaigns is not None:
            workers.append(self.campaigns.worker)
        return workers


def create_live_channel(
    plane: ControlPlane,
    assurance: Optional[AssuranceStores] = None,
    broker: Optional[BrokerClientFactory] = None,
    settings: LiveSettings = LiveSettings(),
) -> LiveChannel:
    """A live channel on the master's control plane: hooks into the registry, the job activity and the pipeline engine.

    Without assurance stores the campaign topics are not served; without a broker the observation
    hub serves job instances only. The producers are at channel.producers.
    """
    channel = LiveChannel(settings)
    hub = ObservationHub(channel, plane, broker)
    nodes = NodesTopic(channel, plane)
    jobs = JobTopics(channel, plane, hub)
    campaigns = CampaignTopics(channel, assurance) if assurance is not None else None
    channel.add_source(TopicKind.NODES, nodes)
    channel.add_source(TopicKind.JOB, jobs)
    channel.add_source(TopicKind.INSTANCE, hub)
    plane.registry.on_change = nodes.node_changed
    plane.activity.listener = jobs
    if campaigns is not None:
        channel.add_source(TopicKind.CAMPAIGN, campaigns)
        if plane.pipeline is not None:
            plane.pipeline.on_change = campaigns.campaigns_changed
    channel.producers = LiveProducers(nodes, jobs, campaigns, hub)
    return channel
