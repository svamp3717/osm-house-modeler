from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import math
from typing import Callable, Iterable

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
UV = tuple[float, float]


@dataclass(slots=True)
class Face:
    vertices: tuple[int, int, int]
    uvs: tuple[int, int, int]
    material: str


@dataclass(slots=True, frozen=True)
class DoorAnimation:
    hinge: Vec3
    open_angle_degrees: float
    vertex_indices: tuple[int, ...]  # OBJ-style 1-based indices


@dataclass(slots=True)
class Mesh:
    vertices: list[Vec3] = field(default_factory=list)
    uvs: list[UV] = field(default_factory=list)
    faces: list[Face] = field(default_factory=list)
    detail_counts: dict[str, int] = field(default_factory=dict)
    door_animations: list[DoorAnimation] = field(default_factory=list)

    def v(self, point: Vec3) -> int:
        self.vertices.append(point)
        return len(self.vertices)

    def vt(self, uv: UV) -> int:
        self.uvs.append(uv)
        return len(self.uvs)

    def tri(self, vertices: Iterable[int], uvs: Iterable[int], material: str) -> None:
        self.faces.append(Face(tuple(vertices), tuple(uvs), material))




@dataclass(slots=True, frozen=True)
class WallOpening:
    edge: int
    center_t: float
    width: float
    z0: float
    z1: float
    kind: str


@dataclass(slots=True, frozen=True)
class FacadeLayout:
    door_edge: int = -1
    door_center_t: float = 0.5
    door_width: float = 1.0
    door_height: float = 2.1
    primary_edge: int = -1
    rear_edge: int = -1
    openings: tuple[WallOpening, ...] = ()

def signed_area(poly: list[Vec2]) -> float:
    return 0.5 * sum(
        poly[i][0] * poly[(i + 1) % len(poly)][1]
        - poly[(i + 1) % len(poly)][0] * poly[i][1]
        for i in range(len(poly))
    )


def _cross(a: Vec2, b: Vec2, c: Vec2) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _inside_triangle_strict(p: Vec2, a: Vec2, b: Vec2, c: Vec2) -> bool:
    """Return True only for points strictly inside a CCW triangle.

    Treating points on an ear edge as "inside" is a common ear-clipping trap for
    OSM footprints because map outlines often contain several collinear nodes.
    """
    eps = 1e-10
    c1, c2, c3 = _cross(a, b, p), _cross(b, c, p), _cross(c, a, p)
    return c1 > eps and c2 > eps and c3 > eps


def _distance_sq(a: Vec2, b: Vec2) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _between(a: Vec2, b: Vec2, c: Vec2, eps: float = 1e-9) -> bool:
    """Whether b lies on the closed segment a-c, assuming near-collinearity."""
    return (
        min(a[0], c[0]) - eps <= b[0] <= max(a[0], c[0]) + eps
        and min(a[1], c[1]) - eps <= b[1] <= max(a[1], c[1]) + eps
    )


def triangulate(poly: list[Vec2]) -> list[tuple[int, int, int]]:
    """Robust ear-clipping triangulation for a simple polygon.

    Returned indices refer to the original ``poly`` list. Consecutive duplicate
    and collinear OSM nodes are ignored rather than causing a concave footprint to
    fall back to an invalid triangle fan that bridges courtyards/notches.
    """
    n = len(poly)
    if n < 3:
        return []

    # Work with original indices so callers can reuse their vertex arrays.
    indices = list(range(n))
    if signed_area(poly) < 0:
        indices.reverse()

    # Strip duplicate/collinear active vertices. They do not change the polygon
    # area but can prevent all ears from being detected.
    changed = True
    while changed and len(indices) > 3:
        changed = False
        for pos in range(len(indices)):
            i0 = indices[pos - 1]
            i1 = indices[pos]
            i2 = indices[(pos + 1) % len(indices)]
            a, b, c = poly[i0], poly[i1], poly[i2]
            if _distance_sq(a, b) < 1e-16 or _distance_sq(b, c) < 1e-16:
                del indices[pos]
                changed = True
                break
            if abs(_cross(a, b, c)) <= 1e-10 and _between(a, b, c):
                del indices[pos]
                changed = True
                break

    if len(indices) < 3:
        return []

    result: list[tuple[int, int, int]] = []
    guard = 0
    max_guard = max(32, len(indices) * len(indices) * 4)

    while len(indices) > 3 and guard < max_guard:
        guard += 1
        clipped = False
        for pos in range(len(indices)):
            i0 = indices[pos - 1]
            i1 = indices[pos]
            i2 = indices[(pos + 1) % len(indices)]
            a, b, c = poly[i0], poly[i1], poly[i2]
            if _cross(a, b, c) <= 1e-10:
                continue

            blocked = False
            for k in indices:
                if k in {i0, i1, i2}:
                    continue
                if _inside_triangle_strict(poly[k], a, b, c):
                    blocked = True
                    break
            if blocked:
                continue

            result.append((i0, i1, i2))
            del indices[pos]
            clipped = True
            break

        if clipped:
            continue

        # Last-resort cleanup for near-collinear numerical noise. Deliberately do
        # not use a fan fallback on concave polygons: a wrong solid roof is worse
        # than a useful error message.
        removed = False
        for pos in range(len(indices)):
            i0 = indices[pos - 1]
            i1 = indices[pos]
            i2 = indices[(pos + 1) % len(indices)]
            if abs(_cross(poly[i0], poly[i1], poly[i2])) <= 1e-8:
                del indices[pos]
                removed = True
                break
        if not removed:
            raise ValueError("Could not triangulate building footprint; polygon may self-intersect")

    if len(indices) == 3:
        a, b, c = (poly[i] for i in indices)
        if abs(_cross(a, b, c)) > 1e-12:
            result.append(tuple(indices))
    return result


def bounds(poly: list[Vec2]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def principal_axes(poly: list[Vec2]) -> tuple[Vec2, Vec2, Vec2]:
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    xx = sum((x - cx) ** 2 for x, _ in poly)
    yy = sum((y - cy) ** 2 for _, y in poly)
    xy = sum((x - cx) * (y - cy) for x, y in poly)
    angle = 0.5 * math.atan2(2 * xy, xx - yy)
    u = (math.cos(angle), math.sin(angle))
    v = (-u[1], u[0])
    return (cx, cy), u, v


def _project(p: Vec2, center: Vec2, axis: Vec2) -> float:
    return (p[0] - center[0]) * axis[0] + (p[1] - center[1]) * axis[1]


def _clip_poly_against_line2d(poly: list[tuple[float, float]], a: tuple[float, float], b: tuple[float, float]) -> list[tuple[float, float]]:
    """Clip a 2D polygon against the left side of directed line a->b."""
    if not poly:
        return []
    ax, ay = a
    bx, by = b
    def side(p: tuple[float, float]) -> float:
        return (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)
    def inside(p: tuple[float, float]) -> bool:
        return side(p) >= -1e-9
    out: list[tuple[float, float]] = []
    prev = poly[-1]
    prev_in = inside(prev)
    prev_d = side(prev)
    for cur in poly:
        cur_in = inside(cur)
        cur_d = side(cur)
        if cur_in != prev_in:
            denom = prev_d - cur_d
            t = 0.0 if abs(denom) < 1e-12 else prev_d / denom
            inter = (prev[0] + (cur[0] - prev[0]) * t, prev[1] + (cur[1] - prev[1]) * t)
            out.append(inter)
        if cur_in:
            out.append(cur)
        prev, prev_in, prev_d = cur, cur_in, cur_d
    clean: list[tuple[float, float]] = []
    for p in out:
        if not clean or math.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1]) > 1e-7:
            clean.append(p)
    if len(clean) > 1 and math.hypot(clean[0][0] - clean[-1][0], clean[0][1] - clean[-1][1]) < 1e-7:
        clean.pop()
    return clean


