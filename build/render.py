"""Render the slideshow from timeline.txt + the song.

  .venv/bin/python build/render.py --format 16x9            # full quality
  .venv/bin/python build/render.py --format 9x16 --preview  # half-res quick check
  .venv/bin/python build/render.py --from 50 --to 70        # render a time range only
"""
import argparse, json, math, subprocess
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
SONG = ROOT / "Lose A Friend.wav"
FONTS = Path("/System/Library/Fonts")

FIRST_PHOTO_BAR = 3      # bar index where the first photo arrives (title before it)
END_CARD_BAR = 116       # bar index where the end card arrives
ZCAP = 1.28              # plates are built big enough for this much zoom


# ---------------------------------------------------------------- timeline

def parse_timeline(manifest):
    chapters, placed = [], set()
    for raw in (ROOT / "timeline.txt").read_text().splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("=="):
            name, _, opt = s[2:].partition("|")
            chapters.append(dict(name=name.strip(), slides=[], slow="slow" in opt))
            continue
        skip, pair = s.startswith("-"), s.startswith("+")
        fields = [f.strip() for f in s.lstrip("+-").split("|")]
        pid = fields[0]
        placed.add(pid)
        opts = {}
        for f in fields[1:]:
            for tok in f.split():
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    opts[k] = v
            if f == "hold":
                opts["hold"] = "1"
        if skip or chapters[-1]["name"].upper().startswith("NEW"):
            continue
        item = dict(id=pid, **opts)
        if pair and chapters[-1]["slides"]:
            chapters[-1]["slides"][-1].append(item)
        else:
            chapters[-1]["slides"].append([item])
    unplaced = [e for e in manifest.values() if e["id"] not in placed]
    if unplaced:
        with open(ROOT / "timeline.txt", "a") as fh:
            if "== NEW" not in (ROOT / "timeline.txt").read_text():
                fh.write("\n== NEW (not placed yet)\n")
            for e in sorted(unplaced, key=lambda e: e["id"]):
                big = max(range(len(e["faces"])), key=lambda i: e["faces"][i]["h"]) if e["faces"] else "c"
                fh.write(f"  {e['id']} | {e['file'][:58]:<58} | focus={big}\n")
        print(f"NOTE: {len(unplaced)} new photo(s) added to the NEW chapter in timeline.txt (not in this render)")
    return [c for c in chapters if c["slides"]]


# ---------------------------------------------------------------- music plan

class Grid:
    """Time grid in half-bar units (h). Bar b starts at h = 2b."""
    def __init__(self, song):
        self.bars, self.beats = song["bars"], song["beats"]
        self.phase, self.dur = song["downbeat_phase"], song["duration"]
        self.barlen = float(np.median(np.diff(self.bars)))
        self.sections = sorted({int(np.argmin([abs(b - t) for b in self.bars])) for t in song["sections"][1:]})

    def t(self, h):
        b, r = divmod(int(h), 2)
        if b >= len(self.bars):
            return min(self.dur, self.bars[-1] + (b - len(self.bars) + 1 + r / 2) * self.barlen)
        if r == 0:
            return self.bars[b]
        i = self.phase + 4 * b + 2
        return self.beats[i] if i < len(self.beats) else self.bars[b] + self.barlen / 2


def allocate(total, weights, unit):
    """Split `total` (half-bars) by weight in multiples of `unit` (each >= 1 unit).
    Cumulative rounding spreads the shorter slides evenly through the chapter."""
    units = total // unit
    if units < len(weights):
        unit, units = 1, total
    cum, acc, edges = sum(weights), 0.0, [0]
    for i, w in enumerate(weights):
        acc += w
        e = round(acc / cum * units)
        e = max(e, edges[-1] + 1)
        e = min(e, units - (len(weights) - 1 - i))
        edges.append(e)
    out = [(b - a) * unit for a, b in zip(edges, edges[1:])]
    out[-1] += total - sum(out)
    return out


