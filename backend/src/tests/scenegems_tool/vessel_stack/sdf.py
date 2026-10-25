"""Small helpers to read generated SDF and parameter text in tests."""

import xml.etree.ElementTree as ET
from typing import Dict, List


def parse_sdf(text: str) -> ET.Element:
    """Root element of a generated SDF. The generators put whitespace before the XML declaration, which Gazebo accepts."""
    return ET.fromstring(text.strip())


def plugins(element: ET.Element, filename: str) -> List[ET.Element]:
    return [plugin for plugin in element.iter("plugin") if plugin.get("filename") == filename]


def child_float(element: ET.Element, tag: str) -> float:
    child = element.find(tag)
    assert child is not None and child.text is not None, f"<{tag}> missing in <{element.tag}>"
    return float(child.text)


def parse_params(text: str) -> Dict[str, float]:
    """ArduPilot parameter file: one 'NAME<TAB>value' per line."""
    params = {}
    for line in text.splitlines():
        name, value = line.split("\t")
        params[name] = float(value)
    return params
