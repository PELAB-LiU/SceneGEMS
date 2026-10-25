"""Payload pieces shared by the job types, and payload parsing.

Each job type defines its payload as a ProtocolModel (frozen, unknown fields rejected).
Large inputs such as trajectories travel as the dictionaries their models serialize to
and are checked by building the model once, so a bad payload fails before any container starts.
"""

from typing import Annotated, Any, Dict, Type, TypeVar

from pydantic import AfterValidator, Field, ValidationError

from scenegems_tool.cluster.node.job_report import JobFailed
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel

PayloadModel = TypeVar("PayloadModel", bound=ProtocolModel)


def _check_trajectories(data: Dict[str, Any]) -> Dict[str, Any]:
    from concrete_level.models.trajectories import Trajectories

    try:
        trajectories = Trajectories.from_dict(data)
    except Exception as error:
        raise ValueError(f"not a serialized Trajectories ({type(error).__name__}: {error})") from error
    if not trajectories.scene_list:
        raise ValueError("the trajectories hold no scene")
    return data


TrajectoriesData = Annotated[Dict[str, Any], AfterValidator(_check_trajectories)]  # Trajectories.to_dict()


class GeofencePayload(ProtocolModel):
    """The reference geofence: the local frame's origin on the map."""

    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    radius_meters: float = Field(gt=0.0)

    def to_geofence(self):
        from scenegems_tool.vessel_stack.contracts.sim_utils import Geofence

        return Geofence(latitude=self.latitude, longitude=self.longitude, radius_meters=self.radius_meters)


def to_trajectories(data: Dict[str, Any]):
    from concrete_level.models.trajectories import Trajectories

    return Trajectories.from_dict(data)


def parse_payload(model: Type[PayloadModel], job: JobSpec) -> PayloadModel:
    """The job's payload as its type's model; an invalid payload fails for good, without a retry."""
    try:
        return model.model_validate(job.payload)
    except ValidationError as error:
        raise JobFailed(f"Invalid {job.job_type.value} payload: {error}", retryable=False) from error
