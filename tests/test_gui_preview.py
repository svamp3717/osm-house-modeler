from pathlib import Path

from osm_house_modeler.gui import load_obj_preview


def test_load_obj_preview_triangulates_polygon(tmp_path: Path) -> None:
    obj = tmp_path / "quad.obj"
    obj.write_text(
        "\n".join([
            "v 0 0 0",
            "v 2 0 0",
            "v 2 2 0",
            "v 0 2 0",
            "usemtl roof",
            "f 1 2 3 4",
        ]) + "\n",
        encoding="utf-8",
    )
    mesh = load_obj_preview(obj)
    assert len(mesh.vertices) == 4
    assert len(mesh.faces) == 2
    assert all(face.material == "roof" for face in mesh.faces)
    assert mesh.lo == (0.0, 0.0, 0.0)
    assert mesh.hi == (2.0, 2.0, 0.0)