def plan(chapters, grid, fmt):
    for c in chapters:  # 9:16 shows pairs one after the other
        if fmt == "9x16":
            c["slides"] = [[it] for s in c["slides"] for it in s]
    def weight(s, last):
        w = 1.0 if len(s) == 1 else 1.6
        w += sum(float(it.get("hold", 0)) for it in s)
        return 3.0 if last else w
    cw = [[weight(s, ci == len(chapters) - 1 and si == len(c["slides"]) - 1) * (2.2 if c["slow"] else 1)
           for si, s in enumerate(c["slides"])] for ci, c in enumerate(chapters)]
    h0, h1 = 2 * FIRST_PHOTO_BAR, 2 * END_CARD_BAR
    # chapter starts: snap the proportional position to a song section (or an 8-bar phrase)
    tot = sum(map(sum, cw))
    starts, acc = [h0], 0
    for ci in range(len(chapters) - 1):
        acc += sum(cw[ci])
        ideal = h0 + (h1 - h0) * acc / tot
        cands = [2 * b for b in grid.sections] + list(range(16, h1, 16))
        lo = starts[-1] + 2 * len(chapters[ci]["slides"]) * 0.6
        cands = [c for c in cands if lo <= c <= h1 - 2 * sum(len(x["slides"]) for x in chapters[ci + 1:]) * 0.6]
        best = min(cands, key=lambda c: abs(c - ideal) + (0 if c // 2 in grid.sections else 3)) if cands else round(ideal)
        starts.append(best)
    starts.append(h1)
    slides = []
    for ci, c in enumerate(chapters):
        lens = allocate(starts[ci + 1] - starts[ci], cw[ci], 2)
        h = starts[ci]
        for si, (s, L) in enumerate(zip(c["slides"], lens)):
            slides.append(dict(items=s, h0=h, h1=h + L, chapter=ci, chapter_start=si == 0))
            h += L
    return slides, starts


# ---------------------------------------------------------------- images

def grade(a):
    f = a.astype(np.float32) / 255.0
    lum = f.mean(axis=2)
    lo, hi = np.percentile(lum, [0.4, 99.6])
    f = 0.5 * f + 0.5 * np.clip((f - lo) / max(hi - lo, 0.05), 0, 1)       # gentle auto-levels
    f = 0.5 + (f - 0.5) * 1.04                                               # a touch of contrast
    g = f.mean(axis=2, keepdims=True)
    f = g + (f - g) * 0.9                                                    # slightly calmer colour
    f = f * np.array([1.025, 1.0, 0.965], np.float32)                        # warm
    f = 0.03 + f * 0.95                                                      # soft film blacks
    return (np.clip(f, 0, 1) * 255).astype(np.uint8)


def trim_borders(a):
    """Remove solid black/white bars (screenshots, scans)."""
    g = a.mean(axis=2)
    def solid(line):
        return line.std() < 4 and (line.mean() < 22 or line.mean() > 243)
    t, b, l, r = 0, g.shape[0], 0, g.shape[1]
    while t < b * 0.3 and solid(g[t, l:r]): t += 1
    while b > g.shape[0] * 0.7 and solid(g[b - 1, l:r]): b -= 1
    while l < r * 0.3 and solid(g[t:b, l]): l += 1
    while r > g.shape[1] * 0.7 and solid(g[t:b, r - 1]): r -= 1
    pad = 2 if (t, b, l, r) != (0, g.shape[0], 0, g.shape[1]) else 0
    return t + pad * (t > 0), b - pad * (b < g.shape[0]), l + pad * (l > 0), r - pad * (r < g.shape[1])


@lru_cache(maxsize=8)
def load_item(pid, crop, focus, manifest_key):
    e = MANIFEST_BY_ID[pid]
    up = BUILD / "upscaled" / f"{pid}.jpg"     # cleaner version of old low-res photos, if made
    a = np.array(Image.open(up if up.exists() else BUILD / "cache" / f"{pid}.jpg").convert("RGB"))
    H, W = a.shape[:2]
    x0, y0, x1, y1 = 0, 0, W, H
    if crop:
        c = [float(v) for v in crop.split(",")]
        x0, y0, x1, y1 = int(c[0] * W), int(c[1] * H), int(c[2] * W), int(c[3] * H)
    sub = a[y0:y1, x0:x1]
    t, b, l, r = trim_borders(sub)
    sub = sub[t:b, l:r]
    ox, oy = x0 + l, y0 + t
    # focus point in the trimmed image (pixels) and face height
    fpt, fh = None, None
    if focus not in (None, "", "c", "none"):
        if "," in focus:
            fx, fy = (float(v) for v in focus.split(","))
            fpt, fh = (fx * W - ox, fy * H - oy), 0.12 * H
        else:
            f = e["faces"][int(focus)]
            fpt = ((f["x"] + f["w"] / 2) * W - ox, (f["y"] + f["h"] / 2) * H - oy)
            fh = f["h"] * H
    # box around every face in the photo, with room for hair and chins, so nobody gets cropped out
    sh, sw = sub.shape[:2]
    boxes = [((f["x"] - 0.5 * f["w"]) * W - ox, (f["y"] - 0.6 * f["h"]) * H - oy,
              (f["x"] + 1.5 * f["w"]) * W - ox, (f["y"] + 1.8 * f["h"]) * H - oy) for f in e["faces"]]
    boxes = [b for b in boxes if b[2] > 0 and b[3] > 0 and b[0] < sw and b[1] < sh]
    keep = None
    if boxes:
        keep = (max(min(b[0] for b in boxes), 0), max(min(b[1] for b in boxes), 0),
                min(max(b[2] for b in boxes), sw), min(max(b[3] for b in boxes), sh))
    return grade(sub), fpt, fh, len(e["faces"]), keep


def resize(a, w, h):
    interp = cv2.INTER_AREA if w < a.shape[1] else cv2.INTER_LANCZOS4
    return cv2.resize(a, (max(1, int(round(w))), max(1, int(round(h)))), interpolation=interp)


def blurred_bg(a, W, H):
    s = max(W / a.shape[1], H / a.shape[0])
    small = resize(a, a.shape[1] * s / 6, a.shape[0] * s / 6)
    sh, sw = small.shape[:2]
    cy, cx = (sh - H // 6) // 2, (sw - W // 6) // 2
    small = small[max(cy, 0):max(cy, 0) + H // 6, max(cx, 0):max(cx, 0) + W // 6]
    small = cv2.GaussianBlur(small, (0, 0), 5)
    bg = resize(small, W, H).astype(np.float32)
    g = bg.mean(axis=2, keepdims=True)
    bg = (g + (bg - g) * 0.8) * 0.55
    return bg


def paste_with_shadow(canvas, img, x, y):
    h, w = img.shape[:2]
    H, W = canvas.shape[:2]
    pad = int(0.04 * max(h, w))
    mask = np.zeros((H, W), np.float32)
    off = int(0.006 * max(H, W))
    mask[max(y + off, 0):y + off + h, max(x, 0):x + w] = 1
    mask = cv2.GaussianBlur(mask, (0, 0), pad / 2.5)
    canvas *= (1 - 0.55 * mask)[..., None]
    canvas[y:y + h, x:x + w] = img
    return canvas


def build_plate(slide, W, H):
    """Return (plate uint8, Lino focus point, box that must stay in frame, max push zoom)."""
    items = slide["items"]
    loaded = [load_item(it["id"], it.get("crop"), it.get("focus"), None) for it in items]
    PW, PH = int(W * ZCAP), int(H * ZCAP)
    A = W / H
    if len(loaded) == 1:
        a, fpt, fh, nfaces, keep = loaded[0]
        r = (a.shape[1] / a.shape[0]) / A
        if 0.72 <= r <= 1 / 0.72:   # cover: crop window moves inside the photo
            s = max(PW / a.shape[1], PH / a.shape[0])
            plate = resize(a, a.shape[1] * s, a.shape[0] * s)
            fp = (fpt[0] * s, fpt[1] * s) if fpt else None
            small_face = fh is not None and fh * s < 0.09 * PH
            zoom = 1.12 if small_face else 1.09
            return plate, fp, (tuple(v * s for v in keep) if keep else None), zoom
        # contain: photo floats over a soft blurred copy of itself
        plate = blurred_bg(a, PW, PH)
        margin = 0.90
        s = min(PW * margin / a.shape[1], PH * margin / a.shape[0])
        img = resize(a, a.shape[1] * s, a.shape[0] * s).astype(np.float32)
        x, y = (PW - img.shape[1]) // 2, (PH - img.shape[0]) // 2
        plate = paste_with_shadow(plate, img, x, y)
        fp = (x + fpt[0] * s, y + fpt[1] * s) if fpt else None
        return np.clip(plate, 0, 255).astype(np.uint8), fp, None, 1.05
    # pair: two photos side by side
    a0 = loaded[0][0]
    plate = blurred_bg(a0, PW, PH)
    gap = int(0.018 * PW)
    boxw, boxh = (PW * 0.92 - gap) / 2, PH * 0.88
    imgs = []
    for a, fpt, fh, _, _ in loaded:
        s = min(boxw / a.shape[1], boxh / a.shape[0])
        imgs.append((resize(a, a.shape[1] * s, a.shape[0] * s).astype(np.float32), fpt, s))
    total = imgs[0][0].shape[1] + gap + imgs[1][0].shape[1]
    x = (PW - total) // 2
    for img, fpt, s in imgs:
        y = (PH - img.shape[0]) // 2
        plate = paste_with_shadow(plate, img, x, y)
        x += img.shape[1] + gap
    return np.clip(plate, 0, 255).astype(np.uint8), None, None, 1.04


def text_plate(lines, W, H):
    """lines: list of (text, (font path, index), size as fraction, tracking, gap after, colour).
    Lines too wide for the frame wrap onto two balanced lines, then shrink if still too wide."""
    PW, PH = int(W * 1.06), int(H * 1.06)
    im = Image.new("RGB", (PW, PH), (6, 6, 6))
    d = ImageDraw.Draw(im)
    maxw = 0.88 * W
    particles = {"de", "del", "della", "da", "das", "do", "dos", "di", "la", "le", "van", "von", "y"}

    def measure(text, f, track):
        widths = [d.textlength(ch, font=f) for ch in text]
        return widths, sum(widths) + track * f.size * max(len(text) - 1, 0)

    blocks = []
    for text, font, size, track, gap_after, col in lines:
        px = int(size * min(PW * 1.25, PH * 1.4))
        f = ImageFont.truetype(str(font[0]), px, index=font[1])
        parts = [text]
        if measure(text, f, track)[1] > maxw and " " in text:
            words = text.split(" ")
            cuts = [k for k in range(1, len(words)) if words[k - 1].lower() not in particles] or list(range(1, len(words)))
            cut = min(cuts, key=lambda k: abs(len(" ".join(words[:k])) - len(" ".join(words[k:]))))
            parts = [" ".join(words[:cut]), " ".join(words[cut:])]
        widest = max(measure(p_, f, track)[1] for p_ in parts)
        if widest > maxw:
            f = ImageFont.truetype(str(font[0]), int(px * maxw / widest), index=font[1])
        asc, desc = f.getmetrics()
        for k, part in enumerate(parts):
            widths, tw = measure(part, f, track)
            last = k == len(parts) - 1
            blocks.append((part, f, widths, tw, asc + desc if last else int((asc + desc) * 0.92),
                           track, gap_after if last else 0, col))
    total = sum(b[4] + b[6] * PH for b in blocks)
    y = (PH - total) / 2
    for text, f, widths, tw, lh, track, gap_after, col in blocks:
        x = (PW - tw) / 2
        for ch, w in zip(text, widths):
            d.text((x, y), ch, font=f, fill=col)
            x += w + track * f.size
        y += lh + gap_after * PH
    return np.array(im)


# ---------------------------------------------------------------- motion

def window_at(plate, fp, keep, zoom, p, push, W, H):
    PH, PW = plate.shape[:2]
    A = W / H
    bw, bh = (PW, PW / A) if PW / PH < A else (PH * A, PH)
    bw, bh = min(bw, PW), min(bh, PH)
    def clamp(cx, cy, ww, wh):
        return (min(max(cx, ww / 2), PW - ww / 2), min(max(cy, wh / 2), PH - wh / 2))
    pc = (PW / 2, PH / 2)
    if keep:  # never zoom so far that someone's face leaves the frame
        zoom = max(1.0, min(zoom, bw / max(keep[2] - keep[0], 1), bh / max(keep[3] - keep[1], 1)))
    if fp:
        end = (fp[0], fp[1] + 0.10 * bh / zoom)     # face sits a little above centre
        start = (pc[0] + 0.3 * (end[0] - pc[0]), pc[1] + 0.3 * (end[1] - pc[1]))
    else:
        end = start = pc
    q = 0.75 * p + 0.25 * (0.5 - 0.5 * math.cos(math.pi * p))
    if not push:
        q = 1 - q
    z = 1 + (zoom - 1) * q
    ww, wh = bw / z, bh / z
    cx = start[0] + (end[0] - start[0]) * q
    cy = start[1] + (end[1] - start[1]) * q
    if keep:
        kx0, ky0, kx1, ky1 = keep
        if kx1 - kx0 <= ww:
            cx = min(max(cx, kx1 - ww / 2), kx0 + ww / 2)
        if ky1 - ky0 <= wh:
            cy = min(max(cy, ky1 - wh / 2), ky0 + wh / 2)
    cx, cy = clamp(cx, cy, ww, wh)
    return cx, cy, ww, wh


def warp(plate, win, W, H):
    cx, cy, ww, wh = win
    s = W / ww
    M = np.float32([[s, 0, W / 2 - s * cx], [0, s, H / 2 - s * cy]])
    return cv2.warpAffine(plate, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", default="16x9", choices=["16x9", "9x16"])
    ap.add_argument("--preview", action="store_true", help="half resolution, fast encode")
    ap.add_argument("--from", dest="t_from", type=float, default=0)
    ap.add_argument("--to", dest="t_to", type=float, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    global MANIFEST_BY_ID
    manifest = json.loads((BUILD / "manifest.json").read_text())["items"]
    MANIFEST_BY_ID = {e["id"]: e for e in manifest.values()}
    song = json.loads((BUILD / "song.json").read_text())
    cfg = json.loads((BUILD / "config.json").read_text())
    grid = Grid(song)

    W, H = (1920, 1080) if args.format == "16x9" else (1080, 1920)
    fps = 30
    if args.preview:
        W, H, fps = W // 2, H // 2, 24

    chapters = parse_timeline(MANIFEST_BY_ID)
    slides, starts = plan(chapters, grid, args.format)

    # transitions
    for i, s in enumerate(slides):
        s["t0"], s["t1"] = grid.t(s["h0"]), grid.t(s["h1"])
        s["dip"] = s["chapter_start"] and s["chapter"] > 0
        s["d_in"] = 2.6 if i == 0 else (1.8 if s["dip"] else 0.9)
    for i, s in enumerate(slides):
        s["d_out"] = slides[i + 1]["d_in"] if i + 1 < len(slides) else 2.8
        s["push"] = (i % 2 == 0) or (s["items"][0].get("focus", "c") not in ("c", "") and
                     len(MANIFEST_BY_ID[s["items"][0]["id"]]["faces"]) >= 3)
        s["kind"] = "photo"
    title_lines = [(cfg["title_top"], (FONTS / "Avenir Next.ttc", 0), 0.018, 0.42, 0.035, (200, 196, 188)),
                   (cfg["title_name"], (FONTS / "Supplemental/Didot.ttc", 0), 0.085, 0.04, 0.02, (240, 236, 228))]
    if cfg.get("title_dates"):
        title_lines.append((cfg["title_dates"], (FONTS / "Avenir Next.ttc", 0), 0.02, 0.3, 0, (200, 196, 188)))
    end_lines = [(cfg["end_text"], (FONTS / "Supplemental/Didot.ttc", 2), 0.062, 0.03, 0, (240, 236, 228))]
    title = dict(kind="card", lines=title_lines, t0=-10, t1=slides[0]["t0"], d_in=0, d_out=slides[0]["d_in"],
                 push=True, dip=False)
    end = dict(kind="card", lines=end_lines, t0=slides[-1]["t1"], t1=grid.dur + 10, d_in=slides[-1]["d_out"],
               d_out=0, push=True, dip=False)
    seq = [title] + slides + [end]

    # print the schedule
    print(f"{args.format}: {len(slides)} slides, {sum(len(s['items']) for s in slides)} photos")
    for s in slides:
        if s["chapter_start"]:
            print(f"  -- {chapters[s['chapter']]['name']} (bar {s['h0'] // 2 + 1}, {s['t0']:.1f}s)")
        print(f"    {s['t0']:6.1f}s  {s['t1'] - s['t0']:4.1f}s  " + " + ".join(it["id"] for it in s["items"]))
    (BUILD / f"plan_{args.format}.json").write_text(json.dumps(
        [dict(t0=s["t0"], t1=s["t1"], ids=[it["id"] for it in s["items"]]) for s in slides], indent=1))

    # finishing layers
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r2 = ((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2
    vignette = (1 - 0.16 * np.clip(r2 / 2, 0, 1) ** 1.2)[..., None]
    rng = np.random.default_rng(7)
    grains = [cv2.GaussianBlur(rng.normal(0, 7.0, (H, W)).astype(np.float32), (0, 0), 0.7)[..., None]
              for _ in range(6)]

    plates = {}
    def get_plate(k):
        if k not in plates:
            s = seq[k]
            if s["kind"] == "card":
                p = text_plate(s["lines"], W, H)
                plates[k] = (p, None, None, 1.035)
            else:
                plates[k] = build_plate(s, W, H)
            for old in [j for j in plates if j < k - 2]:
                del plates[old]
        return plates[k]

    def render_layer(k, t):
        s = seq[k]
        plate, fp, keep, zoom = get_plate(k)
        a, b = s["t0"] - s["d_in"] / 2, s["t1"] + s["d_out"] / 2
        if s["kind"] == "card":
            a, b = (0, s["t1"] + s["d_out"] / 2) if k == 0 else (s["t0"] - s["d_in"] / 2, grid.dur)
        p = min(max((t - a) / max(b - a, 1e-3), 0), 1)
        return warp(plate, window_at(plate, fp, keep, zoom, p, s["push"], W, H), W, H).astype(np.float32)

    t_to = args.t_to if args.t_to is not None else grid.dur
    n0, n1 = int(args.t_from * fps), int(math.ceil(t_to * fps))
    tag = "PREVIEW" if args.preview else "FINAL"
    out = Path(args.out) if args.out else ROOT / "output" / f"Long Live Lino - {args.format} - {tag}.mp4"
    out.parent.mkdir(exist_ok=True)
    enc = ["-c:v", "libx264", "-preset", "veryfast" if args.preview else "slow",
           "-crf", "23" if args.preview else "16", "-pix_fmt", "yuv420p",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps),
           "-i", "-", "-ss", f"{args.t_from}", "-t", f"{t_to - args.t_from}", "-i", str(SONG),
           "-map", "0:v", "-map", "1:a", *enc, "-c:a", "aac", "-b:a", "320k", "-shortest",
           "-movflags", "+faststart", str(out)]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def smooth(x):
        x = min(max(x, 0.0), 1.0)
        return x * x * (3 - 2 * x)

    k = 0
    for n in range(n0, n1):
        t = n / fps
        while k + 1 < len(seq) and t >= seq[k + 1]["t0"] - seq[k + 1]["d_in"] / 2:
            k += 1
        cur = seq[k]
        frame = render_layer(k, t)
        if k > 0 and t < cur["t0"] + cur["d_in"] / 2:                # crossfade, centred on the beat
            x = smooth((t - (cur["t0"] - cur["d_in"] / 2)) / cur["d_in"])
            frame = render_layer(k - 1, t) * (1 - x) + frame * x
            if cur["dip"]:
                frame *= 1 - 0.7 * math.sin(math.pi * x)
        # fade in from / out to black
        fade = smooth(t / 2.2) * smooth((grid.dur - t) / 3.0)
        frame = frame * vignette * fade + grains[n % len(grains)]
        ff.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
        if n % (fps * 10) == 0:
            print(f"  {t:6.1f}s / {t_to:.0f}s", flush=True)
    ff.stdin.close()
    ff.wait()
    print("wrote", out)


if __name__ == "__main__":
    main()
