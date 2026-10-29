"""Render demo_v5 light/dark explainers: Plex Serif display type, sticker
portraits, layout chips, and an edge-tts neural voiceover.

Pure Pillow frames (1280x720@30fps) piped to ffmpeg/libx264. All people,
places, and events are fictional (Aunt Rosa, Grandpa Emil, Ohio farm).
Script lines, turn counts, and segment counts are read from
demo/script.json so on-screen stats always match the real demo script.
An edge-tts neural voiceover (one block per scene, padded/trimmed to
the scene length) is muxed as AAC so narration never overruns its scene.

Map scene draws on demo/assets/basemap_ohio.png (vendored OpenStreetMap
tiles, fetched once). The renderer works fully offline from that file and
fails fast with a clear error when it is missing.

The on-screen store is always called the "saved facts file" (facts.jsonl).

Usage:
  .venv/bin/python demo/make_video_v2.py [--out demo/demo_v5_light.mp4]
  .venv/bin/python demo/make_video_v2.py --preview   # one PNG per scene
  .venv/bin/python demo/make_video_v2.py --theme dark --no-audio
"""

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

W, H, FPS = 1280, 720, 30
INK, MUTED, LINE, ACCENT, PANEL = (
    (20, 32, 28), (75, 85, 99), (216, 220, 217), (14, 107, 94), (244, 245, 244))
CARD = (255, 255, 255)
BG = (251, 252, 251)
MAPDIM = 1.0
THEME_NAME = "light"
SKIN, GRAYH, BROWNH, SHIRT_R, SHIRT_E, SHIRT_K = (
    (242, 205, 170), (155, 155, 160), (90, 70, 55),
    (150, 110, 130), (70, 110, 140), (110, 150, 110))
GOLD = (176, 130, 30)

THEMES = {
    "light": {
        "BG": (251, 252, 251), "INK": (20, 32, 28), "MUTED": (75, 85, 99),
        "LINE": (216, 220, 217), "ACCENT": (14, 107, 94),
        "PANEL": (244, 245, 244), "CARD": (255, 255, 255), "MAPDIM": 1.0,
        "KIND": {"person": (220, 235, 228), "place": (224, 232, 244),
                 "event": (246, 236, 220)},
    },
    "dark": {
        "BG": (16, 23, 21), "INK": (237, 243, 239), "MUTED": (157, 176, 168),
        "LINE": (42, 56, 51), "ACCENT": (53, 208, 165),
        "PANEL": (22, 33, 29), "CARD": (26, 38, 33), "MAPDIM": 0.55,
        "KIND": {"person": (30, 58, 48), "place": (32, 52, 80),
                 "event": (80, 62, 34)},
    },
}

SCENE_KICKER = {"title": "00 · INTRO", "talk": "01 · TALK", "graph": "02 · THINK",
                "map": "03 · MAP", "records": "04 · SAVE", "payoff": "05 · PAYOFF",
                "outro": "06 · OUTRO"}


def set_theme(name):
    global BG, INK, MUTED, LINE, ACCENT, PANEL, CARD, MAPDIM, KIND_FILL, THEME_NAME
    t = THEMES[name]
    BG, INK, MUTED, LINE, ACCENT, PANEL, CARD = (
        t["BG"], t["INK"], t["MUTED"], t["LINE"], t["ACCENT"], t["PANEL"], t["CARD"])
    MAPDIM = t["MAPDIM"]
    KIND_FILL = dict(t["KIND"])
    THEME_NAME = name


def chip(d, xy, s, font, fill=None, outline=None, anchor="mm",
         pad_x=10, pad_y=6, text_fill=None):
    """Label chip: padded rounded rect behind text (min 12px clearances).

    Draws the text with a CARD/PANEL backing so labels never touch art
    beneath them. Returns the chip box.
    """
    fill = CARD if fill is None else fill
    text_fill = INK if text_fill is None else text_fill
    l, t, r, b = d.textbbox(xy, s, font=font, anchor=anchor)
    box = [l - pad_x, t - pad_y, r + pad_x, b + pad_y]
    if outline:
        d.rounded_rectangle(box, radius=8, fill=fill, outline=outline, width=2)
    else:
        d.rounded_rectangle(box, radius=8, fill=fill)
    d.text(xy, s, font=font, fill=text_fill, anchor=anchor)
    return box


