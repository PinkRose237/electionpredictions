"""Draw the Apple TV app icon (two parallax layers) and Top Shelf images into the asset catalog.

Run: uv run --with pillow python tvos/tools/make_icons.py
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1] / "ElectionNight" / "Assets.xcassets"
BRAND = ROOT / "App Icon & Top Shelf Image.brandassets"
DEM, REP, BG = (74, 144, 217), (226, 87, 79), (14, 16, 20)
FONT = next((p for p in ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc") if Path(p).exists()), None)


def font(px):
    return ImageFont.truetype(FONT, px) if FONT else ImageFont.load_default()


def back(w, h):
    """Blue / red halves with a soft diagonal seam."""
    im = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(im)
    d.polygon([(0, 0), (w * 0.58, 0), (w * 0.42, h), (0, h)], fill=DEM)
    d.polygon([(w * 0.58, 0), (w, 0), (w, h), (w * 0.42, h)], fill=REP)
    return im


def front(w, h):
    """'26' and a check mark, transparent around them so the layers separate in parallax."""
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = font(int(h * 0.55))
    box = d.textbbox((0, 0), "26", font=f)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text(((w - tw) / 2 - box[0], (h - th) / 2 - box[1] - h * 0.04), "26", font=f, fill=(255, 255, 255, 255))
    small = font(int(h * 0.1))
    label = "ELECTION NIGHT"
    b2 = d.textbbox((0, 0), label, font=small)
    d.text(((w - (b2[2] - b2[0])) / 2 - b2[0], h * 0.8), label, font=small, fill=(255, 255, 255, 230))
    return im


def write_json(p: Path, obj):
    p.mkdir(parents=True, exist_ok=True)
    (p / "Contents.json").write_text(json.dumps({**obj, "info": {"author": "xcode", "version": 1}}, indent=2))


def imagestack(name, sizes):
    stack = BRAND / f"{name}.imagestack"
    write_json(stack, {"layers": [{"filename": "Front.imagestacklayer"}, {"filename": "Back.imagestacklayer"}]})
    for layer, draw in (("Front", front), ("Back", back)):
        lp = stack / f"{layer}.imagestacklayer"
        write_json(lp, {})
        images = [{"idiom": "tv", "filename": f"{layer.lower()}@{scale}x.png", "scale": f"{scale}x"} for scale, _ in sizes]
        write_json(lp / "Content.imageset", {"images": images})
        for scale, (w, h) in sizes:
            draw(w, h).save(lp / "Content.imageset" / f"{layer.lower()}@{scale}x.png")


def shelf(name, sizes):
    p = BRAND / f"{name}.imageset"
    write_json(p, {"images": [{"idiom": "tv", "filename": f"shelf@{s}x.png", "scale": f"{s}x"} for s, _ in sizes]})
    for s, (w, h) in sizes:
        im = back(w, h)
        im.paste(front(int(h * 1.6), h), (int((w - h * 1.6) / 2), 0), front(int(h * 1.6), h))
        im.save(p / f"shelf@{s}x.png")


def main():
    write_json(ROOT, {})
    write_json(BRAND, {"assets": [
        {"filename": "App Icon - App Store.imagestack", "idiom": "tv", "role": "primary-app-icon", "size": "1280x768"},
        {"filename": "App Icon.imagestack", "idiom": "tv", "role": "primary-app-icon", "size": "400x240"},
        {"filename": "Top Shelf Image Wide.imageset", "idiom": "tv", "role": "top-shelf-image-wide", "size": "2320x720"},
        {"filename": "Top Shelf Image.imageset", "idiom": "tv", "role": "top-shelf-image", "size": "1920x720"},
    ]})
    imagestack("App Icon", [(1, (400, 240)), (2, (800, 480))])
    imagestack("App Icon - App Store", [(1, (1280, 768))])
    shelf("Top Shelf Image", [(1, (1920, 720)), (2, (3840, 1440))])
    shelf("Top Shelf Image Wide", [(1, (2320, 720)), (2, (4640, 1440))])
    print(f"wrote {ROOT}")


if __name__ == "__main__":
    main()
