"""Blend each Real-ESRGAN result 50/50 with a plain enlargement of the original.
The full AI result smooths and slightly reshapes small faces; the blend keeps the clarity
gain while staying true to the original. Output: build/upscaled/<id>.jpg (used by render.py)."""
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "build" / "upscaled" / "raw"
OUT = ROOT / "build" / "upscaled"
AI_WEIGHT = 0.5

for ai_path in sorted(RAW.glob("*_x4.png")):
    pid = ai_path.name.split("_")[0]
    out = OUT / f"{pid}.jpg"
    if out.exists() and out.stat().st_mtime > ai_path.stat().st_mtime:
        continue
    ai = cv2.imread(str(ai_path))
    src = cv2.imread(str(ROOT / "build" / "cache" / f"{pid}.jpg"))
    plain = cv2.resize(src, (ai.shape[1], ai.shape[0]), interpolation=cv2.INTER_LANCZOS4)
    cv2.imwrite(str(out), cv2.addWeighted(ai, AI_WEIGHT, plain, 1 - AI_WEIGHT, 0), [cv2.IMWRITE_JPEG_QUALITY, 95])
    print("blended", pid)