def chrome(d, f, idx, overall, kicker=None):
    """Section chrome: kicker header + footer progress (theme-aware)."""
    tracked(d, (80, 12), SCENE_KICKER[SCENES[idx][0]], f["kick"],
            ACCENT if kicker is None else kicker, anchor="la")
    d.line([(80, 50), (1200, 50)], fill=LINE, width=2)
    d.rectangle([80, H - 22, 1200, H - 16], fill=LINE)
    d.rectangle([80, H - 22, 80 + int(1120 * overall), H - 16], fill=ACCENT)
    # version label floats on its own chip 14px above the bar so the two
    # never touch (v3 drew the text directly onto the bar row).
    chip(d, (1200, H - 44),
         "demo v5 · %s · scene %d/%d" % (THEME_NAME, idx + 1, len(SCENES)),
         f["tiny"], fill=CARD, outline=LINE, anchor="ra",
         text_fill=MUTED)

REPO = "https://github.com/source-while-1/oral-history-interviewer"
OSM_CREDIT = "Map: © OpenStreetMap contributors"
FICTION_BANNER = "Fictional places — illustrative"

HERE = Path(__file__).resolve().parent
BASEMAP = HERE / "assets" / "basemap_ohio.png"
SCRIPT = HERE / "script.json"


def load_script():
    try:
        return json.loads(SCRIPT.read_text())
    except (OSError, ValueError) as e:
        sys.exit("make_video_v2: cannot read demo script %s: %s" % (SCRIPT, e))


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
ROWS = [{"kind": KINDS[i % 3], "text": s["text"], "clip": "clip-%d" % ti,
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
                "make_video_v2: missing basemap %s. "
                "Fetch it once (see demo/README.md) before rendering." % BASEMAP)
        _base = Image.open(BASEMAP).convert("RGB")
    return _base


PLEX = HERE / "assets" / "fonts" / "IBMPlexSans-Variable.ttf"
SERIF = HERE / "assets" / "fonts" / "IBMPlexSerif-Regular.ttf"
SERIF_BOLD = HERE / "assets" / "fonts" / "IBMPlexSerif-Bold.ttf"
_FONT_CANDS = [
    str(PLEX),  # vendored first (see demo/README.md for the OFL note)
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/DejaVuSans.ttf",
]


_FONT_CACHE = {}


def _font(size, bold=False, family="sans"):
    """Vendored IBM Plex first, system fonts next, PIL default last.

    Sans titles/body use the variable Plex Sans (Bold via the wght axis);
    display titles use Plex Serif static cuts. System fallbacks have no
    variable axis, so they render un-bolded rather than failing.
    Loaded once per (size, bold, family) and cached for the renders.
    """
    key = (size, bold, family)
    if key not in _FONT_CACHE:
        if family == "serif":
            cands = [str(SERIF_BOLD if bold else SERIF)] + _FONT_CANDS[1:]
        else:
            cands = list(_FONT_CANDS)
        for path in cands:
            try:
                ft = ImageFont.truetype(path, size)
                if bold and family == "sans":
                    try:
                        ft.set_variation_by_name("Bold")
                    except Exception:
                        pass
                _FONT_CACHE[key] = ft
                break
            except OSError:
                continue
        else:
            _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


def fonts():
    return {
        "title": _font(64, bold=True, family="serif"),
        "h": _font(42, bold=True, family="serif"),
        "body": _font(30),
        "small": _font(24),
        "tiny": _font(20),
        "kick": _font(20, bold=True),
    }


def tracked(draw, xy, s, font, fill, anchor="la", ls=3):
    """Draw with manual letterspacing (display kickers)."""
    widths = [draw.textlength(ch, font=font) for ch in s]
    total = sum(widths) + ls * (len(s) - 1)
    x, y = xy
    if anchor in ("ma", "mm"):
        x -= total / 2
    elif anchor in ("ra", "rm"):
        x -= total
    for ch, w in zip(s, widths):
        draw.text((x, y), ch, font=font, fill=fill,
                  anchor=("l" + anchor[1]) if len(anchor) == 2 else "la")
        x += w + ls
    return total


def text(draw, xy, s, font, fill=None, anchor="la"):
    # NB: fill resolves INK at call time so set_theme() takes effect.
    draw.text(xy, s, font=font, fill=INK if fill is None else fill, anchor=anchor)


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
                           fill=CARD, outline=LINE, width=2)
    ty = y + 40
    if tail_left:
        draw.polygon([(x - 18, ty), (x + 2, ty - 12), (x + 2, ty + 12)], fill=CARD)
        draw.line([(x - 18, ty), (x + 2, ty - 12)], fill=LINE, width=2)
        draw.line([(x - 18, ty), (x + 2, ty + 12)], fill=LINE, width=2)
    for i, ln in enumerate(lines):
        text(draw, (x + pad, y + pad + i * lh), ln, font)
    return h


