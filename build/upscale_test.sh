#!/bin/zsh
# Upscale test: runs Real-ESRGAN (4x) on 7 of the oldest photos.
# Output: build/upscaled_test/<id>_x4.png  (originals are not touched)
set -e
cd "${0:A:h}/.."
R=build/tools/realesrgan
OUT=build/upscaled_test
mkdir -p "$OUT"
chmod +x "$R/realesrgan-ncnn-vulkan"   # the release zip doesn't keep the executable bit
for id in 049 027 033 042 044 029 006; do
  magick "build/cache/$id.jpg" "$OUT/${id}_in.png"
  "$R/realesrgan-ncnn-vulkan" -i "$OUT/${id}_in.png" -o "$OUT/${id}_x4.png" -n realesrgan-x4plus -m "$R/models" -s 4
  echo "done $id"
done
echo "All 7 upscaled into $OUT"
