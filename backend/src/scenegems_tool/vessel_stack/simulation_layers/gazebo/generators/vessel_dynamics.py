"""Parametric dynamics of the generated Gazebo vessel model.

Everything follows the ConcreteVessel's dimensions and limits: the displacement from the
block coefficient, a box inertia, a buoyant collision box that floats the vessel at its
draft, the hydrodynamic coefficients (hydrodynamics.py), twin thrusters sized from the max
speed (thrust_calculation.py) and a windage link that carries the wind force.

An override (vessel_dynamics_overrides.py) replaces an assumption before the derivation, or
a derived value after it. A derived override replaces only that value; nothing derived from
it is recomputed, so overriding the hull mass changes the draft the vessel floats at.
"""

import dataclasses
import math
from dataclasses import dataclass
from typing import Dict, FrozenSet, Mapping, Optional

from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hydrodynamics import RHO_WATER, calculate_hydrodynamics, surge_damping
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.thrust_calculation import size_thrusters

RHO_AIR = 1.225  # kg/m^3
# force_approximation_scaling_factor of the world WindEffects system [1/s]. WindEffects pushes
# a link with mass * factor * (wind velocity - link velocity), so a windage link of mass c / factor
# feels c N per m/s of relative wind, whatever the vessel's own mass.
WIND_FORCE_SCALING = 1.0
# The buoyant box is split into BUOYANCY_GRID x BUOYANCY_GRID cells. gz-sim Harmonic up to at
# least 8.15 slices each collision with a water plane that tilts with the shape (fixed upstream
# in gazebosim/gz-sim#3880, not released yet), so one box gets no restoring moment; the cells'
# differential immersion restores roll and pitch with 1 - 1/n^2 of the metacentric radius. With
# the fix the cells add up to the exact box.
BUOYANCY_GRID = 3


@dataclass(frozen=True)
class DynamicsAssumptions:
    block_coefficient: float = 0.6  # displaced volume over L * B * T
    com_depth_ratio: float = 0.5  # depth of the center of mass below the waterline, share of the draft
    thruster_mass_ratio: float = 0.001  # one thruster's mass, share of the displacement
    thruster_beam_ratio: float = 0.8  # lateral thruster offset, share of the half breadth
    thruster_aft_ratio: float = 0.9  # thruster distance aft of midship, share of the half length
    propeller_kt: float = 0.3  # open-water thrust coefficient (thrust = K_T * rho * n^2 * D^4, n in rev/s)
    resistance_coefficient: float = 0.005  # total resistance coefficient on the wetted surface
    cross_flow_drag_coefficient: float = 1.0  # sway drag coefficient of the underwater side
    linear_damping_share: float = 0.2  # linear share of the surge and yaw damping at their reference speed
    control_margin: float = 1.2  # full thrust reaches margin * max speed, full differential margin * max yaw rate
    surge_added_mass_ratio: float = 0.05  # surge added mass, share of the displacement
    added_mass_cap: float = 0.5  # cap of the other added masses, share of the rigid-body value
    heave_damping_ratio: float = 0.5
    roll_pitch_damping_ratio: float = 0.3
    air_drag_coefficient: float = 0.9  # drag coefficient of the hull side above water
    wind_reference_speed: float = 1.0  # m/s; the windage is linearized at max(wind speed, this)


@dataclass(frozen=True)
class VesselDynamics:
    """Everything the SDF needs, in SI units, body frame x forward, y port, z up, origin at the waterline."""

    # From the vessel, not overridable.
    length: float
    breadth: float
    height: float
    draft: float
    design_speed: float  # full thrust settles here (m/s)
    design_yaw_rate: float  # full differential thrust settles here (rad/s)
    # Mass and inertia.
    hull_mass: float
    com_z: float
    hull_ixx: float
    hull_iyy: float
    hull_izz: float
    # Buoyant collision box.
    collision_length: float
    collision_breadth: float
    collision_height: float
    collision_z: float
    # Windage link (wind force in N per m/s of relative wind equals its mass * WIND_FORCE_SCALING).
    windage_mass: float
    windage_z: float
    # Thrusters.
    thruster_mass: float
    thruster_x: float
    thruster_y: float
    thruster_z: float
    propeller_diameter: float
    motor_length: float
    max_thrust: float
    thrust_coefficient: float
    # Hydrodynamics (gz-sim Hydrodynamics system names).
    xDotU: float
    yDotV: float
    zDotW: float
    nDotR: float
    xU: float
    yV: float
    zW: float
    kP: float
    mQ: float
    nR: float
    xUabsU: float
    yVabsV: float
    nRabsR: float

    @property
    def total_mass(self) -> float:
        return self.hull_mass + 2.0 * self.thruster_mass + self.windage_mass

    @property
    def keel_z(self) -> float:
        return self.collision_z - self.collision_height / 2.0

    @property
    def floating_draft(self) -> float:
        """Draft at which the collision box displaces the total mass."""
        return self.total_mass / (RHO_WATER * self.collision_length * self.collision_breadth)

    @property
    def roll_metacentric_height(self) -> float:
        return _metacentric_height(self.keel_z, self.floating_draft, self.collision_breadth, self.com_z)

    @property
    def pitch_metacentric_height(self) -> float:
        return _metacentric_height(self.keel_z, self.floating_draft, self.collision_length, self.com_z)


