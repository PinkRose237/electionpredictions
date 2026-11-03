"""Build the Apple TV app's map data (ElectionNight/Resources/maps.json).

Inputs (Census, public domain):
  cb_2024_us_state_20m.shp          state outlines (cartographic boundary, 1:20m)
  2024_Gaz_119CDs_national.txt      one interior point per congressional district

Output:
  states: outline rings per state, projected Albers USA style (Alaska and Hawaii as insets), in a
          1000-unit-wide box, simplified for a TV-sized drawing.
  house:  a tile cartogram, one square per House seat. Each state's seats form one contiguous blob grown
          around the state's districts; seats are placed nearest their district's interior point. Tiles
          carry which edges border another state, so the app can draw state lines. Geography is
          approximate on purpose: several states redrew lines for 2026, so only the shape matters.

Run: uv run --with pyshp python tvos/tools/make_maps.py STATES_DIR GAZETTEER.txt OUT.json
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import shapefile  # pyshp

FIPS = {"01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "11": "DC",
        "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
        "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT",
        "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
        "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
        "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY"}
WIDTH = 1000.0


def conic(lon0, lat0, lat1, lat2):
    """Albers equal-area conic projection (unit sphere)."""
    p1, p2, p0 = map(math.radians, (lat1, lat2, lat0))
    n = (math.sin(p1) + math.sin(p2)) / 2
    c = math.cos(p1) ** 2 + 2 * n * math.sin(p1)
    rho0 = math.sqrt(c - 2 * n * math.sin(p0)) / n

    def f(lon, lat):
        dl = lon - lon0
        if dl > 180:
            dl -= 360
        if dl < -180:
            dl += 360
        rho = math.sqrt(max(0.0, c - 2 * n * math.sin(math.radians(lat)))) / n
        th = n * math.radians(dl)
        return rho * math.sin(th), -(rho0 - rho * math.cos(th))  # y grows downward

    return f


LOWER48 = conic(-96, 38.7, 29.5, 45.5)
ALASKA = conic(-154, 58.5, 55, 65)
HAWAII = conic(-157, 19.9, 8, 18)


def make_projector():
    """Fit the lower 48 to WIDTH units and park Alaska / Hawaii as insets bottom-left (like d3.geoAlbersUsa)."""
    # Lower-48 extent from a coarse lon/lat box.
    xs, ys = zip(*[LOWER48(lon, lat) for lon in range(-125, -66, 1) for lat in (24.5, 49.4)])
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    k = WIDTH * 0.94 / (x1 - x0)
    ox, oy = WIDTH * 0.03 - x0 * k, 10 - y0 * k
    # Insets in units of the lower-48 scale: Alaska at 0.35x, Hawaii at 1x, as d3 does.
    ak_k, hi_k = k * 0.35, k
    ax, ay = ALASKA(-154, 58.5)
    hx, hy = HAWAII(-157, 19.9)
    ak_at = (WIDTH * 0.13, (y1 - y0) * k * 0.86)
    hi_at = (WIDTH * 0.29, (y1 - y0) * k * 0.93)

    def proj(lon, lat, st):
        if st == "AK":
            if lon > 0:
                lon -= 360  # Aleutians across the antimeridian
            x, y = ALASKA(lon, lat)
            return ak_at[0] + (x - ax) * ak_k, ak_at[1] + (y - ay) * ak_k
        if st == "HI":
            x, y = HAWAII(lon, lat)
            return hi_at[0] + (x - hx) * hi_k, hi_at[1] + (y - hy) * hi_k
        x, y = LOWER48(lon, lat)
        return ox + x * k, oy + y * k

    return proj


def simplify(pts, tol):
    """Douglas-Peucker on a closed ring."""
    if len(pts) < 5:
        return pts

    def dp(a, b):
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy) or 1e-9
        best, idx = 0.0, -1
        for i in range(a + 1, b):
            x, y = pts[i]
            d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / L
            if d > best:
                best, idx = d, i
        if best > tol:
            return dp(a, idx)[:-1] + dp(idx, b)
        return [pts[a], pts[b]]

    mid = len(pts) // 2
    return dp(0, mid)[:-1] + dp(mid, len(pts) - 1)


def centroid(pts):
    """Area-weighted centroid of a ring (a better label spot than the vertex average)."""
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        f = x1 * y2 - x2 * y1
        a += f
        cx += (x1 + x2) * f
        cy += (y1 + y2) * f
    if abs(a) < 1e-9:
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    return cx / (3 * a), cy / (3 * a)


def ring_area(pts):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2


def build_states(states_dir: Path, proj):
    sf = shapefile.Reader(str(next(states_dir.glob("*.shp"))))
    fields = [f[0] for f in sf.fields[1:]]
    out, centers = {}, {}
    for sr in sf.iterShapeRecords():
        rec = dict(zip(fields, sr.record))
        st = rec["STUSPS"]
        if st not in FIPS.values():
            continue
        shp = sr.shape
        parts = list(shp.parts) + [len(shp.points)]
        rings = []
        for a, b in zip(parts, parts[1:]):
            ring = [proj(lon, lat, st) for lon, lat in shp.points[a:b]]
            ring = simplify(ring, 0.45)
            if len(ring) >= 4 and ring_area(ring) >= 2.0:
                rings.append(ring)
        if not rings:
            continue
        rings.sort(key=ring_area, reverse=True)
        cx, cy = centroid(rings[0])
        out[st] = [[round(v, 1) for p in r for v in p] for r in rings]
        centers[st] = [round(cx, 1), round(cy, 1)]
    return out, centers


def build_house(gaz: Path, proj, height: float, spread: float = 1.7, order_key=None):
    seats: dict[str, list[tuple[str, float, float]]] = {}
    for line in gaz.read_text().splitlines()[1:]:
        f = line.split("\t")
        geoid = f[1].strip()
        st = FIPS.get(geoid[:2])
        if not st or st == "DC" or not geoid[2:].isdigit():  # "ZZ" = water/undefined
            continue
        d = int(geoid[2:])
        x, y = proj(float(f[7]), float(f[6]), st)
        seats.setdefault(st, []).append((f"{st}-{d:02d}", x, y))

    n = sum(len(v) for v in seats.values())
    # Cell size: the lower 48's area shared out ~1.7 cells per seat, leaving room for dense states to spread.
    cell = math.sqrt(WIDTH * height * 0.55 / (n * spread))
    cols, rows = int(WIDTH / cell) + 4, int(height / cell) + 4
    taken: dict[tuple[int, int], str] = {}

    def room(start, need):
        seen, todo = {start}, [start]
        while todo and len(seen) < need:
            i, j = todo.pop()
            for c in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if c not in seen and c not in taken and 0 <= c[0] < cols and 0 <= c[1] < rows:
                    seen.add(c)
                    todo.append(c)
        return len(seen) >= need

    def to_cell(x, y):
        return x / cell + 2, y / cell + 2

    # Small delegations first: they land on their real spot, and big states grow around them. (Of the orders
    # tried, this keeps states nearest their true positions.)
    order = sorted(seats, key=order_key or (lambda s: len(seats[s])))
    tiles = []
    for st in order:
        pts = [to_cell(x, y) for _, x, y in seats[st]]
        mx, my = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        free = [(i, j) for i in range(cols) for j in range(rows) if (i, j) not in taken]
        free.sort(key=lambda c: (c[0] + 0.5 - mx) ** 2 + (c[1] + 0.5 - my) ** 2)
        # Seed at the nearest free cell with room for the whole delegation, so a state is never boxed in.
        seed = next(c for c in free if room(c, len(pts)))
        blob = [seed]
        taken[seed] = st
        while len(blob) < len(pts):
            frontier = {(i + di, j + dj) for i, j in blob for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1))}
            frontier = [c for c in frontier if c not in taken and 0 <= c[0] < cols and 0 <= c[1] < rows]
            # Nearest the state's centre, with a pull toward its far-flung districts so the blob keeps its shape.
            def cost(c):
                cx, cy = c[0] + 0.5, c[1] + 0.5
                near = min((cx - px) ** 2 + (cy - py) ** 2 for px, py in pts)
                return (cx - mx) ** 2 + (cy - my) ** 2 + 0.6 * near
            nxt = min(frontier, key=cost)
            blob.append(nxt)
            taken[nxt] = st
        # Seats to cells: repeatedly match the closest remaining (district, cell) pair.
        pairs = sorted(((pts[k][0] - (c[0] + 0.5)) ** 2 + (pts[k][1] - (c[1] + 0.5)) ** 2, k, c)
                       for k in range(len(pts)) for c in blob)
        used_k, used_c = set(), set()
        for _, k, c in pairs:
            if k in used_k or c in used_c:
                continue
            used_k.add(k)
            used_c.add(c)
            tiles.append({"id": seats[st][k][0], "st": st, "x": c[0], "y": c[1]})

    # Trim empty margins, then mark the edges that face another state (or nothing).
    minx, miny = min(t["x"] for t in tiles), min(t["y"] for t in tiles)
    for t in tiles:
        t["x"] -= minx
        t["y"] -= miny
    at = {(t["x"], t["y"]): t["st"] for t in tiles}
    for t in tiles:
        e = ""
        for ch, (dx, dy) in zip("trbl", ((0, -1), (1, 0), (0, 1), (-1, 0))):
            if at.get((t["x"] + dx, t["y"] + dy)) != t["st"]:
                e += ch
        t["edges"] = e
    labels = {}
    for st in seats:
        mine = [t for t in tiles if t["st"] == st]
        cx = sum(t["x"] for t in mine) / len(mine) + 0.5
        cy = sum(t["y"] for t in mine) / len(mine) + 0.5
        labels[st] = [round(cx, 2), round(cy, 2)]
    return {"cols": max(t["x"] for t in tiles) + 1, "rows": max(t["y"] for t in tiles) + 1,
            "tiles": sorted(tiles, key=lambda t: t["id"]), "labels": labels}


def main(states_dir, gaz, out):
    proj = make_projector()
    states, centers = build_states(Path(states_dir), proj)
    height = max(v for rings in states.values() for r in rings for v in r[1::2]) + 10
    house = build_house(Path(gaz), proj, height)
    Path(out).write_text(json.dumps({"width": WIDTH, "height": round(height, 1), "states": states,
                                     "centers": centers, "house": house}, separators=(",", ":")))
    print(f"states {len(states)}, house tiles {len(house['tiles'])} on {house['cols']}x{house['rows']}, "
          f"{Path(out).stat().st_size // 1024} KB")


if __name__ == "__main__":
    main(*sys.argv[1:4])
