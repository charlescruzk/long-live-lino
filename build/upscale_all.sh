#!/bin/zsh
# Upscale the old low-resolution photos (shortest side <= 720 px) with Real-ESRGAN 4x.
# Raw results go to build/upscaled/raw/; build/blend_upscaled.py then mixes them 50/50
# with the original so faces stay true to life. Already-done photos are skipped.
set -e
cd "${0:A:h}/.."
R=build/tools/realesrgan
RAW=build/upscaled/raw
mkdir -p "$RAW"
chmod +x "$R/realesrgan-ncnn-vulkan"
ids=($(.venv/bin/python -c "
import json
m = json.load(open('build/manifest.json'))['items'].values()
print(' '.join(e['id'] for e in sorted(m, key=lambda e: e['id']) if e['kind'] == 'photo' and min(e['w'], e['h']) <= 720))"))
for id in $ids; do
  [[ -f "$RAW/${id}_x4.png" ]] && continue
  magick "build/cache/$id.jpg" "$RAW/${id}_in.png"
  "$R/realesrgan-ncnn-vulkan" -i "$RAW/${id}_in.png" -o "$RAW/${id}_x4.png" -n realesrgan-x4plus -m "$R/models" -s 4 2>/dev/null
  rm "$RAW/${id}_in.png"
  echo "upscaled $id"
done
.venv/bin/python build/blend_upscaled.py
