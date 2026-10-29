"""Render demo/demo_v2.mp4: a ~90s explainer of the full 3-turn demo.

Pure Pillow frames (1280x720@30fps) piped to ffmpeg/libx264. All people,
places, and events are fictional (Aunt Rosa, Grandpa Emil, Ohio farm).
Script lines, turn counts, and segment counts are read from
demo/script.json so on-screen stats always match the real demo script.

Map scene draws on demo/assets/basemap_ohio.png (vendored OpenStreetMap
tiles, fetched once). The renderer works fully offline from that file and
fails fast with a clear error when it is missing.

The on-screen store is always called the "saved facts file" (facts.jsonl).

Usage:
  .venv/bin/python demo/make_video_v2.py [--out demo/demo_v2.mp4]
  .venv/bin/python demo/make_video_v2.py --preview   # one PNG per scene
"""

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1280, 720, 30
INK, MUTED, LINE, ACCENT, PANEL = (
    (20, 32, 28), (75, 85, 99), (216, 220, 217), (14, 107, 94), (244, 245, 244))
SKIN, GRAYH, BROWNH, SHIRT_R, SHIRT_E, SHIRT_K = (
    (242, 205, 170), (155, 155, 160), (90, 70, 55),
    (150, 110, 130), (70, 110, 140), (110, 150, 110))
GOLD = (176, 130, 30)

REPO = "https://github.com/source-while-1/oral-history-interviewer"
OSM_CREDIT = "Map: \u00a9 OpenStreetMap contributors"
FICTION_BANNER = "Fictional places \u2014 illustrative"

HERE = Path(__file__).resolve().parent
BASEMAP = HERE / "assets" / "basemap_ohio.png"
SCRIPT = HERE / "script.json"


def load_script():
    try:
        return json.loads(SCRIPT.read_text())
    except (OSError, ValueError) as e:
        sys.exit(f"make_video_v2: cannot read demo script {SCRIPT}: {e}")


DATA = load_script()
TURNS = DATA["turns"]
N_TURNS = len(TURNS)
SEGS = [(ti, s) for ti, t in enumerate(TURNS) for s in t["segments"]]
N_SEGS = len(SEGS)

# The same three fictional points, used by the graph, map, and records scenes.
PLACES = [
    ("family farm", 40.10, -82.95),
    ("red barn", 40.06, -82.88),
    ("county fairgrounds", 40.00, -82.80),
]

KINDS = ["person", "place", "event", "person", "place", "event"]
ROWS = [{"kind": KINDS[i % 3], "text": s["text"], "clip": f"clip-{ti}",
         "start": s["start"], "end": s["end"], "seg": s["id"]}
        for i, (ti, s) in enumerate(SEGS)]

# Vendored basemap geometry: 3x2 tiles of z11, x in 551..553, y in 774..775.
_Z, _X0, _Y0, _NX, _NY = 11, 551, 774, 3, 2


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def basemap_xy(lat, lon, bw, bh):
    """Fictional lat/lon -> pixel on the raw basemap image (bw x bh)."""
    n = 2 ** _Z
    mx = (lon + 180.0) / 360.0 * n
    latr = math.radians(lat)
    my = (1.0 - math.log(math.tan(latr) + 1.0 / math.cos(latr)) / math.pi) / 2.0 * n
    return (mx - _X0) / _NX * bw, (my - _Y0) / _NY * bh


_base = None


def basemap():
    global _base
    if _base is None:
        if not BASEMAP.is_file():
            sys.exit(
                f"make_video_v2: missing basemap {BASEMAP}. "
                "Fetch it once (see demo/README.md) before rendering.")
        _base = Image.open(BASEMAP).convert("RGB")
    return _base


_FONT_CANDS = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/DejaVuSans.ttf",
]


def _font(size):
    for path in _FONT_CANDS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def fonts():
    return {
        "title": _font(64),
        "h": _font(42),
        "body": _font(30),
        "small": _font(24),
        "tiny": _font(20),
    }


def text(draw, xy, s, font, fill=INK, anchor="la"):
    draw.text(xy, s, font=font, fill=fill, anchor=anchor)


