"""Render demo_v14 light/dark explainers: the generational story. The
grandson sets up one link per grandparent; Rosa and Emil each talk with
the app on their own time (pause, resume, consent each); he leaves a
topic for next time; years later his grandchild asks the family, hears
both great-grandparents' real voices, sees agreement plus the honest
disagreement side by side, and visits a labeled reconstruction. Restyled
to match the redesigned index.html — 3-step nav (one step visible at a
time), plain-language headings, details-collapsed panels, light + dark
themes — with Plex Serif display type, full-body v5-style portraits,
layout chips, and an edge-tts neural voiceover.

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
  .venv/bin/python demo/make_video_v14.py [--out demo/demo_v14_light.mp4]
  .venv/bin/python demo/make_video_v14.py --preview   # one PNG per scene
  .venv/bin/python demo/make_video_v14.py --theme dark --no-audio
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

SCENE_KICKER = {"title": "00 · INTRO", "links": "01 · ONE LINK EACH",
                "rosa": "02 · ROSA'S TURN", "emil": "03 · EMIL'S TURN",
                "pause": "04 · GENTLE PAUSE", "resume": "05 · COME BACK",
                "consent": "06 · HER RULES",
                "ask": "07 · YEARS LATER · ASK THE FAMILY",
                "character": "08 · VISIT HER STORIES",
                "outro": "09 · OUTRO"}

# Which of the 3 redesigned-UI steps each scene belongs to (None = intro /
# outro framing, drawn with Step 1 active since the product says
# "Start at step 1"). Mirrors index.html nav.modes: one visible step at
# a time, the active button marked like aria-current="step".
STEP_ACTIVE = {"title": 0, "links": 0, "rosa": 0, "emil": 0, "pause": 0,
               "resume": 0, "consent": 0, "ask": 1, "character": 2,
               "outro": 0}
STEP_LABELS = ("1 · Record a story", "2 · Ask the recordings",
               "3 · Talk with the AI")


def draw_stepnav(d, f, active):
    """The redesigned index.html step nav: 3 buttons, one active at a time.

    Fixed strip y=60..100 under the kicker rule; scene headings moved to
    y=108 so nothing touches it (see check_layout). Active step carries
    the ACCENT outline like aria-current="step"; inactive steps are quiet
    PANEL buttons. Labels avoid person names (duplicate-label check).
    """
    xs = (80, 456, 832)
    for i, (x0, label) in enumerate(zip(xs, STEP_LABELS)):
        x1 = x0 + 366
        on = (i == active)
        d.rounded_rectangle([x0, 60, x1, 100], radius=10,
                            fill=CARD if on else PANEL,
                            outline=ACCENT if on else LINE,
                            width=3 if on else 2)
        reg_box("panel", [x0, 60, x1, 100], "step nav %d" % (i + 1))
        d.text(((x0 + x1) / 2, 80), label, font=f["tiny"],
               fill=ACCENT if on else MUTED, anchor="mm")
        l, t, r, b = d.textbbox(((x0 + x1) / 2, 80), label,
                                font=f["tiny"], anchor="mm")
        reg_box("text", (l, t, r, b), label)


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
    reg_box("panel", [80, H - 22, 1200, H - 16], "progress bar")
    d.rectangle([80, H - 22, 80 + int(1120 * overall), H - 16], fill=ACCENT)
    # version label floats on its own chip 14px above the bar so the two
    # never touch (v3 drew the text directly onto the bar row).
    chip(d, (1200, H - 56),
         "demo v14 · %s · scene %d/%d" % (THEME_NAME, idx + 1, len(SCENES)),
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
        sys.exit("make_video_v14: cannot read demo script %s: %s" % (SCRIPT, e))


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
SPOKEN_LOG = []  # one dict per spoken line: scene/speaker/text/src
KIND_SPEAKER = {"rosa": "Aunt Rosa", "emil": "Grandpa Emil",
                "ghost": "Aunt Rosa", "kid": None}
NAMES = ("Aunt Rosa", "Grandpa Emil", "you · interviewer")
DIALOGUE_SCENES = ("links", "rosa", "emil", "pause", "resume", "consent",
                   "character")
# NOTE: "ask" answers through system panels, never speech bubbles, so it
# is exempt from the per-scene bubble-coverage rule.


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
        sys.exit("make_video_v14: bubble without speaker anchor in scene %s "
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


def draw_dashed_ring(d, cx, cy, rad, color, width=3, dash=14, gap=10):
    """Dashed circle outline (marks the reconstruction as not-real)."""
    a = 0
    while a < 360:
        d.arc([cx - rad, cy - rad, cx + rad, cy + rad], a,
              min(a + dash, 360), fill=color, width=width)
        a += dash + gap


def _portrait_base(img, d, key, label, label_xy, draw_art, shoulders=True,
                    show_chip=True, ghost=False):
    """Stickerize portrait art onto img, name on a chip (never in sticker).

    The sticker art uses fixed colors on both themes, so each portrait is
    composited once per geometry and cached; only the cheap chip redraws per
    frame. The key MUST include position: the same person appears at title
    positions and talk positions, and a label-only key reuses the wrong art.
    Set show_chip=False where an adjacent panel already names the speaker
    (avoids duplicate name labels); the full sticker extent is still logged
    for the overlap check either way. ghost=True washes the portrait out,
    rings the head dashed, and labels it an AI reconstruction instead of
    a living person.
    """
    name, x, y, r = key
    layer = _STICKER_CACHE.get(key + (shoulders, ghost))
    if layer is None:
        art = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw_art(ImageDraw.Draw(art))
        layer = _sticker_layer(art)
        _STICKER_CACHE[key + (shoulders, ghost)] = layer
    img.paste(layer, (0, 0), layer)
    if ghost:
        wash = Image.new("RGB", (2 * r + 56, r + 200), BG)
        region = (int(x - r - 28), int(y - r - 46))
        img.paste(Image.blend(img.crop(region + (
            region[0] + 2 * r + 56, region[1] + r + 200)), wash, 0.45),
            region)
        draw_dashed_ring(d, x, y, r + 20, ACCENT)
    if show_chip:
        chip(d, label_xy, label, _font(24), anchor="ma", text_fill=INK,
             **({"fill": PANEL, "outline": ACCENT} if ghost else {}))
        l, t, rr, b = d.textbbox(label_xy, label, font=_font(24), anchor="ma")
        bottom = b + 8
    else:
        bottom = y + 142
    # Conservative sticker extent: art plus outline rings (shoulders span
    # roughly x +/- 80, head top minus hair, chip bottom when shown).
    reg_box("char", (x - 92, y - r - 70, x + 92, bottom),
            label if show_chip else "")


def portrait_rosa(img, d, x, y, r=62, shoulders=True, show_chip=True,
                   ghost=False, label=None):
    who = "Ghost Rosa" if ghost else "Aunt Rosa"
    tag = label if label is not None else ("AI reconstruction" if ghost
                                           else "Aunt Rosa")
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
    _portrait_base(img, d, (who, x, y, r), tag, (x, y + 152), art,
                   shoulders=shoulders, show_chip=show_chip, ghost=ghost)


def portrait_ghost(img, d, x, y, r=62, shoulders=True, show_chip=True):
    """The labeled AI reconstruction: Rosa's features, washed out with a
    dashed ring and an AI-reconstruction tag instead of a name chip."""
    portrait_rosa(img, d, x, y, r=r, shoulders=shoulders,
                  show_chip=show_chip, ghost=True)


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


TALK_R = {"rosa": 62, "emil": 62, "kid": 56, "ghost": 62}
TALK_PAINT = {"rosa": portrait_rosa, "emil": portrait_emil, "kid": portrait_kid,
              "ghost": portrait_ghost}
TALK_NAME = {"rosa": "Aunt Rosa", "emil": "Grandpa Emil",
             "kid": "you · interviewer", "ghost": "AI reconstruction"}


def say(img, d, f, kind, x, y, w, raw, wrap_w, pcx, pcy=None,
        show_chip=True, src="session"):
    """One anchored line of dialogue: bubble + illustrated speaker.

    kind is "rosa"/"emil" (interviewees), "kid" (the interviewer), or
    "ghost" (the labeled AI reconstruction, drawn washed-out with a
    dashed ring instead of a living portrait). The v5-style full
    portrait (shoulders + head) is drawn at (pcx, cy) beside the
    bubble, with a single name chip below it when show_chip (omit it
    where an adjacent panel already names the speaker); the bubble
    tail aims at the head center. The bubble is drawn FIRST so the
    tail slides under the portrait instead of painting over the
    face. src is "session" for lines quoted from demo/script.json turns
    (the consistency check requires them to match the same speaker's
    turn) or "product" for invented product-UI lines (audited, never
    presented as session quotes). Returns the bubble height.
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
    SPOKEN_LOG.append({"scene": CUR_SCENE, "kind": kind, "text": raw,
                       "src": src})
    return h


