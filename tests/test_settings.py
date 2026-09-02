from __future__ import annotations

import json

from osm_house_modeler.gui import _load_last_way_id, _save_last_way_id, _settings_path


def test_last_way_id_round_trip(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    monkeypatch.setenv("OSM_HOUSE_MODELER_SETTINGS", str(settings))

    assert _load_last_way_id() == ""
    _save_last_way_id(1387763228)
    assert _settings_path() == settings
    assert _load_last_way_id() == "1387763228"
    assert json.loads(settings.read_text(encoding="utf-8"))["last_way_id"] == 1387763228


def test_invalid_saved_way_id_is_ignored(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text('{"last_way_id": "banana"}', encoding="utf-8")
    monkeypatch.setenv("OSM_HOUSE_MODELER_SETTINGS", str(settings))
    assert _load_last_way_id() == ""