def wrap(draw, s, font, max_w):
    words, lines, cur = s.split(), [], ""
    for wd in words:
        trial = (cur + " " + wd).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def bubble(draw, x, y, w, lines, font, lh=38, pad=18, tail_left=True):
    h = len(lines) * lh + pad * 2
    draw.rounded_rectangle([x, y, x + w, y + h], radius=14,
                           fill="white", outline=LINE, width=2)
    ty = y + 40
    if tail_left:
        draw.polygon([(x - 18, ty), (x + 2, ty - 12), (x + 2, ty + 12)], fill="white")
        draw.line([(x - 18, ty), (x + 2, ty - 12)], fill=LINE, width=2)
        draw.line([(x - 18, ty), (x + 2, ty + 12)], fill=LINE, width=2)
    for i, ln in enumerate(lines):
        text(draw, (x + pad, y + pad + i * lh), ln, font)
    return h


def portrait_rosa(d, x, y, r=62):
    d.ellipse([x - 70, y + 30, x + 70, y + 130], fill=SHIRT_R)  # shoulders
    d.ellipse([x - 26, y - r - 46, x + 26, y - r + 6], fill=GRAYH)  # bun
    d.ellipse([x - r, y - r, x + r, y + r], fill=SKIN, outline=INK, width=3)
    d.arc([x - r - 6, y - r - 10, x + r + 6, y + 20], 200, 340, fill=GRAYH, width=12)
    for sx in (-1, 1):  # glasses
        d.rounded_rectangle([x + sx * 44 - 26, y - 22, x + sx * 44 + 26, y + 18],
                            radius=10, outline=INK, width=3)
    d.line([(x - 18, y - 4), (x + 18, y - 4)], fill=INK, width=3)
    for sx in (-1, 1):
        d.ellipse([x + sx * 44 - 5, y - 8, x + sx * 44 + 5, y + 2], fill=INK)
    d.arc([x - 24, y + 12, x + 24, y + 48], 20, 160, fill=INK, width=3)
    text(d, (x, y + 152), "Aunt Rosa", _font(24), anchor="ma")


def portrait_emil(d, x, y, r=62):
    d.ellipse([x - 70, y + 30, x + 70, y + 130], fill=SHIRT_E)
    d.ellipse([x - r, y - r, x + r, y + r], fill=SKIN, outline=INK, width=3)
    d.arc([x - r - 4, y - r - 14, x + r + 4, y + 10], 200, 340, fill=BROWNH, width=8)
    for sx in (-1, 1):
        d.ellipse([x + sx * 26 - 6, y - 12, x + sx * 26 + 6, y], fill=INK)
    d.ellipse([x - 34, y + 16, x + 34, y + 40], fill=BROWNH)  # mustache
    d.arc([x - 20, y + 22, x + 20, y + 52], 20, 160, fill=(60, 45, 35), width=3)
    text(d, (x, y + 152), "Grandpa Emil", _font(24), anchor="ma")


def portrait_kid(d, x, y, r=56):
    d.ellipse([x - 64, y + 26, x + 64, y + 120], fill=SHIRT_K)
    d.ellipse([x - r, y - r, x + r, y + r], fill=SKIN, outline=INK, width=3)
    d.arc([x - r - 4, y - r - 16, x + r + 4, y + 30], 185, 355, fill=BROWNH, width=16)
    for sx in (-1, 1):
        d.ellipse([x + sx * 24 - 6, y - 6, x + sx * 24 + 6, y + 6], fill=INK)
    d.arc([x - 22, y + 14, x + 22, y + 46], 20, 160, fill=INK, width=3)
    text(d, (x, y + 142), "you \u00b7 interviewer", _font(24), anchor="ma")


def frame_title(img, d, f, p):
    text(d, (W / 2, 150), "Oral History Interviewer", f["title"], anchor="ma")
    if p > 0.2:
        text(d, (W / 2, 240), "Every fact links back to the voice that said it.",
             f["body"], anchor="ma")
    if p > 0.4:
        portrait_rosa(d, 440, 420)
        portrait_emil(d, 640, 420)
        portrait_kid(d, 840, 420)
    if p > 0.65:
        text(d, (W / 2, 640), "a hackathon demo \u00b7 all people and places fictional",
             f["small"], fill=MUTED, anchor="ma")


