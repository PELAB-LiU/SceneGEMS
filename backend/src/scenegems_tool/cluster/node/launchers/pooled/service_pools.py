"""The pooled services of one node: started on first use, sized by the node's slots, removed together."""

import threading
from typing import Callable, Dict, Optional

from scenegems_tool.cluster.node.instance_scope import InstanceScope
from scenegems_tool.cluster.node.launchers.pooled.pooled_service import PooledService
from scenegems_tool.cluster.node.launchers.pooled.scene_generation_pool import SceneGenerationPool
from scenegems_tool.cluster.node.launchers.pooled.trajectory_generation_pool import TrajectoryGenerationPool
from scenegems_tool.cluster.node.subsystem import Subsystem
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

POOL_INDEX = 0  # one pool per subsystem and node; the index leaves room for more
_POOL_CLASSES = {
    Subsystem.SCENE_GENERATION: SceneGenerationPool,
    Subsystem.TRAJECTORY_GENERATION: TrajectoryGenerationPool,
}


class ServicePools:
    def __init__(
        self,
        master_id: str,
        node_id: str,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        workers: Callable[[Subsystem], int],
        broker_network: Optional[str] = None,
    ):
        self.master_id = master_id
        self.node_id = node_id
        self.mqtt_connection = mqtt_connection
        self.reference_geofence = reference_geofence
        self.workers = workers
        self.broker_network = broker_network
        self._pools: Dict[Subsystem, PooledService] = {}
        self._lock = threading.Lock()

    def scope(self, subsystem: Subsystem) -> InstanceScope:
        return InstanceScope.pooled(self.master_id, self.node_id, subsystem.value, POOL_INDEX)

    def get(self, subsystem: Subsystem) -> PooledService:
        """The subsystem's running pool, started with the node's worker count the first time it is asked for."""
        with self._lock:
            pool = self._pools.get(subsystem)
            if pool is None:
                pool = _POOL_CLASSES[subsystem].for_scope(self.scope(subsystem), self.mqtt_connection, self.reference_geofence, self.workers(subsystem), self.broker_network)
                self._pools[subsystem] = pool
            return pool

    def shutdown(self) -> None:
        with self._lock:
            pools = list(self._pools.values())
            self._pools.clear()
        for pool in pools:
            pool.destroy()
