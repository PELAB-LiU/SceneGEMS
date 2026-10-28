# Base configuration parameters
# These are common parameters used across all configuration types

ONE_N_MILE_IN_M = 1852.001  # Conversion factor: 1 nautical mile = 1852.001 meters

# Numerical precision
EPSILON = 1.0e-10  # Small epsilon value for floating-point comparisons and avoiding division by zero

# Time constants (in seconds)
ONE_SECOND = 1  # One second
FOUR_MINUTES_IN_SEC = 240  # Four minutes in seconds
ONE_HOUR_IN_SEC = 3600  # One hour in seconds

SIX_NAUTICAL_MILES = 11112.006  # Six nautical miles in meters

# Heading angle bounds (in radians)
MIN_HEADING = -3.141592653589793  # Minimum heading angle: -π radians (-180 degrees)
MAX_HEADING = 3.141592653589793  # Maximum heading angle: π radians (180 degrees)

MIN_COORD = -12038.0065  # Minimum coordinate value in meters
MAX_COORD = 12038.0065  # Maximum coordinate value in meters (6.5 nautical miles = 24076.013 m)
MAX_DISTANCE = 34048.62411247095  # Maximum distance in scenario (diagonal: MAX_COORD * sqrt(2))
MAX_TEMPORAL_DISTANCE = 7200  # Maximum temporal distance: 2 hours in seconds


# Angular measurements (in radians)
PHANTOM_SHIP_ANGLE = 0.33161255787892263  # Phantom ship angle: 19.0 degrees in radians
BOW_ANGLE = 0.17453292519943295  # Bow sector angle: 10.0 degrees in radians (forward sector)
STERN_ANGLE = 2.356194490192345  # Stern sector angle: 135.0 degrees in radians (rear sector)
SIDE_ANGLE = 1.9634954084936207  # Side sector angle: 112.5 degrees in radians (port/starboard sectors)
BEAM_ROTATION_ANGLE = 0.9817477042468103  # Half of side angle: 56.25 degrees in radians
HALF_BOW_ANGLE = 0.08726646259971647  # Half of bow angle: 5.0 degrees in radians
HALF_SIDE_ANGLE = 0.9817477042468103  # Half of side angle: 56.25 degrees in radians

# Visibility distance constants (in meters)
# Based on COLREGS visibility rules for different vessel sizes
VISIBILITY_DIST_2 = 3704.002  # 2 nautical miles visibility distance (3704.002 meters)
VISIBILITY_DIST_3 = 5556.003  # 3 nautical miles visibility distance (5556.003 meters)
VISIBILITY_DIST_5 = 9260.005  # 5 nautical miles visibility distance (9260.005 meters)
VISIBILITY_DIST_6 = 11112.006  # 6 nautical miles visibility distance (11112.006 meters)