SPEAKERS = [("rosa", "Aunt Rosa"), ("emil", "Grandpa Emil"), ("rosa", "Aunt Rosa")]


def frame_talk(img, d, f, p):
    text(d, (80, 56), "Talk \u2014 three turns, one interview", f["h"])
    q = min(2.999, p * 3)
    ti = int(q)
    tp = q - ti
    turn = TURNS[ti]
    who, name = SPEAKERS[ti]
    text(d, (80, 130), f"Turn {ti + 1} of {N_TURNS} \u00b7 {name}", f["body"])
    portrait_kid(d, 200, 330)
    if who == "rosa":
        portrait_rosa(d, 470, 330)
    else:
        portrait_emil(d, 470, 330)
    lines = []
    for j, s in enumerate(turn["segments"]):
        if tp > 0.15 + j * 0.3:
            lines += wrap(d, s["text"], f["small"], 560)
            if j < len(turn["segments"]) - 1:
                lines.append("")
    lines = lines or ["\u2026"]
    bubble(d, 600, 210, 600, lines[:6], f["small"])
    if tp > 0.7:
        s0 = turn["segments"][0]
        text(d, (600, 560),
             f"{s0['id']} \u00b7 {s0['start']:.1f}\u2013{s0['end']:.1f}s   "
             f"{turn['segments'][-1]['id']} \u00b7 "
             f"{turn['segments'][-1]['start']:.1f}\u2013{turn['segments'][-1]['end']:.1f}s",
             f["tiny"], fill=MUTED)
    for i in range(48):  # device waveform
        hh = 14 + 70 * abs(math.sin(i * 0.7 + p * 30)) * (0.3 + 0.7 * tp)
        x = 600 + i * 12
        d.rectangle([x, 648 - hh, x + 8, 648], fill=ACCENT)


NODES = [
    ("Aunt Rosa", "person", 300, 300),
    ("Grandpa Emil", "person", 300, 510),
    ("family farm", "place", 640, 220),
    ("red barn", "place", 640, 410),
    ("county fair", "place", 640, 580),
    ("grew up on a farm", "event", 990, 300),
    ("barn built \u00b7 1958", "event", 990, 500),
]
EDGES = [(0, 2), (0, 5), (5, 2), (1, 3), (1, 6), (6, 3), (0, 4)]
KIND_FILL = {"person": (220, 235, 228), "place": (224, 232, 244), "event": (246, 236, 220)}


def frame_graph(img, d, f, p):
    text(d, (80, 56), "Think \u2014 facts become a family graph", f["h"])
    boxes = {}
    for j, (label, kind, cx, cy) in enumerate(NODES):
        if p < 0.05 + j * 0.08:
            continue
        boxes[j] = (cx, cy)
    for k, (a, b) in enumerate(EDGES):  # edges first, nodes on top
        if p > 0.62 + k * 0.04 and a in boxes and b in boxes:
            d.line([boxes[a], boxes[b]], fill=MUTED, width=3)
    for j, (cx, cy) in boxes.items():
        label, kind, _, _ = NODES[j]
        bw, bh = 250, 76
        box = [cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2]
        d.rounded_rectangle(box, radius=10, fill=KIND_FILL[kind], outline=LINE, width=2)
        text(d, (cx, cy - 12), label, f["small"], anchor="ma")
        text(d, (cx, cy + 20), kind, f["tiny"], fill=MUTED, anchor="ma")
    text(d, (80, 660), f"{len(boxes)} nodes \u00b7 {sum(1 for k in range(len(EDGES)) if p > 0.62 + k * 0.04)} links",
         f["tiny"], fill=MUTED)


def fiction_banner(d, f):
    d.rectangle([0, 0, W, 46], fill=(60, 60, 60))
    text(d, (W / 2, 23), FICTION_BANNER, f["small"], fill="white", anchor="ma")