def frame_title(img, d, f, p):
    text(d, (W / 2, 150), "Oral History Interviewer", f["title"], anchor="ma")
    if p > 0.2:
        text(d, (W / 2, 240), "Every story keeps its voice.",
             f["body"], anchor="ma")
    if p > 0.4:
        portrait_rosa(img, d, 440, 420)
        portrait_emil(img, d, 640, 420)
        portrait_kid(img, d, 840, 420)
    if p > 0.65:
        text(d, (W / 2, 628), "a demo · everyone here is fictional",
             f["small"], fill=MUTED, anchor="ma")


def frame_links(img, d, f, p):
    text(d, (80, 108), "Step 1 · One link per grandparent", f["h"])
    # the grandson sets it up: one personal link card per grandparent.
    if p > 0.08:
        d.rounded_rectangle([80, 180, 560, 400], radius=14, fill=CARD,
                            outline=ACCENT, width=3)
        reg_box("panel", [80, 180, 560, 400], "Rosa link card")
        text(d, (320, 216), "Rosa's link", f["body"], anchor="ma")
        text(d, (320, 300), "rosa-1958", _font(40, bold=True),
             fill=ACCENT, anchor="ma")
        text(d, (320, 356), "for Aunt Rosa", f["small"],
             fill=MUTED, anchor="ma")
    if p > 0.3:
        d.rounded_rectangle([640, 180, 1200, 400], radius=14, fill=CARD,
                            outline=ACCENT, width=3)
        reg_box("panel", [640, 180, 1200, 400], "Emil link card")
        text(d, (920, 216), "Emil's link", f["body"], anchor="ma")
        text(d, (920, 300), "emil-1958", _font(40, bold=True),
             fill=ACCENT, anchor="ma")
        text(d, (920, 356), "for Grandpa Emil", f["small"],
             fill=MUTED, anchor="ma")
    if p > 0.55:
        # the grandson's own words: a statement, never a question — every
        # interview question in this story comes from the app itself.
        # (Product-illustrated line, not a session quote.)
        say(img, d, f, "kid", 600, 470, 600,
            "I set up one link for each of them.", 560, 200,
            pcy=540, show_chip=False, src="product")
    if p > 0.8:
        chip(d, (600, 620), "Each talks on their own time",
             f["tiny"], fill=CARD, outline=LINE, anchor="lm",
             text_fill=MUTED)