# Fixed dark ink for every portrait line/detail on both themes, so the
# same sticker reads clean on light and dark (no theme swapping).
STICKER_INK = (25, 30, 28)
STICKER_WHITE, STICKER_OUTER = (255, 255, 255, 255), (25, 30, 28, 255)


def _sticker_layer(art):
    """Outline a transparent portrait layer: black mask largest, white ring
    middle, art on top (alpha-dilation compositing)."""
    alpha = art.split()[3]
    black = alpha.filter(ImageFilter.MaxFilter(19))  # ~9px outer ring
    white = alpha.filter(ImageFilter.MaxFilter(11))  # ~5px white ring
    out = Image.new("RGBA", art.size, (0, 0, 0, 0))
    out.paste(Image.new("RGBA", art.size, STICKER_OUTER), (0, 0), black)
    out.paste(Image.new("RGBA", art.size, STICKER_WHITE), (0, 0), white)
    return Image.alpha_composite(out, art)


_STICKER_CACHE = {}


def _portrait_base(img, d, key, label, label_xy, draw_art):
    """Stickerize portrait art onto img, name on a chip (never in sticker).

    The sticker art uses fixed colors on both themes, so each portrait is
    composited once per geometry and cached; only the cheap chip redraws per
    frame. The key MUST include position: the same person appears at title
    positions and talk positions, and a label-only key reuses the wrong art.
    """
    layer = _STICKER_CACHE.get(key)
    if layer is None:
        art = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw_art(ImageDraw.Draw(art))
        layer = _sticker_layer(art)
        _STICKER_CACHE[key] = layer
    img.paste(layer, (0, 0), layer)
    chip(d, label_xy, label, _font(24), anchor="ma", text_fill=INK)


def portrait_rosa(img, d, x, y, r=62):
    def art(a):
        a.ellipse([x - 70, y + 30, x + 70, y + 130], fill=SHIRT_R)  # shoulders
        a.ellipse([x - 26, y - r - 46, x + 26, y - r + 6], fill=GRAYH)  # bun
        a.ellipse([x - r, y - r, x + r, y + r], fill=SKIN,
                  outline=STICKER_INK, width=3)
        a.arc([x - r - 6, y - r - 10, x + r + 6, y + 20], 200, 340,
              fill=GRAYH, width=12)
        for sx in (-1, 1):  # glasses
            a.rounded_rectangle([x + sx * 44 - 26, y - 22, x + sx * 44 + 26, y + 18],
                                radius=10, outline=STICKER_INK, width=3)
        a.line([(x - 18, y - 4), (x + 18, y - 4)], fill=STICKER_INK, width=3)
        for sx in (-1, 1):
            a.ellipse([x + sx * 44 - 5, y - 8, x + sx * 44 + 5, y + 2],
                      fill=STICKER_INK)
        a.arc([x - 24, y + 12, x + 24, y + 48], 20, 160,
              fill=STICKER_INK, width=3)
    _portrait_base(img, d, ("Aunt Rosa", x, y, r), "Aunt Rosa", (x, y + 152), art)


def portrait_emil(img, d, x, y, r=62):
    def art(a):
        a.ellipse([x - 70, y + 30, x + 70, y + 130], fill=SHIRT_E)
        a.ellipse([x - r, y - r, x + r, y + r], fill=SKIN,
                  outline=STICKER_INK, width=3)
        a.arc([x - r - 4, y - r - 14, x + r + 4, y + 10], 200, 340,
              fill=BROWNH, width=8)
        for sx in (-1, 1):
            a.ellipse([x + sx * 26 - 6, y - 12, x + sx * 26 + 6, y],
                      fill=STICKER_INK)
        a.ellipse([x - 34, y + 16, x + 34, y + 40], fill=BROWNH)  # mustache
        a.arc([x - 20, y + 22, x + 22, y + 52], 20, 160,
              fill=(60, 45, 35), width=3)
    _portrait_base(img, d, ("Grandpa Emil", x, y, r), "Grandpa Emil", (x, y + 152), art)


