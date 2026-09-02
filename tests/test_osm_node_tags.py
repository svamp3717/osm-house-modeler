from __future__ import annotations

from io import BytesIO

import osm_house_modeler.osm as osm


_XML = b'''<osm version="0.6">
  <node id="1" lat="59.0" lon="18.0" />
  <node id="2" lat="59.0" lon="18.001">
    <tag k="entrance" v="main" />
    <tag k="door" v="yes" />
  </node>
  <node id="3" lat="59.001" lon="18.001" />
  <node id="4" lat="59.001" lon="18.0" />
  <way id="123">
    <nd ref="1" />
    <nd ref="2" />
    <nd ref="3" />
    <nd ref="4" />
    <nd ref="1" />
    <tag k="building" v="house" />
  </way>
</osm>'''


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return self.payload


def test_fetch_way_preserves_node_tags(monkeypatch) -> None:
    monkeypatch.setattr(osm, "urlopen", lambda _request, timeout=20.0: _Response(_XML))
    way = osm.fetch_way(123)
    assert len(way.lon_lat) == 4
    assert len(way.node_tags) == 4
    assert way.node_tags[1]["entrance"] == "main"
    assert way.node_tags[1]["door"] == "yes"
    assert way.node_tags[0] == {}


def test_osmway_node_tags_default_is_backward_compatible() -> None:
    way = osm.OSMWay(1, ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)), {"building": "yes"})
    assert way.node_tags == ()
