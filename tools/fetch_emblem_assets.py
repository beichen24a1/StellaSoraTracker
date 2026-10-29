"""Refresh bundled emblem thumbnails and their exact StellaBase mappings."""
from __future__ import annotations

import hashlib
import io
import json
import re
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://stella.ennead.cc/api/emblems?lang=cn"


def read(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "StellaSoraTracker/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("Resource exceeds 4 MiB")
    return data


def main() -> None:
    entries = json.loads(read(SOURCE))["emblems"]
    records = []
    images = {}
    for entry in entries:
        item_id = int(entry["id"])
        background = entry["background"]
        if item_id <= 0 or not re.fullmatch(r"Icon/Equipment/[A-Za-z0-9_]+", background):
            raise ValueError("Unexpected emblem resource path")
        url = f"https://api.ennead.cc/stella/assets/{background}.png"
        image = read(url)
        with Image.open(io.BytesIO(image)) as picture:
            if picture.format != "PNG":
                raise ValueError("Expected a PNG thumbnail")
            picture.verify()
        if item_id in images:
            raise ValueError("Duplicate emblem ID")
        images[item_id] = image
        records.append({"id": item_id, "name": entry["name"], "icon": entry["icon"],
                        "source": url, "sha256": hashlib.sha256(image).hexdigest()})
    if not records:
        raise ValueError("Empty emblem catalogue")
    folder = ROOT / "assets/emblems"
    folder.mkdir(parents=True, exist_ok=True)
    for item_id, image in images.items():
        (folder / f"{item_id}.png").write_bytes(image)
    manifest = {"source": SOURCE, "items": records}
    (ROOT / "frontend/src/emblems.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(records)} emblem thumbnails ({sum(map(len, images.values()))} bytes)")


if __name__ == "__main__":
    main()