def portrait_kid(img, d, x, y, r=56):
    def art(a):
        a.ellipse([x - 64, y + 26, x + 64, y + 120], fill=SHIRT_K)
        a.ellipse([x - r, y - r, x + r, y + r], fill=SKIN,
                  outline=STICKER_INK, width=3)
        a.arc([x - r - 4, y - r - 16, x + r + 4, y + 30], 185, 355,
              fill=BROWNH, width=16)
        for sx in (-1, 1):
            a.ellipse([x + sx * 24 - 6, y - 6, x + sx * 24 + 6, y + 6],
                      fill=STICKER_INK)
        a.arc([x - 22, y + 14, x + 22, y + 46], 20, 160,
              fill=STICKER_INK, width=3)
    _portrait_base(img, d, ("you · interviewer", x, y, r), "you · interviewer",
                   (x, y + 142), art)


def frame_title(img, d, f, p):
    text(d, (W / 2, 150), "Oral History Interviewer", f["title"], anchor="ma")
    if p > 0.2:
        text(d, (W / 2, 240), "Every fact links back to the voice that said it.",
             f["body"], anchor="ma")
    if p > 0.4:
        portrait_rosa(img, d, 440, 420)
        portrait_emil(img, d, 640, 420)
        portrait_kid(img, d, 840, 420)
    if p > 0.65:
        text(d, (W / 2, 628), "a hackathon demo · all people and places fictional",
             f["small"], fill=MUTED, anchor="ma")


SPEAKERS = [("rosa", "Aunt Rosa"), ("emil", "Grandpa Emil"), ("rosa", "Aunt Rosa")]


def frame_talk(img, d, f, p):
    text(d, (80, 56), "Talk — three turns, one interview", f["h"])
    q = min(2.999, p * 3)
    ti = int(q)
    tp = q - ti
    turn = TURNS[ti]
    who, name = SPEAKERS[ti]
    text(d, (80, 130), "Turn %d of %d · %s" % (ti + 1, N_TURNS, name), f["body"])
    portrait_kid(img, d, 200, 330)
    if who == "rosa":
        portrait_rosa(img, d, 470, 330)
    else:
        portrait_emil(img, d, 470, 330)
    lines = []
    for j, s in enumerate(turn["segments"]):
        if tp > 0.15 + j * 0.3:
            lines += wrap(d, s["text"], f["small"], 560)
            if j < len(turn["segments"]) - 1:
                lines.append("")
    lines = lines or ["…"]
    bubble(d, 600, 210, 600, lines[:6], f["small"])
    if tp > 0.7:
        s0 = turn["segments"][0]
        # chip-backed markers sit 28px+ clear of the waveform row below
        chip(d, (600, 540),
             "%s · %.1f–%.1fs   %s · %.1f–%.1fs" % (
                 s0["id"], s0["start"], s0["end"],
                 turn["segments"][-1]["id"],
                 turn["segments"][-1]["start"], turn["segments"][-1]["end"]),
             f["tiny"], fill=PANEL, outline=LINE, anchor="lm",
             text_fill=MUTED)
    for i in range(48):  # device waveform (capped so it never nears the chips)
        hh = 10 + 46 * abs(math.sin(i * 0.7 + p * 30)) * (0.3 + 0.7 * tp)
        x = 600 + i * 12
        d.rectangle([x, 648 - hh, x + 8, 648], fill=ACCENT)


NODES = [
    ("Aunt Rosa", "person", 300, 300),
    ("Grandpa Emil", "person", 300, 510),
    ("family farm", "place", 640, 220),
    ("red barn", "place", 640, 410),
    ("county fair", "place", 640, 580),
    ("grew up on a farm", "event", 990, 300),
    ("barn built · 1958", "event", 990, 500),
]
EDGES = [(0, 2), (0, 5), (5, 2), (1, 3), (1, 6), (6, 3), (0, 4)]
KIND_FILL = {"person": (220, 235, 228), "place": (224, 232, 244), "event": (246, 236, 220)}