_FIXED_FIELDS = frozenset({"length", "breadth", "height", "draft", "design_speed", "design_yaw_rate"})
ASSUMPTION_KEYS: FrozenSet[str] = frozenset(field.name for field in dataclasses.fields(DynamicsAssumptions))
VALUE_KEYS: FrozenSet[str] = frozenset(field.name for field in dataclasses.fields(VesselDynamics)) - _FIXED_FIELDS
OVERRIDE_KEYS: FrozenSet[str] = ASSUMPTION_KEYS | VALUE_KEYS


def _metacentric_height(keel_z: float, draft: float, waterplane_width: float, com_z: float) -> float:
    """GM of the gridded box floating at the given draft: center of buoyancy plus metacentric radius minus center of mass."""
    buoyancy_z = keel_z + draft / 2.0
    metacentric_radius = waterplane_width**2 / (12.0 * draft) * (1.0 - 1.0 / BUOYANCY_GRID**2)
    return buoyancy_z + metacentric_radius - com_z


def _box_inertia(mass: float, x: float, y: float, z: float) -> Dict[str, float]:
    return {"ixx": mass / 12.0 * (y**2 + z**2), "iyy": mass / 12.0 * (x**2 + z**2), "izz": mass / 12.0 * (x**2 + y**2)}


def check_inertia(name: str, ixx: float, iyy: float, izz: float) -> None:
    """Gazebo rejects a link whose principal moments break the triangle inequality (Error Code 19)."""
    moments = (ixx, iyy, izz)
    if min(moments) <= 0 or ixx + iyy < izz or iyy + izz < ixx or ixx + izz < iyy:
        raise ValueError(f"{name}: inertia ixx={ixx:.6g}, iyy={iyy:.6g}, izz={izz:.6g} is not a valid rigid body (positive moments satisfying the triangle inequality)")


