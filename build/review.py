"""Contact sheet of the timeline: order, start time, and which face is treated as Lino.
Writes "REVIEW - photo order (page N).jpg" in the project folder."""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
FONT = "/System/Library/Fonts/Avenir Next.ttc"
TILE, COLS, ROWS = 300, 6, 5

manifest = {e["id"]: e for e in json.loads((BUILD / "manifest.json").read_text())["items"].values()}
plan = json.loads((BUILD / "plan_16x9.json").read_text())
start = {}
for n, s in enumerate(plan, 1):
    for pid in s["ids"]:
        start.setdefault(pid, (n, s["t0"]))

entries = []  # ("chapter", name) | ("photo", pid, focus, note, skipped)
for raw in (ROOT / "timeline.txt").read_text().splitlines():
    s = raw.strip()
    if not s or s.startswith("#"):
        continue
    if s.startswith("=="):
        entries.append(("chapter", s[2:].split("|")[0].strip()))
        continue
    fields = [f.strip() for f in s.lstrip("+-").split("|")]
    focus = next((t.split("=", 1)[1] for f in fields[1:] for t in f.split() if t.startswith("focus=")), "c")
    note = fields[3] if len(fields) > 3 else ""
    entries.append(("photo", fields[0], focus, note, s.startswith("-")))

f_big = ImageFont.truetype(FONT, 30, index=1)
f_mid = ImageFont.truetype(FONT, 17, index=0)
f_small = ImageFont.truetype(FONT, 15, index=0)
GOLD, RED = (232, 190, 90), (240, 90, 80)

cells, chapter = [], ""
for e in entries:
    if e[0] == "chapter":
        chapter = e[1]
        cells.append(("header", chapter))
        continue
    _, pid, focus, note, skipped = e
    m = manifest[pid]
    im = Image.open(BUILD / "cache" / f"{pid}.jpg").convert("RGB")
    im.thumbnail((TILE - 10, TILE - 70))
    W, H = im.size
    d = ImageDraw.Draw(im)
    for i, f in enumerate(m["faces"]):
        box = (f["x"] * W, f["y"] * H, (f["x"] + f["w"]) * W, (f["y"] + f["h"]) * H)
        is_lino = focus == str(i)
        d.rectangle(box, outline=GOLD if is_lino else (255, 255, 255), width=4 if is_lino else 1)
        if not is_lino:
            d.text((box[0] + 2, box[3]), str(i), fill="white", font=f_small)
    if "," in focus:
        x, y = (float(v) * s for v, s in zip(focus.split(","), (W, H)))
        d.ellipse((x - 14, y - 14, x + 14, y + 14), outline=GOLD, width=4)
    if skipped:
        im = Image.blend(im, Image.new("RGB", im.size, (20, 20, 20)), 0.6)
    cells.append(("photo", pid, im, note, skipped))

pages, page = [], []
for c in cells:
    if c[0] == "header" and page and len(page) % COLS:
        page += [None] * (COLS - len(page) % COLS)       # chapters start on a new row
    page.append(c)
    if len(page) >= COLS * ROWS:
        pages.append(page[:COLS * ROWS]); page = page[COLS * ROWS:]
if page:
    pages.append(page)

for old in ROOT.glob("REVIEW - photo order*.jpg"):
    old.unlink()
for pn, page in enumerate(pages, 1):
    sheet = Image.new("RGB", (COLS * TILE, ROWS * TILE + 70), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    d.text((20, 18), f"Long Live Lino: photo order (page {pn}/{len(pages)})   "
                     "gold box = Lino    red = please check    dimmed = left out", fill="white", font=f_mid)
    for k, c in enumerate(page):
        if c is None:
            continue
        x, y = (k % COLS) * TILE, (k // COLS) * TILE + 70
        if c[0] == "header":
            d.text((x + 16, y + TILE // 2 - 30), c[1], fill=GOLD, font=f_big)
            continue
        _, pid, im, note, skipped = c
        sheet.paste(im, (x + (TILE - im.width) // 2, y + 5))
        n, t = start.get(pid, (None, None))
        label = f"#{n}  {int(t // 60)}:{t % 60:04.1f}  id {pid}" if n else f"id {pid}  (left out)"
        d.text((x + 8, y + TILE - 62), label, fill="white", font=f_mid)
        flag = note.startswith("?") or "?" in note
        d.text((x + 8, y + TILE - 38), note[:40], fill=RED if flag else (190, 190, 190), font=f_small)
    out = ROOT / f"REVIEW - photo order (page {pn}).jpg"
    sheet.save(out, quality=88)
    print("wrote", out.name)
