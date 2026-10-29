"""Render demo/demo.mp4: a ~55s explainer of one interview turn.

Pure Pillow frames (1280x720@30fps) piped to ffmpeg/libx264. Same fictional
script as demo/script.json (Aunt Rosa, Grandpa Emil — invented names).
Usage: python3 demo/make_video.py [--out demo/demo.mp4]
"""

import argparse
import math
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1280, 720, 30
INK, MUTED, LINE, ACCENT, PANEL = (
    (20, 32, 28), (75, 85, 99), (216, 220, 217), (14, 107, 94), (244, 245, 244))
FONT = "/System/Library/Fonts/Helvetica.ttc"


def fonts():
    return {
        "title": ImageFont.truetype(FONT, 64),
        "h": ImageFont.truetype(FONT, 44),
        "body": ImageFont.truetype(FONT, 32),
        "small": ImageFont.truetype(FONT, 26),
    }


def text(draw, xy, s, font, fill=INK, anchor="la"):
    draw.text(xy, s, font=font, fill=fill, anchor=anchor)


def chip(draw, xy, label, font):
    x, y = xy
    w = int(draw.textlength(label, font=font)) + 36
    draw.rounded_rectangle([x, y, x + w, y + 52], radius=8,
                           fill=(230, 240, 236), outline=LINE, width=2)
    text(draw, (x + 18, y + 26), label, font, anchor="lm")
    return w + 14


def frame_title(d, f, p):
    text(d, (W / 2, 250), "Oral History Interviewer", f["title"], anchor="ma")
    if p > 0.25:
        text(d, (W / 2, 350), "Every fact links back to the voice that said it.",
             f["body"], anchor="ma")
    if p > 0.55:
        text(d, (W / 2, 420), "a hackathon demo · all names fictional",
             f["small"], fill=MUTED, anchor="ma")


WORDS = "I grew up on a farm in Ohio with Aunt Rosa.".split()


def frame_talk(d, f, p):
    text(d, (80, 70), "1 · Talk — push to talk", f["h"])
    n = min(len(WORDS), int(p * len(WORDS)) + 1)
    text(d, (80, 170), " ".join(WORDS[:n]), f["body"])
    text(d, (80, 230), "seg-0 · 0.0–3.5s   seg-1 · 3.5–6.0s", f["small"], fill=MUTED)
    for i in range(48):
        h = 20 + 90 * abs(math.sin(i * 0.7 + p * 12)) * (0.3 + 0.7 * p)
        x = 80 + i * 22
        d.rectangle([x, 560 - h, x + 12, 560], fill=ACCENT)


Q = "What was your favorite memory with Aunt Rosa on the farm?"
CHIPS = ["person · Aunt Rosa · seg-0", "place · farm in Ohio · seg-0",
         "event · grew up on a farm · seg-0"]


def frame_think(d, f, p):
    text(d, (80, 70), "2 · Think — two Fireworks calls at once", f["h"])
    q = Q[: int(p * 2 * len(Q))]
    d.rounded_rectangle([80, 170, 1200, 270], radius=8, fill=PANEL, outline=LINE, width=2)
    text(d, (110, 220), "Q: " + q, f["body"], anchor="lm")
    for j, c in enumerate(CHIPS):
        if p > 0.45 + j * 0.15:
            chip(d, (80 + sum(int(d.textlength(x, font=f["small"])) + 50
                              for x in CHIPS[:j]), 330), c, f["small"])


def frame_map(d, f, p):
    text(d, (80, 70), "3 · Map — timeline and family map fill in", f["h"])
    if p > 0.15:
        text(d, (80, 180), "undated — grew up on a farm in Ohio  [clip 0.0–3.5s]", f["body"])
    for j, (name, init) in enumerate([("Aunt Rosa", "AR"), ("Grandpa Emil", "GE")]):
        if p > 0.35 + j * 0.2:
            r = int(60 * min(1.0, (p - 0.35 - j * 0.2) * 5))
            x, y = 220 + j * 320, 470
            d.ellipse([x - r, y - r, x + r, y + r], fill=(220, 235, 228))
            if r > 30:
                text(d, (x, y), init, f["h"], anchor="mm")
                text(d, (x, y + 90), name, f["body"], anchor="ma")


def frame_replay(d, f, p):
    text(d, (80, 70), "4 · Replay — click a fact, hear the moment", f["h"])
    d.rounded_rectangle([80, 170, 1200, 270], radius=8, outline=ACCENT, width=4)
    text(d, (110, 220), "▶  person · Aunt Rosa   0.0–3.5s", f["body"], anchor="lm")
    d.rounded_rectangle([80, 330, 1200, 366], radius=6, fill=PANEL)
    d.rectangle([80, 330, 80 + int(1120 * min(1.0, p * 1.2)), 366], fill=ACCENT)
    text(d, (80, 420), f"{min(3.5, p * 4.2):.1f}s / 3.5s", f["small"], fill=MUTED)


def frame_outro(d, f, p):
    text(d, (W / 2, 200), "Try it yourself", f["h"], anchor="ma")
    if p > 0.2:
        text(d, (W / 2, 300), "python3 demo/replay.py", f["body"], anchor="ma")
    if p > 0.4:
        text(d, (W / 2, 360), "github.com/source-while-1/oral-history-interviewer",
             f["body"], anchor="ma")
    if p > 0.6:
        text(d, (W / 2, 450), "Live path: MOCK_LLM=0 with a Fireworks key",
             f["small"], fill=MUTED, anchor="ma")


SCENES = [("title", 6), ("talk", 10), ("think", 12), ("map", 12),
          ("replay", 8), ("outro", 8)]
FUNCS = {"title": frame_title, "talk": frame_talk, "think": frame_think,
         "map": frame_map, "replay": frame_replay, "outro": frame_outro}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "demo.mp4"))
    args = ap.parse_args()
    f = fonts()
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
                img = Image.new("RGB", (W, H), "white")
                d = ImageDraw.Draw(img)
                FUNCS[name](d, f, k / (secs * FPS))
                ff.stdin.write(img.tobytes())
                n += 1
    finally:
        ff.stdin.close()
        rc = ff.wait()
    if rc != 0:
        sys.exit(f"ffmpeg failed (rc={rc})")
    print(f"wrote {args.out}: {n} frames, {n / FPS:.0f}s")


if __name__ == "__main__":
    main()
