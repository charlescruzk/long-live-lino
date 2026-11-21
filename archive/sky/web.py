"""Export the timeline as a looping web slideshow in docs/ (open docs/index.html, served by GitHub Pages).

  .venv/bin/python build/web.py

Reuses render.py's timeline parsing, crops, border trim and colour grade, so the
page shows the same photos, order and look as the videos. Each photo is written as
a small script holding a data: URL, so WebGL can use it straight from file://.
"""
import base64, hashlib, io, json
from pathlib import Path

import numpy as np
from PIL import Image

import render

ROOT, BUILD = render.ROOT, render.BUILD
WEB = ROOT / "docs"
LONG_EDGE = 2200


def read_quotes(minimum):
    """quotes.txt: photo | confidence | line. Keeps lines at or above `minimum`."""
    out = {}
    for raw in (ROOT / "quotes.txt").read_text().splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        key, conf, line = (f.strip() for f in (raw.split("|", 2) + ["", ""])[:3])
        if line and float(conf or 0) >= minimum:
            out[key] = line
    return out


def main():
    manifest = json.loads((BUILD / "manifest.json").read_text())["items"]
    render.MANIFEST_BY_ID = {e["id"]: e for e in manifest.values()}
    cfg = json.loads((BUILD / "config.json").read_text())
    (WEB / "photos").mkdir(parents=True, exist_ok=True)
    quotes = read_quotes(cfg.get("quote_min", 0.8))

    chapters, written, group = [], set(), 0
    for c in render.parse_timeline(manifest):
        slides = []
        for s in c["slides"]:
            group += 1                    # photos shown side by side in the video are one moment
            items = []
            for it in s:
                crop, focus = it.get("crop"), it.get("focus")
                key = it["id"] + ("_" + hashlib.md5(crop.encode()).hexdigest()[:6] if crop else "")
                a, fpt, fh, _, _ = render.load_item(it["id"], crop, focus, None)
                h, w = a.shape[:2]
                k = min(1.0, LONG_EDGE / max(w, h))
                if k < 1:
                    a = render.resize(a, w * k, h * k)
                buf = io.BytesIO()
                Image.fromarray(a).save(buf, "JPEG", quality=86, optimize=True, progressive=True)
                b64 = base64.b64encode(buf.getvalue()).decode()
                (WEB / "photos" / f"{key}.js").write_text(f'LINO_IMG["{key}"]="data:image/jpeg;base64,{b64}";\n')
                written.add(f"{key}.js")
                tone = a.reshape(-1, 3).mean(axis=0)
                tone = tone.mean() + (tone - tone.mean()) * 1.6          # push the photo's cast a little
                items.append(dict(
                    key=key, w=a.shape[1], h=a.shape[0],
                    fx=round(fpt[0] / w, 3) if fpt else 0.5,
                    fy=round(fpt[1] / h, 3) if fpt else 0.45,
                    fh=round(fh / h, 3) if fh else None,
                    tone=[int(v) for v in np.clip(tone, 0, 255)],
                    hold="hold" in it, group=group, quote=quotes.get(key)))
            slides.append(items)
        chapters.append(dict(name=c["name"], slow=c["slow"], slides=slides))
    for f in (WEB / "photos").iterdir():   # photos taken out of the timeline
        if f.name not in written:
            f.unlink()

    data = dict(title=cfg, chapters=chapters)
    (WEB / "data.js").write_text("window.LINO = " + json.dumps(data, separators=(",", ":")) + ";\nwindow.LINO_IMG = {};\n")
    n = sum(len(s) for c in chapters for s in c["slides"])
    q = sum(1 for c in chapters for s in c["slides"] for it in s if it["quote"])
    print(f"docs/: {n} photos, {q} with a quote -> {WEB / 'index.html'}")


if __name__ == "__main__":
    main()