def frame_rosa(img, d, f, p):
    text(d, (80, 108), "Step 1 · Rosa talks on her own time", f["h"])
    text(d, (1200, 122), "Tuesday · her link", f["small"],
         fill=MUTED, anchor="ra")
    if p > 0.08:
        chip(d, (1200, 200), "App asks Rosa: tell me about the farm",
             f["small"], fill=CARD, outline=ACCENT, anchor="rm",
             text_fill=INK)
    if p > 0.3:
        # Rosa's own recorded words (session quote, checked).
        say(img, d, f, "rosa", 600, 230, 600,
            "I grew up on a farm in Ohio with Grandpa Emil.", 560, 470,
            pcy=330, show_chip=False)
    if p > 0.6:
        chip(d, (600, 420),
             "The app remembers Grandpa Emil for next time",
             f["tiny"], fill=CARD, outline=LINE, anchor="lm",
             text_fill=MUTED)
    if p > 0.8:
        chip(d, (80, 620), "> What we've learned so far (collapsed)",
             f["tiny"], fill=CARD, outline=LINE, anchor="lm",
             text_fill=MUTED)


def frame_emil(img, d, f, p):
    text(d, (80, 108), "Step 1 · Emil talks on his own time", f["h"])
    text(d, (1200, 122), "Thursday · his link", f["small"],
         fill=MUTED, anchor="ra")
    if p > 0.08:
        chip(d, (1200, 200), "App asks Emil: tell me about the barn",
             f["small"], fill=CARD, outline=ACCENT, anchor="rm",
             text_fill=INK)
    if p > 0.3:
        # Emil's own recorded words (session quote, checked).
        say(img, d, f, "emil", 600, 230, 600,
            "I built that barn in 1958 with my brother.", 560, 470,
            pcy=330, show_chip=False)
    if p > 0.6:
        chip(d, (600, 420),
             "The app remembers Aunt Rosa for next time",
             f["tiny"], fill=CARD, outline=LINE, anchor="lm",
             text_fill=MUTED)
    if p > 0.8:
        chip(d, (80, 620), "> What we've learned so far (collapsed)",
             f["tiny"], fill=CARD, outline=LINE, anchor="lm",
             text_fill=MUTED)


