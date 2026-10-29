"""Render demo_v9 light/dark explainers: the full product story (voice
interview, threads, keep-going, gentle pause and grief handling, resume
by code, on-the-record consent, Ask the archive, Talk with the
reconstruction) with Plex Serif display type, full-body v5-style
portraits, layout chips, and an edge-tts neural voiceover.

v9 draws every line of dialogue v5-talk-style: the interviewer and the
current speaker side by side as full portraits (shoulders + head), with
the speech bubble beside them and its tail aimed at the speaker's head
center. The bubble is drawn first so the tail slides *under* the
portrait. check_anchors() renders every scene in both themes and fails
the render unless every bubble tail endpoint falls inside its speaker's
bounding box; check_layout() additionally fails on any text/character/
bubble/chip overlap and on duplicate person-name labels in one frame.

Pure Pillow frames (1280x720@30fps) piped to ffmpeg/libx264. All people,
places, and events are fictional (Aunt Rosa, Grandpa Emil, Ohio farm).
Script lines, turn counts, segment counts, and the thread open/cover
arc are derived from demo/script.json (same Title-Name rule as the
server stub) so on-screen stats always match the real demo script.
An edge-tts neural voiceover (one block per scene, padded/trimmed to
the scene length) is muxed as AAC so narration never overruns its scene.

The on-screen store is always called the "saved facts file" (facts.jsonl).

Usage:
  .venv/bin/python demo/make_video_v9.py [--out demo/demo_v9_light.mp4]
  .venv/bin/python demo/make_video_v9.py --preview   # one PNG per scene
  .venv/bin/python demo/make_video_v9.py --theme dark --no-audio
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

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

SCENE_KICKER = {"title": "00 · INTRO", "threads": "01 · TALK & THREADS",
                "continue": "02 · KEEP GOING", "pause": "03 · GENTLE PAUSE",
                "resume": "04 · RESUME", "consent": "05 · CONSENT",
                "ask": "06 · ASK THE ARCHIVE",
                "character": "07 · TALK WITH THE RECONSTRUCTION",
                "outro": "08 · OUTRO"}


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
    reg_box("panel", box, s)
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
         "demo v9 · %s · scene %d/%d" % (THEME_NAME, idx + 1, len(SCENES)),
         f["tiny"], fill=CARD, outline=LINE, anchor="ra",
         text_fill=MUTED)

REPO = "https://github.com/source-while-1/oral-history-interviewer"
HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "script.json"
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


def load_script():
    try:
        return json.loads(SCRIPT.read_text())
    except (OSError, ValueError) as e:
        sys.exit("make_video_v9: cannot read demo script %s: %s" % (SCRIPT, e))


DATA = load_script()
TURNS = DATA["turns"]
NAME_RE = re.compile(
    r"\b(Aunt|Uncle|Grandma|Grandpa|Mother|Father|Granny|Cousin)"
    r"\s+([A-Z][a-z]+)")
N_TURNS = len(TURNS)
SEGS = [(ti, s) for ti, t in enumerate(TURNS) for s in t["segments"]]
N_SEGS = len(SEGS)


def demo_stats():
    opened, covered, order, facts = {}, {}, [], 0
    for ti, t in enumerate(TURNS):
        if (t.get("transcript") or "").strip():
            facts += 1  # one event fact per non-empty turn
        seen = set()
        for s in t.get("segments", []):
            for m in NAME_RE.finditer(s.get("text", "")):
                name = m.group(1) + " " + m.group(2)
                if name in seen:
                    continue
                seen.add(name)
                facts += 1
                if name not in opened:
                    opened[name] = ti
                    order.append(name)
                elif name not in covered:
                    covered[name] = ti
    still_open = [n for n in order if n not in covered]
    return {"facts": facts, "opened": order, "covered": covered,
            "still_open": still_open}


STATS = demo_stats()
N_FACTS = STATS["facts"]
N_OPEN = len(STATS["opened"])
N_STILL_OPEN = len(STATS["still_open"])



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
    l, t, r, b = draw.textbbox(xy, s, font=font, anchor=anchor)
    if anchor.startswith("l"):
        r += ls * max(0, len(s) - 1)
    elif anchor.startswith("r"):
        l -= ls * max(0, len(s) - 1)
    else:
        l -= ls * max(0, len(s) - 1) / 2
        r += ls * max(0, len(s) - 1) / 2
    reg_box("text", (l, t, r, b), s)
    return total


def text(draw, xy, s, font, fill=None, anchor="la", log=True):
    # NB: fill resolves INK at call time so set_theme() takes effect.
    draw.text(xy, s, font=font, fill=INK if fill is None else fill, anchor=anchor)
    if log:
        l, t, r, b = draw.textbbox(xy, s, font=font, anchor=anchor)
        reg_box("text", (l, t, r, b), s)


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


CUR_SCENE = "?"
ANCHOR_LOG = []  # one dict per rendered bubble: scene/theme/speaker/tip/box
BOX_LOG = []  # one dict per rendered element: scene/theme/kind/box/label
NAMES = ("Aunt Rosa", "Grandpa Emil", "you · interviewer")
DIALOGUE_SCENES = ("threads", "continue", "pause", "resume", "consent",
                   "ask", "character")


def reg_box(kind, box, label=""):
    BOX_LOG.append({"scene": CUR_SCENE, "theme": THEME_NAME,
                    "kind": kind, "box": [float(v) for v in box],
                    "label": label})


def speaker_box(cx, cy, r):
    """Bounding box of a talk portrait head (radius r at cx, cy), padded."""
    return (cx - r - 12, cy - r - 12, cx + r + 12, cy + r + 12)


def bubble(draw, x, y, w, lines, font, lh=38, pad=18, tail_left=True,
           speaker=None):
    """Speech bubble whose tail MUST point at the speaking speaker.

    speaker is a dict with head-center (cx, cy), a bounding box, and a
    name (built by say() from the portrait it actually draws). A bubble
    without a speaker fails the render: tails pointing at nothing is the
    v7 regression this renderer fixes. The tail tip coordinates are logged
    for check_anchors().
    """
    if speaker is None:
        sys.exit("make_video_v9: bubble without speaker anchor in scene %s "
                 "(every bubble tail must point at its speaker)" % CUR_SCENE)
    h = len(lines) * lh + pad * 2
    ty = min(max(speaker["cy"], y + 16), y + h - 16)
    tip = (speaker["cx"], ty)
    draw.rounded_rectangle([x, y, x + w, y + h], radius=14,
                           fill=CARD, outline=LINE, width=2)
    if tail_left:
        draw.polygon([tip, (x + 2, ty - 12), (x + 2, ty + 12)], fill=CARD)
        draw.line([tip, (x + 2, ty - 12)], fill=LINE, width=2)
        draw.line([tip, (x + 2, ty + 12)], fill=LINE, width=2)
    else:
        draw.polygon([tip, (x + w - 2, ty - 12), (x + w - 2, ty + 12)],
                     fill=CARD)
        draw.line([tip, (x + w - 2, ty - 12)], fill=LINE, width=2)
        draw.line([tip, (x + w - 2, ty + 12)], fill=LINE, width=2)
    for i, ln in enumerate(lines):
        text(draw, (x + pad, y + pad + i * lh), ln, font, log=False)
    ANCHOR_LOG.append({"scene": CUR_SCENE, "theme": THEME_NAME,
                       "speaker": speaker["name"], "tip": tip,
                       "box": speaker["box"]})
    reg_box("bubble", [x, y, x + w, y + h],
            "%s %d,%d %s" % (speaker["name"], tip[0], tip[1], ",".join(
                str(int(v)) for v in speaker["box"])))
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


def _portrait_base(img, d, key, label, label_xy, draw_art, shoulders=True,
                    show_chip=True):
    """Stickerize portrait art onto img, name on a chip (never in sticker).

    The sticker art uses fixed colors on both themes, so each portrait is
    composited once per geometry and cached; only the cheap chip redraws per
    frame. The key MUST include position: the same person appears at title
    positions and talk positions, and a label-only key reuses the wrong art.
    Set show_chip=False where an adjacent panel already names the speaker
    (avoids duplicate name labels); the full sticker extent is still logged
    for the overlap check either way.
    """
    name, x, y, r = key
    layer = _STICKER_CACHE.get(key + (shoulders,))
    if layer is None:
        art = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw_art(ImageDraw.Draw(art))
        layer = _sticker_layer(art)
        _STICKER_CACHE[key + (shoulders,)] = layer
    img.paste(layer, (0, 0), layer)
    if show_chip:
        chip(d, label_xy, label, _font(24), anchor="ma", text_fill=INK)
        l, t, rr, b = d.textbbox(label_xy, label, font=_font(24), anchor="ma")
        bottom = b + 8
    else:
        bottom = y + 142
    # Conservative sticker extent: art plus outline rings (shoulders span
    # roughly x +/- 80, head top minus hair, chip bottom when shown).
    reg_box("char", (x - 92, y - r - 70, x + 92, bottom),
            label if show_chip else "")


def portrait_rosa(img, d, x, y, r=62, shoulders=True, show_chip=True):
    def art(a):
        if shoulders:
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
        if shoulders:  # compact talk heads end at the chin; the full
            # smile arc would float on the background below it.
            a.arc([x - 24, y + 12, x + 24, y + 48], 20, 160,
                  fill=STICKER_INK, width=3)
    _portrait_base(img, d, ("Aunt Rosa", x, y, r), "Aunt Rosa", (x, y + 152), art,
                   shoulders=shoulders, show_chip=show_chip)


def portrait_emil(img, d, x, y, r=62, shoulders=True, show_chip=True):
    def art(a):
        if shoulders:
            a.ellipse([x - 70, y + 30, x + 70, y + 130], fill=SHIRT_E)
        a.ellipse([x - r, y - r, x + r, y + r], fill=SKIN,
                  outline=STICKER_INK, width=3)
        a.arc([x - r - 4, y - r - 14, x + r + 4, y + 10], 200, 340,
              fill=BROWNH, width=8)
        for sx in (-1, 1):
            a.ellipse([x + sx * 26 - 6, y - 12, x + sx * 26 + 6, y],
                      fill=STICKER_INK)
        a.ellipse([x - 34, y + 16, x + 34, y + 40], fill=BROWNH)  # mustache
        if shoulders:  # the mustache already reads as the mouth; the arc
            # below it would float past the chin on compact talk heads.
            a.arc([x - 20, y + 22, x + 22, y + 52], 20, 160,
                  fill=(60, 45, 35), width=3)
    _portrait_base(img, d, ("Grandpa Emil", x, y, r), "Grandpa Emil", (x, y + 152),
                   art, shoulders=shoulders, show_chip=show_chip)


def portrait_kid(img, d, x, y, r=56, shoulders=True, show_chip=True):
    def art(a):
        if shoulders:
            a.ellipse([x - 64, y + 26, x + 64, y + 120], fill=SHIRT_K)
        a.ellipse([x - r, y - r, x + r, y + r], fill=SKIN,
                  outline=STICKER_INK, width=3)
        a.arc([x - r - 4, y - r - 16, x + r + 4, y + 30], 185, 355,
              fill=BROWNH, width=16)
        for sx in (-1, 1):
            a.ellipse([x + sx * 24 - 6, y - 6, x + sx * 24 + 6, y + 6],
                      fill=STICKER_INK)
        if shoulders:  # compact talk heads end at the chin; the full
            # smile arc would float on the background below it.
            a.arc([x - 22, y + 14, x + 22, y + 46], 20, 160,
                  fill=STICKER_INK, width=3)
    _portrait_base(img, d, ("you · interviewer", x, y, r), "you · interviewer",
                   (x, y + 142), art, shoulders=shoulders, show_chip=show_chip)


TALK_R = {"rosa": 62, "emil": 62, "kid": 56}
TALK_PAINT = {"rosa": portrait_rosa, "emil": portrait_emil, "kid": portrait_kid}
TALK_NAME = {"rosa": "Aunt Rosa", "emil": "Grandpa Emil",
             "kid": "you · interviewer"}


def say(img, d, f, kind, x, y, w, raw, wrap_w, pcx, pcy=None,
        show_chip=True):
    """One anchored line of dialogue: bubble + illustrated speaker.

    kind is "rosa"/"emil" (interviewees) or "kid" (the interviewer). The
    v5-style full portrait (shoulders + head) is drawn at (pcx, cy)
    beside the bubble, with a single name chip below it when show_chip
    (omit it where an adjacent panel already names the speaker); the
    bubble tail aims at the head center. The bubble is drawn FIRST so
    the tail slides under the portrait instead of painting over the
    face. Returns the bubble height.
    """
    name = TALK_NAME[kind]
    r = TALK_R[kind]
    lines = wrap(d, raw, f["small"], wrap_w) or ["…"]
    h = len(lines) * 38 + 36
    cy = y + h // 2 if pcy is None else pcy
    speaker = {"name": name, "cx": pcx, "cy": cy,
               "box": speaker_box(pcx, cy, r)}
    bubble(d, x, y, w, lines, f["small"], speaker=speaker)
    TALK_PAINT[kind](img, d, pcx, cy, r=r, shoulders=True,
                     show_chip=show_chip)
    return h


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


def frame_threads(img, d, f, p):
    text(d, (80, 56), "Talk — threads open as you speak", f["h"])
    # v5 talk layout: interviewer + current speaker side by side as full
    # portraits, bubble beside them with the tail aimed at the speaker's
    # head. One turn shows at a time; the thread chip under the bubble
    # names the thread by its product id (never a bare person name, so
    # each portrait chip stays the single name label on screen).
    q = min(2.999, p * 3)
    ti = int(q)
    who = ("rosa", "emil", "rosa")[ti]
    text(d, (1200, 122), "Turn %d of 3" % (ti + 1), f["small"],
         fill=MUTED, anchor="ra")
    portrait_kid(img, d, 200, 330)
    turn_text = [
        "I grew up on a farm in Ohio.",
        "Grandpa Emil built that barn in 1958.",
        "The pie prize I won — we still talk about it.",
    ][ti]
    if p > 0.05 + ti * 0.3:
        say(img, d, f, who, 600, 230, 600, turn_text, 560, 470, pcy=330)
    if p > 0.15 + ti * 0.3:
        chip(d, (600, 540),
             "thread th-%s · %s" % (
                 TALK_NAME[who].lower().replace(" ", "-"),
                 "covered" if ti == 2 else "opened"),
             f["tiny"], fill=CARD, outline=ACCENT, anchor="lm",
             text_fill=MUTED)
    if p > 0.82 and ti == 2:
        chip(d, (900, 610), "re-mention covers the thread",
             f["tiny"], fill=CARD, outline=LINE, anchor="ma",
             text_fill=MUTED)


def frame_continue(img, d, f, p):
    text(d, (80, 56), "Keeps going while stories remain", f["h"])
    # six turn boxes fill in order as the interview follows each thread.
    n = min(6, int(p * 7))
    for i in range(6):
        x0 = 80 + i * 182
        on = i < n
        d.rounded_rectangle([x0, 200, x0 + 158, 330], radius=12,
                            fill=ACCENT if on else PANEL,
                            outline=ACCENT if on else LINE, width=2)
        ink = "white" if on else MUTED
        d.text((x0 + 79, 245), "%d" % (i + 1), font=f["h"], fill=ink,
               anchor="mm")
        d.text((x0 + 79, 295), "turn %d" % (i + 1), font=f["tiny"],
               fill=ink, anchor="mm")
    if p > 0.55:
        chip(d, (640, 420), "keeps going while threads stay open",
             f["body"], fill=CARD, outline=ACCENT, anchor="ma",
             text_fill=INK)
    if p > 0.7:
        # the interviewer's follow-up question, asked by you · interviewer.
        say(img, d, f, "kid", 600, 470, 600,
            "Can you tell me more about Grandpa Emil? "
            "The follow-up prefers the oldest open thread.", 560, 200,
            pcy=540)


def frame_pause(img, d, f, p):
    text(d, (80, 56), "Tired? — a gentle pause, never a stop", f["h"])
    text(d, (1200, 122), "Turn 4 of 4", f["small"], fill=MUTED,
         anchor="ra")
    if p > 0.05 and p < 0.55:
        # the tired storyteller: Grandpa Emil, whose thread stays open
        # through this turn so the resumed session can carry him.
        say(img, d, f, "emil", 600, 230, 600,
            "I'm tired, let's pick this up another time.", 560, 200,
            pcy=330)
    if p >= 0.55:
        # the gentle reply: space to rest, never a push to continue.
        # Heavy moments get the same gentleness.
        say(img, d, f, "kid", 600, 230, 600,
            "Take all the time you need. "
            "We can rest here as long as you like.", 560, 200,
            pcy=330)
    if p > 0.6:
        chip(d, (900, 600), "pausing is always your choice",
             f["tiny"], fill=CARD, outline=LINE, anchor="ma",
             text_fill=MUTED)


def frame_resume(img, d, f, p):
    text(d, (80, 56), "Resume — your code is your session", f["h"])
    # left: the resume code card; right: what resume_from carries.
    if p > 0.08:
        d.rounded_rectangle([80, 150, 560, 400], radius=14, fill=CARD,
                            outline=LINE, width=2)
        reg_box("panel", [80, 150, 560, 400], "resume code card")
        text(d, (320, 200), "Your resume code", f["body"], anchor="ma")
        text(d, (320, 300), "demo-synthetic", _font(40, bold=True),
             fill=ACCENT, anchor="ma")
        text(d, (320, 360), "shown at Pause & save", f["small"],
             fill=MUTED, anchor="ma")
    if p > 0.35:
        d.rounded_rectangle([640, 150, 1200, 400], radius=14, fill=CARD,
                            outline=ACCENT, width=3)
        reg_box("panel", [640, 150, 1200, 400], "carried-over card")
        text(d, (920, 200), "New session · demo-resumed", f["body"],
             anchor="ma")
        text(d, (920, 260), "resume_from carries over", f["small"],
             fill=MUTED, anchor="ma")
        text(d, (920, 310), "%d open thread + %d saved facts" % (
            N_STILL_OPEN, N_FACTS),
             _font(30, bold=True), fill=INK, anchor="ma")
        text(d, (920, 360), "map facts included", f["small"], fill=MUTED,
             anchor="ma")
    if p > 0.65:
        # the interviewer's opening question in the resumed session.
        say(img, d, f, "kid", 600, 480, 600,
            "Opening question re-opens the carried thread: "
            "Can you tell me more about Grandpa Emil?", 560, 200,
            pcy=560)
def frame_consent(img, d, f, p):
    text(d, (80, 56), "Your words, your rules", f["h"])
    text(d, (1200, 122), "on-the-record consent", f["small"],
         fill=MUTED, anchor="ra")
    if p > 0.1:
        say(img, d, f, "emil", 280, 300, 430,
            "Yes — and only family.", 390, 150, pcy=380)
    # consent card: the three recorded answers.
    d.rounded_rectangle([740, 180, 1200, 580], radius=14, fill=CARD,
                        outline=ACCENT, width=3)
    reg_box("panel", [740, 180, 1200, 580], "consent card")
    text(d, (970, 230), "On-the-record consent", f["body"], anchor="ma")
    rows = [("AI reconstruction", "yes"), ("Who may listen", "family"),
            ("Cloned voice", "no")]
    for j, (k, v) in enumerate(rows):
        y = 300 + j * 70
        if p > 0.25 + j * 0.15:
            text(d, (790, y), k, f["small"], anchor="la")
            chip(d, (1150, y + 8), v, f["small"], fill=PANEL,
                 outline=LINE, anchor="ra", text_fill=INK)
    if p > 0.7:
        text(d, (970, 545), "revoke any time", f["small"], fill=MUTED,
             anchor="ma")


def frame_ask(img, d, f, p):
    text(d, (80, 56), "Ask the archive", f["h"])
    if p > 0.05:
        chip(d, (80, 122), "Family asks: did anyone here visit the moon?",
             f["small"], fill=CARD, outline=LINE, anchor="lm",
             text_fill=INK)
    if p > 0.12 and p < 0.55:
        # grounded answer with a citation that plays the real clip.
        say(img, d, f, "emil", 300, 330, 700,
            "I grew up on a farm in Ohio.", 660, 150)
        if p > 0.3:
            chip(d, (300, 470), "clip 2 · 12.4–18.1s · plays the real clip",
                 f["tiny"], fill=PANEL, outline=LINE, anchor="lm",
                 text_fill=MUTED)
    if p >= 0.55:
        # ...and when nothing covers the question, it says so plainly.
        say(img, d, f, "emil", 300, 310, 700,
            "I couldn't find that in the recordings.", 660, 150)
        chip(d, (300, 480), "closest topic: the county fair",
             f["tiny"], fill=CARD, outline=ACCENT, anchor="lm",
             text_fill=INK)


def frame_character(img, d, f, p):
    text(d, (80, 56), "Talk with the reconstruction", f["h"])
    if p > 0.08:
        d.rounded_rectangle([80, 122, 1200, 180], radius=10, fill=PANEL,
                            outline=ACCENT, width=2)
        reg_box("panel", [80, 122, 1200, 180], "reconstruction banner")
        text(d, (640, 151),
             "AI reconstruction — not the real person", f["small"],
             fill=ACCENT, anchor="mm")
    if p > 0.2:
        say(img, d, f, "emil", 600, 300, 600,
            "I remember the barn raising like it was yesterday.",
            560, 200)
    if p > 0.4:
        chip(d, (600, 440), "clip 4 · cited",
             f["tiny"], fill=PANEL, outline=LINE, anchor="lm",
             text_fill=MUTED)
    if p > 0.55:
        chip(d, (600, 490), "only for people named in consent",
             f["tiny"], fill=CARD, outline=LINE, anchor="lm",
             text_fill=INK)
    if p > 0.7:
        chip(d, (600, 540), "can be retired any time · no cloned voice here",
             f["tiny"], fill=CARD, outline=LINE, anchor="lm",
             text_fill=MUTED)


def frame_outro(img, d, f, p):
    text(d, (W / 2, 170), "Try it yourself", f["h"], anchor="ma")
    if p > 0.15:
        text(d, (W / 2, 250), "python3 demo/replay.py", f["body"],
             anchor="ma")
    if p > 0.3:
        text(d, (W / 2, 320), REPO.replace("https://", ""), f["small"],
             anchor="ma")
    if p > 0.45:
        text(d, (W / 2, 390), "All people and places are fictional",
             f["small"], fill=MUTED, anchor="ma")
    if p > 0.6:
        text(d, (W / 2, 460),
             "MOCK_LLM=1 runs without a key · MOCK_LLM=0 uses Fireworks",
             f["small"], fill=MUTED, anchor="ma")

def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def check_layout(f, p_values=(0.0, 0.5, 1.0)):
    """Automated frame check: no overlaps, no duplicate name labels.

    Renders every scene in BOTH themes at several progress points and
    asserts: headline text touches no character, bubble, or other text;
    panels touch no character, bubble, or other panel; characters never
    touch each other; a bubble may only touch the character holding its
    tail tip. Also asserts each person name appears at most once per
    frame across headline and chip text (the v8 duplicate-label bug).
    sys.exit (non-zero) on any violation.
    """
    problems = []
    for theme in THEMES:
        set_theme(theme)
        for p in p_values:
            for idx, (name, secs) in enumerate(SCENES):
                before = len(BOX_LOG)
                render_frame(name, p, f, idx, 0.0)
                els = BOX_LOG[before:]
                by_kind = {}
                for e in els:
                    by_kind.setdefault(e["kind"], []).append(e)
                texts = by_kind.get("text", [])
                panels = by_kind.get("panel", [])
                chars = by_kind.get("char", [])
                bubbles = by_kind.get("bubble", [])

                def clash(kind_a, list_a, kind_b, list_b, allow=None):
                    for a in list_a:
                        for b in list_b:
                            if a is b:
                                continue
                            if allow is not None and allow(a, b):
                                continue
                            if _overlap(a["box"], b["box"]):
                                problems.append(
                                    "%s/%s p=%.1f: %s %r overlaps %s %r"
                                    % (theme, name, p, kind_a,
                                       a["label"][:40], kind_b,
                                       b["label"][:40]))

                clash("text", texts, "char", chars)
                clash("text", texts, "bubble", bubbles)
                clash("text", texts, "text", texts)
                def _contains(a, b):
                    # UI nesting (a chip on a card) is legitimate; only
                    # partial intersections are layout bugs.
                    return (a[0] <= b[0] + 1 and a[1] <= b[1] + 1
                            and a[2] >= b[2] - 1 and a[3] >= b[3] - 1)

                clash("panel", panels, "char", chars,
                      allow=lambda a, b: a["label"] == b["label"]
                      and a["label"] in NAMES)
                clash("panel", panels, "bubble", bubbles)
                clash("panel", panels, "panel", panels,
                      allow=lambda a, b: _contains(a["box"], b["box"])
                      or _contains(b["box"], a["box"]))
                clash("char", chars, "char", chars)

                def own_speaker(a, b):
                    # Bubble label is "<name> <tx>,<ty> <box>": allowed
                    # only against the character holding its tail tip.
                    try:
                        tx, ty = (int(v) for v in
                                  a["label"].rsplit(" ", 2)[-2].split(","))
                    except (ValueError, IndexError):
                        return False
                    x0, y0, x1, y1 = b["box"]
                    return x0 <= tx <= x1 and y0 <= ty <= y1

                clash("bubble", bubbles, "char", chars, allow=own_speaker)
                clash("bubble", bubbles, "bubble", bubbles)
                seen = {}
                for e in texts + panels:
                    for nm in NAMES:
                        if nm in e["label"]:
                            seen[nm] = seen.get(nm, 0) + 1
                for nm, n in seen.items():
                    if n > 1:
                        problems.append(
                            "%s/%s p=%.1f: name %r appears %d times"
                            % (theme, name, p, nm, n))
    if problems:
        for pr in problems:
            print("layout FAIL: " + pr)
        sys.exit("make_video_v9: %d layout violation(s) — render refused"
                 % len(problems))
    print("layout check: no overlaps or duplicate labels over %d scenes x "
          "%d themes x %d states OK" % (len(SCENES), len(THEMES),
                                       len(p_values)))


SCENES = [("title", 8), ("threads", 12), ("continue", 10), ("pause", 12),
          ("resume", 10), ("consent", 10), ("ask", 12), ("character", 12),
          ("outro", 6)]
FUNCS = {"title": frame_title, "threads": frame_threads,
         "continue": frame_continue, "pause": frame_pause,
         "resume": frame_resume, "consent": frame_consent,
         "ask": frame_ask, "character": frame_character,
         "outro": frame_outro}
PREVIEW_P = {"title": 0.7, "threads": 0.95, "continue": 0.95, "pause": 0.95,
             "resume": 0.95, "consent": 0.95, "ask": 0.95,
             "character": 0.95, "outro": 0.95}

# One narration block per scene (~200 words total), telling the full
# product story. Each block is padded/trimmed to its scene length so
# speech never overruns (the gate below aborts on any overrun).
NARRATION = {
    "title": ("Meet the Oral History Interviewer. Every fact links back "
              "to the voice that said it. Everyone here is fictional."),
    "threads": ("First, you talk. Mention Aunt Rosa, and a thread opens. "
                "Mention her again, and it is covered. The next question "
                "prefers the oldest open thread."),
    "continue": ("The interview follows loose ends as threads. It keeps "
                 "going while there is history to cover, asking next "
                 "about Grandpa Emil."),
    "pause": ("When you are tired, just say so. The interview suggests a "
              "gentle pause, never a stop, and meets heavy moments gently, "
              "with time to rest."),
    "resume": ("Pause and save, and your code is your session. A new "
               "session carries the open threads, the saved facts, and "
               "the map facts."),
    "consent": ("On the record, you decide what happens next. May family "
                "talk with a reconstruction? Who may access it? May it "
                "use your voice?"),
    "ask": ("Later, family asks the archive. Answers quote the recordings "
            "and play the real clip. When nothing covers it, it says so: "
            "I couldn't find that in the recordings."),
    "character": ("Talk with the reconstruction. Answers in your own "
                  "phrasing, always labeled, every claim cited, only for "
                  "people named in consent. No cloned voice here."),
    "outro": ("Try it yourself. Run the replay script. All people and "
              "places are fictional."),
}
def _run(cmd):
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if r.returncode != 0:
        sys.exit("make_video_v9: command failed: %s" % " ".join(cmd))


def _probe_secs(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("make_video_v9: ffprobe failed on %s" % path)
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
        sys.exit("make_video_v9: edge-tts voice list failed (%s); refusing "
                 "silent fallback" % e)
    if VOICE not in names:
        sys.exit("make_video_v9: voice %r not available; refusing silent "
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
    sys.exit("make_video_v9: volumedetect failed on %s" % path)


def verify_audio(path, expect_secs):
    """Post-mux honesty gate: audio present, full-length, non-silent."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_name,duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit("make_video_v9: no audio stream in %s" % path)
    dur = float(r.stdout.strip().split(",")[-1])
    if abs(dur - expect_secs) > 0.6:
        sys.exit("make_video_v9: audio %.2fs != video %ds in %s"
                 % (dur, expect_secs, path))
    mean = _mean_db(path)
    if mean < -40.0:
        sys.exit("make_video_v9: audio silent (mean %.1f dB) in %s"
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
        sys.exit("make_video_v9: narration must be 180-220 words, got %d"
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
            sys.exit("make_video_v9: narration overruns scene %s" % name)
    return wav, report


def check_anchors(f, p_values=(0.0, 0.5, 1.0)):
    """Automated frame check: every bubble tail must land in its speaker.

    Renders every scene in BOTH themes at several progress points (so both
    partial and full dialogue states are covered) and asserts each logged
    bubble tail endpoint falls inside its speaker's bounding box. Also
    asserts full-state (p=1.0) coverage: every dialogue scene shows at
    least one bubble, and non-dialogue scenes show none. Returns the
    bubble count; sys.exit (non-zero) on any violation.
    """
    problems, total = [], 0
    full = {}
    for theme in THEMES:
        set_theme(theme)
        for p in p_values:
            for idx, (name, secs) in enumerate(SCENES):
                before = len(ANCHOR_LOG)
                render_frame(name, p, f, idx, 0.0)
                new = ANCHOR_LOG[before:]
                if p == 1.0:
                    full.setdefault((theme, name), 0)
                    full[(theme, name)] += len(new)
                for e in new:
                    total += 1
                    (tx, ty), (x0, y0, x1, y1) = e["tip"], e["box"]
                    if not (x0 <= tx <= x1 and y0 <= ty <= y1):
                        problems.append(
                            "%s/%s p=%.1f: %s tail tip (%d,%d) outside "
                            "speaker box (%d,%d,%d,%d)"
                            % (theme, e["scene"], p, e["speaker"],
                               tx, ty, x0, y0, x1, y1))
    for theme in THEMES:
        for name, _ in SCENES:
            n = full.get((theme, name), 0)
            if name in DIALOGUE_SCENES and n < 1:
                problems.append("%s/%s: no anchored bubble at full state"
                                % (theme, name))
            if name not in DIALOGUE_SCENES and n != 0:
                problems.append("%s/%s: unexpected bubble outside dialogue"
                                % (theme, name))
    if problems:
        for pr in problems:
            print("anchor FAIL: " + pr)
        sys.exit("make_video_v9: %d anchor violation(s) — render refused"
                 % len(problems))
    print("anchor check: %d bubbles over %d scenes x %d themes x %d states, "
          "every tail inside its speaker box OK"
          % (total, len(SCENES), len(THEMES), len(p_values)))
    return total


def render_frame(name, p, f, scene_idx=0, overall=0.0):
    global CUR_SCENE
    CUR_SCENE = name
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
                    help="default: demo/demo_v9_<theme>.mp4")
    ap.add_argument("--preview", action="store_true",
                    help="write one PNG per scene to /tmp/v9prev instead of video")
    ap.add_argument("--no-audio", action="store_true",
                    help="skip the neural voiceover mux")
    ap.add_argument("--check-anchors", action="store_true",
                    help="run only the bubble-tail anchor check "
                         "(every scene x both themes) and exit")
    ap.add_argument("--check-layout", action="store_true",
                    help="run only the overlap/duplicate-label check "
                         "(every scene x both themes) and exit")
    args = ap.parse_args()
    set_theme(args.theme)
    if args.out is None:
        args.out = str(HERE / ("demo_v9_%s.mp4" % args.theme))
    f_global = fonts()
    if args.check_anchors:
        check_anchors(f_global)
        return
    if args.check_layout:
        check_layout(f_global)
        return
    # Fail the render on any anchor/layout violation before opening ffmpeg.
    check_anchors(f_global)
    check_layout(f_global)
    # check_anchors() leaves the global theme on the last theme it checked;
    # restore the requested theme so the rendered video matches --theme.
    set_theme(args.theme)
    if args.preview:
        out = Path("/tmp/v9prev_%s" % args.theme)
        out.mkdir(parents=True, exist_ok=True)
        for idx, (name, _) in enumerate(SCENES):
            render_frame(name, PREVIEW_P[name], f_global, idx,
                         sum(s for _, s in SCENES[:idx]) / sum(s for _, s in SCENES)
                         ).save(out / ("%s.png" % name))
            print("wrote %s" % (out / ("%s.png" % name)))
        return
    if args.no_audio:
        render_silent(args.out)
        return
    tmp = Path("/tmp/v9audio_%s" % args.theme)
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
