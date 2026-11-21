"""Date hints for photos that are not placed yet (the NEW chapter of timeline.txt).

  .venv/bin/python build/date_hints.py

Prints id, best date guess, where the date came from, and the file name.
The camera date (EXIF DateTimeOriginal) is trusted. A date in the file name
is a guess: Screenshot_, Snapchat-, -WA (WhatsApp) and anything saved after
October 2026 is when the photo was saved or re-shared, not when it was taken.
"""
import json, re, subprocess
from pathlib import Path

from PIL import Image
import pillow_heif

pillow_heif.register_heif_opener()
ROOT = Path(__file__).resolve().parent.parent
PHOTOS = ROOT / "photos"
VIDEO = {".mov", ".mp4", ".m4v"}


def exif_date(f):
    try:
        if f.suffix.lower() in VIDEO:
            out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format_tags=creation_time",
                                           "-of", "csv=p=0", str(f)]).decode().strip()
            return out[:10] if out else None
        ex = Image.open(f).getexif()
        v = ex.get_ifd(0x8769).get(36867) or ex.get(306)        # DateTimeOriginal, else DateTime
        return v[:10].replace(":", "-") if v else None
    except Exception:
        return None


def name_date(name):
    m = re.search(r"(20\d\d)[-_]?([01]\d)[-_]?([0-3]\d)", name)
    return f"{m[1]}-{m[2]}-{m[3]}" if m else None


def main():
    items = json.loads((ROOT / "build" / "manifest.json").read_text())["items"]
    placed = set()
    in_new = False
    for raw in (ROOT / "timeline.txt").read_text().splitlines():
        s = raw.strip()
        if s.startswith("=="):
            in_new = s[2:].strip().upper().startswith("NEW")
        elif s and not s.startswith("#") and not in_new:
            placed.add(s.lstrip("+-").split("|")[0].strip())
    for e in sorted(items.values(), key=lambda e: e["id"]):
        if e["id"] in placed:
            continue
        f = PHOTOS / e["file"]
        cam, nam = exif_date(f), name_date(Path(e["file"]).name)
        saved = re.search(r"screenshot|snapchat|-wa\d|^vid-", e["file"], re.I) or (nam or "") >= "2026-10"
        if cam and cam >= "1990" and not cam.startswith("2026-1"):
            date, src = cam, "camera"
        elif nam:
            date, src = nam, "name (saved/shared?)" if saved else "name"
        else:
            date, src = (cam or "?"), "camera (saved?)" if cam else "-"
        print(f"{e['id']}  {date:<10}  {src:<20}  {e['kind']:<5}  {len(e['faces'])}f  {e['file']}")


if __name__ == "__main__":
    main()