def frame_pause(img, d, f, p):
    text(d, (80, 108), "Step 1 · Rosa rests when she needs to", f["h"])
    text(d, (1200, 122), "Her link · evening", f["small"], fill=MUTED,
         anchor="ra")
    if p > 0.05:
        # the tired storyteller is Rosa herself: the pause beat belongs
        # to the same interviewee as the resume and consent beats.
        # (Product-illustrated line, not a session quote.)
        say(img, d, f, "rosa", 600, 250, 600,
            "I would like to rest now. I will come back.", 560, 150,
            pcy=310, show_chip=False, src="product")
    if p > 0.35:
        # the gentle reply is the point of this scene: the app itself
        # answers her, in a panel — never a question from a relative.
        d.rounded_rectangle([740, 420, 1200, 560], radius=12, fill=PANEL,
                            outline=ACCENT, width=2)
        reg_box("panel", [740, 420, 1200, 560], "app rests panel")
        text(d, (780, 452), "THE APP RESTS WITH HER", f["tiny"],
             fill=MUTED, anchor="la")
        text(d, (780, 492), "Take all the time you need.",
             f["small"], anchor="la")
    if p > 0.6:
        chip(d, (900, 620), "Rest as long as you like",
             f["tiny"], fill=CARD, outline=LINE, anchor="ma",
             text_fill=MUTED)
    if p > 0.8:
        chip(d, (1200, 168), "> Her code to come back",
             f["tiny"], fill=CARD, outline=LINE, anchor="ra",
             text_fill=MUTED)


def frame_resume(img, d, f, p):
    text(d, (80, 108), "Step 1 · Rosa comes back anytime", f["h"])
    # left: her code card; right: the welcome-back card (plain words,
    # no function names, counts, or map-facts inventory).
    if p > 0.08:
        d.rounded_rectangle([80, 168, 560, 380], radius=14, fill=CARD,
                            outline=LINE, width=2)
        reg_box("panel", [80, 168, 560, 380], "resume code card")
        text(d, (320, 200), "Rosa's code to come back", f["body"],
             anchor="ma")
        text(d, (320, 296), "rosa-1958", _font(40, bold=True),
             fill=ACCENT, anchor="ma")
        text(d, (320, 350), "we showed it when she paused", f["small"],
             fill=MUTED, anchor="ma")
    if p > 0.35:
        d.rounded_rectangle([640, 168, 1200, 380], radius=14, fill=CARD,
                            outline=ACCENT, width=3)
        reg_box("panel", [640, 168, 1200, 380], "carried-over card")
        text(d, (920, 200), "Welcome back, Rosa", f["body"],
             anchor="ma")
        text(d, (920, 256), "picks up where she left off", f["small"],
             fill=MUTED, anchor="ma")
        text(d, (920, 306), "%d stories kept" % N_STILL_OPEN,
             _font(30, bold=True), fill=INK, anchor="ma")
    if p > 0.65:
        # Rosa herself, back on her link: a statement, never a question.
        # (Product-illustrated line, not a session quote.)
        say(img, d, f, "rosa", 600, 460, 600,
            "I am back. My stories are still here.", 560, 200,
            pcy=516, show_chip=False, src="product")
    if p > 0.8:
        chip(d, (600, 620), "Grandson leaves a topic: the winter harvest",
             f["tiny"], fill=CARD, outline=LINE, anchor="lm",
             text_fill=MUTED)
def frame_consent(img, d, f, p):
    text(d, (80, 108), "Step 1 · Rosa's words, her rules", f["h"])
    if p > 0.1:
        # Rosa consents on screen herself: the reconstruction later may
        # only show her because she said yes here.
        # (Product-illustrated line, not a session quote.)
        say(img, d, f, "rosa", 280, 300, 430,
            "Yes, only family may listen.", 390, 150, pcy=380,
            show_chip=False, src="product")
    # consent card: the three recorded answers.
    d.rounded_rectangle([740, 180, 1200, 580], radius=14, fill=CARD,
                        outline=ACCENT, width=3)
    reg_box("panel", [740, 180, 1200, 580], "consent card")
    text(d, (970, 230), "Your words, your rules", f["body"], anchor="ma")
    rows = [("Share my stories", "yes"), ("Who may listen", "family"),
            ("Copy my voice", "no")]
    for j, (k, v) in enumerate(rows):
        y = 300 + j * 70
        if p > 0.25 + j * 0.15:
            text(d, (790, y), k, f["small"], anchor="la")
            chip(d, (1150, y + 8), v, f["small"], fill=PANEL,
                 outline=LINE, anchor="ra", text_fill=INK)
    if p > 0.7:
        text(d, (970, 545), "you can take it back anytime", f["small"],
             fill=MUTED, anchor="ma")
    if p > 0.85:
        chip(d, (80, 614), "> What we've learned so far (collapsed)",
             f["tiny"], fill=CARD, outline=LINE, anchor="lm",
             text_fill=MUTED)