def frame_map(img, d, f, p):
    fiction_banner(d, f)
    text(d, (80, 66), "Map \u2014 the family farm, on a real basemap", f["h"])
    px, py, pw, ph = 80, 150, 1120, 470
    bm = basemap()
    bw, bh = bm.size
    scale = max(pw / bw, ph / bh)
    rw, rh = int(bw * scale), int(bh * scale)
    big = bm.resize((rw, rh), Image.BILINEAR)
    big = big.crop(((rw - pw) // 2, (rh - ph) // 2,
                    (rw + pw) // 2, (rh + ph) // 2))
    img.paste(big, (px, py))
    d.rectangle([px, py, px + pw, py + ph], outline=LINE, width=2)

    def panel_xy(lat, lon):
        bx, by = basemap_xy(lat, lon, bw, bh)
        return (px + bx * scale - (rw - pw) // 2,
                py + by * scale - (rh - ph) // 2)

    pts = [(name, panel_xy(lat, lon), lat, lon) for name, lat, lon in PLACES]
    drops = []
    for j, (name, (cx, cy), lat, lon) in enumerate(pts):
        t0 = 0.12 + j * 0.16
        if p < t0:
            continue
        k = min(1.0, (p - t0) * 4)
        drops.append((name, cx, cy - (1 - k) ** 2 * 160, lat, lon))
    if p > 0.62 and len(drops) == 3:  # arcs under the pins
        pairs = [(0, 1), (1, 2), (0, 2)]
        for k, (a, b) in enumerate(pairs):
            if p < 0.62 + k * 0.08:
                continue
            (na, xa, ya, la1, lo1), (nb, xb, yb, la2, lo2) = drops[a], drops[b]
            km = haversine_km(la1, lo1, la2, lo2)
            mx, my = (xa + xb) / 2, (ya + yb) / 2 - (60 + 30 * k)
            prev = None
            for s in range(21):
                t = s / 20
                qx = (1 - t) ** 2 * xa + 2 * (1 - t) * t * mx + t ** 2 * xb
                qy = (1 - t) ** 2 * ya + 2 * (1 - t) * t * my + t ** 2 * yb
                if prev is not None:
                    d.line([prev, (qx, qy)], fill=GOLD, width=4)
                prev = (qx, qy)
            label = f"{km:.1f} km"
            tw = d.textlength(label, font=f["tiny"]) + 16
            d.rounded_rectangle([mx - tw / 2, my - 16, mx + tw / 2, my + 16],
                                radius=6, fill="white", outline=GOLD, width=2)
            text(d, (mx, my), label, f["tiny"], anchor="mm")
    for name, cx, cy, lat, lon in drops:
        d.ellipse([cx - 13, cy - 13, cx + 13, cy + 13], fill=(180, 40, 40),
                  outline="white", width=3)
        d.polygon([(cx - 8, cy + 8), (cx + 8, cy + 8), (cx, cy + 24)], fill=(180, 40, 40))
        lw = d.textlength(name, font=f["tiny"]) + 20
        ly = min(cy - 52, py + ph - 40) if cy > py + 120 else cy + 30
        d.rounded_rectangle([cx - lw / 2, ly, cx + lw / 2, ly + 32], radius=6, fill="white")
        text(d, (cx, ly + 16), name, f["tiny"], anchor="mm")
    text(d, (px, py + ph + 26), OSM_CREDIT, f["tiny"], fill=MUTED)
    text(d, (px + pw, py + ph + 26), "same 3 fictional points as the graph",
         f["tiny"], fill=MUTED, anchor="ra")


def frame_records(img, d, f, p):
    text(d, (80, 56), "Save \u2014 every fact cites its clip slice", f["h"])
    text(d, (80, 122), "saved facts file \u00b7 facts.jsonl", f["body"])
    y = 180
    shown = 0
    for j, r in enumerate(ROWS):
        if p < 0.06 + j * 0.13:
            continue
        shown += 1
        d.rounded_rectangle([80, y, 1200, y + 62], radius=8, fill=PANEL,
                            outline=LINE, width=2)
        text(d, (104, y + 31), r["kind"], f["small"], fill=ACCENT, anchor="lm")
        t = r["text"]
        if d.textlength(t, font=f["small"]) > 560:
            while t and d.textlength(t + "\u2026", font=f["small"]) > 560:
                t = t[:-1]
            t += "\u2026"
        text(d, (250, y + 31), t, f["small"], anchor="lm")
        text(d, (1176, y + 31), f"{r['clip']} {r['start']:.1f}\u2013{r['end']:.1f}s",
             f["tiny"], fill=MUTED, anchor="rm")
        y += 70
    text(d, (80, 660),
         f"{N_TURNS} turns \u00b7 {N_SEGS} segments \u00b7 {shown} saved facts (from demo/script.json)",
         f["tiny"], fill=MUTED)


def frame_payoff(img, d, f, p):
    text(d, (W / 2, 120), "Three turns become lasting history", f["h"], anchor="ma")
    vals = [(N_TURNS, "turns"), (N_SEGS, "segments"), (len(ROWS), "saved facts")]
    for j, (v, label) in enumerate(vals):
        cx = 340 + j * 300
        n = int(v * min(1.0, max(0.0, p * 1.4 - j * 0.15)))
        text(d, (cx, 330), str(n), _font(110), fill=ACCENT, anchor="ma")
        text(d, (cx, 430), label, f["body"], anchor="ma")
    if p > 0.55:
        text(d, (W / 2, 540), "Every fact links back to the voice that said it.",
             f["body"], anchor="ma")
    if p > 0.75:
        text(d, (W / 2, 600), "timeline + family map + replay", f["small"],
             fill=MUTED, anchor="ma")


def frame_outro(img, d, f, p):
    text(d, (W / 2, 170), "Try it yourself", f["h"], anchor="ma")
    if p > 0.15:
        text(d, (W / 2, 260), "python3 demo/replay.py", f["body"], anchor="ma")
    if p > 0.3:
        text(d, (W / 2, 330), REPO.replace("https://", ""), f["small"], anchor="ma")
    if p > 0.45:
        text(d, (W / 2, 410), OSM_CREDIT, f["small"], fill=MUTED, anchor="ma")
    if p > 0.6:
        text(d, (W / 2, 470), "All people and places fictional \u2014 invented for this demo",
             f["small"], fill=MUTED, anchor="ma")
    if p > 0.75:
        text(d, (W / 2, 540), "Live path: MOCK_LLM=0 with a Fireworks key",
             f["small"], fill=MUTED, anchor="ma")


SCENES = [("title", 8), ("talk", 18), ("graph", 14), ("map", 16),
          ("records", 14), ("payoff", 10), ("outro", 10)]
FUNCS = {"title": frame_title, "talk": frame_talk, "graph": frame_graph,
         "map": frame_map, "records": frame_records, "payoff": frame_payoff,
         "outro": frame_outro}
PREVIEW_P = {"title": 0.7, "talk": 0.8, "graph": 0.95, "map": 0.95,
             "records": 0.95, "payoff": 0.95, "outro": 0.95}


def render_frame(name, p, f):
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    FUNCS[name](img, d, f, p)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "demo_v2.mp4"))
    ap.add_argument("--preview", action="store_true",
                    help="write one PNG per scene to /tmp/v2prev instead of video")
    args = ap.parse_args()
    f = fonts()
    if args.preview:
        out = Path("/tmp/v2prev")
        out.mkdir(parents=True, exist_ok=True)
        for name, _ in SCENES:
            render_frame(name, PREVIEW_P[name], f).save(out / f"{name}.png")
            print(f"wrote {out / f'{name}.png'}")
        return
    basemap()  # fail fast before opening ffmpeg
    total = sum(s * FPS for _, s in SCENES)
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-framerate", str(FPS), "-i", "-",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "22",
         "-movflags", "+faststart", args.out],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    n = 0
    try:
        for name, secs in SCENES:
            for k in range(secs * FPS):
                ff.stdin.write(render_frame(name, k / (secs * FPS), f).tobytes())
                n += 1
    finally:
        ff.stdin.close()
        rc = ff.wait()
    if rc != 0:
        sys.exit(f"ffmpeg failed (rc={rc})")
    print(f"wrote {args.out}: {n} frames, {n / FPS:.0f}s")


if __name__ == "__main__":
    main()