def frame_graph(img, d, f, p):
    text(d, (80, 56), "Think — facts become a family graph", f["h"])
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
        bw, bh = 250, 88  # tall enough that kind never touches the edge
        box = [cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2]
        d.rounded_rectangle(box, radius=10, fill=KIND_FILL[kind], outline=LINE, width=2)
        text(d, (cx, cy - 16), label, f["small"], anchor="ma")
        text(d, (cx, cy + 16), kind, f["tiny"], fill=MUTED, anchor="ma")
    if p > 0.62:
        chip(d, (80, 652),
             "%d nodes · %d links" % (
                 len(boxes),
                 sum(1 for k in range(len(EDGES)) if p > 0.62 + k * 0.04)),
             f["tiny"], fill=CARD, outline=LINE, anchor="lm",
             text_fill=MUTED)


def fiction_banner(d, f):
    d.rectangle([0, 0, W, 46], fill=(60, 60, 60))
    text(d, (W / 2, 23), FICTION_BANNER, f["small"], fill="white", anchor="ma")


def frame_map(img, d, f, p):
    fiction_banner(d, f)
    text(d, (80, 66), "Map — the family farm, on a real basemap", f["h"])
    px, py, pw, ph = 80, 150, 1120, 470
    bm = basemap()
    bw, bh = bm.size
    scale = max(pw / bw, ph / bh)
    rw, rh = int(bw * scale), int(bh * scale)
    big = bm.resize((rw, rh), Image.BILINEAR)
    big = big.crop(((rw - pw) // 2, (rh - ph) // 2,
                    (rw + pw) // 2, (rh + ph) // 2))
    if MAPDIM < 1.0:  # dark theme: dim the photographic basemap
        big = ImageEnhance.Brightness(big).enhance(MAPDIM)
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
            mx, my = (xa + xb) / 2, (ya + yb) / 2 - (72 + 30 * k)
            prev = None
            for s in range(21):
                t = s / 20
                qx = (1 - t) ** 2 * xa + 2 * (1 - t) * t * mx + t ** 2 * xb
                qy = (1 - t) ** 2 * ya + 2 * (1 - t) * t * my + t ** 2 * yb
                if prev is not None:
                    d.line([prev, (qx, qy)], fill=GOLD, width=4)
                prev = (qx, qy)
            label = "%.1f km" % km
            tw = d.textlength(label, font=f["tiny"]) + 20
            # chip floats 8px above the arc apex: clear of pins and arc alike
            d.rounded_rectangle([mx - tw / 2, my - 24, mx + tw / 2, my + 8],
                                radius=6, fill=CARD, outline=GOLD, width=2)
            text(d, (mx, my - 8), label, f["tiny"], anchor="mm")
    for name, cx, cy, lat, lon in drops:
        d.ellipse([cx - 13, cy - 13, cx + 13, cy + 13], fill=(180, 40, 40),
                  outline="white", width=3)
        d.polygon([(cx - 8, cy + 8), (cx + 8, cy + 8), (cx, cy + 24)], fill=(180, 40, 40))
        lw = d.textlength(name, font=f["tiny"]) + 20
        ly = min(cy - 56, py + ph - 44) if cy > py + 120 else cy + 34
        d.rounded_rectangle([cx - lw / 2, ly, cx + lw / 2, ly + 32], radius=6,
                            fill=CARD, outline=LINE, width=2)
        text(d, (cx, ly + 16), name, f["tiny"], anchor="mm")
    chip(d, (px, py + ph + 30), OSM_CREDIT,
         f["tiny"], fill=CARD, outline=LINE, anchor="lm", text_fill=MUTED)
    chip(d, (px + pw, py + ph + 30), "same 3 fictional points as the graph",
         f["tiny"], fill=CARD, outline=LINE, anchor="rm", text_fill=MUTED)


def frame_records(img, d, f, p):
    text(d, (80, 56), "Save — every fact cites its clip slice", f["h"])
    text(d, (80, 122), "saved facts file · facts.jsonl", f["body"])
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
            while t and d.textlength(t + "…", font=f["small"]) > 560:
                t = t[:-1]
            t += "…"
        text(d, (250, y + 31), t, f["small"], anchor="lm")
        text(d, (1176, y + 31), "%s %.1f–%.1fs" % (r["clip"], r["start"], r["end"]),
             f["tiny"], fill=MUTED, anchor="rm")
        y += 70
    chip(d, (80, 652),
         "%d turns · %d segments · %d saved facts (from demo/script.json)" % (
             N_TURNS, N_SEGS, shown),
         f["tiny"], fill=CARD, outline=LINE, anchor="lm", text_fill=MUTED)


def frame_payoff(img, d, f, p):
    text(d, (W / 2, 120), "Three turns become lasting history", f["h"], anchor="ma")
    vals = [(N_TURNS, "turns"), (N_SEGS, "segments"), (len(ROWS), "saved facts")]
    for j, (v, label) in enumerate(vals):
        cx = 340 + j * 300
        n = int(v * min(1.0, max(0.0, p * 1.4 - j * 0.15)))
        text(d, (cx, 330), str(n), _font(110, bold=True), fill=ACCENT, anchor="ma")
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
        text(d, (W / 2, 470), "All people and places fictional — invented for this demo",
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

# One narration block per scene (~200 words total), describing the process.
# Each block is padded/trimmed to its scene length so speech never overruns.
NARRATION = {
    "title": ("Meet the Oral History Interviewer. Every fact links back "
              "to the voice that said it. Everyone here is fictional."),
    "talk": ("First, you talk. Three turns, one interview. Each spoken answer "
             "is saved as an audio clip, sliced into timestamped segments. "
             "Here, Aunt Rosa remembers the county fair pie prize she won, "
             "and every slice keeps its start and end time."),
    "graph": ("Then the system thinks. Each answer becomes facts in a family "
              "graph. People, places, and events become linked nodes. "
              "Seven nodes, seven links, each traced to the words that "
              "produced them."),
    "map": ("Then the map. The family farm, the red barn, and the county "
            "fairgrounds appear as fictional pins on a real OpenStreetMap "
            "basemap. Golden arcs mark the real distances between them, "
            "computed in kilometers."),
    "records": ("Every fact lands in the saved facts file. Each row cites its "
                "clip slice to the tenth of a second. Three turns, six "
                "segments, six saved facts. Play any fact to hear its "
                "exact moment."),
    "payoff": ("Three turns become lasting history. Six segments, six saved "
               "facts, and every single one can be replayed."),
    "outro": ("Try it yourself. Run the replay script and bring your own "
              "family stories. All people and places here are fictional."),
}


def _run(cmd):
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if r.returncode != 0:
        sys.exit("make_video_v2: command failed: %s" % " ".join(cmd))


def _probe_secs(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("make_video_v2: ffprobe failed on %s" % path)
    return float(r.stdout.strip())


VOICE = "en-US-AvaNeural"


async def _edge_voices():
    import edge_tts
    return [v["ShortName"] for v in await edge_tts.list_voices()]


def _check_voice():
    """Fail fast unless the named edge-tts neural voice is reachable.

    The muxed track is edge-tts synthesis of the NARRATION text, so the
    voiceover claim rests on this voice actually rendering (not a silent
    fallback). Requires network at render time.
    """
    try:
        import asyncio
        names = asyncio.run(_edge_voices())
    except Exception as e:
        sys.exit("make_video_v2: edge-tts voice list failed (%s); refusing "
                 "silent fallback" % e)
    if VOICE not in names:
        sys.exit("make_video_v2: voice %r not available; refusing silent "
                 "fallback" % VOICE)


def _synth(text, out_path):
    """Render narration audio with the edge-tts neural voice (mp3)."""
    import asyncio
    import edge_tts
    asyncio.run(edge_tts.Communicate(text, VOICE).save(str(out_path)))


def _mean_db(path):
    r = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-map", "0:a",
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "mean_volume" in line:
            return float(line.split("mean_volume:")[1].split("dB")[0])
    sys.exit("make_video_v2: volumedetect failed on %s" % path)


def verify_audio(path, expect_secs):
    """Post-mux honesty gate: audio present, full-length, non-silent."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_name,duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit("make_video_v2: no audio stream in %s" % path)
    dur = float(r.stdout.strip().split(",")[-1])
    if abs(dur - expect_secs) > 0.6:
        sys.exit("make_video_v2: audio %.2fs != video %ds in %s"
                 % (dur, expect_secs, path))
    mean = _mean_db(path)
    if mean < -40.0:
        sys.exit("make_video_v2: audio silent (mean %.1f dB) in %s"
                 % (mean, path))
    print("audio check: %s %.2fs mean %.1f dB OK" % (path, dur, mean))


def build_narration(tmpdir):
    """Render one padded/trimmed wav per scene with edge-tts, then concat.

    Returns (wav_path, [(scene, speech_secs, scene_secs, words)]).
    """
    tmpdir.mkdir(parents=True, exist_ok=True)
    _check_voice()
    words_total = sum(len(v.split()) for v in NARRATION.values())
    print("narration: %d words total" % words_total)
    if not 180 <= words_total <= 220:
        sys.exit("make_video_v2: narration must be 180-220 words, got %d"
                 % words_total)
    parts = []
    report = []
    for name, secs in SCENES:
        mp3 = tmpdir / ("%s.mp3" % name)
        out = tmpdir / ("%s.wav" % name)
        _synth(NARRATION[name], mp3)
        speech = _probe_secs(mp3)
        _run(["ffmpeg", "-y", "-i", str(mp3),
              "-af", "apad,atrim=0:%d" % secs,
              "-ar", "44100", "-ac", "1", str(out)])
        fitted = _probe_secs(out)
        report.append((name, speech, fitted, secs, len(NARRATION[name].split())))
        parts.append(out)
    lst = tmpdir / "concat.txt"
    lst.write_text("".join("file '%s'\n" % p for p in parts))
    wav = tmpdir / "narration.wav"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
          "-c", "copy", str(wav)])
    for name, speech, fitted, secs, nw in report:
        status = "OK" if speech <= secs and abs(fitted - secs) < 0.1 else "OVERRUN"
        print("  %-8s speech %5.2fs vs scene %2ds (%2d words) fitted %5.2fs %s"
              % (name, speech, secs, nw, fitted, status))
        if speech > secs:
            sys.exit("make_video_v2: narration overruns scene %s" % name)
    return wav, report


def render_frame(name, p, f, scene_idx=0, overall=0.0):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    FUNCS[name](img, d, f, p)
    # map kicker sits on the dark fiction banner on both themes: light ink.
    chrome(d, f, scene_idx, overall,
           kicker=(238, 242, 240) if name == "map" else None)
    return img


def render_silent(out_path):
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", "%dx%d" % (W, H), "-framerate", str(FPS), "-i", "-",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "22",
         "-movflags", "+faststart", str(out_path)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    n = 0
    done = 0
    total = sum(s * FPS for _, s in SCENES)
    try:
        for idx, (name, secs) in enumerate(SCENES):
            for k in range(secs * FPS):
                overall = (done + k) / total
                ff.stdin.write(render_frame(name, k / (secs * FPS), f_global,
                                            idx, overall).tobytes())
                n += 1
            done += secs * FPS
    finally:
        ff.stdin.close()
        rc = ff.wait()
    if rc != 0:
        sys.exit("ffmpeg failed (rc=%d)" % rc)
    print("wrote %s: %d frames, %ds" % (out_path, n, n / FPS))


f_global = None


def main():
    global f_global
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", choices=tuple(THEMES), default="light")
    ap.add_argument("--out", default=None,
                    help="default: demo/demo_v5_<theme>.mp4")
    ap.add_argument("--preview", action="store_true",
                    help="write one PNG per scene to /tmp/v5prev instead of video")
    ap.add_argument("--no-audio", action="store_true",
                    help="skip the neural voiceover mux")
    args = ap.parse_args()
    set_theme(args.theme)
    if args.out is None:
        args.out = str(HERE / ("demo_v5_%s.mp4" % args.theme))
    f_global = fonts()
    if args.preview:
        out = Path("/tmp/v5prev_%s" % args.theme)
        out.mkdir(parents=True, exist_ok=True)
        for idx, (name, _) in enumerate(SCENES):
            render_frame(name, PREVIEW_P[name], f_global, idx,
                         sum(s for _, s in SCENES[:idx]) / sum(s for _, s in SCENES)
                         ).save(out / ("%s.png" % name))
            print("wrote %s" % (out / ("%s.png" % name)))
        return
    basemap()  # fail fast before opening ffmpeg
    if args.no_audio:
        render_silent(args.out)
        return
    tmp = Path("/tmp/v5audio_%s" % args.theme)
    silent = tmp / "silent.mp4"
    tmp.mkdir(parents=True, exist_ok=True)
    render_silent(silent)
    narration, _ = build_narration(tmp)
    _run(["ffmpeg", "-y", "-i", str(silent), "-i", str(narration),
          "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
          "-shortest", str(args.out)])
    verify_audio(args.out, sum(s for _, s in SCENES))
    print("wrote %s (video + neural voiceover)" % args.out)


if __name__ == "__main__":
    main()
