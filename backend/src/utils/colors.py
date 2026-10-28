from typing import Tuple

import matplotlib.colors as mcolors


# Function to lighten a color
def lighten_color(color, amount=0.5):
    """Lightens the given color by mixing it with white."""
    try:
        c = mcolors.to_rgb(color)
        lightened = [(1 - amount) * c[i] + amount for i in range(3)]
        return mcolors.to_hex(lightened)
    except ValueError:
        return color  # If color name is invalid, return it unchanged


colors = ["blue", "red", "green", "orange", "purple", "grey", "olive"]
new_colors = [c for c in list(mcolors.CSS4_COLORS.keys()) if c not in colors]
light_colors = [
    "lightblue",
    "salmon",
    "lightgreen",
    "moccasin",
    "thistle",
    "lightgrey",
    "y",
]
new_light_colors = [lighten_color(c) for c in new_colors]
colors += new_colors
light_colors += new_light_colors


def to_rgb(color: str) -> Tuple[int, int, int]:
    return tuple(int(c * 255) for c in mcolors.to_rgb(color))
