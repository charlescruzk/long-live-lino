"""Normalize new files in photos/ into build/cache/*.jpg and detect faces (Apple Vision).
Incremental: files already in build/manifest.json are skipped."""
import hashlib, json, os, subprocess, sys
from pathlib import Path
from PIL import Image, ImageOps
import pillow_heif
import Vision, Quartz
from Foundation import NSURL

pillow_heif.register_heif_opener()
ROOT = Path(__file__).resolve().parent.parent
PHOTOS, CACHE = ROOT / "photos", ROOT / "build" / "cache"
MANIFEST = ROOT / "build" / "manifest.json"
CACHE.mkdir(parents=True, exist_ok=True)
VIDEO = {".mov", ".mp4", ".m4v"}
IMAGE = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".webp", ".tif", ".tiff"}

def faces(path):
    url = NSURL.fileURLWithPath_(str(path))
    req = Vision.VNDetectFaceRectanglesRequest.alloc().init()
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
    handler.performRequests_error_([req], None)
    out = []
    for r in req.results() or []:
        b = r.boundingBox()  # normalized, origin bottom-left
        out.append(dict(x=b.origin.x, y=1 - b.origin.y - b.size.height, w=b.size.width, h=b.size.height,
                        conf=float(r.confidence())))
    return sorted(out, key=lambda f: f["x"])

manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"items": {}}
items = manifest["items"]
next_id = max([int(v["id"]) for v in items.values()] + [0]) + 1
added = []
md5 = lambda f: hashlib.md5(f.read_bytes()).hexdigest()
# byte-identical copies ("IMG_0448 2.png", a re-sent photo in a BATCH folder) are skipped
known = {md5(PHOTOS / k) for k in items if (PHOTOS / k).exists()}
# subfolders (BATCH2, BATCH3, ...) are included; keys are paths relative to photos/
for f in sorted(PHOTOS.rglob("*"), key=lambda p: str(p.relative_to(PHOTOS)).lower()):
    ext, key = f.suffix.lower(), str(f.relative_to(PHOTOS))
    if not f.is_file() or any(part.startswith(".") for part in f.relative_to(PHOTOS).parts) \
            or key in items or ext not in IMAGE | VIDEO:
        continue
    if (h := md5(f)) in known:
        print(f"skip  duplicate  {key}")
        continue
    known.add(h)
    pid = f"{next_id:03d}"; next_id += 1
    out = CACHE / f"{pid}.jpg"
    entry = dict(id=pid, file=key, kind="video" if ext in VIDEO else "photo")
    if ext in VIDEO:
        dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                             "-of", "csv=p=0", str(f)]).decode())
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur/2:.2f}", "-i", str(f), "-frames:v", "1", str(out)], check=True)
        entry["duration"] = dur
    else:
        im = Image.open(f); im.seek(0)
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((3200, 3200), Image.LANCZOS)
        im.save(out, quality=95)
    w, h = Image.open(out).size
    entry.update(w=w, h=h, faces=faces(out))
    items[key] = entry
    added.append(key)
    print(f"{pid}  {len(entry['faces'])} faces  {w}x{h}  {key}")
MANIFEST.write_text(json.dumps(manifest, indent=1))
print(f"added {len(added)}, total {len(items)}")