def frame_ask(img, d, f, p):
    # Years later, the grandson's child searches the family archive. The
    # archive answers as the system, never through a character's mouth:
    # one voice panel per great-grandparent, then agreement and the
    # honest disagreement side by side. No portraits here.
    text(d, (80, 100), "Step 2 · Years later: ask the family", f["h"])
    if p > 0.05:
        chip(d, (80, 186), "The archive is asked: where did Rosa grow up?",
             f["small"], fill=CARD, outline=LINE, anchor="lm",
             text_fill=INK)
    if p > 0.2:
        d.rounded_rectangle([80, 212, 1200, 332], radius=12, fill=PANEL,
                            outline=ACCENT, width=2)
        reg_box("panel", [80, 212, 1200, 332], "archive Rosa answer panel")
        text(d, (120, 230), "HER OWN WORDS", f["tiny"], fill=MUTED,
             anchor="la")
        text(d, (120, 266), "\u201cI grew up on a farm in Ohio with "
                          "Grandpa Emil.\u201d",
             f["small"], anchor="la")
        SPOKEN_LOG.append({"scene": CUR_SCENE, "kind": "rosa",
                           "text": "I grew up on a farm in Ohio with "
                                   "Grandpa Emil.",
                           "src": "session"})
    if p > 0.35:
        chip(d, (80, 350),
             "plays Rosa\u2019s own voice \u25b6",
             f["tiny"], fill=PANEL, outline=LINE, anchor="lm",
             text_fill=MUTED)
    if p > 0.45:
        chip(d, (80, 386), "The archive is asked: when was the barn built?",
             f["small"], fill=CARD, outline=LINE, anchor="lm",
             text_fill=INK)
    if p > 0.55:
        d.rounded_rectangle([80, 418, 1200, 538], radius=12, fill=PANEL,
                            outline=ACCENT, width=2)
        reg_box("panel", [80, 418, 1200, 538], "archive Emil answer panel")
        text(d, (120, 436), "HIS OWN WORDS", f["tiny"], fill=MUTED,
             anchor="la")
        text(d, (120, 472), "\u201cI built that barn in 1958 with my "
                          "brother.\u201d",
             f["small"], anchor="la")
        SPOKEN_LOG.append({"scene": CUR_SCENE, "kind": "emil",
                           "text": "I built that barn in 1958 with my "
                                   "brother.",
                           "src": "session"})
    if p > 0.7:
        chip(d, (80, 564),
             "They agree: the county-fair pie prize, both voices",
             f["tiny"], fill=CARD, outline=ACCENT, anchor="lm",
             text_fill=INK)
    if p > 0.82:
        chip(d, (80, 604),
             "They differ: barn year, Emil 1958 vs Rosa 1959, side by side",
             f["tiny"], fill=CARD, outline=LINE, anchor="lm",
             text_fill=INK)
    if p > 0.92:
        # the collapsed "Which recordings?" details from Step 2.
        chip(d, (80, 642), "> Which recordings the archive played: both",
             f["tiny"], fill=CARD, outline=LINE, anchor="lm",
             text_fill=MUTED)


def frame_character(img, d, f, p):
    # The reconstruction never wears a living face: Rosa's features
    # washed out, dashed ring, AI-reconstruction tag on the figure
    # itself — plus the banner above. It answers with her own recorded
    # words (a session quote, checked), never invented ones. She may
    # only appear here because she consented on screen earlier.
    text(d, (80, 108), "Step 3 · Visit Rosa's stories", f["h"])
    if p > 0.08:
        d.rounded_rectangle([80, 160, 1200, 218], radius=10, fill=PANEL,
                            outline=ACCENT, width=2)
        reg_box("panel", [80, 160, 1200, 218], "reconstruction banner")
        text(d, (640, 189),
             "Not the real person — her recorded stories", f["small"],
             fill=ACCENT, anchor="mm")
    if p > 0.2:
        say(img, d, f, "ghost", 600, 300, 600,
            "I grew up on a farm in Ohio with Grandpa Emil.", 560, 200,
            pcy=380)
    if p > 0.4:
        chip(d, (600, 440), "Her words · from her recording",
             f["tiny"], fill=PANEL, outline=LINE, anchor="lm",
             text_fill=MUTED)
    if p > 0.55:
        chip(d, (600, 490), "only because she said yes",
             f["tiny"], fill=CARD, outline=LINE, anchor="lm",
             text_fill=INK)
    if p > 0.7:
        chip(d, (600, 540), "close it any time · never her voice, only her words",
             f["tiny"], fill=CARD, outline=LINE, anchor="lm",
             text_fill=MUTED)
    if p > 0.85:
        chip(d, (600, 590), "> Who may visit",
             f["tiny"], fill=CARD, outline=LINE, anchor="lm",
             text_fill=INK)


