"""Hydrodynamic coefficients of the generated vessel model (gz-sim Hydrodynamics system, SNAME names).

Every coefficient is negative (it opposes the motion) and follows the vessel's dimensions:

- surge: the total resistance at max speed from a resistance coefficient on the wetted surface;
- sway: hull lift, linear with Clarke's (1983) derivative Y'v taken at max speed, plus quadratic
  cross-flow drag of the underwater side;
- yaw: calibrated so that full differential thrust reaches the design yaw rate (control margin
  times the vessel's max angular speed);
- heave, roll and pitch: linear damping at a fixed damping ratio of the buoyancy restoring;
- added mass from strip theory, capped below the rigid-body value because the gz-sim system
  applies it explicitly from the previous step's acceleration, which diverges at or above it.

Surge and yaw split their damping at a reference speed into a linear share (low-speed
stability) and a quadratic remainder. The coefficients are constants (the gz-sim system has no
speed-dependent terms), and the model leaves out the added-mass Coriolis terms (see
vessel_model_generator.py), so the hull is directionally stable as a twin-screw hull with skegs.
"""

import math
from typing import Dict, Tuple

RHO_WATER = 1025.0  # kg/m^3
GRAVITY = 9.81  # m/s^2


def split_damping(damping_at_reference: float, reference_speed: float, linear_share: float) -> Tuple[float, float]:
    """(linear, quadratic) coefficients whose sum at the reference speed is the given damping."""
    linear = -linear_share * damping_at_reference / reference_speed
    quadratic = -(1.0 - linear_share) * damping_at_reference / reference_speed**2
    return linear, quadratic


def surge_damping(length: float, breadth: float, draft: float, max_speed: float, resistance_coefficient: float, linear_damping_share: float) -> Tuple[float, float]:
    """(xU, xUabsU) from the total resistance at max speed on the wetted surface of a box hull."""
    wetted_surface = length * (breadth + 2.0 * draft)
    resistance = 0.5 * RHO_WATER * resistance_coefficient * wetted_surface * max_speed**2
    return split_damping(resistance, max_speed, linear_damping_share)


def damping_force(linear: float, quadratic: float, speed: float) -> float:
    """Magnitude of the damping force (or moment) at the given speed."""
    return abs(linear) * speed + abs(quadratic) * speed**2


def calculate_hydrodynamics(
    *,
    length: float,
    breadth: float,
    draft: float,
    displacement_mass: float,
    hull_ixx: float,
    hull_iyy: float,
    hull_izz: float,
    roll_metacentric_height: float,
    pitch_metacentric_height: float,
    waterplane_area: float,
    max_speed: float,
    yaw_moment_at_full_differential: float,
    design_yaw_rate: float,
    resistance_coefficient: float,
    cross_flow_drag_coefficient: float,
    linear_damping_share: float,
    block_coefficient: float,
    surge_added_mass_ratio: float,
    added_mass_cap: float,
    heave_damping_ratio: float,
    roll_pitch_damping_ratio: float,
) -> Dict[str, float]:
    mass = displacement_mass

    # Added mass (strip theory): sway as a half plate of depth T, heave as a half plate of
    # breadth B, yaw as the sway strips weighted by their lever arm.
    sway_strip = 0.5 * RHO_WATER * math.pi * draft**2 * length
    heave_strip = 0.5 * RHO_WATER * math.pi * (breadth / 2.0) ** 2 * length
    yaw_strip = sway_strip * length**2 / 12.0
    xDotU = -surge_added_mass_ratio * mass
    yDotV = -min(sway_strip, added_mass_cap * mass)
    zDotW = -min(heave_strip, added_mass_cap * mass)
    nDotR = -min(yaw_strip, added_mass_cap * hull_izz)

    # Surge: resistance at max speed.
    xU, xUabsU = surge_damping(length, breadth, draft, max_speed, resistance_coefficient, linear_damping_share)

    # Sway: hull lift (Clarke's linear derivative, made dimensional at max speed) and cross-flow drag.
    clarke_yv = math.pi * (draft / length) ** 2 * (1.0 + 0.40 * block_coefficient * breadth / draft)
    yV = -0.5 * RHO_WATER * length**2 * max_speed * clarke_yv
    yVabsV = -0.5 * RHO_WATER * cross_flow_drag_coefficient * length * draft

    # Yaw: full differential thrust balances the yaw damping at the design yaw rate.
    nR, nRabsR = split_damping(yaw_moment_at_full_differential, design_yaw_rate, linear_damping_share)

    # Heave, roll and pitch: linear damping at a damping ratio of the hydrostatic stiffness.
    heave_stiffness = RHO_WATER * GRAVITY * waterplane_area
    zW = -2.0 * heave_damping_ratio * math.sqrt(heave_stiffness * (mass - zDotW))
    roll_stiffness = mass * GRAVITY * roll_metacentric_height
    kP = -2.0 * roll_pitch_damping_ratio * math.sqrt(roll_stiffness * hull_ixx)
    pitch_stiffness = mass * GRAVITY * pitch_metacentric_height
    mQ = -2.0 * roll_pitch_damping_ratio * math.sqrt(pitch_stiffness * hull_iyy)

    return {
        "xDotU": xDotU,
        "yDotV": yDotV,
        "zDotW": zDotW,
        "nDotR": nDotR,
        "xU": xU,
        "yV": yV,
        "zW": zW,
        "kP": kP,
        "mQ": mQ,
        "nR": nR,
        "xUabsU": xUabsU,
        "yVabsV": yVabsV,
        "nRabsR": nRabsR,
    }
