#!/usr/bin/env python3
"""Travekorea auto-publisher: posts due items from content/posts.json to
Instagram, Facebook Page and Threads through the official Meta APIs.

Runs on a schedule (GitHub Actions). Idempotent: every successful post is
recorded in state/published.json, so a post is never published twice.

Env vars (GitHub Actions secrets/vars):
  META_PAGE_TOKEN      long-lived Facebook Page access token
  META_PAGE_ID         Facebook Page id
  META_IG_USER_ID      Instagram Business account id (linked to the Page)
  THREADS_TOKEN        long-lived Threads user access token
  THREADS_USER_ID      Threads user id
  MEDIA_BASE_URL       public base URL of media/ (e.g. GitHub Pages)
  CATCHUP_MINUTES      publish posts up to this many minutes late (default 90)
  DRY_RUN              "1" = only print what would be posted
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSTS = os.path.join(ROOT, "content", "posts.json")
STATE = os.path.join(ROOT, "state", "published.json")

GRAPH = "https://graph.facebook.com/v21.0"
THREADS = "https://graph.threads.net/v1.0"

ENV = os.environ.get
DRY = ENV("DRY_RUN") == "1"
CATCHUP = int(ENV("CATCHUP_MINUTES") or 90)
BASE = (ENV("MEDIA_BASE_URL") or "").rstrip("/")


class ApiError(Exception):
    pass


def call(method, url, params):
    data = urllib.parse.urlencode(params).encode()
    if method == "GET":
        req = urllib.request.Request(url + "?" + data.decode())
    else:
        req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise ApiError(f"{method} {url.split('?')[0]} -> {e.code}: {body[:500]}")


def media_url(name):
    if name.startswith("http"):
        return name
    return f"{BASE}/{urllib.parse.quote(name)}"


def is_video(name):
    return name.lower().endswith((".mp4", ".mov"))


# ---------------- Instagram ----------------
def ig_wait(cid, token, limit=600):
    t0 = time.time()
    while time.time() - t0 < limit:
        st = call("GET", f"{GRAPH}/{cid}", {"fields": "status_code", "access_token": token})
        code = st.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise ApiError(f"IG container {cid} status {code}")
        time.sleep(10)
    raise ApiError(f"IG container {cid} not ready after {limit}s")


def ig_publish(post):
    tok, uid = ENV("META_PAGE_TOKEN"), ENV("META_IG_USER_ID")
    fmt, media, cap = post["format"], post["media"], post.get("caption", "")
    ep = f"{GRAPH}/{uid}/media"
    if fmt == "carousel":
        kids = []
        for m in media[:10]:
            p = {"is_carousel_item": "true", "access_token": tok}
            if is_video(m):
                p.update(media_type="VIDEO", video_url=media_url(m))
            else:
                p["image_url"] = media_url(m)
            cid = call("POST", ep, p)["id"]
            ig_wait(cid, tok)
            kids.append(cid)
        cid = call("POST", ep, {"media_type": "CAROUSEL", "children": ",".join(kids),
                                "caption": cap, "access_token": tok})["id"]
    elif fmt == "reels":
        p = {"media_type": "REELS", "video_url": media_url(media[0]), "caption": cap,
             "share_to_feed": "true", "access_token": tok}
        if post.get("cover"):
            p["cover_url"] = media_url(post["cover"])
        cid = call("POST", ep, p)["id"]
    elif fmt == "story":
        ids = []
        for m in media:  # several media = consecutive stories (e.g. quiz question, then answer)
            p = {"media_type": "STORIES", "access_token": tok}
            p["video_url" if is_video(m) else "image_url"] = media_url(m)
            cid = call("POST", ep, p)["id"]
            ig_wait(cid, tok)
            ids.append(call("POST", f"{GRAPH}/{uid}/media_publish",
                            {"creation_id": cid, "access_token": tok})["id"])
        return ",".join(ids)
    else:  # feed
        cid = call("POST", ep, {"image_url": media_url(media[0]), "caption": cap,
                                "access_token": tok})["id"]
    ig_wait(cid, tok)
    return call("POST", f"{GRAPH}/{uid}/media_publish",
                {"creation_id": cid, "access_token": tok})["id"]


# ---------------- Facebook Page ----------------
def fb_publish(post):
    tok, pid = ENV("META_PAGE_TOKEN"), ENV("META_PAGE_ID")
    fmt, media, cap = post["format"], post["media"], post.get("caption", "")
    if fmt == "reels" or is_video(media[0]) and fmt != "story":
        return call("POST", f"{GRAPH}/{pid}/videos",
                    {"file_url": media_url(media[0]), "description": cap,
                     "access_token": tok})["id"]
    if fmt == "story":
        ids = []
        for m in media:
            if is_video(m):
                raise ApiError("FB video story not supported by this script; skipped")
            photo = call("POST", f"{GRAPH}/{pid}/photos",
                         {"url": media_url(m), "published": "false", "access_token": tok})
            ids.append(call("POST", f"{GRAPH}/{pid}/photo_stories",
                            {"photo_id": photo["id"], "access_token": tok}).get("post_id", photo["id"]))
        return ",".join(ids)
    if fmt == "carousel" and len(media) > 1:
        ids = []
        for m in media[:10]:
            ids.append(call("POST", f"{GRAPH}/{pid}/photos",
                            {"url": media_url(m), "published": "false",
                             "access_token": tok})["id"])
        p = {"message": cap, "access_token": tok}
        for i, fid in enumerate(ids):
            p[f"attached_media[{i}]"] = json.dumps({"media_fbid": fid})
        return call("POST", f"{GRAPH}/{pid}/feed", p)["id"]
    return call("POST", f"{GRAPH}/{pid}/photos",
                {"url": media_url(media[0]), "caption": cap, "access_token": tok})["id"]


# ---------------- Threads ----------------
def threads_text(post):
    t = post.get("threads_text") or post.get("caption", "")
    return t if len(t) <= 500 else t[:497].rsplit(" ", 1)[0] + "..."


def th_wait(cid, tok, limit=600):
    t0 = time.time()
    while time.time() - t0 < limit:
        st = call("GET", f"{THREADS}/{cid}", {"fields": "status,error_message", "access_token": tok})
        if st.get("status") == "FINISHED":
            return
        if st.get("status") in ("ERROR", "EXPIRED"):
            raise ApiError(f"Threads container {cid}: {st}")
        time.sleep(10)
    raise ApiError(f"Threads container {cid} not ready after {limit}s")


def th_publish(post):
    tok, uid = ENV("THREADS_TOKEN"), ENV("THREADS_USER_ID")
    ep = f"{THREADS}/{uid}/threads"
    media, text = post["media"], threads_text(post)

    def item(m, child):
        p = {"access_token": tok}
        if child:
            p["is_carousel_item"] = "true"
        if is_video(m):
            p.update(media_type="VIDEO", video_url=media_url(m))
        else:
            p.update(media_type="IMAGE", image_url=media_url(m))
        return p

    if len(media) > 1:
        kids = []
        for m in media[:20]:
            cid = call("POST", ep, item(m, True))["id"]
            th_wait(cid, tok)
            kids.append(cid)
        cid = call("POST", ep, {"media_type": "CAROUSEL", "children": ",".join(kids),
                                "text": text, "access_token": tok})["id"]
    elif media:
        p = item(media[0], False)
        p["text"] = text
        cid = call("POST", ep, p)["id"]
    else:
        cid = call("POST", ep, {"media_type": "TEXT", "text": text, "access_token": tok})["id"]
    th_wait(cid, tok)
    return call("POST", f"{THREADS}/{uid}/threads_publish",
                {"creation_id": cid, "access_token": tok})["id"]


PUBLISHERS = {"instagram": ig_publish, "facebook": fb_publish, "threads": th_publish}


def load(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, STATE)


def main():
    posts = load(POSTS, [])
    state = load(STATE, {})
    now = datetime.now(timezone.utc)
    failures = 0
    for post in sorted(posts, key=lambda p: p["publish_at"]):
        if post.get("skip"):
            continue
        due = datetime.fromisoformat(post["publish_at"])
        if due > now:
            continue
        rec = state.setdefault(post["id"], {})
        for plat in post.get("platforms", ["instagram", "facebook", "threads"]):
            if plat == "threads" and post["format"] == "story":
                continue
            if rec.get(plat, {}).get("status") in ("ok", "missed"):
                continue
            if now - due > timedelta(minutes=CATCHUP):
                rec[plat] = {"status": "missed", "at": now.isoformat()}
                print(f"MISSED {post['id']} {plat} (due {due})")
                continue
            if DRY:
                print(f"DRY {post['id']} -> {plat} {post['format']} {post['media']}")
                continue
            tries = rec.get(plat, {}).get("tries", 0)
            try:
                pid = PUBLISHERS[plat](post)
                rec[plat] = {"status": "ok", "id": pid, "at": now.isoformat()}
                print(f"OK {post['id']} -> {plat} {pid}")
            except Exception as e:  # keep going with other posts/platforms
                failures += 1
                rec[plat] = {"status": "error", "tries": tries + 1, "error": str(e)[:400],
                             "at": now.isoformat()}
                print(f"ERROR {post['id']} -> {plat}: {e}", file=sys.stderr)
            save_state(state)
    if not DRY:
        save_state(state)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