def frame_outro(img, d, f, p):
    text(d, (W / 2, 170), "Every story keeps its voice.", f["h"],
         anchor="ma")
    if p > 0.15:
        text(d, (W / 2, 250), "Record one person you love", f["body"],
             anchor="ma")
    if p > 0.28:
        text(d, (W / 2, 320), "Ask them tonight.", f["body"],
             anchor="ma")
    if p > 0.42:
        text(d, (W / 2, 390), REPO.replace("https://", ""), f["small"],
             anchor="ma")
    if p > 0.55:
        text(d, (W / 2, 445), "developers: python3 demo/replay.py",
             f["small"], fill=MUTED, anchor="ma")
    if p > 0.68:
        text(d, (W / 2, 500), "All people and places are fictional",
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
                      and len(a["label"]) > 0)
                clash("panel", panels, "bubble", bubbles)
                clash("panel", panels, "panel", panels,
                      allow=lambda a, b: _contains(a["box"], b["box"])
                      or _contains(b["box"], a["box"]))
                clash("text", texts, "panel", panels,
                      allow=lambda a, b: _contains(b["box"], a["box"]))
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
                for e in els:
                    x0, y0, x1, y1 = e["box"]
                    if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
                        problems.append(
                            "%s/%s p=%.1f: %s %r off-canvas %s"
                            % (theme, name, p, e["kind"],
                               e["label"][:40],
                               [int(v) for v in e["box"]]))
    if problems:
        for pr in problems:
            print("layout FAIL: " + pr)
        sys.exit("make_video_v14: %d layout violation(s) — render refused"
                 % len(problems))
    print("layout check: no overlaps or duplicate labels over %d scenes x "
          "%d themes x %d states OK" % (len(SCENES), len(THEMES),
                                       len(p_values)))


def _norm_quote(s):
    return re.sub(r"\s+", " ",
                  re.sub(r"[^a-z0-9 ]", "", s.lower())).strip()


FIRST_PERSON_RE = re.compile(
    r"\b(i|me|my|mine|myself|we|us|our|ours|ourselves)\b",
    re.IGNORECASE)


def check_quotes(f):
    """Every session-sourced line must map to the same speaker's turn.

    Renders every scene in BOTH themes at several progress points (so
    animated moments are all collected), then requires each src="session"
    line to (1) appear (normalized) inside a demo/script.json turn spoken
    by the SAME speaker, (2) contain a first-person marker (genuine
    first-person speech by its labeled speaker), and (3) NOT contain the
    speaker's own name tokens (no third-person self-mention: Rosa never
    says "rosa", Emil never says "emil"). src="product" lines are listed
    for audit but never presented as session quotes. sys.exit (non-zero)
    on any mismatch.
    """
    SPOKEN_LOG.clear()
    for theme in THEMES:
        set_theme(theme)
        for p in (0.1, 0.5, 1.0):
            for idx, (name, secs) in enumerate(SCENES):
                render_frame(name, p, f, idx, 0.0)
    script = json.loads(SCRIPT.read_text())
    by_speaker = {}
    for t in script.get("turns", []):
        if t.get("speaker"):
            by_speaker.setdefault(t["speaker"], []).append(
                _norm_quote(t.get("transcript", "")))
    by_key = {}
    for e in SPOKEN_LOG:
        by_key.setdefault((e["scene"], e["text"]), e)
    problems = []
    for key in sorted(by_key):
        e = by_key[key]
        if e["src"] != "session":
            print("quote audit (product line): %s: %r (%s)" % (
                e["scene"], e["text"][:60], e["kind"]))
            continue
        want = KIND_SPEAKER.get(e["kind"])
        norm = _norm_quote(e["text"])
        own_tokens = set(want.lower().split()) if want else set()
        if not want or not any(norm and norm in t for t in
                               by_speaker.get(want, [])):
            problems.append(
                "%s: %r is not spoken by %s in demo/script.json"
                % (e["scene"], e["text"][:60], want))
            continue
        if not FIRST_PERSON_RE.search(e["text"]):
            problems.append(
                "%s: %r has no first-person marker (not genuine "
                "first-person speech by %s)"
                % (e["scene"], e["text"][:60], want))
            continue
        hit = own_tokens.intersection(norm.split())
        if hit:
            problems.append(
                "%s: %r mentions the speaker's own name %r (%s speaks "
                "of themselves in the third person)"
                % (e["scene"], e["text"][:60], sorted(hit), want))
            continue
        print("quote OK (session line): %s: %r (%s)" % (
            e["scene"], e["text"][:60], want))
    if problems:
        for pr in problems:
            print("quote FAIL: " + pr)
        sys.exit("make_video_v14: %d quote/speaker mismatch(es) — "
                 "render refused" % len(problems))
    print("quote check: %d session lines map to the same speaker's "
          "turns OK" % sum(1 for e in by_key.values()
                            if e["src"] == "session"))


