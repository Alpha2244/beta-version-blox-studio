import json
import os
import sys
import time
import urllib.parse
import urllib.request


def publish_instagram(video_url: str, caption: str):
    ig_user_id = os.environ.get("IG_USER_ID", "").strip()
    ig_token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not ig_user_id or not ig_token:
        sys.exit("ERROR: ENABLE_IG_UPLOAD=true but IG_USER_ID or IG_ACCESS_TOKEN is missing.")

    base = f"https://graph.facebook.com/v21.0/{ig_user_id}"

    params = urllib.parse.urlencode({
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "true",
        "access_token": ig_token,
    }).encode("utf-8")
    req = urllib.request.Request(f"{base}/media", data=params, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        creation_id = json.loads(resp.read().decode("utf-8"))["id"]
    print(f"[Instagram] Created container: {creation_id}", flush=True)

    for _ in range(30):
        status_url = f"https://graph.facebook.com/v21.0/{creation_id}?fields=status_code&access_token={ig_token}"
        with urllib.request.urlopen(status_url, timeout=30) as resp:
            status = json.loads(resp.read().decode("utf-8")).get("status_code")
        if status == "FINISHED":
            break
        if status == "ERROR":
            sys.exit(f"ERROR: Instagram rejected video container {creation_id}")
        time.sleep(5)

    pub_params = urllib.parse.urlencode({
        "creation_id": creation_id,
        "access_token": ig_token,
    }).encode("utf-8")
    pub_req = urllib.request.Request(f"{base}/media_publish", data=pub_params, method="POST")
    with urllib.request.urlopen(pub_req, timeout=60) as resp:
        media_id = json.loads(resp.read().decode("utf-8"))["id"]
    print(f"[Instagram] PUBLISHED Reel ID: {media_id}", flush=True)


def main(project_dir: str):
    enable_ig = os.environ.get("ENABLE_IG_UPLOAD", "false").strip().lower() == "true"
    meta_path = os.path.join(project_dir, "meta.json")
    meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {}
    caption = f"{meta.get('title', '')}\n\n{meta.get('caption', '#storytime #plottwist #shorts')}".strip()

    if not enable_ig:
        print("[Publish] ENABLE_IG_UPLOAD=false -> Instagram upload skipped. Download your MP4 from Releases or Artifacts.", flush=True)
        return

    video_url = os.environ.get("RELEASE_VIDEO_URL", "").strip()
    if not video_url:
        sys.exit("ERROR: RELEASE_VIDEO_URL is missing.")
    publish_instagram(video_url, caption)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python auto/publish_reel.py kit/projects/<name>")
    main(os.path.abspath(sys.argv[1]))
