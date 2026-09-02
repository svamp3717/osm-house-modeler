from __future__ import annotations

from dataclasses import dataclass
import math
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

USER_AGENT = "osm-house-modeler/0.1 (+https://www.openstreetmap.org/)"
EARTH_RADIUS_M = 6_378_137.0


@dataclass(slots=True, frozen=True)
class OSMWay:
    way_id: int
    lon_lat: tuple[tuple[float, float], ...]
    tags: dict[str, str]
    # Tags for each referenced node, aligned with ``lon_lat``. Most OSM nodes
    # have no tags, so entries are usually empty dicts. Keeping this optional
    # data on the fetched way lets mapped ``entrance=*`` / ``door=*`` nodes
    # influence procedural door placement without making entrance metadata a
    # prerequisite for loading an otherwise valid building way.
    node_tags: tuple[dict[str, str], ...] = ()

    @property
    def center(self) -> tuple[float, float]:
        lon = sum(p[0] for p in self.lon_lat) / len(self.lon_lat)
        lat = sum(p[1] for p in self.lon_lat) / len(self.lon_lat)
        return lon, lat


def fetch_way(way_id: int, timeout: float = 20.0) -> OSMWay:
    """Fetch one OSM way and its referenced nodes from the main OSM API."""
    url = f"https://api.openstreetmap.org/api/0.6/way/{int(way_id)}/full"
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/xml"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except HTTPError as exc:
        raise RuntimeError(f"OSM returned HTTP {exc.code} for way {way_id}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach OpenStreetMap: {exc.reason}") from exc

    root = ET.fromstring(payload)
    nodes: dict[int, tuple[tuple[float, float], dict[str, str]]] = {}
    for node in root.findall("node"):
        node_id = int(node.attrib["id"])
        coordinate = (float(node.attrib["lon"]), float(node.attrib["lat"]))
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in node.findall("tag")}
        nodes[node_id] = (coordinate, tags)

    way = next((w for w in root.findall("way") if int(w.attrib["id"]) == int(way_id)), None)
    if way is None:
        raise RuntimeError(f"OSM way {way_id} was not present in the response")

    points: list[tuple[float, float]] = []
    point_tags: list[dict[str, str]] = []
    for nd in way.findall("nd"):
        ref = int(nd.attrib["ref"])
        if ref not in nodes:
            raise RuntimeError(f"OSM response is missing node {ref} referenced by way {way_id}")
        coordinate, tags = nodes[ref]
        points.append(coordinate)
        point_tags.append(dict(tags))

    if len(points) >= 2 and points[0] == points[-1]:
        points.pop()
        point_tags.pop()
    if len(points) < 3:
        raise ValueError(f"OSM way {way_id} does not form a polygon")

    tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
    if tags.get("area") == "no":
        raise ValueError(f"OSM way {way_id} is explicitly tagged area=no")
    return OSMWay(int(way_id), tuple(points), tags, tuple(point_tags))


def lon_lat_to_local_m(points: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    """Convert lon/lat into a local metric tangent-plane approximation."""
    lon0 = sum(p[0] for p in points) / len(points)
    lat0 = sum(p[1] for p in points) / len(points)
    lat0r = math.radians(lat0)
    result = []
    for lon, lat in points:
        x = EARTH_RADIUS_M * math.radians(lon - lon0) * math.cos(lat0r)
        y = EARTH_RADIUS_M * math.radians(lat - lat0)
        result.append((x, y))
    return tuple(result)


_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def parse_length_m(value: str | None) -> float | None:
    if not value:
        return None
    text = value.strip().lower().replace(",", ".")
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    number = float(match.group(0))
    if "ft" in text or "feet" in text or "foot" in text or "'" in text:
        number *= 0.3048
    elif "cm" in text:
        number *= 0.01
    return number