def derive_vessel_dynamics(vessel: ConcreteVessel, wind_speed: float = 0.0, overrides: Optional[Mapping[str, float]] = None) -> VesselDynamics:
    overrides = dict(overrides or {})
    unknown = set(overrides) - OVERRIDE_KEYS
    if unknown:
        raise ValueError(f"vessel {vessel.id} ({vessel.type}): unknown vessel dynamics keys {sorted(unknown)}")
    if vessel.max_speed <= 0 or vessel.max_angular_speed <= 0:
        raise ValueError(f"vessel {vessel.id} ({vessel.type}): max speed and max angular speed must be positive to size the thrusters")
    a = dataclasses.replace(DynamicsAssumptions(), **{key: float(value) for key, value in overrides.items() if key in ASSUMPTION_KEYS})

    length, breadth, height, draft = vessel.length, vessel.breadth, vessel.height, vessel.draft
    freeboard = height - draft
    design_speed = a.control_margin * vessel.max_speed
    design_yaw_rate = a.control_margin * vessel.max_angular_speed

    # Mass: the displacement at the draft, shared by hull, thrusters and windage link.
    displacement_mass = RHO_WATER * a.block_coefficient * length * breadth * draft
    thruster_mass = a.thruster_mass_ratio * displacement_mass
    side_area_above_water = length * freeboard
    windage_coefficient = 0.5 * RHO_AIR * a.air_drag_coefficient * side_area_above_water * max(wind_speed, a.wind_reference_speed)
    windage_mass = windage_coefficient / WIND_FORCE_SCALING
    hull_mass = displacement_mass - 2.0 * thruster_mass - windage_mass
    com_z = -a.com_depth_ratio * draft
    inertia = _box_inertia(hull_mass, length, breadth, height)

    # Buoyant collision box: the block coefficient shrinks length and breadth so that the box
    # displaces the total mass at the draft. It is centered on the waterline (keel at -T, top at
    # +T for reserve buoyancy): measured in gz-sim 8.11, the floating height errs in proportion to
    # the box center's height above the water (about 25% of it), so only a centered box floats
    # exactly at the design draft.
    shrink = math.sqrt(a.block_coefficient)
    collision_length, collision_breadth = length * shrink, breadth * shrink
    collision_z = 0.0
    keel_z = -draft

    propeller_diameter = vessel.propeller_diameter if vessel.propeller_diameter > 0 else 0.6 * draft
    motor_length = vessel.motor_length if vessel.motor_length > 0 else 1.5 * propeller_diameter

    xU, xUabsU = surge_damping(length, breadth, draft, vessel.max_speed, a.resistance_coefficient, a.linear_damping_share)
    thrusters = size_thrusters(
        length=length,
        breadth=breadth,
        propeller_diameter=propeller_diameter,
        design_speed=design_speed,
        xU=xU,
        xUabsU=xUabsU,
        thruster_beam_ratio=a.thruster_beam_ratio,
        thruster_aft_ratio=a.thruster_aft_ratio,
        propeller_kt=a.propeller_kt,
    )
    hydro = calculate_hydrodynamics(
        length=length,
        breadth=breadth,
        draft=draft,
        displacement_mass=displacement_mass,
        hull_ixx=inertia["ixx"],
        hull_iyy=inertia["iyy"],
        hull_izz=inertia["izz"],
        roll_metacentric_height=_metacentric_height(keel_z, draft, collision_breadth, com_z),
        pitch_metacentric_height=_metacentric_height(keel_z, draft, collision_length, com_z),
        waterplane_area=collision_length * collision_breadth,
        max_speed=vessel.max_speed,
        # Full differential thrust: one thruster full ahead, the other full astern.
        yaw_moment_at_full_differential=2.0 * thrusters.max_thrust * thrusters.thruster_y,
        design_yaw_rate=design_yaw_rate,
        resistance_coefficient=a.resistance_coefficient,
        cross_flow_drag_coefficient=a.cross_flow_drag_coefficient,
        linear_damping_share=a.linear_damping_share,
        block_coefficient=a.block_coefficient,
        surge_added_mass_ratio=a.surge_added_mass_ratio,
        added_mass_cap=a.added_mass_cap,
        heave_damping_ratio=a.heave_damping_ratio,
        roll_pitch_damping_ratio=a.roll_pitch_damping_ratio,
    )

    dynamics = VesselDynamics(
        length=length,
        breadth=breadth,
        height=height,
        draft=draft,
        design_speed=design_speed,
        design_yaw_rate=design_yaw_rate,
        hull_mass=hull_mass,
        com_z=com_z,
        hull_ixx=inertia["ixx"],
        hull_iyy=inertia["iyy"],
        hull_izz=inertia["izz"],
        collision_length=collision_length,
        collision_breadth=collision_breadth,
        collision_height=2.0 * draft,
        collision_z=collision_z,
        windage_mass=windage_mass,
        windage_z=freeboard / 2.0,
        thruster_mass=thruster_mass,
        thruster_x=thrusters.thruster_x,
        thruster_y=thrusters.thruster_y,
        thruster_z=com_z,
        propeller_diameter=propeller_diameter,
        motor_length=motor_length,
        max_thrust=thrusters.max_thrust,
        thrust_coefficient=thrusters.thrust_coefficient,
        **hydro,
    )
    dynamics = dataclasses.replace(dynamics, **{key: float(value) for key, value in overrides.items() if key in VALUE_KEYS})
    _validate(dynamics, f"vessel {vessel.id} ({vessel.type})")
    return dynamics


def _validate(dynamics: VesselDynamics, name: str) -> None:
    for field in ("hull_mass", "thruster_mass", "windage_mass", "collision_length", "collision_breadth", "collision_height", "propeller_diameter", "motor_length", "max_thrust"):
        if getattr(dynamics, field) <= 0:
            raise ValueError(f"{name}: {field} must be positive, got {getattr(dynamics, field):.6g}")
    check_inertia(f"{name} hull", dynamics.hull_ixx, dynamics.hull_iyy, dynamics.hull_izz)
    if dynamics.floating_draft >= dynamics.collision_height:
        raise ValueError(f"{name}: the collision box cannot carry the total mass ({dynamics.total_mass:.6g} kg); the vessel would sink")
    if dynamics.roll_metacentric_height <= 0:
        raise ValueError(f"{name}: the hull is unstable in roll (metacentric height {dynamics.roll_metacentric_height:.3g} m); raise com_depth_ratio or the collision breadth")