def _clip_poly_to_convex2d(poly: list[tuple[float, float]], clipper: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Clip ``poly`` to a convex polygon regardless of clipper winding.

    ``_clip_poly_against_line2d`` keeps the left side of each directed edge, so
    the clip polygon must be counter-clockwise. Gable profiles are naturally
    authored left-eave -> ridge -> right-eave, which is clockwise in the local
    (distance, height) plane. Normalising here prevents the attic-window cutter
    from deleting most of the exterior gable wall and exposing the interior roof
    lining through what looks like a missing roof/texture.
    """
    out = list(poly)
    if len(clipper) < 3:
        return []
    boundary = list(clipper)
    if signed_area(boundary) < 0.0:
        boundary.reverse()
    for a, b in zip(boundary, boundary[1:] + boundary[:1]):
        out = _clip_poly_against_line2d(out, a, b)
        if not out:
            break
    return out


def _is_convex(poly: list[Vec2]) -> bool:
    sign = 0
    n = len(poly)
    for i in range(n):
        c = _cross(poly[i], poly[(i + 1) % n], poly[(i + 2) % n])
        if abs(c) < 1e-9:
            continue
        current = 1 if c > 0 else -1
        if sign and current != sign:
            return False
        sign = current
    return True


def _clip_halfplane(poly: list[Vec2], center: Vec2, axis: Vec2, keep_positive: bool) -> list[Vec2]:
    """Clip one convex polygon by dot(point-center, axis) >= 0 (or <= 0).

    The roof code only calls this on already-triangulated pieces. Clipping an
    entire concave U-shaped footprint can produce disconnected regions represented
    by one invalid polygon, which was the source of the visible roof bridges/gaps.
    """
    if not poly:
        return []

    def d(p: Vec2) -> float:
        return _project(p, center, axis)

    def inside(p: Vec2) -> bool:
        value = d(p)
        return value >= -1e-9 if keep_positive else value <= 1e-9

    out: list[Vec2] = []
    prev = poly[-1]
    prev_in = inside(prev)
    prev_d = d(prev)
    for cur in poly:
        cur_in = inside(cur)
        cur_d = d(cur)
        if cur_in != prev_in:
            denom = prev_d - cur_d
            t = 0.0 if abs(denom) < 1e-12 else prev_d / denom
            inter = (prev[0] + (cur[0] - prev[0]) * t, prev[1] + (cur[1] - prev[1]) * t)
            out.append(inter)
        if cur_in:
            out.append(cur)
        prev, prev_in, prev_d = cur, cur_in, cur_d

    clean: list[Vec2] = []
    for p in out:
        if not clean or math.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1]) > 1e-7:
            clean.append(p)
    if len(clean) > 1 and math.hypot(clean[0][0] - clean[-1][0], clean[0][1] - clean[-1][1]) < 1e-7:
        clean.pop()
    return clean


def _roof_uv(mesh: Mesh, p: Vec2, origin: Vec2) -> int:
    return mesh.vt(((p[0] - origin[0]) / 2.5, (p[1] - origin[1]) / 2.5))


def _add_roof_polygon(
    mesh: Mesh,
    roof_poly: list[Vec2],
    height_fn: Callable[[Vec2], float],
    uv_origin: Vec2,
) -> None:
    if len(roof_poly) < 3:
        return
    if signed_area(roof_poly) < 0:
        roof_poly = list(reversed(roof_poly))
    tris = triangulate(roof_poly)
    verts = [mesh.v((x, y, height_fn((x, y)))) for x, y in roof_poly]
    uvs = [_roof_uv(mesh, p, uv_origin) for p in roof_poly]
    for i0, i1, i2 in tris:
        mesh.tri((verts[i0], verts[i1], verts[i2]), (uvs[i0], uvs[i1], uvs[i2]), "roof")


def _roof_boundary_height_fn(poly: list[Vec2], wall_h: float, roof_h: float, roof_style: str):
    center, u, v = principal_axes(poly)
    pu = [_project(p, center, u) for p in poly]
    pv = [_project(p, center, v) for p in poly]
    ru = max(abs(x) for x in pu) or 1.0
    rv = max(abs(y) for y in pv) or 1.0
    short_axis = v if ru >= rv else u
    short_radius = rv if ru >= rv else ru

    if roof_style in {"gabled", "dome", "onion"}:
        power = 1.0 if roof_style == "gabled" else (1.7 if roof_style == "dome" else 0.65)

        def h(p: Vec2) -> float:
            s = abs(_project(p, center, short_axis)) / short_radius
            return wall_h + roof_h * max(0.0, 1.0 - s) ** power

        return h, center, u, v, ru, rv, short_axis

    def h(p: Vec2) -> float:
        a = abs(_project(p, center, u)) / ru
        b = abs(_project(p, center, v)) / rv
        return wall_h + roof_h * max(0.0, 1.0 - max(a, b))

    return h, center, u, v, ru, rv, short_axis


def _add_wall_quad(mesh: Mesh, p0: Vec2, p1: Vec2, z0: float, z1: float, material: str, uv_scale: float = 1.0) -> None:
    """Add a vertical quad whose lower edge is z0 and upper edge is z1."""
    if z1 <= z0 + 1e-9:
        return
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if length <= 1e-9:
        return
    a = mesh.v((p0[0], p0[1], z0))
    b = mesh.v((p1[0], p1[1], z0))
    c = mesh.v((p1[0], p1[1], z1))
    d = mesh.v((p0[0], p0[1], z1))
    ua = mesh.vt((0.0, 0.0))
    ub = mesh.vt((length / uv_scale, 0.0))
    uc = mesh.vt((length / uv_scale, (z1 - z0) / uv_scale))
    ud = mesh.vt((0.0, (z1 - z0) / uv_scale))
    mesh.tri((a, b, c), (ua, ub, uc), material)
    mesh.tri((a, c, d), (ua, uc, ud), material)


def _add_gable_closure(
    mesh: Mesh,
    p0: Vec2,
    p1: Vec2,
    wall_h: float,
    height_fn: Callable[[Vec2], float],
    center: Vec2,
    ridge_axis: Vec2,
) -> None:
    """Fill the vertical area between the eave and a gable-like roof edge.

    If an outline edge crosses the ridge, insert the ridge intersection as a real
    profile point. The previous endpoint-only implementation left triangular holes
    at gable ends and along notches in concave footprints.
    """
    d0 = _project(p0, center, ridge_axis)
    d1 = _project(p1, center, ridge_axis)
    profile: list[Vec2] = [p0]
    if d0 * d1 < -1e-10:
        t = d0 / (d0 - d1)
        ridge = (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)
        profile.append(ridge)
    profile.append(p1)

    for a2, b2 in zip(profile, profile[1:]):
        za = height_fn(a2)
        zb = height_fn(b2)
        if max(za, zb) <= wall_h + 1e-6:
            continue
        length = math.hypot(b2[0] - a2[0], b2[1] - a2[1])
        a = mesh.v((a2[0], a2[1], wall_h))
        b = mesh.v((b2[0], b2[1], wall_h))
        c = mesh.v((b2[0], b2[1], zb))
        d = mesh.v((a2[0], a2[1], za))
        ua = mesh.vt((0.0, 0.0))
        ub = mesh.vt((length / 3.0, 0.0))
        uc = mesh.vt((length / 3.0, max(0.0, zb - wall_h) / 3.0))
        ud = mesh.vt((0.0, max(0.0, za - wall_h) / 3.0))
        mesh.tri((a, b, c), (ua, ub, uc), "wall")
        mesh.tri((a, c, d), (ua, uc, ud), "wall")


def _add_boundary_closure(
    mesh: Mesh,
    p0: Vec2,
    p1: Vec2,
    wall_h: float,
    height_fn: Callable[[Vec2], float],
) -> None:
    """Fill a straight raised roof boundary above the wall eave."""
    za = height_fn(p0)
    zb = height_fn(p1)
    if max(za, zb) <= wall_h + 1e-6:
        return
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    a = mesh.v((p0[0], p0[1], wall_h))
    b = mesh.v((p1[0], p1[1], wall_h))
    c = mesh.v((p1[0], p1[1], zb))
    d = mesh.v((p0[0], p0[1], za))
    ua = mesh.vt((0.0, 0.0)); ub = mesh.vt((length / 3.0, 0.0))
    uc = mesh.vt((length / 3.0, max(0.0, zb - wall_h) / 3.0))
    ud = mesh.vt((0.0, max(0.0, za - wall_h) / 3.0))
    mesh.tri((a, b, c), (ua, ub, uc), "wall")
    mesh.tri((a, c, d), (ua, uc, ud), "wall")


def _add_foundation(mesh: Mesh, poly: list[Vec2], depth: float) -> None:
    """Add a continuous below-grade skirt and bottom slab.

    The wall base remains at Z=0. The foundation extends downward so terrain can
    intersect the model on a slope without exposing a floating wall edge.
    """
    depth = max(0.0, float(depth))
    if depth <= 1e-6:
        return
    for i, p0 in enumerate(poly):
        p1 = poly[(i + 1) % len(poly)]
        _add_wall_quad(mesh, p0, p1, -depth, 0.0, "foundation", uv_scale=1.5)

    # Close the underside as well. It is normally buried, but makes the exported
    # mesh a much less surprising solid when inspected or moved above terrain.
    minx, miny, _, _ = bounds(poly)
    for i0, i1, i2 in triangulate(poly):
        points = (poly[i0], poly[i1], poly[i2])
        verts = [mesh.v((x, y, -depth)) for x, y in points]
        uvs = [mesh.vt(((x - minx) / 2.0, (y - miny) / 2.0)) for x, y in points]
        mesh.tri((verts[2], verts[1], verts[0]), (uvs[2], uvs[1], uvs[0]), "foundation")


def _facade_panel_span(
    edge_a: Vec2, edge_b: Vec2, center_t: float, width: float, edge_margin: float
) -> tuple[float, float, float, float, float] | None:
    """Return edge-frame placement data shared by panels and real openings."""
    dx = edge_b[0] - edge_a[0]
    dy = edge_b[1] - edge_a[1]
    length = math.hypot(dx, dy)
    if length <= 1e-8 or width <= 0.0:
        return None
    ux, uy = dx / length, dy / length
    margin = max(0.08, min(edge_margin, length * 0.25))
    available = length - 2.0 * margin
    if available < 0.35:
        return None
    half = min(width * 0.5, available * 0.5)
    if half < 0.18:
        return None
    center_dist = max(margin + half, min(length - margin - half, center_t * length))
    return length, ux, uy, center_dist, half


def _add_facade_panel(
    mesh: Mesh,
    edge_a: Vec2,
    edge_b: Vec2,
    center_t: float,
    width: float,
    z0: float,
    z1: float,
    material: str,
    offset: float = 0.16,
    edge_margin: float = 0.08,
) -> bool:
    """Add a facade quad just outside a CCW wall without touching corners."""
    if z1 <= z0:
        return False
    span = _facade_panel_span(edge_a, edge_b, center_t, width, edge_margin)
    if span is None:
        return False
    _length, ux, uy, center_dist, half = span
    nx, ny = uy, -ux
    cx = edge_a[0] + ux * center_dist + nx * offset
    cy = edge_a[1] + uy * center_dist + ny * offset
    p0 = (cx - ux * half, cy - uy * half)
    p1 = (cx + ux * half, cy + uy * half)

    a = mesh.v((p0[0], p0[1], z0))
    b = mesh.v((p1[0], p1[1], z0))
    c = mesh.v((p1[0], p1[1], z1))
    d = mesh.v((p0[0], p0[1], z1))
    ua = mesh.vt((0.0, 0.0)); ub = mesh.vt((1.0, 0.0)); uc = mesh.vt((1.0, 1.0)); ud = mesh.vt((0.0, 1.0))
    mesh.tri((a, b, c), (ua, ub, uc), material)
    mesh.tri((a, c, d), (ua, uc, ud), material)
    return True


def _add_frame_ring(
    mesh: Mesh,
    point_fn: Callable[[float, float], Vec3],
    s0: float,
    s1: float,
    z0: float,
    z1: float,
    material: str = "window_frame",
) -> bool:
    """Add a simple rectangular frame without any central glass fill."""
    width = s1 - s0
    height = z1 - z0
    if width <= 0.18 or height <= 0.25:
        return False
    border = min(max(0.05, min(width, height) * 0.13), width * 0.22, height * 0.22)
    uvb = 0.12

    def quad(pa: Vec3, pb: Vec3, pc: Vec3, pd: Vec3, u0: float, v0: float, u1: float, v1: float) -> None:
        a = mesh.v(pa); b = mesh.v(pb); c = mesh.v(pc); d = mesh.v(pd)
        ua = mesh.vt((u0, v0)); ub = mesh.vt((u1, v0)); uc = mesh.vt((u1, v1)); ud = mesh.vt((u0, v1))
        mesh.tri((a, b, c), (ua, ub, uc), material)
        mesh.tri((a, c, d), (ua, uc, ud), material)

    # left / right / top / bottom frame strips using only the border regions of
    # the window texture so the frame remains but the glass centre disappears.
    quad(point_fn(s0, z0), point_fn(s0 + border, z0), point_fn(s0 + border, z1), point_fn(s0, z1), 0.0, 0.0, uvb, 1.0)
    quad(point_fn(s1 - border, z0), point_fn(s1, z0), point_fn(s1, z1), point_fn(s1 - border, z1), 1.0 - uvb, 0.0, 1.0, 1.0)
    quad(point_fn(s0 + border, z1 - border), point_fn(s1 - border, z1 - border), point_fn(s1 - border, z1), point_fn(s0 + border, z1), uvb, 0.0, 1.0 - uvb, uvb)
    quad(point_fn(s0 + border, z0), point_fn(s1 - border, z0), point_fn(s1 - border, z0 + border), point_fn(s0 + border, z0 + border), uvb, 1.0 - uvb, 1.0 - uvb, 1.0)
    return True


def _add_facade_frame(
    mesh: Mesh,
    edge_a: Vec2,
    edge_b: Vec2,
    center_t: float,
    width: float,
    z0: float,
    z1: float,
    material: str = "window_frame",
    offset: float = 0.16,
    edge_margin: float = 0.08,
) -> bool:
    span = _facade_panel_span(edge_a, edge_b, center_t, width, edge_margin)
    if span is None or z1 <= z0:
        return False
    _length, ux, uy, center_dist, half = span
    nx, ny = uy, -ux
    cx = edge_a[0] + ux * center_dist + nx * offset
    cy = edge_a[1] + uy * center_dist + ny * offset

    def point_fn(s: float, z: float) -> Vec3:
        px = cx + ux * (s - center_dist)
        py = cy + uy * (s - center_dist)
        return (px, py, z)

    return _add_frame_ring(mesh, point_fn, center_dist - half, center_dist + half, z0, z1, material)



def _opening_rectangles_for_edge(
    layout: FacadeLayout, edge: int, length: float, wall_h: float
) -> list[tuple[float, float, float, float, str]]:
    result: list[tuple[float, float, float, float, str]] = []
    for opening in layout.openings:
        if opening.edge != edge:
            continue
        half = opening.width * 0.5
        centre = max(0.0, min(length, opening.center_t * length))
        s0 = max(0.0, centre - half)
        s1 = min(length, centre + half)
        z0 = max(0.0, opening.z0)
        z1 = min(wall_h, opening.z1)
        if s1 - s0 >= 0.18 and z1 - z0 >= 0.25:
            result.append((s0, s1, z0, z1, opening.kind))
    return result


def _wall_solid_cells(
    length: float, wall_h: float, openings: list[tuple[float, float, float, float, str]]
) -> list[tuple[float, float, float, float]]:
    """Return merged rectangular wall solids around rectangular apertures."""
    sb = sorted({0.0, length, *(v for o in openings for v in o[:2])})
    zb = sorted({0.0, wall_h, *(v for o in openings for v in o[2:4])})
    cols = len(sb) - 1
    rows = len(zb) - 1
    solid = [[True] * cols for _ in range(rows)]
    for row in range(rows):
        zc = (zb[row] + zb[row + 1]) * 0.5
        for col in range(cols):
            sc = (sb[col] + sb[col + 1]) * 0.5
            solid[row][col] = not any(
                o0 < sc < o1 and oz0 < zc < oz1
                for o0, o1, oz0, oz1, _kind in openings
            )

    used = [[False] * cols for _ in range(rows)]
    rectangles: list[tuple[float, float, float, float]] = []
    for row in range(rows):
        for col in range(cols):
            if not solid[row][col] or used[row][col]:
                continue
            col_end = col + 1
            while col_end < cols and solid[row][col_end] and not used[row][col_end]:
                col_end += 1
            row_end = row + 1
            while row_end < rows and all(
                solid[row_end][candidate] and not used[row_end][candidate]
                for candidate in range(col, col_end)
            ):
                row_end += 1
            for rr in range(row, row_end):
                for cc in range(col, col_end):
                    used[rr][cc] = True
            rectangles.append((sb[col], sb[col_end], zb[row], zb[row_end]))
    return rectangles


def _add_wall_cell(
    mesh: Mesh, edge_a: Vec2, edge_b: Vec2, s0: float, s1: float, z0: float, z1: float,
    *, inward_offset: float, material: str, reverse: bool = False, uv_scale: float = 3.0,
) -> None:
    length, tangent, _outward = _edge_frame(edge_a, edge_b)
    if length <= 1e-8 or s1 <= s0 or z1 <= z0:
        return
    # For a CCW polygon the interior lies to the left of each directed edge.
    inward = (-tangent[1], tangent[0])
    def point(s: float, z: float) -> Vec3:
        return (
            edge_a[0] + tangent[0] * s + inward[0] * inward_offset,
            edge_a[1] + tangent[1] * s + inward[1] * inward_offset,
            z,
        )
    a = mesh.v(point(s0, z0)); b = mesh.v(point(s1, z0))
    c = mesh.v(point(s1, z1)); d = mesh.v(point(s0, z1))
    ua = mesh.vt((s0 / uv_scale, z0 / uv_scale)); ub = mesh.vt((s1 / uv_scale, z0 / uv_scale))
    uc = mesh.vt((s1 / uv_scale, z1 / uv_scale)); ud = mesh.vt((s0 / uv_scale, z1 / uv_scale))
    if reverse:
        mesh.tri((a, c, b), (ua, uc, ub), material)
        mesh.tri((a, d, c), (ua, ud, uc), material)
    else:
        mesh.tri((a, b, c), (ua, ub, uc), material)
        mesh.tri((a, c, d), (ua, uc, ud), material)


def _add_wall_with_openings(
    mesh: Mesh, edge_a: Vec2, edge_b: Vec2, edge: int, wall_h: float,
    layout: FacadeLayout, *, inward_offset: float = 0.0, material: str = "wall", reverse: bool = False,
) -> None:
    length = math.hypot(edge_b[0] - edge_a[0], edge_b[1] - edge_a[1])
    openings = _opening_rectangles_for_edge(layout, edge, length, wall_h)
    for s0, s1, z0, z1 in _wall_solid_cells(length, wall_h, openings):
        # The cell boundaries are derived from the same exact breakpoint values, so
        # they meet without geometric gaps. Do not overlap coplanar cells here: that
        # causes depth-buffer fighting in the OpenGL viewer and appears as black seams.
        _add_wall_cell(
            mesh, edge_a, edge_b, s0, s1, z0, z1,
            inward_offset=inward_offset, material=material, reverse=reverse,
        )


def _add_opening_reveals_and_fill(
    mesh: Mesh, poly: list[Vec2], wall_h: float, layout: FacadeLayout, wall_thickness: float,
    *, door_open_angle_degrees: float = 38.0,
) -> None:
    """Add opening reveals for true apertures.

    In simple interior mode the user explicitly wants hollow openings rather than
    decorative glass panes or a separate door leaf, so windows and doors remain
    genuinely open through the wall thickness.
    """
    window_holes = 0
    door_holes = 0
    for edge, edge_a in enumerate(poly):
        edge_b = poly[(edge + 1) % len(poly)]
        length, tangent, _outward = _edge_frame(edge_a, edge_b)
        if length <= 1e-8:
            continue
        inward = (-tangent[1], tangent[0])
        for s0, s1, z0, z1, kind in _opening_rectangles_for_edge(layout, edge, length, wall_h):
            # Four reveal strips for windows; doors deliberately omit the threshold
            # so the floor remains a genuinely walkable opening.
            def p(s: float, z: float, offset: float) -> Vec3:
                return (
                    edge_a[0] + tangent[0] * s + inward[0] * offset,
                    edge_a[1] + tangent[1] * s + inward[1] * offset,
                    z,
                )
            strips = [
                (p(s0, z0, 0.0), p(s0, z0, wall_thickness), p(s0, z1, wall_thickness), p(s0, z1, 0.0)),
                (p(s1, z0, 0.0), p(s1, z1, 0.0), p(s1, z1, wall_thickness), p(s1, z0, wall_thickness)),
                (p(s0, z1, 0.0), p(s0, z1, wall_thickness), p(s1, z1, wall_thickness), p(s1, z1, 0.0)),
            ]
            if kind not in {"door", "balcony_door"}:
                strips.append((p(s0, z0, 0.0), p(s1, z0, 0.0), p(s1, z0, wall_thickness), p(s0, z0, wall_thickness)))
            for quad in strips:
                ids = tuple(mesh.v(point) for point in quad)
                _mesh_quad(mesh, ids, "interior_wall")

            if kind == "window":
                # The visible frame belongs on the exterior face, while the reveal
                # geometry continues through the wall thickness behind it. A tiny
                # outward bias prevents the frame from z-fighting with the wall.
                exterior_offset = -0.012
                _add_frame_ring(
                    mesh, lambda s, z: p(s, z, exterior_offset),
                    s0, s1, z0, z1, "window_frame",
                )
                window_holes += 1
            elif kind == "door":
                width = s1 - s0
                hinge = p(s0, 0.0, wall_thickness * 0.55)
                angle = math.radians(max(0.0, min(110.0, door_open_angle_degrees)))
                direction = (
                    tangent[0] * math.cos(angle) + inward[0] * math.sin(angle),
                    tangent[1] * math.cos(angle) + inward[1] * math.sin(angle),
                )
                centre = (
                    hinge[0] + direction[0] * width * 0.5,
                    hinge[1] + direction[1] * width * 0.5,
                )
                perpendicular = (-direction[1], direction[0])
                first_vertex = len(mesh.vertices) + 1
                if _add_oriented_box(
                    mesh, centre, direction, perpendicular, width, 0.055,
                    max(0.02, z0), z1, "door_openable",
                ):
                    mesh.door_animations.append(DoorAnimation(
                        (hinge[0], hinge[1], max(0.02, z0)),
                        math.degrees(angle),
                        tuple(range(first_vertex, len(mesh.vertices) + 1)),
                    ))
                    door_holes += 1
            elif kind == "balcony_door":
                # Fixed balcony access leaf. It deliberately does not register a
                # DoorAnimation, so the viewer's open/close control only affects
                # the primary entrance door.
                width = s1 - s0
                centre = p((s0 + s1) * 0.5, z0, wall_thickness * 0.35)
                _add_oriented_box(
                    mesh, (centre[0], centre[1]), tangent, inward,
                    width, 0.055, max(0.02, z0), z1, "door",
                )
    if window_holes:
        mesh.detail_counts["window_holes"] = window_holes
    if door_holes:
        mesh.detail_counts["door_holes"] = door_holes
        mesh.detail_counts["openable_doors"] = door_holes


def _add_interior_floor_polygon(mesh: Mesh, poly: list[Vec2], z: float, material: str, *, reverse: bool = False) -> None:
    minx, miny, _, _ = bounds(poly)
    for i0, i1, i2 in triangulate(poly):
        points = (poly[i0], poly[i1], poly[i2])
        verts = [mesh.v((x, y, z)) for x, y in points]
        uvs = [mesh.vt(((x - minx) / 2.5, (y - miny) / 2.5)) for x, y in points]
        if reverse:
            mesh.tri((verts[2], verts[1], verts[0]), (uvs[2], uvs[1], uvs[0]), material)
        else:
            mesh.tri(tuple(verts), tuple(uvs), material)


def _add_interior_roof_polygon(
    mesh: Mesh,
    roof_poly: list[Vec2],
    height_fn: Callable[[Vec2], float],
    uv_origin: Vec2,
    *,
    z_offset: float = 0.03,
) -> None:
    if len(roof_poly) < 3:
        return
    if signed_area(roof_poly) < 0:
        roof_poly = list(reversed(roof_poly))
    tris = triangulate(roof_poly)
    verts = [mesh.v((x, y, height_fn((x, y)) - z_offset)) for x, y in roof_poly]
    uvs = [_roof_uv(mesh, p, uv_origin) for p in roof_poly]
    for i0, i1, i2 in tris:
        # Reverse the winding so the underside reads as an inward-facing surface.
        mesh.tri((verts[i2], verts[i1], verts[i0]), (uvs[i2], uvs[i1], uvs[i0]), "interior_ceiling")


def _add_interior_roof_surfaces(
    mesh: Mesh,
    poly: list[Vec2],
    wall_h: float,
    roof_h: float,
    roof_style: str,
    height_fn: Callable[[Vec2], float],
    center: Vec2,
    short_axis: Vec2,
) -> None:
    if roof_h <= 0.0 or roof_style not in {"gabled", "dome", "onion", "hipped", "pyramidal"}:
        return
    minx, miny, _, _ = bounds(poly)
    uv_origin = (minx, miny)
    base_tris = triangulate(poly)
    convex_footprint = _is_convex(poly)
    if roof_style in {"gabled", "dome", "onion"}:
        for i0, i1, i2 in base_tris:
            tri = [poly[i0], poly[i1], poly[i2]]
            side_a = _clip_halfplane(tri, center, short_axis, True)
            side_b = _clip_halfplane(tri, center, short_axis, False)
            _add_interior_roof_polygon(mesh, side_a, height_fn, uv_origin)
            _add_interior_roof_polygon(mesh, side_b, height_fn, uv_origin)
    elif roof_style in {"hipped", "pyramidal"} and convex_footprint:
        for i0, i1, i2 in base_tris:
            _add_interior_roof_polygon(mesh, [poly[i0], poly[i1], poly[i2]], height_fn, uv_origin)
    else:
        for i0, i1, i2 in base_tris:
            _add_interior_roof_polygon(mesh, [poly[i0], poly[i1], poly[i2]], height_fn, uv_origin)


def _add_simple_interior(
    mesh: Mesh, poly: list[Vec2], wall_h: float, levels: int, layout: FacadeLayout,
    *, wall_thickness: float, family: str, door_open_angle_degrees: float = 38.0,
    roof_storey: bool = False, roof_style: str = "flat", roof_h: float = 0.0,
    height_fn: Callable[[Vec2], float] | None = None, center: Vec2 = (0.0, 0.0), short_axis: Vec2 = (1.0, 0.0),
) -> None:
    """Create a lightweight hollow shell with genuine apertures and floors."""
    wall_thickness = max(0.10, min(0.55, float(wall_thickness)))
    for edge, a in enumerate(poly):
        b = poly[(edge + 1) % len(poly)]
        _add_wall_with_openings(
            mesh, a, b, edge, wall_h, layout, inward_offset=wall_thickness,
            material="interior_wall", reverse=True,
        )
    _add_opening_reveals_and_fill(
        mesh, poly, wall_h, layout, wall_thickness, door_open_angle_degrees=door_open_angle_degrees,
    )

    # Ground floor, simple intermediate slabs, and ceiling. The shell is kept
    # intentionally unfurnished and low-poly; this mode is for enterable geometry,
    # not an unsolicited interior-design simulator.
    _add_interior_floor_polygon(mesh, poly, 0.035, "interior_floor")
    level_count = max(1, int(levels))
    floor_h = wall_h / level_count
    for level in range(1, level_count):
        _add_interior_floor_polygon(mesh, poly, level * floor_h, "interior_floor")

    if roof_storey and roof_style == "gabled" and roof_h > 0.0 and height_fn is not None:
        # Add an attic floor at the eave and keep the roof volume open above it,
        # so gable/attic windows and upper-storey openings actually look into a
        # real void instead of a flat ceiling immediately behind the frame.
        _add_interior_floor_polygon(mesh, poly, wall_h + 0.035, "interior_floor")
        _add_interior_roof_surfaces(mesh, poly, wall_h, roof_h, roof_style, height_fn, center, short_axis)
        mesh.detail_counts["interior_attic_space"] = 1
    else:
        _add_interior_floor_polygon(mesh, poly, max(0.10, wall_h - 0.055), "interior_ceiling", reverse=True)
    # Simple interior deliberately stays open-plan: no procedural room dividers.
    mesh.detail_counts["interior_floors"] = level_count + (1 if roof_storey else 0)
    mesh.detail_counts["interior_partitions"] = 0



def _detail_material(material_or_style: object, default: str = "detail_masonry") -> str:
    text = str(material_or_style or "").casefold()
    if any(token in text for token in ("metal", "steel", "iron", "aluminium", "zinc", "copper", "galvan")):
        return "detail_metal"
    if any(token in text for token in ("wood", "timber", "plank", "board")):
        return "detail_wood"
    return default


def _edge_frame(a: Vec2, b: Vec2) -> tuple[float, Vec2, Vec2]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return 0.0, (1.0, 0.0), (0.0, -1.0)
    tangent = (dx / length, dy / length)
    # Polygon is normalised CCW, so the exterior is to the right of the edge.
    outward = (tangent[1], -tangent[0])
    return length, tangent, outward


def _point_on_edge(a: Vec2, b: Vec2, t: float) -> Vec2:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _mesh_quad(mesh: Mesh, points: tuple[int, int, int, int], material: str) -> None:
    u0 = mesh.vt((0.0, 0.0)); u1 = mesh.vt((1.0, 0.0))
    u2 = mesh.vt((1.0, 1.0)); u3 = mesh.vt((0.0, 1.0))
    a, b, c, d = points
    mesh.tri((a, b, c), (u0, u1, u2), material)
    mesh.tri((a, c, d), (u0, u2, u3), material)


def _add_oriented_box(
    mesh: Mesh, center: Vec2, axis_width: Vec2, axis_depth: Vec2,
    width: float, depth: float, z0: float, z1: float, material: str,
) -> bool:
    width = max(0.01, float(width)); depth = max(0.01, float(depth))
    if z1 <= z0 + 1e-6:
        return False
    wx, wy = axis_width
    dx, dy = axis_depth
    wl = math.hypot(wx, wy) or 1.0
    dl = math.hypot(dx, dy) or 1.0
    wx, wy = wx / wl, wy / wl
    dx, dy = dx / dl, dy / dl
    hw, hd = width * 0.5, depth * 0.5
    corners = [
        (center[0] - wx * hw - dx * hd, center[1] - wy * hw - dy * hd),
        (center[0] + wx * hw - dx * hd, center[1] + wy * hw - dy * hd),
        (center[0] + wx * hw + dx * hd, center[1] + wy * hw + dy * hd),
        (center[0] - wx * hw + dx * hd, center[1] - wy * hw + dy * hd),
    ]
    # ``axis_depth`` is often the building's outward/right-hand normal. In that
    # common case the four generated XY corners are clockwise, so the old box
    # helper emitted downward/inward normals on half the balcony rail/post faces.
    # Pyglet still draws those faces with culling disabled, but its lighting makes
    # them nearly black, which looks like a missing texture. Normalise the footprint
    # winding here so every box has outward-facing side normals and an upward top.
    if signed_area(corners) < 0.0:
        corners.reverse()
    bottom = [mesh.v((x, y, z0)) for x, y in corners]
    top = [mesh.v((x, y, z1)) for x, y in corners]
    _mesh_quad(mesh, (bottom[0], bottom[3], bottom[2], bottom[1]), material)
    _mesh_quad(mesh, (top[0], top[1], top[2], top[3]), material)
    _mesh_quad(mesh, (bottom[0], bottom[1], top[1], top[0]), material)
    _mesh_quad(mesh, (bottom[1], bottom[2], top[2], top[1]), material)
    _mesh_quad(mesh, (bottom[2], bottom[3], top[3], top[2]), material)
    _mesh_quad(mesh, (bottom[3], bottom[0], top[0], top[3]), material)
    return True


def _add_stair_run(
    mesh: Mesh,
    door_point: Vec2,
    tangent: Vec2,
    outward: Vec2,
    *,
    width: float,
    tread: float,
    rise: float,
    count: int,
    material: str,
) -> None:
    """Add one clean stepped prism using visible treads/risers instead of boxes.

    Stacking closed boxes creates coincident internal faces and very thin exposed
    strips. Pyglet's OBJ renderer can shade those strips nearly black, which made
    otherwise textured stairs look untextured. This emits only the actual visible
    staircase skin, with stable normals and UVs.
    """
    count = max(1, int(count))
    width = max(0.20, float(width))
    tread = max(0.12, float(tread))
    rise = max(0.06, float(rise))
    hw = width * 0.5
    bottom = -rise * count
    top_bias = 0.025

    def point(s: float, d: float, z: float) -> Vec3:
        return (
            door_point[0] + tangent[0] * s + outward[0] * d,
            door_point[1] + tangent[1] * s + outward[1] * d,
            z,
        )

    def quad(points: tuple[Vec3, Vec3, Vec3, Vec3], uv_w: float, uv_h: float) -> None:
        ids = tuple(mesh.v(v) for v in points)
        uv_w = max(0.05, uv_w)
        uv_h = max(0.05, uv_h)
        u0 = mesh.vt((0.0, 0.0)); u1 = mesh.vt((uv_w, 0.0))
        u2 = mesh.vt((uv_w, uv_h)); u3 = mesh.vt((0.0, uv_h))
        a, b, c, d = ids
        mesh.tri((a, b, c), (u0, u1, u2), material)
        mesh.tri((a, c, d), (u0, u2, u3), material)

    # Treads and risers. Segment zero is the innermost/highest tread.
    for step in range(count):
        d0 = step * tread
        d1 = (step + 1) * tread
        top = top_bias - step * rise
        # t x outward is clockwise in XY, so this ordering points the tread up.
        quad((
            point(-hw, d0, top), point(-hw, d1, top),
            point(hw, d1, top), point(hw, d0, top),
        ), width / 1.5, tread / 1.5)
        if step > 0:
            higher = top_bias - (step - 1) * rise
            quad((
                point(-hw, d0, top), point(hw, d0, top),
                point(hw, d0, higher), point(-hw, d0, higher),
            ), width / 1.5, rise / 1.5)

        # Side skins are non-overlapping rectangles, one per tread depth.
        quad((
            point(-hw, d0, bottom), point(-hw, d1, bottom),
            point(-hw, d1, top), point(-hw, d0, top),
        ), tread / 1.5, max(0.05, top - bottom) / 1.5)
        quad((
            point(hw, d1, bottom), point(hw, d0, bottom),
            point(hw, d0, top), point(hw, d1, top),
        ), tread / 1.5, max(0.05, top - bottom) / 1.5)

    # Close only the exposed outer end. The wall/foundation hides the inner end.
    outer_d = count * tread
    outer_top = top_bias - (count - 1) * rise
    quad((
        point(-hw, outer_d, bottom), point(hw, outer_d, bottom),
        point(hw, outer_d, outer_top), point(-hw, outer_d, outer_top),
    ), width / 1.5, max(0.05, outer_top - bottom) / 1.5)


def _largest_triangle_anchor(poly: list[Vec2]) -> Vec2:
    best_area = -1.0
    best = poly[0]
    for i0, i1, i2 in triangulate(poly):
        a, b, c = poly[i0], poly[i1], poly[i2]
        area = abs(_cross(a, b, c)) * 0.5
        if area > best_area:
            best_area = area
            best = ((a[0] + b[0] + c[0]) / 3.0, (a[1] + b[1] + c[1]) / 3.0)
    return best


def _add_exterior_details(
    mesh: Mesh, poly: list[Vec2], wall_h: float, roof_h: float, roof_style: str,
    height_fn: Callable[[Vec2], float], center: Vec2, u: Vec2, v: Vec2, ridge_axis: Vec2,
    *, levels: int, foundation_depth: float, facade: FacadeLayout,
    building_class: str, detail_spec: dict[str, object] | None, seed: int | str,
) -> None:
    """Add seeded secondary architecture without changing the footprint shell."""
    spec = dict(detail_spec or {})
    if not spec or not poly:
        return

    def block(name: str) -> dict[str, object]:
        raw = spec.get(name) or {}
        return dict(raw) if isinstance(raw, dict) else {}

    def enabled(name: str) -> bool:
        return bool(block(name).get("enabled", False))

    edge = facade.door_edge if facade.door_edge >= 0 else facade.primary_edge
    if edge >= 0:
        a, b = poly[edge], poly[(edge + 1) % len(poly)]
        edge_len, tangent, outward = _edge_frame(a, b)
        door_point = _point_on_edge(a, b, facade.door_center_t)
    else:
        a = b = poly[0]
        edge_len, tangent, outward = 0.0, (1.0, 0.0), (0.0, -1.0)
        door_point = poly[0]

    stairs = block("stairs")
    if facade.door_edge >= 0 and enabled("stairs") and foundation_depth > 0.08 and facade.door_width < 1.8:
        rise = max(0.09, float(stairs.get("step_rise_m", 0.16) or 0.16))
        tread = max(0.22, float(stairs.get("step_depth_m", 0.30) or 0.30))
        max_steps = max(1, int(float(stairs.get("max_steps", 4) or 4)))
        count = max(1, min(max_steps, int(max(rise, min(foundation_depth, rise * max_steps)) / rise)))
        width = max(facade.door_width + 0.35, float(stairs.get("width_m", facade.door_width + 0.6) or facade.door_width + 0.6))
        width = min(width, max(facade.door_width + 0.2, edge_len - 0.35))
        stair_finish = str(stairs.get("material") or stairs.get("type") or "").casefold()
        # Use primary materials here on purpose. Pyglet's legacy OBJ path is much
        # more reliable with the always-present wall/foundation texture groups than
        # with optional secondary detail groups. Timber stairs inherit the facade;
        # stone/concrete/metal stairs use the foundation texture.
        material = "wall" if any(token in stair_finish for token in ("wood", "timber", "plank", "board")) else "foundation"
        _add_stair_run(
            mesh, door_point, tangent, outward,
            width=width, tread=tread, rise=rise, count=count, material=material,
        )
        mesh.detail_counts["stairs"] = count

    porch = block("porches")
    if facade.door_edge >= 0 and enabled("porches") and facade.door_width < 1.8 and edge_len > facade.door_width + 0.8:
        width = max(facade.door_width + 0.8, float(porch.get("width_m", 2.4) or 2.4))
        width = min(width, max(facade.door_width + 0.4, edge_len - 0.45))
        depth = max(0.55, float(porch.get("depth_m", 1.25) or 1.25))
        material = _detail_material(porch.get("material") or porch.get("type"), "detail_wood")
        slab_center = (door_point[0] + outward[0] * depth * 0.5, door_point[1] + outward[1] * depth * 0.5)
        _add_oriented_box(mesh, slab_center, tangent, outward, width, depth, -0.08, 0.02, material)
        canopy_z = min(wall_h - 0.15, facade.door_height + 0.30)
        canopy_material = "roof" if any(k in str(porch.get("type", "")).casefold() for k in ("pitched", "shingle", "tile")) else material
        _add_oriented_box(mesh, slab_center, tangent, outward, width, depth, canopy_z, canopy_z + 0.12, canopy_material)
        post = 0.10
        front = (door_point[0] + outward[0] * (depth - post), door_point[1] + outward[1] * (depth - post))
        for sign in (-1.0, 1.0):
            pc = (front[0] + tangent[0] * sign * (width * 0.5 - post), front[1] + tangent[1] * sign * (width * 0.5 - post))
            _add_oriented_box(mesh, pc, tangent, outward, post, post, 0.0, canopy_z, material)
        mesh.detail_counts["porches"] = 1

    balcony = block("balconies")
    if edge >= 0 and enabled("balconies") and levels >= 2 and edge_len >= 2.6:
        requested = max(1, int(float(balcony.get("count", 1) or 1)))
        count = min(requested, max(1, levels - 1), 3)
        width = max(1.4, float(balcony.get("width_m", 2.8) or 2.8))
        width = min(width, edge_len - 0.55)
        depth = max(0.65, float(balcony.get("depth_m", 1.10) or 1.10))
        rail_h = max(0.72, float(balcony.get("railing_height_m", 0.95) or 0.95))
        balcony_detail_material = _detail_material(balcony.get("material") or balcony.get("type"), "detail_metal")
        # Use a dedicated balcony material/object in OBJ output. Reusing wall/roof/
        # foundation materials made pyglet merge balcony faces into large material
        # groups, and some variants ended up rendered with a flat fallback rather
        # than a bound texture. A dedicated material has one unambiguous map_Kd.
        is_masonry_balcony = balcony_detail_material == "detail_masonry"
        material = "balcony"
        slab_material = "balcony"
        floor_h = wall_h / max(1, levels)
        centre_t = facade.door_center_t if 0.2 < facade.door_center_t < 0.8 else 0.5
        wall_point = _point_on_edge(a, b, centre_t)
        for idx in range(count):
            level = min(levels - 1, idx + 1)
            floor_z = level * floor_h
            bc = (wall_point[0] + outward[0] * depth * 0.5, wall_point[1] + outward[1] * depth * 0.5)
            _add_oriented_box(mesh, bc, tangent, outward, width, depth, floor_z - 0.12, floor_z, slab_material)
            # Masonry balconies use a parapet. Metal/timber variants use open
            # rails with posts, which reads far better than a mysterious solid
            # sheet floating in front of the windows.
            front_c = (wall_point[0] + outward[0] * (depth - 0.04), wall_point[1] + outward[1] * (depth - 0.04))
            if is_masonry_balcony:
                _add_oriented_box(mesh, front_c, tangent, outward, width, 0.09, floor_z, floor_z + rail_h * 0.78, material)
            else:
                _add_oriented_box(mesh, front_c, tangent, outward, width, 0.07, floor_z + rail_h - 0.08, floor_z + rail_h, material)
                post_spacing = max(0.65, float(balcony.get("post_spacing_m", 1.35) or 1.35))
                posts = max(2, int(math.ceil(width / post_spacing)) + 1)
                for post_index in range(posts):
                    offset_t = -width * 0.5 + width * post_index / max(1, posts - 1)
                    pc = (front_c[0] + tangent[0] * offset_t, front_c[1] + tangent[1] * offset_t)
                    _add_oriented_box(mesh, pc, tangent, outward, 0.055, 0.055, floor_z, floor_z + rail_h, material)
            for sign in (-1.0, 1.0):
                side_c = (
                    wall_point[0] + tangent[0] * sign * (width * 0.5 - 0.035) + outward[0] * depth * 0.5,
                    wall_point[1] + tangent[1] * sign * (width * 0.5 - 0.035) + outward[1] * depth * 0.5,
                )
                if is_masonry_balcony:
                    _add_oriented_box(mesh, side_c, outward, tangent, depth, 0.07, floor_z, floor_z + rail_h * 0.78, material)
                else:
                    _add_oriented_box(mesh, side_c, outward, tangent, depth, 0.06, floor_z + rail_h - 0.08, floor_z + rail_h, material)
                    for fraction in (0.0, 0.5, 1.0):
                        pc = (
                            side_c[0] + outward[0] * (fraction - 0.5) * depth,
                            side_c[1] + outward[1] * (fraction - 0.5) * depth,
                        )
                        _add_oriented_box(mesh, pc, tangent, outward, 0.05, 0.05, floor_z, floor_z + rail_h, material)
        mesh.detail_counts["balconies"] = count

    chimney = block("chimneys")
    if building_class not in {"shed", "garage", "apartments", "apartment"} and enabled("chimneys") and roof_h > 0.25 and roof_style not in {"dome", "onion"}:
        count = min(2, max(1, int(float(chimney.get("count", 1) or 1))))
        width = max(0.28, float(chimney.get("width_m", 0.52) or 0.52))
        depth = max(0.24, float(chimney.get("depth_m", 0.42) or 0.42))
        height = max(0.45, float(chimney.get("height_m", 1.15) or 1.15))
        material = _detail_material(chimney.get("material") or chimney.get("type"), "detail_masonry")
        anchor = _largest_triangle_anchor(poly)
        for index in range(count):
            shift = (index - (count - 1) * 0.5) * max(0.8, width * 2.1)
            point = (anchor[0] + u[0] * shift, anchor[1] + u[1] * shift)
            # If an offset leaves the polygon's safe roof area, fall back to the guaranteed anchor.
            if count > 1:
                point = ((point[0] + anchor[0]) * 0.5, (point[1] + anchor[1]) * 0.5)
            roof_z = height_fn(point)
            base_z = max(wall_h, roof_z - 0.22)
            _add_oriented_box(mesh, point, u, v, width, depth, base_z, roof_z + height, material)
            if material != "detail_metal":
                _add_oriented_box(mesh, point, u, v, width * 1.12, depth * 1.12, roof_z + height, roof_z + height + 0.08, material)
        mesh.detail_counts["chimneys"] = count

    rain = block("rainwater")
    if bool(rain.get("enabled", False)):
        material = _detail_material(rain.get("material"), "detail_metal")
        gutter_w = max(0.05, float(rain.get("gutter_width_m", 0.10) or 0.10))
        down_w = max(0.045, float(rain.get("downspout_width_m", 0.08) or 0.08))
        gutter_edges: list[int] = []
        for i, p0 in enumerate(poly):
            p1 = poly[(i + 1) % len(poly)]
            length, et, eo = _edge_frame(p0, p1)
            if length < 0.5:
                continue
            if roof_style == "gabled":
                d0 = _project(p0, center, ridge_axis); d1 = _project(p1, center, ridge_axis)
                if d0 * d1 < -1e-9:
                    continue  # gable end, not an eave
            elif roof_style in {"dome", "onion"}:
                continue
            mid = _point_on_edge(p0, p1, 0.5)
            gc = (mid[0] + eo[0] * gutter_w * 0.55, mid[1] + eo[1] * gutter_w * 0.55)
            _add_oriented_box(mesh, gc, et, eo, length, gutter_w, wall_h - gutter_w * 0.35, wall_h + gutter_w * 0.35, material)
            gutter_edges.append(i)
        if gutter_edges:
            wanted = min(max(0, int(float(rain.get("downspouts", 2) or 2))), len(gutter_edges) * 2)
            candidates: list[tuple[Vec2, Vec2, Vec2]] = []
            seen: set[tuple[int, int]] = set()
            for i in gutter_edges:
                p0, p1 = poly[i], poly[(i + 1) % len(poly)]
                _length, et, eo = _edge_frame(p0, p1)
                for pnt in (p0, p1):
                    key = (round(pnt[0] * 1000), round(pnt[1] * 1000))
                    if key in seen:
                        continue
                    seen.add(key); candidates.append((pnt, et, eo))
            for pnt, et, eo in candidates[:wanted]:
                dc = (pnt[0] + eo[0] * down_w * 0.6, pnt[1] + eo[1] * down_w * 0.6)
                _add_oriented_box(mesh, dc, et, eo, down_w, down_w, -0.05, wall_h, material)
            mesh.detail_counts["gutters"] = len(gutter_edges)
            mesh.detail_counts["downspouts"] = min(wanted, len(candidates))

def _nearest_wall_position(poly: list[Vec2], point: Vec2, max_distance: float = 1.8) -> tuple[int, float] | None:
    best: tuple[float, float, int, float] | None = None
    for edge in range(len(poly)):
        a = poly[edge]
        b = poly[(edge + 1) % len(poly)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length <= 1e-9:
            continue
        ux, uy = dx / length, dy / length
        along = max(0.0, min(length, (point[0] - a[0]) * ux + (point[1] - a[1]) * uy))
        qx, qy = a[0] + ux * along, a[1] + uy * along
        distance = math.hypot(point[0] - qx, point[1] - qy)
        if distance > max_distance:
            continue
        score = (distance, -length, edge, along)
        if best is None or score[:2] < best[:2]:
            best = score
    if best is None:
        return None
    return best[2], best[3]


def _float(spec: dict[str, object], key: str, default: float) -> float:
    try:
        return float(spec.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _add_windows_and_door(
    mesh: Mesh,
    poly: list[Vec2],
    wall_h: float,
    levels: int,
    add_windows: bool,
    add_doors: bool,
    *,
    family: str = "residential",
    building_class: str = "residential",
    outbuilding_kind: str = "",
    seed: int | str = 0,
    entrance_points: tuple[Vec2, ...] = (),
    window_spec: dict[str, object] | None = None,
    door_spec: dict[str, object] | None = None,
    balcony_spec: dict[str, object] | None = None,
    emit_panels: bool = True,
) -> FacadeLayout:
    if wall_h < 2.0 or not poly:
        return FacadeLayout()

    detailed_window_spec = bool(window_spec)
    window_spec = dict(window_spec or {})
    door_spec = dict(door_spec or {})
    balcony_spec = dict(balcony_spec or {})
    levels = max(1, min(30, int(levels)))
    floor_h = wall_h / levels
    edge_lengths = [
        math.hypot(
            poly[(i + 1) % len(poly)][0] - poly[i][0],
            poly[(i + 1) % len(poly)][1] - poly[i][1],
        )
        for i in range(len(poly))
    ]
    openings: list[WallOpening] = []

    def add_opening(
        edge: int, center_t: float, width: float, z0: float, z1: float,
        kind: str, *, material: str, offset: float, edge_margin: float,
    ) -> bool:
        if edge < 0 or edge >= len(poly) or z1 <= z0:
            return False
        a = poly[edge]
        b = poly[(edge + 1) % len(poly)]
        span = _facade_panel_span(a, b, center_t, width, edge_margin)
        if span is None:
            return False
        length, _ux, _uy, center_dist, half = span
        actual_center_t = center_dist / length
        actual_width = half * 2.0
        openings.append(WallOpening(edge, actual_center_t, actual_width, z0, z1, kind))
        if emit_panels:
            _add_facade_panel(
                mesh, a, b, actual_center_t, actual_width, z0, z1,
                material, offset=offset, edge_margin=edge_margin,
            )
        return True

    corner_clearance = max(0.35, _float(door_spec, "corner_clearance_m", 0.7))
    keep_clear = max(0.15, _float(door_spec, "keep_clear_of_windows_m", 0.35))
    door_width = max(0.72, _float(door_spec, "primary_width_m", 1.0))
    door_height = max(1.8, _float(door_spec, "primary_height_m", 2.1))
    if family in {"industrial", "agricultural"} or (family == "outbuilding" and outbuilding_kind == "garage"):
        door_width = max(door_width, _float(door_spec, "utility_width_m", door_width))
        door_height = max(door_height, _float(door_spec, "utility_height_m", door_height))
    elif family == "outbuilding":
        door_width = max(0.72, _float(door_spec, "service_width_m", door_width))
        door_height = max(1.8, _float(door_spec, "service_height_m", door_height))
    door_height = min(wall_h - 0.08, door_height)

    door_edge = -1
    door_center_t = 0.5
    if add_doors:
        # A mapped OSM entrance is authoritative when it lies close to this way.
        for point in entrance_points:
            located = _nearest_wall_position(poly, point)
            if located is None:
                continue
            edge, along = located
            length = edge_lengths[edge]
            minimum_room = door_width + 2.0 * corner_clearance
            if length < minimum_room:
                continue
            door_edge = edge
            door_center_t = max(
                (corner_clearance + door_width * 0.5) / length,
                min(1.0 - (corner_clearance + door_width * 0.5) / length, along / length),
            )
            break

        if door_edge < 0 and edge_lengths:
            longest = max(edge_lengths)
            candidates = [
                index for index, length in enumerate(edge_lengths)
                if length >= door_width + 2.0 * corner_clearance and length >= longest * 0.72
            ]
            if candidates:
                digest = sha256(f"{seed}:{family}:{building_class}:door".encode("utf-8")).digest()
                door_edge = candidates[int.from_bytes(digest[:4], "big") % len(candidates)]
                # Rerolls can shift the door as well as choosing a facade, but stay
                # within the region's configured corner clearances.
                length = edge_lengths[door_edge]
                low = (corner_clearance + door_width * 0.5) / length
                high = 1.0 - low
                if high > low:
                    unit = int.from_bytes(digest[4:8], "big") / 2**32
                    door_center_t = low + (high - low) * (0.34 + 0.32 * unit)

    if door_edge >= 0:
        add_opening(
            door_edge, door_center_t, door_width, 0.025, door_height,
            "door", material="door", offset=0.18, edge_margin=corner_clearance,
        )

    def edge_midpoint(index: int) -> Vec2:
        a = poly[index]
        b = poly[(index + 1) % len(poly)]
        return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)

    primary_edge = door_edge if door_edge >= 0 else (max(range(len(edge_lengths)), key=lambda i: edge_lengths[i]) if edge_lengths else -1)
    rear_edge = -1
    if primary_edge >= 0 and len(poly) > 1:
        px, py = edge_midpoint(primary_edge)
        rear_candidates = [i for i in range(len(poly)) if i != primary_edge]
        if rear_candidates:
            rear_edge = max(
                rear_candidates,
                key=lambda i: (edge_midpoint(i)[0] - px) ** 2 + (edge_midpoint(i)[1] - py) ** 2,
            )
    # Every generated balcony gets a fixed access door on the wall behind it.
    # Plan these before ordinary windows so the facade generator can keep window
    # bays clear of the balcony-door footprint. In simple-interior mode these are
    # true wall apertures with a fixed leaf; exterior-only keeps the historical
    # facade-panel approach used by ordinary windows and doors.
    balcony_door_count = 0
    balcony_enabled = bool(balcony_spec.get("enabled", False))
    balcony_edge = door_edge if door_edge >= 0 else primary_edge
    if balcony_enabled and balcony_edge >= 0 and levels >= 2 and edge_lengths[balcony_edge] >= 2.6:
        requested = max(1, int(float(balcony_spec.get("count", 1) or 1)))
        balcony_count = min(requested, max(1, levels - 1), 3)
        balcony_door_width = max(0.72, min(1.45, float(balcony_spec.get("door_width_m", 0.95) or 0.95)))
        balcony_door_height = max(1.85, min(2.40, float(balcony_spec.get("door_height_m", 2.08) or 2.08)))
        centre_t = door_center_t if 0.2 < door_center_t < 0.8 else 0.5
        floor_h = wall_h / levels
        for idx in range(balcony_count):
            level = min(levels - 1, idx + 1)
            z0 = level * floor_h + 0.025
            z1 = min(wall_h - 0.08, (level + 1) * floor_h - 0.12, z0 + balcony_door_height)
            if z1 - z0 < 1.65:
                continue
            if add_opening(
                balcony_edge, centre_t, balcony_door_width, z0, z1,
                "balcony_door", material="door", offset=0.18, edge_margin=corner_clearance,
            ):
                balcony_door_count += 1
    if balcony_door_count:
        mesh.detail_counts["balcony_doors"] = balcony_door_count

    def current_layout() -> FacadeLayout:
        return FacadeLayout(
            door_edge, door_center_t, door_width, door_height, primary_edge, rear_edge, tuple(openings)
        )

    if not add_windows:
        return current_layout()
    if building_class in {"shed", "garage", "barn"}:
        # Hard semantic rule: these utility/agricultural classes stay windowless
        # even when a broad regional family profile contains domestic-ish defaults.
        return current_layout()
    if family in {"outbuilding", "agricultural", "industrial"} and not detailed_window_spec:
        # Backward-compatible generic utility shells stay windowless. Detailed
        # house_styles profiles can explicitly opt them into utility/clerestory windows.
        return current_layout()

    density = max(0.0, _float(window_spec, "density_multiplier", 1.0))
    if density <= 0.01:
        return current_layout()
    window_width = max(0.42, _float(window_spec, "width_m", 1.15))
    window_height = max(0.38, _float(window_spec, "height_m", 1.20))
    sill_height = max(0.25, _float(window_spec, "sill_height_m", 0.9))
    edge_margin = max(0.30, _float(window_spec, "edge_margin_m", 0.55))
    target_spacing = max(1.1, _float(window_spec, "target_bay_spacing_m", 3.0) / max(0.25, density))
    set_name = str(window_spec.get("set_name", "context_default") or "context_default")
    placement_style = str(window_spec.get("placement_style", "regular_aligned") or "regular_aligned")
    horizontal_jitter = max(0.0, min(0.45, _float(window_spec, "horizontal_jitter_fraction", 0.0)))
    vertical_jitter = max(0.0, min(0.40, _float(window_spec, "vertical_jitter_m", 0.0)))
    omit_probability = max(0.0, min(0.85, _float(window_spec, "omit_bay_probability", 0.0)))
    phase_fraction = max(0.0, min(0.45, _float(window_spec, "floor_phase_shift_fraction", 0.0)))
    front_density = max(0.1, _float(window_spec, "front_density_multiplier", 1.0))
    side_density = max(0.1, _float(window_spec, "side_density_multiplier", 1.0))
    rear_density = max(0.1, _float(window_spec, "rear_density_multiplier", 1.0))
    minimum_primary = max(0, int(_float(window_spec, "minimum_windows_per_primary_facade", 1)))
    maximum_per_wall = max(0, int(_float(window_spec, "maximum_windows_per_wall", 12)))
    paired_gap_fraction = max(0.12, min(0.8, _float(window_spec, "paired_group_gap_fraction", 0.34)))

    def random_unit(label: str) -> float:
        digest = sha256(f"{seed}:{family}:{building_class}:{label}".encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") / 2**64

    # Utility families use the detailed JSON's low/very-low density rather than
    # domestic window rows. Industrial halls keep fixed/clerestory strips.
    if family in {"outbuilding", "agricultural", "industrial", "shop"}:
        floor_indices = [0]
    else:
        floor_indices = list(range(levels))

    def role_multiplier(edge: int) -> float:
        if edge == primary_edge:
            return front_density
        if edge == rear_edge:
            return rear_density
        return side_density

    def layout_positions(
        *, edge: int, length: float, margin: float, usable: float, count: int,
        local_width: float, local_spacing: float, level: int,
    ) -> list[float]:
        if count <= 0:
            return []
        if placement_style == "paired_groups" and count >= 2:
            group_count = max(1, (count + 1) // 2)
            group_centres = [margin + usable * (g + 0.5) / group_count for g in range(group_count)]
            pair_sep = min(local_spacing * paired_gap_fraction, local_width * 1.10)
            positions: list[float] = []
            for group_index, centre in enumerate(group_centres):
                positions.append(centre - pair_sep * 0.5)
                if len(positions) < count:
                    positions.append(centre + pair_sep * 0.5)
            positions = positions[:count]
        else:
            positions = [margin + usable * (bay + 0.5) / count for bay in range(count)]

        if placement_style == "staggered_floors" and level > 0:
            direction = -1.0 if level % 2 else 1.0
            shift = direction * local_spacing * phase_fraction
            positions = [p + shift for p in positions]

        jitter_scale = 0.0
        if placement_style in {"irregular_cottage", "sparse_asymmetric"}:
            jitter_scale = horizontal_jitter
        elif placement_style == "staggered_floors":
            jitter_scale = horizontal_jitter * 0.45
        elif placement_style == "storefront_rhythm" and edge != primary_edge:
            jitter_scale = horizontal_jitter * 0.35

        if jitter_scale > 0.0:
            max_jitter_m = min(local_spacing, usable / max(1, count)) * jitter_scale
            positions = [
                p + (random_unit(f"edge:{edge}:level:{level}:bay:{bay}:jitter") * 2.0 - 1.0) * max_jitter_m
                for bay, p in enumerate(positions)
            ]

        min_center = margin + local_width * 0.5
        max_center = length - margin - local_width * 0.5
        if max_center < min_center:
            return []
        return [max(min_center, min(max_center, p)) for p in positions]

    for edge, length in enumerate(edge_lengths):
        if length < window_width + 2.0 * edge_margin:
            continue
        a = poly[edge]
        b = poly[(edge + 1) % len(poly)]
        local_width = window_width
        local_height = window_height
        local_spacing = target_spacing
        local_sill = sill_height

        if family == "shop" and edge == primary_edge and set_name == "storefront":
            local_width *= 1.6
            local_height *= 1.45
            local_sill = max(0.25, min(local_sill, 0.45))
            local_spacing *= 1.30
        elif family == "industrial":
            local_width *= 1.25
            local_height *= 0.78
            local_sill = max(local_sill, min(2.4, wall_h * 0.55))
            local_spacing *= 1.45
        elif family in {"outbuilding", "agricultural"}:
            local_width *= 0.75
            local_height *= 0.78
            local_spacing *= 1.9

        usable = length - 2.0 * edge_margin
        if usable < local_width * 0.75:
            continue
        base_count = usable / max(local_spacing, local_width * 1.15)
        count = max(1, int(round(base_count * role_multiplier(edge))))

        if placement_style == "sparse_asymmetric":
            count = max(1, int(round(count * 0.65)))
        elif placement_style == "storefront_rhythm" and edge == primary_edge:
            count = max(1, int(round(count * 1.20)))
        elif placement_style == "clerestory_band":
            count = max(1, int(round(count * 1.10)))

        if edge == primary_edge:
            count = max(minimum_primary, count)
        # Symmetric facades deliberately choose a centre-aware bay count. A
        # primary facade with a door prefers paired windows around it; a wall
        # without a door prefers an odd count with one centred bay.
        if placement_style == "symmetric_bays":
            if edge == door_edge and count % 2:
                count += 1
            elif edge != door_edge and count % 2 == 0:
                count += 1
        count = min(count, maximum_per_wall)
        if family in {"outbuilding", "agricultural"}:
            count = min(count, maximum_per_wall, 3)
        elif family == "industrial":
            count = min(count, maximum_per_wall, 8)

        for level in floor_indices:
            positions = layout_positions(
                edge=edge, length=length, margin=edge_margin, usable=usable, count=count,
                local_width=local_width, local_spacing=local_spacing, level=level,
            )
            if not positions:
                continue

            forced_indices: set[int] = set()
            if edge == primary_edge and minimum_primary > 0:
                centre = length * 0.5
                forced_indices = set(
                    sorted(range(len(positions)), key=lambda i: abs(positions[i] - centre))[:minimum_primary]
                )

            base = level * floor_h
            floor_vertical_jitter = 0.0
            if placement_style in {"irregular_cottage", "sparse_asymmetric", "staggered_floors"}:
                floor_vertical_jitter = vertical_jitter
            for bay, along in enumerate(positions):
                omission_label = f"edge:{edge}:level:{level if placement_style not in {'regular_aligned', 'symmetric_bays'} else 0}:bay:{bay}:omit"
                effective_omit = 0.0 if placement_style == "symmetric_bays" else omit_probability
                if bay not in forced_indices and effective_omit > 0.0 and random_unit(omission_label) < effective_omit:
                    continue

                v_offset = 0.0
                if floor_vertical_jitter > 0.0:
                    v_offset = (random_unit(f"edge:{edge}:level:{level}:bay:{bay}:vertical") * 2.0 - 1.0) * floor_vertical_jitter
                z0 = base + local_sill + v_offset
                z1 = min(base + floor_h - 0.24, z0 + local_height)
                if placement_style == "clerestory_band":
                    z0 = max(z0, base + floor_h * 0.58)
                    z1 = min(base + floor_h - 0.20, z0 + local_height * 0.72)
                if z1 - z0 < 0.38:
                    continue
                # Keep ordinary window bays clear of both the primary entrance
                # and fixed balcony doors. The vertical-overlap test lets windows
                # on unrelated storeys keep their normal rhythm.
                blocked_by_door = False
                for existing in openings:
                    if existing.edge != edge or existing.kind not in {"door", "balcony_door"}:
                        continue
                    if z1 <= existing.z0 or z0 >= existing.z1:
                        continue
                    existing_center_m = existing.center_t * length
                    if abs(along - existing_center_m) < (existing.width + local_width) * 0.5 + keep_clear:
                        blocked_by_door = True
                        break
                if blocked_by_door:
                    continue
                add_opening(
                    edge, along / length, local_width, z0, z1,
                    "window", material="window", offset=0.17, edge_margin=edge_margin,
                )

    return current_layout()



def _plan_roof_storey_gable_windows(
    poly: list[Vec2],
    wall_h: float,
    roof_h: float,
    height_fn: Callable[[Vec2], float],
    center: Vec2,
    ridge_axis: Vec2,
    *,
    seed: int | str,
    window_spec: dict[str, object] | None,
    roof_storey_spec: dict[str, object] | None,
) -> tuple[WallOpening, ...]:
    """Return attic-window opening plans on gable ends without emitting geometry."""
    if roof_h <= 0.0 or not poly:
        return ()
    window_spec = dict(window_spec or {})
    spec = dict(roof_storey_spec or {})
    if not bool(spec.get("gable_ends_only", True)):
        return ()

    minimum_roof_height = max(1.5, _float(spec, "minimum_roof_height_m", 2.35))
    if roof_h < minimum_roof_height - 1e-6:
        return ()
    width = max(0.42, _float(window_spec, "width_m", 1.15)) * max(0.4, _float(spec, "window_width_scale", 0.82))
    height = max(0.38, _float(window_spec, "height_m", 1.20)) * max(0.4, _float(spec, "window_height_scale", 0.78))
    sill = max(0.20, _float(spec, "sill_above_eave_m", 0.42))
    top_clearance = max(0.18, _float(spec, "top_clearance_m", 0.34))
    side_clearance = max(0.12, _float(spec, "side_clearance_m", 0.30))
    requested_count = max(1, min(3, int(_float(spec, "windows_per_gable", 1))))

    def random_unit(label: str) -> float:
        digest = sha256(f"{seed}:roof-storey:{label}".encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") / 2**64

    planned: list[WallOpening] = []
    for edge, p0 in enumerate(poly):
        p1 = poly[(edge + 1) % len(poly)]
        d0 = _project(p0, center, ridge_axis)
        d1 = _project(p1, center, ridge_axis)
        if d0 * d1 >= -1e-9 or abs(d0 - d1) <= 1e-9:
            continue
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if length <= 1e-6:
            continue
        ridge_t = d0 / (d0 - d1)
        if not 0.05 < ridge_t < 0.95:
            continue
        ridge = (p0[0] + (p1[0] - p0[0]) * ridge_t, p0[1] + (p1[1] - p0[1]) * ridge_t)
        peak_z = height_fn(ridge)
        if peak_z - wall_h < minimum_roof_height - 1e-6:
            continue

        z0 = wall_h + sill
        z1 = min(peak_z - top_clearance, z0 + height)
        if z1 - z0 < 0.45:
            continue

        left_len = length * ridge_t
        right_len = length * (1.0 - ridge_t)
        z_left = height_fn(p0)
        z_right = height_fn(p1)

        def distance_from_ridge_at_height(side_len: float, eave_z: float, target_z: float) -> float:
            rise = peak_z - eave_z
            if rise <= 1e-8:
                return 0.0
            fraction_from_eave = max(0.0, min(1.0, (target_z - eave_z) / rise))
            return side_len * (1.0 - fraction_from_eave)

        safe_left = distance_from_ridge_at_height(left_len, z_left, z1) - side_clearance
        safe_right = distance_from_ridge_at_height(right_len, z_right, z1) - side_clearance
        if safe_left <= width * 0.5 or safe_right <= width * 0.5:
            continue

        safe_start = ridge_t * length - safe_left
        safe_end = ridge_t * length + safe_right
        safe_span = safe_end - safe_start
        count = requested_count
        if count >= 2 and safe_span < 2.0 * width + max(0.35, width * 0.40):
            count = 1

        centres: list[float]
        if count == 1:
            jitter = (random_unit(f"edge:{edge}:centre") * 2.0 - 1.0) * min(width * 0.18, safe_span * 0.05)
            centres = [ridge_t * length + jitter]
        else:
            separation = min(max(width * 1.35, 0.35), max(width * 1.05, safe_span * 0.34))
            centres = [ridge_t * length - separation * 0.5, ridge_t * length + separation * 0.5]

        for centre_m in centres:
            half = width * 0.5
            if centre_m - half < safe_start or centre_m + half > safe_end:
                continue
            planned.append(WallOpening(edge, centre_m / length, width, z0, z1, "window"))
    return tuple(planned)


def _add_gable_closure_with_openings(
    mesh: Mesh,
    p0: Vec2,
    p1: Vec2,
    wall_h: float,
    height_fn: Callable[[Vec2], float],
    center: Vec2,
    ridge_axis: Vec2,
    openings: tuple[WallOpening, ...],
) -> None:
    """Fill a gable triangle while leaving true attic-window apertures."""
    length, tangent, _outward = _edge_frame(p0, p1)
    if length <= 1e-8:
        return
    d0 = _project(p0, center, ridge_axis)
    d1 = _project(p1, center, ridge_axis)
    if d0 * d1 >= -1e-9 or abs(d0 - d1) <= 1e-9:
        _add_gable_closure(mesh, p0, p1, wall_h, height_fn, center, ridge_axis)
        return
    ridge_t = d0 / (d0 - d1)
    if not 0.0 < ridge_t < 1.0:
        _add_gable_closure(mesh, p0, p1, wall_h, height_fn, center, ridge_axis)
        return
    ridge_s = length * ridge_t
    ridge = (p0[0] + (p1[0] - p0[0]) * ridge_t, p0[1] + (p1[1] - p0[1]) * ridge_t)
    peak_z = height_fn(ridge)
    if peak_z <= wall_h + 1e-6:
        return
    tri2d = [(0.0, wall_h), (ridge_s, peak_z), (length, wall_h)]
    s_breaks = sorted({0.0, length, *(max(0.0, min(length, x)) for opening in openings for x in (opening.center_t * length - opening.width * 0.5, opening.center_t * length + opening.width * 0.5))})
    z_breaks = sorted({wall_h, peak_z, *(max(wall_h, min(peak_z, z)) for opening in openings for z in (opening.z0, opening.z1))})

    def point3(s: float, z: float) -> Vec3:
        return (p0[0] + tangent[0] * s, p0[1] + tangent[1] * s, z)

    for si in range(len(s_breaks) - 1):
        sx0, sx1 = s_breaks[si], s_breaks[si + 1]
        if sx1 - sx0 <= 1e-6:
            continue
        for zi in range(len(z_breaks) - 1):
            sz0, sz1 = z_breaks[zi], z_breaks[zi + 1]
            if sz1 - sz0 <= 1e-6:
                continue
            sc = (sx0 + sx1) * 0.5
            zc = (sz0 + sz1) * 0.5
            if any((o.center_t * length - o.width * 0.5) < sc < (o.center_t * length + o.width * 0.5) and o.z0 < zc < o.z1 for o in openings):
                continue
            rect = [(sx0, sz0), (sx1, sz0), (sx1, sz1), (sx0, sz1)]
            clipped = _clip_poly_to_convex2d(rect, tri2d)
            if len(clipped) < 3:
                continue
            if abs(signed_area(clipped)) < 1e-8:
                continue
            if signed_area(clipped) < 0:
                clipped = list(reversed(clipped))
            tris = triangulate(clipped)
            verts = [mesh.v(point3(s, z)) for s, z in clipped]
            uvs = [mesh.vt((s / 3.0, max(0.0, z - wall_h) / 3.0)) for s, z in clipped]
            for i0, i1, i2 in tris:
                mesh.tri((verts[i0], verts[i1], verts[i2]), (uvs[i0], uvs[i1], uvs[i2]), "wall")


def _add_exterior_gable_frame(
    mesh: Mesh,
    edge_a: Vec2,
    edge_b: Vec2,
    opening: WallOpening,
    *,
    outward_offset: float = 0.012,
) -> bool:
    """Add a four-strip attic frame just outside the gable wall plane.

    The opening itself remains completely empty into the attic. Keeping the visible
    casing outside matches the normal lower-floor windows and avoids the tiny timber
    frame appearing recessed inside the gable wall.
    """
    length, tangent, outward = _edge_frame(edge_a, edge_b)
    if length <= 1e-8:
        return False
    centre = max(0.0, min(length, opening.center_t * length))
    half = min(opening.width * 0.5, centre, length - centre)
    if half <= 0.09:
        return False
    s0, s1 = centre - half, centre + half
    offset = max(0.004, float(outward_offset))

    def point_fn(s: float, z: float) -> Vec3:
        return (
            edge_a[0] + tangent[0] * s + outward[0] * offset,
            edge_a[1] + tangent[1] * s + outward[1] * offset,
            z,
        )

    return _add_frame_ring(
        mesh, point_fn, s0, s1, opening.z0, opening.z1, "window_frame"
    )



def _emit_roof_storey_gable_windows(
    mesh: Mesh,
    poly: list[Vec2],
    openings: tuple[WallOpening, ...],
    *,
    frame_only: bool = False,
    frame_offset: float = 0.012,
) -> int:
    added = 0
    by_edge: dict[int, list[WallOpening]] = {}
    for opening in openings:
        by_edge.setdefault(opening.edge, []).append(opening)
    for edge, edge_openings in by_edge.items():
        p0 = poly[edge]
        p1 = poly[(edge + 1) % len(poly)]
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if length <= 1e-8:
            continue
        for opening in edge_openings:
            if frame_only:
                # Use the same exterior four-strip casing as the lower windows.
                # The centre stays completely open into the attic.
                if _add_exterior_gable_frame(
                    mesh, p0, p1, opening, outward_offset=frame_offset,
                ):
                    added += 1
                continue
            added_ok = _add_facade_panel(
                mesh, p0, p1, opening.center_t, opening.width, opening.z0, opening.z1,
                "window", offset=0.19, edge_margin=0.12,
            )
            if added_ok:
                added += 1
    return added


def _add_roof_storey_gable_windows(
    mesh: Mesh,
    poly: list[Vec2],
    wall_h: float,
    roof_h: float,
    height_fn: Callable[[Vec2], float],
    center: Vec2,
    ridge_axis: Vec2,
    *,
    seed: int | str,
    window_spec: dict[str, object] | None,
    roof_storey_spec: dict[str, object] | None,
    frame_only: bool = False,
) -> int:
    openings = _plan_roof_storey_gable_windows(
        poly, wall_h, roof_h, height_fn, center, ridge_axis,
        seed=seed, window_spec=window_spec, roof_storey_spec=roof_storey_spec,
    )
    return _emit_roof_storey_gable_windows(mesh, poly, openings, frame_only=frame_only)



def build_mesh(
    poly_input: tuple[Vec2, ...],
    wall_h: float,
    roof_h: float,
    roof_style: str,
    *,
    levels: int | None = None,
    add_windows: bool = True,
    add_doors: bool = True,
    family: str = "residential",
    building_class: str = "residential",
    outbuilding_kind: str = "",
    foundation_depth: float = 1.0,
    seed: int | str = 0,
    entrance_points: tuple[Vec2, ...] = (),
    window_spec: dict[str, object] | None = None,
    door_spec: dict[str, object] | None = None,
    roof_storey: bool = False,
    roof_storey_spec: dict[str, object] | None = None,
    add_details: bool = True,
    exterior_detail_spec: dict[str, object] | None = None,
    interior_mode: str = "exterior_only",
    wall_thickness: float = 0.22,
    door_open_angle_degrees: float = 38.0,
) -> Mesh:
    poly = list(poly_input)
    if len(poly) < 3:
        raise ValueError("Building footprint needs at least three points")
    if signed_area(poly) < 0:
        poly.reverse()
    mesh = Mesh()
    n = len(poly)
    _add_foundation(mesh, poly, foundation_depth)

    height_fn, center, u, v, ru, rv, short_axis = _roof_boundary_height_fn(poly, wall_h, roof_h, roof_style)
    convex_footprint = _is_convex(poly)
    normalised_interior_mode = str(interior_mode or "exterior_only").strip().casefold().replace(" ", "_")
    if normalised_interior_mode not in {"exterior_only", "simple_interior"}:
        raise ValueError("interior_mode must be 'exterior_only' or 'simple_interior'")
    inferred_levels = levels if levels is not None else max(1, round(wall_h / 3.0))
    roof_storey_openings: tuple[WallOpening, ...] = ()
    if roof_storey and add_windows and roof_style == "gabled":
        roof_storey_openings = _plan_roof_storey_gable_windows(
            poly, wall_h, roof_h, height_fn, center, short_axis,
            seed=seed, window_spec=window_spec, roof_storey_spec=roof_storey_spec,
        )

    # Balcony doors are part of facade planning rather than the late detail pass,
    # so windows can avoid them and interior mode can cut a real opening. They are
    # only planned when exterior details themselves are enabled.
    balcony_spec: dict[str, object] = {}
    if add_details and isinstance(exterior_detail_spec, dict):
        raw_balcony_spec = exterior_detail_spec.get("balconies") or {}
        if isinstance(raw_balcony_spec, dict):
            balcony_spec = dict(raw_balcony_spec)

    # Interior mode needs opening coordinates *before* wall tessellation. Exterior
    # mode keeps the cheaper historical solid walls plus decorative facade panels.
    if normalised_interior_mode == "simple_interior":
        facade_layout = _add_windows_and_door(
            mesh, poly, wall_h, inferred_levels, add_windows, add_doors,
            family=family, building_class=building_class, outbuilding_kind=outbuilding_kind,
            seed=seed, entrance_points=entrance_points,
            window_spec=window_spec, door_spec=door_spec, balcony_spec=balcony_spec,
            emit_panels=False,
        )
    else:
        facade_layout = FacadeLayout()

    # Walls. Each edge gets independent UVs to avoid stretching around corners.
    cumulative = 0.0
    for i in range(n):
        j = (i + 1) % n
        x0, y0 = poly[i]
        x1, y1 = poly[j]
        length = math.hypot(x1 - x0, y1 - y0)
        if length <= 1e-9:
            continue
        if normalised_interior_mode == "simple_interior":
            _add_wall_with_openings(
                mesh, poly[i], poly[j], i, wall_h, facade_layout, material="wall"
            )
        else:
            a = mesh.v((x0, y0, 0.0)); b = mesh.v((x1, y1, 0.0))
            c = mesh.v((x1, y1, wall_h)); d = mesh.v((x0, y0, wall_h))
            ua = mesh.vt((cumulative / 3.0, 0.0)); ub = mesh.vt(((cumulative + length) / 3.0, 0.0))
            uc = mesh.vt(((cumulative + length) / 3.0, wall_h / 3.0)); ud = mesh.vt((cumulative / 3.0, wall_h / 3.0))
            mesh.tri((a, b, c), (ua, ub, uc), "wall")
            mesh.tri((a, c, d), (ua, uc, ud), "wall")
        cumulative += length

        if roof_h > 0 and roof_style in {"gabled", "dome", "onion"}:
            edge_openings = tuple(opening for opening in roof_storey_openings if opening.edge == i)
            if roof_style == "gabled" and normalised_interior_mode == "simple_interior" and edge_openings:
                _add_gable_closure_with_openings(mesh, poly[i], poly[j], wall_h, height_fn, center, short_axis, edge_openings)
            else:
                _add_gable_closure(mesh, poly[i], poly[j], wall_h, height_fn, center, short_axis)
        elif roof_h > 0 and roof_style in {"hipped", "pyramidal"} and not convex_footprint:
            _add_boundary_closure(mesh, poly[i], poly[j], wall_h, height_fn)

    minx, miny, _, _ = bounds(poly)
    uv_origin = (minx, miny)
    base_tris = triangulate(poly)

    if roof_style == "flat" or roof_h <= 0:
        for i0, i1, i2 in base_tris:
            _add_roof_polygon(mesh, [poly[i0], poly[i1], poly[i2]], lambda _p: wall_h, uv_origin)
    elif roof_style in {"gabled", "dome", "onion"}:
        # Triangulate the *original* footprint first, then clip each convex ear by
        # the ridge plane. This preserves concave notches/courtyards and still
        # creates real ridge vertices where needed.
        for i0, i1, i2 in base_tris:
            tri = [poly[i0], poly[i1], poly[i2]]
            side_a = _clip_halfplane(tri, center, short_axis, True)
            side_b = _clip_halfplane(tri, center, short_axis, False)
            _add_roof_polygon(mesh, side_a, height_fn, uv_origin)
            _add_roof_polygon(mesh, side_b, height_fn, uv_origin)
    elif roof_style in {"hipped", "pyramidal"} and convex_footprint:
        apex = center
        apex_z = wall_h + roof_h
        apex_i = mesh.v((apex[0], apex[1], apex_z))
        apex_uv = _roof_uv(mesh, apex, uv_origin)
        for i in range(n):
            j = (i + 1) % n
            vi = mesh.v((poly[i][0], poly[i][1], wall_h))
            vj = mesh.v((poly[j][0], poly[j][1], wall_h))
            ui = _roof_uv(mesh, poly[i], uv_origin)
            uj = _roof_uv(mesh, poly[j], uv_origin)
            mesh.tri((vi, vj, apex_i), (ui, uj, apex_uv), "roof")
    else:
        # Concave hip/pyramid approximation: preserve exact footprint topology and
        # apply the regional roof-height field to each ear independently. It may
        # have extra creases, but it cannot bridge empty space in a U/L footprint.
        for i0, i1, i2 in base_tris:
            _add_roof_polygon(mesh, [poly[i0], poly[i1], poly[i2]], height_fn, uv_origin)

    if normalised_interior_mode == "simple_interior":
        _add_simple_interior(
            mesh, poly, wall_h, inferred_levels, facade_layout,
            wall_thickness=wall_thickness, family=family,
            door_open_angle_degrees=door_open_angle_degrees,
            roof_storey=roof_storey, roof_style=roof_style, roof_h=roof_h,
            height_fn=height_fn, center=center, short_axis=short_axis,
        )
    else:
        facade_layout = _add_windows_and_door(
            mesh, poly, wall_h, inferred_levels, add_windows, add_doors,
            family=family, building_class=building_class, outbuilding_kind=outbuilding_kind,
            seed=seed, entrance_points=entrance_points,
            window_spec=window_spec, door_spec=door_spec, balcony_spec=balcony_spec,
        )
    if roof_storey and add_windows and roof_style == "gabled":
        if normalised_interior_mode == "simple_interior":
            _emit_roof_storey_gable_windows(
                mesh, poly, roof_storey_openings, frame_only=True,
                frame_offset=0.012,
            )
        else:
            _add_roof_storey_gable_windows(
                mesh, poly, wall_h, roof_h, height_fn, center, short_axis,
                seed=seed, window_spec=window_spec, roof_storey_spec=roof_storey_spec,
            )
    if add_details:
        _add_exterior_details(
            mesh, poly, wall_h, roof_h, roof_style, height_fn, center, u, v, short_axis,
            levels=inferred_levels, foundation_depth=foundation_depth, facade=facade_layout,
            building_class=building_class, detail_spec=exterior_detail_spec, seed=seed,
        )
    return mesh
