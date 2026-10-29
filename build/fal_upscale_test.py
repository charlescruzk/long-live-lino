"""Paid A/B upscale test on fal.ai (approved by Charles 2026-10-29, est. ~$1.15 total).

Runs 3 restoration setups on the same 7 test photos, 1 output each (21 images):
  seedvr        fal-ai/seedvr/upscale/image   ~$0.001/MP output
  topaz_rec     fal-ai/topaz/upscale/image    Recovery V2, face enhancement OFF   $0.08 (<=24MP)
  topaz_lowres  fal-ai/topaz/upscale/image    Low Resolution V2, face enh. OFF    $0.08 (<=24MP)

Privacy: photos are sent inline as data URIs (never uploaded to fal storage); SeedVR uses
sync_mode so its output isn't kept in request history. Key comes from env FAL_KEY only.
Usage:  FAL_KEY=... python build/fal_upscale_test.py [--only setup] [--ids 027,049]
"""
import argparse, base64, json, os, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "upscaled_fal"
LEDGER = OUT / "ledger.json"
IDS = ["049", "027", "033", "042", "044", "029", "006"]
MAX_EDGE = 3000   # keep every Topaz output well under the 24 MP / $0.08 tier

SETUPS = {
    "seedvr": ("fal-ai/seedvr/upscale/image",
               lambda f: dict(upscale_mode="factor", upscale_factor=f, output_format="png", sync_mode=True)),
    "topaz_rec": ("fal-ai/topaz/upscale/image",
                  lambda f: dict(model="Recovery V2", upscale_factor=f, face_enhancement=False, output_format="png")),
    "topaz_lowres": ("fal-ai/topaz/upscale/image",
                     lambda f: dict(model="Low Resolution V2", upscale_factor=f, face_enhancement=False,
                                    output_format="png")),
}


def call(endpoint, payload, key):
    hdr = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    req = urllib.request.Request(f"https://queue.fal.run/{endpoint}", json.dumps(payload).encode(), hdr)
    sub = json.load(urllib.request.urlopen(req, timeout=120))
    status_url, resp_url = sub["status_url"], sub["response_url"]
    for _ in range(300):
        st = json.load(urllib.request.urlopen(urllib.request.Request(status_url, headers=hdr), timeout=60))
        if st["status"] == "COMPLETED":
            break
        time.sleep(2)
    else:
        raise TimeoutError(sub["request_id"])
    res = json.load(urllib.request.urlopen(urllib.request.Request(resp_url, headers=hdr), timeout=120))
    return sub["request_id"], res


def save_image(res, path):
    url = res["image"]["url"]
    if url.startswith("data:"):
        path.write_bytes(base64.b64decode(url.split(",", 1)[1]))
    else:
        path.write_bytes(urllib.request.urlopen(url, timeout=120).read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=list(SETUPS))
    ap.add_argument("--ids")
    args = ap.parse_args()
    key = os.environ["FAL_KEY"]
    manifest = {e["id"]: e for e in json.loads((ROOT / "build" / "manifest.json").read_text())["items"].values()}
    ledger = json.loads(LEDGER.read_text()) if LEDGER.exists() else []
    ids = args.ids.split(",") if args.ids else IDS
    for name, (endpoint, params) in SETUPS.items():
        if args.only and name != args.only:
            continue
        (OUT / name).mkdir(parents=True, exist_ok=True)
        for pid in ids:
            dest = OUT / name / f"{pid}.png"
            if dest.exists():
                print(f"skip {name} {pid} (already have it)")
                continue
            e = manifest[pid]
            factor = round(max(1.0, min(4.0, MAX_EDGE / max(e["w"], e["h"]))), 2)
            src = base64.b64encode((ROOT / "build" / "cache" / f"{pid}.jpg").read_bytes()).decode()
            payload = dict(image_url=f"data:image/jpeg;base64,{src}", **params(factor))
            rid, res = call(endpoint, payload, key)
            save_image(res, dest)
            ow, oh = res["image"].get("width"), res["image"].get("height")
            ledger.append(dict(setup=name, id=pid, request_id=rid, factor=factor, out=[ow, oh],
                               time=time.strftime("%Y-%m-%d %H:%M:%S")))
            LEDGER.write_text(json.dumps(ledger, indent=1))
            print(f"{name:13s} {pid}  x{factor}  -> {ow}x{oh}  ({rid})")
    print(f"done; {len(ledger)} paid outputs logged in {LEDGER.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
