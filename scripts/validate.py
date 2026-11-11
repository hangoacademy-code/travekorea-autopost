#!/usr/bin/env python3
"""Check content/posts.json before it goes live. Exit 1 on any error."""
import json
import os
import re
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEDIA = os.path.join(ROOT, "media")
FORMATS = {"feed", "carousel", "reels", "story"}
PLATFORMS = {"instagram", "facebook", "threads"}


def main():
    posts = json.load(open(os.path.join(ROOT, "content", "posts.json"), encoding="utf-8"))
    errors, warns, ids, slots = [], [], set(), {}
    for i, p in enumerate(posts):
        tag = p.get("id", f"#{i}")
        for k in ("id", "publish_at", "format", "media", "platforms"):
            if k not in p:
                errors.append(f"{tag}: field '{k}' kosong")
        if p.get("id") in ids:
            errors.append(f"{tag}: id dobel")
        ids.add(p.get("id"))
        try:
            dt = datetime.fromisoformat(p["publish_at"])
            if dt.tzinfo is None:
                errors.append(f"{tag}: publish_at tanpa zona waktu (pakai +09:00)")
            slots.setdefault(p["publish_at"], []).append(tag)
        except Exception:
            errors.append(f"{tag}: publish_at tidak valid")
        fmt = p.get("format")
        if fmt not in FORMATS:
            errors.append(f"{tag}: format '{fmt}' tidak dikenal")
        bad = set(p.get("platforms", [])) - PLATFORMS
        if bad:
            errors.append(f"{tag}: platform tidak dikenal {bad}")
        media = p.get("media", [])
        if not media:
            errors.append(f"{tag}: media kosong (IG wajib gambar/video)")
        if fmt == "carousel" and not 2 <= len(media) <= 10:
            errors.append(f"{tag}: carousel harus 2-10 slide (ada {len(media)})")
        if fmt in ("reels",) and not media[0].lower().endswith((".mp4", ".mov")):
            errors.append(f"{tag}: reels harus video")
        for m in media + ([p["cover"]] if p.get("cover") else []):
            if m.startswith("http"):
                continue
            f = os.path.join(MEDIA, m)
            if not os.path.exists(f):
                errors.append(f"{tag}: file media tidak ada: {m}")
            elif os.path.getsize(f) > (100 if m.endswith(".mp4") else 8) * 1024 * 1024:
                errors.append(f"{tag}: file terlalu besar: {m}")
        cap = p.get("caption", "")
        if fmt != "story" and not cap:
            warns.append(f"{tag}: caption kosong")
        if len(cap) > 2200:
            errors.append(f"{tag}: caption {len(cap)} > 2200 karakter (batas IG)")
        if len(re.findall(r"#\w+", cap)) > 30:
            errors.append(f"{tag}: lebih dari 30 hashtag")
        tt = p.get("threads_text") or ""
        if tt and len(tt) > 500:
            errors.append(f"{tag}: threads_text {len(tt)} > 500")
        if "threads" in p.get("platforms", []) and not tt and len(cap) > 500:
            warns.append(f"{tag}: caption >500, akan dipotong untuk Threads")
    for t, tags in slots.items():
        if len(tags) > 1:
            warns.append(f"{t}: {len(tags)} post di jam yang sama: {tags}")
    for w in warns:
        print("PERINGATAN", w)
    for e in errors:
        print("ERROR", e)
    print(f"{len(posts)} post dicek, {len(errors)} error, {len(warns)} peringatan")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
