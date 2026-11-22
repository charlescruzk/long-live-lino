"""Build the ceremony slideshow in docs/ (open docs/index.html, or the GitHub Pages site).

  .venv/bin/python build/slideshow.py

It reads timeline.txt and build/config.json. Photos keep the same
crops, border trim, Lino focus point and colour grade as the videos (render.py).
It writes:
  docs/media/<key>.jpg      the graded photo (re-encoded, so no camera/GPS metadata)
  docs/media/<key>.bg.jpg   a small, blurred, darkened copy that sits behind it
  docs/media/<key>.mp4      clips (videos and animated GIFs): muted, graded, up to 9 s
  docs/slides.js            the running order, loaded with a <script> tag so file:// works
Anything in docs/media that is no longer in the timeline is removed.
"""
import hashlib, json, subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

import render

ROOT, BUILD = render.ROOT, render.BUILD
WEB = ROOT / "docs"
MEDIA = WEB / "media"
LONG_EDGE = 2400          # photos
CLIP_EDGE = 1920          # clips
CLIP_MAX = 9.0            # seconds
# ffmpeg version of render.grade(): a touch of contrast, calmer colour, warm, soft blacks
CLIP_GRADE = ("eq=contrast=1.05:saturation=0.9,"
              "colorchannelmixer=rr=1.025:bb=0.965,"
              "lutrgb=r='8+val*0.95':g='8+val*0.95':b='8+val*0.95'")


def save_jpg(a, path, quality):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(a).save(path, "JPEG", quality=quality, optimize=True, progressive=True)


def backdrop(a):
    """Blurred, desaturated, darkened copy (the same look as render.blurred_bg), 480 px wide."""
    h, w = a.shape[:2]
    k = 40 / max(w, h)
    small = render.resize(a, w * k, h * k).astype(np.float32)
    small = cv2.GaussianBlur(small, (0, 0), 1.6)
    big = cv2.resize(small, (480, max(1, round(480 * h / w))), interpolation=cv2.INTER_CUBIC)
    big = cv2.GaussianBlur(big, (0, 0), 6)
    g = big.mean(axis=2, keepdims=True)
    big = (g + (big - g) * 0.8) * 0.5
    return np.clip(big, 0, 255).astype(np.uint8)


def face_point(entry, focus):
    """Normalized (x, y) of the chosen face in the original frame, or None."""
    if focus in (None, "", "c", "none"):
        return None
    if "," in focus:
        return tuple(float(v) for v in focus.split(","))
    f = entry["faces"][int(focus)]
    return f["x"] + f["w"] / 2, f["y"] + f["h"] / 2


def is_clip(entry):
    if entry["kind"] == "video":
        return True
    if entry["file"].lower().endswith(".gif"):
        return getattr(Image.open(ROOT / "photos" / entry["file"]), "n_frames", 1) > 1
    return False


def probe_duration(src):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "csv=p=0", str(src)]).decode().strip()
    return float(out) if out and out != "N/A" else 0.0


def make_clip(entry, opt):
    src = ROOT / "photos" / entry["file"]
    dur = entry.get("duration") or probe_duration(src)
    if opt:
        start, length = (float(v) for v in opt.split(","))
    else:
        length = min(dur, CLIP_MAX) if dur else CLIP_MAX
        start = max(0.0, (dur - length) / 2) if dur else 0.0
    key = entry["id"] + "_" + hashlib.md5(f"{start:.2f},{length:.2f},{CLIP_GRADE}".encode()).hexdigest()[:6]
    out = MEDIA / f"{key}.mp4"
    if not out.exists():
        scale = (f"scale='trunc(iw*min(1,{CLIP_EDGE}/max(iw,ih))/2)*2':"
                 f"'trunc(ih*min(1,{CLIP_EDGE}/max(iw,ih))/2)*2':flags=lanczos")
        cmd = ["ffmpeg", "-v", "error", "-y"]
        if src.suffix.lower() == ".gif":
            cmd += ["-i", str(src)]
        else:
            cmd += ["-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", str(src)]
        cmd += ["-an", "-vf", f"{scale},{CLIP_GRADE},format=yuv420p", "-c:v", "libx264", "-preset", "slow",
                "-crf", "21", "-movflags", "+faststart", "-map_metadata", "-1", str(out)]
        subprocess.run(cmd, check=True)
    real = probe_duration(out)
    st = json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "json", str(out)]))["streams"][0]
    w, h = st["width"], st["height"]
    return key, out, real, w, h


def main():
    manifest = json.loads((BUILD / "manifest.json").read_text())["items"]
    render.MANIFEST_BY_ID = by_id = {e["id"]: e for e in manifest.values()}
    cfg = json.loads((BUILD / "config.json").read_text())
    MEDIA.mkdir(parents=True, exist_ok=True)

    chapters, written = [], set()
    n_photo = n_clip = 0
    for c in render.parse_timeline(manifest):
        slides = []
        for it in (x for s in c["slides"] for x in s):          # pairs play one after the other
            e = by_id[it["id"]]
            crop, focus = it.get("crop"), it.get("focus")
            if is_clip(e):
                key, out, dur, w, h = make_clip(e, it.get("clip"))
                still = np.array(Image.open(BUILD / "cache" / f"{e['id']}.jpg").convert("RGB"))
                save_jpg(backdrop(render.grade(still)), MEDIA / f"{key}.bg.jpg", 80)
                fp = face_point(e, focus)
                written |= {out.name, f"{key}.bg.jpg"}
                slides.append(dict(key=key, kind="clip", w=w, h=h, dur=round(dur, 2),
                                   fx=round(fp[0], 3) if fp else 0.5, fy=round(fp[1], 3) if fp else 0.45,
                                   hold="hold" in it))
                n_clip += 1
                continue
            key = it["id"] + ("_" + hashlib.md5(crop.encode()).hexdigest()[:6] if crop else "")
            a, fpt, fh, _, keep = render.load_item(it["id"], crop, focus, None)
            h, w = a.shape[:2]
            k = min(1.0, LONG_EDGE / max(w, h))
            img = render.resize(a, w * k, h * k) if k < 1 else a
            if f"{key}.jpg" not in written:
                save_jpg(img, MEDIA / f"{key}.jpg", 88)
                save_jpg(backdrop(a), MEDIA / f"{key}.bg.jpg", 80)
            written |= {f"{key}.jpg", f"{key}.bg.jpg"}
            slides.append(dict(
                key=key, kind="photo", w=img.shape[1], h=img.shape[0],
                fx=round(fpt[0] / w, 3) if fpt else 0.5,
                fy=round(fpt[1] / h, 3) if fpt else 0.45,
                keep=[round(keep[0] / w, 3), round(keep[1] / h, 3), round(keep[2] / w, 3), round(keep[3] / h, 3)]
                if keep else None,
                hold="hold" in it))
            n_photo += 1
        chapters.append(dict(name=c["name"], slow=c["slow"], slides=slides))

    for f in MEDIA.iterdir():           # taken out of the timeline
        if f.name not in written:
            f.unlink()
    data = dict(title=cfg, chapters=chapters)
    (WEB / "slides.js").write_text("window.SLIDES = " + json.dumps(data, separators=(",", ":")) + ";\n")
    mb = sum(f.stat().st_size for f in MEDIA.iterdir()) / 1e6
    print(f"docs/: {n_photo} photos, {n_clip} clips, {mb:.0f} MB in docs/media -> {WEB / 'index.html'}")


if __name__ == "__main__":
    main()