def check_story(f):
    """Story-consistency gate for the generational story: fail unless —

    1. the reconstructed person is shown consenting (the ghost maps to
       Rosa, so the consent scene must carry Rosa's own yes);
    2. the pause, resume, and consent beats all belong to that same
       interviewee (every bubble in those scenes speaks as Rosa);
    3. every interview question comes from the app, never a family
       member (no spoken bubble may ask anything; every on-screen
       question mark must sit in an app/archive panel).
    sys.exit (non-zero) on any mismatch.
    """
    SPOKEN_LOG.clear()
    ANCHOR_LOG.clear()
    for theme in THEMES:
        set_theme(theme)
        for p in (0.1, 0.5, 1.0):
            for idx, (name, secs) in enumerate(SCENES):
                render_frame(name, p, f, idx, 0.0)
    problems = []
    spoken = {}
    for e in SPOKEN_LOG:
        spoken.setdefault((e["scene"], e["text"]), e)
    anchors = {}
    for e in ANCHOR_LOG:
        anchors.setdefault((e["scene"], e["speaker"], e["tip"]), e)

    # 1. the reconstruction (ghost -> Rosa) must be shown consenting.
    ghost_person = KIND_SPEAKER.get("ghost")
    consent_kinds = {KIND_SPEAKER.get(e["kind"]) for e in spoken.values()
                     if e["scene"] == "consent" and e["src"] != "archive"}
    consent_texts = [e["text"] for e in spoken.values()
                     if e["scene"] == "consent"]
    if ghost_person not in consent_kinds:
        problems.append(
            "reconstruction shows %s but the consent scene never shows "
            "%s consenting" % (ghost_person, ghost_person))
    if not any("yes" in t.lower() for t in consent_texts):
        problems.append("consent scene shows no yes from the interviewee")
    for e in spoken.values():
        if e["scene"] == "character" and e["kind"] == "ghost" \
                and e["src"] != "session":
            problems.append("character scene: the reconstruction speaks "
                            "invented words %r" % e["text"][:60])

    # 2. pause/resume/consent beats belong to the same interviewee.
    for beat in ("pause", "resume", "consent"):
        who = {e["speaker"] for e in anchors.values()
               if e["scene"] == beat}
        if not who:
            problems.append("%s beat shows nobody speaking" % beat)
        elif who != {ghost_person}:
            problems.append(
                "%s beat belongs to %s, not the interviewee %s"
                % (beat, sorted(who), ghost_person))

    # 3. all interview questions come from the app, never a relative.
    for key in sorted(spoken):
        e = spoken[key]
        if "?" in e["text"]:
            problems.append(
                "%s: spoken line asks %r (questions must come from the "
                "app, never a family member)" % (e["scene"],
                                                 e["text"][:60]))
    asked_app = len({
        e["label"] for e in BOX_LOG
        if e["kind"] == "panel" and "?" in e["label"]
        and ("app" in e["label"].lower()
             or "archive" in e["label"].lower())})
    if asked_app < 2:
        problems.append("fewer than 2 app-asked questions on screen "
                        "(found %d)" % asked_app)
    for label in sorted({e["label"] for e in BOX_LOG}):
        if "?" in label and "app" not in label.lower() \
                and "archive" not in label.lower():
            problems.append("on-screen question is not app-asked: %r"
                            % label[:60])

    # the family arc must show both: agreement and the honest
    # disagreement, side by side.
    labels = " ".join(e["label"] for e in BOX_LOG)
    if "pie prize" not in labels:
        problems.append("ask scene never shows what they agree on")
    if "1958" not in labels or "1959" not in labels:
        problems.append("ask scene never shows the 1958 vs 1959 "
                        "disagreement side by side")
    if problems:
        for pr in problems:
            print("story FAIL: " + pr)
        sys.exit("make_video_v14: %d story-consistency violation(s) — "
                 "render refused" % len(problems))
    print("story check: reconstruction=%s consented; pause/resume/consent "
          "all %s; %d app-asked questions; agreement + disagreement shown OK"
          % (ghost_person, ghost_person, asked_app))


SCENES = [("title", 12), ("links", 12), ("rosa", 12), ("emil", 12),
          ("pause", 11), ("resume", 11), ("consent", 11), ("ask", 16),
          ("character", 15), ("outro", 10)]
FUNCS = {"title": frame_title, "links": frame_links,
         "rosa": frame_rosa, "emil": frame_emil, "pause": frame_pause,
         "resume": frame_resume, "consent": frame_consent,
         "ask": frame_ask, "character": frame_character,
         "outro": frame_outro}
PREVIEW_P = {"title": 0.7, "links": 0.95, "rosa": 0.95, "emil": 0.95,
             "pause": 0.95, "resume": 0.95, "consent": 0.95, "ask": 0.95,
             "character": 0.95, "outro": 0.95}

