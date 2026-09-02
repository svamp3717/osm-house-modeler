from pathlib import Path

from osm_house_modeler.viewer import _obj_texture_dependencies, _resource_roots


def test_resource_root_is_absolute_model_directory(tmp_path: Path) -> None:
    model = tmp_path / "nested" / "house.obj"
    model.parent.mkdir()
    model.write_text("v 0 0 0\n", encoding="utf-8")

    roots = _resource_roots(model)

    assert roots == [str(model.parent.resolve())]
    assert Path(roots[0]).is_absolute()


def test_obj_texture_dependencies_resolve_beside_mtl(tmp_path: Path) -> None:
    model = tmp_path / "way_1.obj"
    mtl = tmp_path / "way_1.mtl"
    wall = tmp_path / "wall.png"
    roof = tmp_path / "roof.png"
    model.write_text("mtllib way_1.mtl\nv 0 0 0\n", encoding="utf-8")
    mtl.write_text(
        "newmtl wall\nmap_Kd wall.png\n\n"
        "newmtl roof\nmap_Kd roof.png\n",
        encoding="utf-8",
    )
    wall.write_bytes(b"png")
    roof.write_bytes(b"png")

    deps = _obj_texture_dependencies(model)

    assert deps == [
        ("wall.png", wall.resolve()),
        ("roof.png", roof.resolve()),
    ]
    assert all(path.is_file() for _, path in deps)


def test_obj_texture_dependencies_include_foundation_and_openings(tmp_path: Path) -> None:
    model = tmp_path / "way_2.obj"
    mtl = tmp_path / "way_2.mtl"
    model.write_text("mtllib way_2.mtl\nv 0 0 0\n", encoding="utf-8")
    names = ["foundation.png", "wall.png", "roof.png", "window.png", "door.png"]
    mtl.write_text(
        "\n\n".join(f"newmtl m{i}\nmap_Kd {name}" for i, name in enumerate(names)) + "\n",
        encoding="utf-8",
    )
    for name in names:
        (tmp_path / name).write_bytes(b"png")
    deps = _obj_texture_dependencies(model)
    assert [name for name, _ in deps] == names
    assert all(path.is_file() for _, path in deps)