# One narration block per scene (~200 words total), telling the
# generational story: the grandson, Rosa, Emil, and years later the
# grandson's child. Names are always explicit (never bare "he"/"she"
# across a cut) so the who's-who survives the time jump. Each block is
# padded/trimmed to its scene length so speech never overruns (the gate
# below aborts on any overrun).
NARRATION = {
    "title": ("Rosa is eighty-two. She remembers the Ohio farm. "
              "Her brother Emil does too. One day both voices go quiet. "
              "Unless Rosa's grandson asks now."),
    "links": ("So the grandson starts simple. He makes one link for Rosa, "
              "and one for Emil. Each of them can talk on their own time."),
    "rosa": ("On Tuesday Rosa opens her link. The app asks about the farm. "
             "She talks. It remembers the people she names for next time."),
    "emil": ("On Thursday Emil opens his own link. The app asks about the "
             "barn. He built that barn in nineteen fifty-eight. His own "
             "words."),
    "pause": ("Then Rosa gets tired. She says she needs to rest. The app "
              "does not push. It keeps her place."),
    "resume": ("The next Sunday Rosa comes back. One short code brings her "
               "home. The grandson leaves a topic for next time."),
    "consent": ("But first, Rosa decides. Only family may listen. Nothing "
                "speaks in her voice. And she can take it back."),
    "ask": ("Years later the grandson's child searches the family archive. "
            "Both answers come back in their own voices. The pie prize "
            "they agree on. The barn year they remember differently."),
    "character": ("And when they miss Rosa, they can visit her stories. "
                  "Not the real person. Only what she recorded. Only "
                  "because she said yes."),
    "outro": ("Every story keeps its voice. Start with one person you "
              "love. Ask them tonight."),
}
def _run(cmd):
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if r.returncode != 0:
        sys.exit("make_video_v14: command failed: %s" % " ".join(cmd))


def _probe_secs(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("make_video_v14: ffprobe failed on %s" % path)
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
        sys.exit("make_video_v14: edge-tts voice list failed (%s); refusing "
                 "silent fallback" % e)
    if VOICE not in names:
        sys.exit("make_video_v14: voice %r not available; refusing silent "
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
    sys.exit("make_video_v14: volumedetect failed on %s" % path)


def verify_audio(path, expect_secs):
    """Post-mux honesty gate: audio present, full-length, non-silent."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_name,duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit("make_video_v14: no audio stream in %s" % path)
    dur = float(r.stdout.strip().split(",")[-1])
    if abs(dur - expect_secs) > 0.6:
        sys.exit("make_video_v14: audio %.2fs != video %ds in %s"
                 % (dur, expect_secs, path))
    mean = _mean_db(path)
    if mean < -40.0:
        sys.exit("make_video_v14: audio silent (mean %.1f dB) in %s"
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
    if not 180 <= words_total <= 240:
        sys.exit("make_video_v14: narration must be 180-240 words, got %d"
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
            sys.exit("make_video_v14: narration overruns scene %s" % name)
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
        sys.exit("make_video_v14: %d anchor violation(s) — render refused"
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
    # Redesigned-UI framing on every scene: 3-step nav, one step active.
    draw_stepnav(d, f, STEP_ACTIVE[name])
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
                    help="default: demo/demo_v14_<theme>.mp4")
    ap.add_argument("--preview", action="store_true",
                    help="write one PNG per scene to /tmp/v14prev instead of video")
    ap.add_argument("--no-audio", action="store_true",
                    help="skip the neural voiceover mux")
    ap.add_argument("--check-anchors", action="store_true",
                    help="run only the bubble-tail anchor check "
                         "(every scene x both themes) and exit")
    ap.add_argument("--check-layout", action="store_true",
                    help="run only the overlap/duplicate-label check "
                         "(every scene x both themes) and exit")
    ap.add_argument("--check-quotes", action="store_true",
                    help="run only the quote/speaker consistency check "
                         "against demo/script.json and exit")
    ap.add_argument("--check-story", action="store_true",
                    help="run only the generational story-consistency "
                         "check (consent, beats, app-asked questions) "
                         "and exit")
    args = ap.parse_args()
    set_theme(args.theme)
    if args.out is None:
        args.out = str(HERE / ("demo_v14_%s.mp4" % args.theme))
    f_global = fonts()
    if args.check_anchors:
        check_anchors(f_global)
        return
    if args.check_layout:
        check_layout(f_global)
        return
    if args.check_quotes:
        check_quotes(f_global)
        return
    if args.check_story:
        check_story(f_global)
        return
    # Fail the render on any anchor/layout/quote/story violation.
    check_anchors(f_global)
    check_layout(f_global)
    check_quotes(f_global)
    check_story(f_global)
    # check_anchors() leaves the global theme on the last theme it checked;
    # restore the requested theme so the rendered video matches --theme.
    set_theme(args.theme)
    if args.preview:
        out = Path("/tmp/v14prev_%s" % args.theme)
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
    tmp = Path("/tmp/v14audio_%s" % args.theme)
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
