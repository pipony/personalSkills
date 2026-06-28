#!/usr/bin/env python3
"""
transcribe.py — Turn a short video's spoken content into a text transcript.

Supports:
  - 小红书 (Xiaohongshu / RED): xiaohongshu.com, xhslink.com
  - 哔哩哔哩 (Bilibili):        bilibili.com, b23.tv
  - 小宇宙 (Xiaoyuzhou podcast): xiaoyuzhoufm.com  (episode links)

Pipeline:
  1. Resolve the note/video/episode id and fetch metadata (title, author, duration).
  2. Get the spoken content:
       * Bilibili: prefer the video's own subtitles (AI/CC) when available —
         they are more accurate than ASR and instant. Otherwise download audio.
       * Xiaohongshu: videos have no subtitles, so always download audio.
       * 小宇宙: podcasts have no fetchable subtitles (the transcript endpoint
         needs auth), so always download audio.
  3. If audio: extract 16 kHz mono wav with ffmpeg, transcribe with mlx_whisper.
  4. Write raw_text.txt, segments.txt (timestamped) and metadata.json.

Why the platform-specific tricks:
  - XHS renders note data in `window.__INITIAL_STATE__`; feed links must have
    `source=web_explore_feed`/`m_source` stripped or the SSR page omits the note.
  - Bilibili's signed playurl (wbi) 412s/-400s anonymously and yt-dlp hits the
    same wall; the legacy `platform=html5` playurl still returns a stream
    anonymously, so we use that for audio.
  - 小宇宙 episode pages embed `__NEXT_DATA__` (Next.js SSR JSON) holding the
    episode; the audio is a public CDN URL (media.xyzcdn.net, no token/signature),
    so we download it directly. Channel links (/podcast/<id>) are NOT a single
    episode — ask for an /episode/<id> link instead.
  - huggingface.co is often blocked in mainland China, so the mlx model endpoint
    defaults to https://hf-mirror.com (cached after first download).

Usage:
    python3 transcribe.py <url> [--out-dir DIR] [--model REPO] [--language LANG]
                                  [--force-asr]
    LANG: 'auto' (default) auto-detect; or 'zh','en',... 'zh' is a good override
    for Chinese content where auto-detect is flaky on short clips.
    --force-asr: ignore Bilibili subtitles and always transcribe the audio.

Exit codes: 2 not a video / image-only note / podcast channel (not an episode),
3 link/token problem, 4 no playable stream, 5 missing dependency,
6 unsupported/unknown URL.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
import urllib.request

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")

DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def die(code, msg):
    print(f"\n[ERROR] {msg}", file=sys.stderr)
    sys.exit(code)


def http_get(url, referer="https://www.bilibili.com/", cookie=None, timeout=20):
    """GET returning raw bytes with browser-ish headers."""
    headers = {"User-Agent": UA, "Referer": referer}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout).read()


def fetch_html_curl(url, out_path, referer="https://www.xiaohongshu.com/"):
    """curl-based HTML fetch following redirects. Returns effective URL."""
    effective = subprocess.run([
        "curl", "-sL", url,
        "-H", f"User-Agent: {UA}",
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "-H", "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
        "-H", f"Referer: {referer}",
        "--max-time", "45",
        "-w", "%{url_effective}",
        "-o", out_path,
    ], capture_output=True, text=True).stdout.strip()
    return effective or url


# --------------------------------------------------------------------------
# Helpers shared across platforms
# --------------------------------------------------------------------------

def drop_hallucinated_segments(segments):
    """Drop segments that are low-diversity repetition (Whisper hallucination).

    Whisper can emit a looping run of one or two characters ('男男男…',
    '叢 叢 叢…') anywhere — often at a silent or musical moment. Natural speech
    in any language never produces a long run dominated by <15% unique chars,
    so that is a safe signal. Short legit repetitions ('哈哈哈哈','好的好的')
    stay under the length threshold and are kept.
    """
    kept = []
    for s in segments:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        unique = set(text)
        # A whole segment that is one character repeated ('演演演演演','男男男男')
        # is always a hallucination (or pure laughter) — safe to drop.
        if len(text) >= 4 and len(unique) <= 1:
            continue
        # Long run dominated by a tiny set of chars (looser, only when long).
        if len(text) >= 10 and len(unique) / max(len(text), 1) < 0.15:
            continue
        kept.append(s)
    return kept


def deloop_text(text, max_iter=5):
    """Collapse a short phrase repeated 4+ times in a row (Whisper loop) to 2x.

    Whisper sometimes stutters on a phrase inside an otherwise valid segment,
    e.g. '主要的作用是什么,是什么,是什么,…,很简单' — the segment-level drop
    won't catch it because legit text sits alongside the loop. A 2–8 char
    phrase repeating 4+ times consecutively doesn't occur in natural speech, so
    collapsing it to two copies is safe ('哈哈哈哈' is 1-char and unaffected).
    """
    pat = re.compile(r"(.{2,8})\1{3,}")
    for _ in range(max_iter):
        new = pat.sub(lambda m: m.group(1) * 2, text)
        if new == text:
            break
        text = new
    return text


def ensure_mlx():
    """Run under an interpreter that actually has mlx_whisper.

    Homebrew can flip the default `python3` between 3.13/3.14 when other
    packages are installed, and mlx-whisper lives in only one of them. If the
    current interpreter lacks it, transparently re-exec under one that has it.
    """
    try:
        import mlx_whisper  # noqa: F401
        return
    except ImportError:
        pass
    for cand in ("python3.13", "python3.12", "python3.11"):
        p = shutil.which(cand)
        if p:
            try:
                subprocess.run([p, "-c", "import mlx_whisper"], check=True,
                               capture_output=True)
                os.execv(p, [p] + sys.argv)
            except Exception:
                continue
    die(5, "mlx_whisper is not installed in any python3.11+ interpreter. "
           "Install with: python3.13 -m pip install -U mlx-whisper")


# --------------------------------------------------------------------------
# Xiaohongshu
# --------------------------------------------------------------------------

def extract_note_id(url):
    m = re.search(r"([0-9a-f]{24})", url or "")
    return m.group(1) if m else None


def clean_xhs_url(url):
    """Drop params that make XHS return a feed page instead of this note."""
    parts = urlparse(url)
    qs = [(k, v) for k, v in parse_qsl(parts.query) if k not in ("source", "m_source")]
    return urlunparse(parts._replace(query=urlencode(qs)))


def parse_initial_state(html):
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>", html, re.S)
    if not m:
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", html, re.S)
    if not m:
        return None
    return json.loads(re.sub(r"\bundefined\b", "null", m.group(1)))


def process_xhs(url, out_dir, language):
    original_url = url
    url = clean_xhs_url(url)
    note_id = extract_note_id(url)
    state = entry = None
    last_reason = ""
    for attempt in range(1, 5):
        print(f"[xhs] fetching page (attempt {attempt}/4) ...")
        html_path = os.path.join(out_dir, "_note.html")
        effective = fetch_html_curl(url, html_path)
        if not note_id:
            note_id = extract_note_id(effective)
        with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
            html = f.read()
        try:
            os.remove(html_path)
        except OSError:
            pass
        state = parse_initial_state(html)
        if not state:
            last_reason = ("no window.__INITIAL_STATE__ in page; the token may have expired, "
                           "re-copy the full URL (with xsec_token) from the browser")
            time.sleep(5)
            continue
        note_map = (((state.get("note") or {}).get("noteDetailMap")) or {})
        entry = note_map.get(note_id)
        if entry:
            break
        last_reason = ("note not in page data; XHS returned a degraded SSR page; "
                       "if it keeps failing the xsec_token has expired, re-copy the URL")
        time.sleep(5)
    if not entry:
        if not note_id:
            die(3, "Could not find a 24-hex note id in the URL.")
        die(3, f"Could not load XHS note {note_id} after 4 attempts: {last_reason}")

    detail = entry.get("note") or entry
    ntype = detail.get("type") or ""
    if ntype != "video" or not detail.get("video"):
        die(2, "This Xiaohongshu note is not a video (looks like an image/text post).")

    title = detail.get("title") or ""
    desc = detail.get("desc") or ""
    if not title:
        title = (desc.split("\n")[0].strip() or "小红书视频")[:40]
    user = detail.get("user") or {}
    author = user.get("nickname") or user.get("nick_name") or user.get("name") or ""
    duration = (((detail.get("video") or {}).get("media") or {}).get("video") or {}).get("duration")

    # Pick a playable stream URL (camelCase keys: masterUrl / backupUrls).
    streams = ((detail.get("video") or {}).get("media") or {}).get("stream") or {}
    video_url = None
    for codec in ("h264", "h265", "av1", "h266"):
        for s in streams.get(codec, []) or []:
            if s.get("masterUrl"):
                video_url = s["masterUrl"]
                break
        if video_url:
            break
    if not video_url:
        for codec in ("h264", "h265", "av1", "h266"):
            for s in streams.get(codec, []) or []:
                if s.get("backupUrls"):
                    video_url = s["backupUrls"][0]
                    break
            if video_url:
                break
    if not video_url:
        die(4, "Could not find a playable XHS video stream URL.")

    video_path = os.path.join(out_dir, "video.mp4")
    audio_path = os.path.join(out_dir, "audio.wav")
    print(f"[xhs] downloading video ...")
    dl = subprocess.run(["curl", "-sL", video_url, "-H", f"User-Agent: {UA}",
                         "-H", "Referer: https://www.xiaohongshu.com/",
                         "--max-time", "180", "-o", video_path])
    if dl.returncode != 0 or not os.path.exists(video_path) or os.path.getsize(video_path) < 10000:
        die(4, "XHS video download failed; the stream URL may have expired.")
    print(f"[xhs] extracting audio ...")
    subprocess.run(["ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000",
                    "-c:a", "pcm_s16le", audio_path], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        os.remove(video_path)
    except OSError:
        pass

    return {
        "platform": "xiaohongshu", "id": note_id, "title": title, "author": author,
        "desc": desc, "duration": duration, "audio_path": audio_path,
        "sub_segments": None, "source_method": "audio+asr", "url": original_url,
    }


# --------------------------------------------------------------------------
# Bilibili
# --------------------------------------------------------------------------

def resolve_bili_id(url):
    """Return ('bvid', bv) or ('aid', aid). Resolves b23.tv short links."""
    if "b23.tv/" in url:
        eff = subprocess.run(["curl", "-sIL", "-o", "/dev/null", "-w", "%{url_effective}",
                              url, "--max-time", "15", "-H", f"User-Agent: {UA}"],
                             capture_output=True, text=True).stdout.strip()
        url = eff or url
    m = re.search(r"BV[0-9A-Za-z]{10}", url)
    if m:
        return ("bvid", m.group(0))
    m = re.search(r"[/=_]av(\d+)", url)
    if m:
        return ("aid", m.group(1))
    return (None, None)


def process_bili(url, out_dir, language, force_asr):
    kind, vid = resolve_bili_id(url)
    if not vid:
        die(6, "Could not find a BV/av id in the Bilibili URL.")
    key = "bvid" if kind == "bvid" else "aid"
    data = json.loads(http_get(
        f"https://api.bilibili.com/x/web-interface/view?{key}={vid}"))["data"]
    aid = data["aid"]
    # pick page (?p= or default 1)
    m = re.search(r"[?&]p=(\d+)", url)
    pno = int(m.group(1)) if m else 1
    pages = data.get("pages") or []
    page = pages[min(pno - 1, len(pages) - 1)] if pages else {}
    cid = page.get("cid") or data.get("cid")
    if not cid:
        die(4, "Could not find a cid for this Bilibili video.")

    title = data.get("title") or ""
    author = (data.get("owner") or {}).get("name") or ""
    desc = data.get("desc") or ""
    if not title:
        title = (desc.split("\n")[0].strip() or "B站视频")[:40]
    duration = data.get("duration")

    print(f"[bili] {key}={vid} | title: {title}")

    # --- subtitles (preferred over ASR) ---
    sub_segments = None
    sub_lang = None
    if not force_asr:
        try:
            pv2 = json.loads(http_get(
                f"https://api.bilibili.com/x/player/v2?aid={aid}&cid={cid}"))["data"]
            subs = (pv2.get("subtitle") or {}).get("subtitles") or []
            chosen = None
            for pref in ("zh-Hans", "ai-Zh", "zh-CN", "zh", "zh-Hant", "en"):
                chosen = next((s for s in subs if s.get("lan") == pref), None)
                if chosen:
                    break
            if not chosen and subs:
                chosen = subs[0]
            if chosen:
                su = chosen.get("subtitle_url", "")
                if su.startswith("//"):
                    su = "https:" + su
                sj = json.loads(http_get(su))
                body = sj.get("body") or []
                segs = [(float(b.get("from", 0)), float(b.get("to", 0)),
                         (b.get("content") or "").strip())
                        for b in body if (b.get("content") or "").strip()]
                if segs:
                    sub_segments = segs
                    sub_lang = chosen.get("lan_doc") or chosen.get("lan")
                    print(f"[bili] using subtitles ({sub_lang}, {len(segs)} lines) — skipping ASR")
        except Exception as e:
            print(f"[bili] subtitle fetch failed ({e}); will fall back to ASR")
            sub_segments = None

    # --- audio (only when no usable subtitles) ---
    audio_path = None
    if not sub_segments:
        stream_url = None
        for qn in ("16", "32"):
            try:
                pu = json.loads(http_get(
                    f"https://api.bilibili.com/x/player/playurl?avid={aid}&cid={cid}"
                    f"&qn={qn}&platform=html5&high_quality=1"))
                durl = (pu.get("data") or {}).get("durl") or []
                if durl and durl[0].get("url"):
                    stream_url = durl[0]["url"]
                    break
            except Exception:
                continue
        if not stream_url:
            die(4, "Could not get a playable Bilibili audio stream (html5 playurl). "
                   "The video may be region/member-restricted.")
        raw = os.path.join(out_dir, "bili_stream.mp4")
        audio_path = os.path.join(out_dir, "audio.wav")
        print(f"[bili] downloading audio stream ...")
        dl = subprocess.run(["curl", "-sL", "--max-time", "300", "-o", raw, stream_url,
                             "-H", f"User-Agent: {UA}", "-H", "Referer: https://www.bilibili.com/"])
        if dl.returncode != 0 or not os.path.exists(raw) or os.path.getsize(raw) < 10000:
            die(4, "Bilibili stream download failed.")
        print(f"[bili] extracting audio ...")
        subprocess.run(["ffmpeg", "-y", "-i", raw, "-vn", "-ac", "1", "-ar", "16000",
                        "-c:a", "pcm_s16le", audio_path], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            os.remove(raw)
        except OSError:
            pass

    return {
        "platform": "bilibili", "id": vid if kind == "bvid" else f"av{vid}",
        "title": title, "author": author, "desc": desc, "duration": duration,
        "audio_path": audio_path, "sub_segments": sub_segments,
        "source_method": "subtitles" if sub_segments else "audio+asr", "url": url,
        "page": pno, "subtitle_lang": sub_lang,
    }


# --------------------------------------------------------------------------
# Xiaoyuzhou (小宇宙 podcast)
# --------------------------------------------------------------------------

XYZ_EPISODE_RE = re.compile(r"xiaoyuzhoufm\.com/episode/([A-Za-z0-9_-]+)")
XYZ_PODCAST_RE = re.compile(r"xiaoyuzhoufm\.com/podcast/([A-Za-z0-9_-]+)")


def strip_html(s):
    """Crude tag stripper for the shownotes field (podcast notes are HTML)."""
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p>\s*<p[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&")
           .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
           .replace("&#39;", "'"))
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def process_xyz(url, out_dir, language):
    if XYZ_PODCAST_RE.search(url) and not XYZ_EPISODE_RE.search(url):
        die(2, "This is a 小宇宙 podcast CHANNEL link (a whole show), not a single "
               "episode. Open one episode and copy its /episode/<id> link instead.")

    print("[xyz] fetching episode page ...")
    html_path = os.path.join(out_dir, "_episode.html")
    fetch_html_curl(url, html_path, referer="https://www.xiaoyuzhoufm.com/")
    with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
        html = f.read()
    try:
        os.remove(html_path)
    except OSError:
        pass

    nd = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                   html, re.S)
    if not nd:
        die(3, "Could not find episode data on the 小宇宙 page; the link may be invalid.")
    data = json.loads(nd.group(1))
    pp = ((data.get("props") or {}).get("pageProps") or {})
    ep = pp.get("episode")
    if not ep:
        code = pp.get("statusCode")
        if code and code != 200:
            die(3, f"小宇宙 returned status {code} for this episode "
                   f"(it may be private/member-only).")
        die(3, "Could not find episode data on the 小宇宙 page; check the link.")
    if ep.get("isPrivateMedia") or ep.get("payType") not in (None, "FREE"):
        die(4, "This 小宇宙 episode is paid/member-only; its audio is not publicly downloadable.")

    eid = ep.get("eid") or (XYZ_EPISODE_RE.search(url) or ["", ""])[1]
    title = ep.get("title") or ""
    desc = ep.get("description") or ""
    duration = ep.get("duration")
    shownotes = strip_html(ep.get("shownotes") or "")
    podcast = ep.get("podcast") or {}
    show = podcast.get("title") or ""
    pub_date = ep.get("pubDate") or ""
    # The recognizable "author" of a podcast episode is its show; fall back to
    # the internal author handle.
    author = show or podcast.get("author") or ""
    if not title:
        title = (desc.split("\n")[0].strip() or "小宇宙播客")[:40]

    # Public CDN audio URL — no token or signature required.
    audio_url = ((ep.get("enclosure") or {}).get("url")
                 or ((ep.get("media") or {}).get("source") or {}).get("url"))
    if not audio_url:
        die(4, "Could not find a playable 小宇宙 audio URL.")

    print(f"[xyz] eid={eid} | {show} · {title}")
    raw = os.path.join(out_dir, "xyz_audio.m4a")
    audio_path = os.path.join(out_dir, "audio.wav")
    print("[xyz] downloading audio ...")
    # Podcasts can be hours long / hundreds of MB — allow a generous timeout.
    dl = subprocess.run(["curl", "-sL", audio_url, "-H", f"User-Agent: {UA}",
                         "-H", "Referer: https://www.xiaoyuzhoufm.com/",
                         "--max-time", "1200", "-o", raw])
    if dl.returncode != 0 or not os.path.exists(raw) or os.path.getsize(raw) < 10000:
        die(4, "小宇宙 audio download failed; the CDN URL may have changed.")
    print("[xyz] extracting audio ...")
    subprocess.run(["ffmpeg", "-y", "-i", raw, "-vn", "-ac", "1", "-ar", "16000",
                    "-c:a", "pcm_s16le", audio_path], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        os.remove(raw)
    except OSError:
        pass

    return {
        "platform": "xiaoyuzhou", "id": eid, "title": title, "author": author,
        "desc": shownotes or desc, "duration": duration, "audio_path": audio_path,
        "sub_segments": None, "source_method": "audio+asr", "url": url,
        "show": show, "pub_date": pub_date,
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def detect_platform(url):
    u = url.lower()
    if "xiaohongshu.com" in u or "xhslink.com" in u:
        return "xhs"
    if "bilibili.com" in u or "b23.tv" in u:
        return "bili"
    if "xiaoyuzhoufm.com" in u:
        return "xyz"
    return None


def main():
    ap = argparse.ArgumentParser(
        description="Transcribe a Xiaohongshu / Bilibili video or Xiaoyuzhou podcast episode.")
    ap.add_argument("url", help="URL (Xiaohongshu, Bilibili, or 小宇宙 episode)")
    ap.add_argument("--out-dir", help="Output directory (default /tmp/v2t_<id>)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--language", default="auto",
                    help="'auto' (default), or 'zh'/'en'/... ; use 'zh' if auto-detect is flaky")
    ap.add_argument("--force-asr", action="store_true",
                    help="Ignore Bilibili subtitles; always transcribe audio")
    args = ap.parse_args()

    if shutil.which("ffmpeg") is None:
        die(5, "ffmpeg not found. Install with: brew install ffmpeg")

    platform = detect_platform(args.url)
    if not platform:
        die(6, "Unrecognized URL — supply a Xiaohongshu / Bilibili video or 小宇宙 episode link.")

    stage = "/tmp/_v2t_stage"
    os.makedirs(stage, exist_ok=True)
    if platform == "xhs":
        note = process_xhs(args.url, stage, args.language)
    elif platform == "bili":
        note = process_bili(args.url, stage, args.language, args.force_asr)
    else:
        note = process_xyz(args.url, stage, args.language)

    out_dir = args.out_dir or f"/tmp/v2t_{note['id']}"
    os.makedirs(out_dir, exist_ok=True)
    # Move staged audio into the real out dir.
    if note["audio_path"] and os.path.exists(note["audio_path"]):
        new_audio = os.path.join(out_dir, "audio.wav")
        shutil.move(note["audio_path"], new_audio)
        note["audio_path"] = new_audio

    # --- produce text ---
    segments = []  # list of {start, end, text}
    asr_elapsed = 0.0
    model_used = ""
    if note["sub_segments"]:
        for st, en, txt in note["sub_segments"]:
            segments.append({"start": st, "end": en, "text": txt})
        model_used = f"subtitles ({note.get('subtitle_lang') or 'auto'})"
    else:
        ensure_mlx()
        import mlx_whisper
        model_used = args.model
        lang = None if args.language == "auto" else args.language
        prompt = (note["title"] + "。" + note.get("desc", ""))[:200]
        print(f"[asr] transcribing with mlx_whisper (model={args.model}, lang={args.language}) ...")
        t0 = time.time()
        result = mlx_whisper.transcribe(
            note["audio_path"], path_or_hf_repo=args.model, language=lang,
            initial_prompt=prompt, verbose=False)
        asr_elapsed = time.time() - t0
        raw_segments = result.get("segments") or []
        for s in raw_segments:
            s["text"] = deloop_text(s.get("text") or "")
        segments = drop_hallucinated_segments(raw_segments)

    raw_text = "".join((s.get("text") or "") for s in segments).strip()

    with open(os.path.join(out_dir, "raw_text.txt"), "w", encoding="utf-8") as f:
        f.write(raw_text + "\n")
    with open(os.path.join(out_dir, "segments.txt"), "w", encoding="utf-8") as f:
        for s in segments:
            f.write(f"[{float(s.get('start', 0)):06.2f} -> {float(s.get('end', 0)):06.2f}] "
                    f"{(s.get('text') or '').strip()}\n")
    metadata = {
        "platform": note["platform"], "id": note["id"], "url": note["url"],
        "title": note["title"], "author": note["author"], "desc": note["desc"],
        "duration_seconds": note.get("duration"),
        "source_method": note["source_method"], "model": model_used,
        "language": args.language, "segment_count": len(segments),
        "asr_elapsed_seconds": round(asr_elapsed, 1), "out_dir": out_dir,
    }
    # Podcast-only extras, when present.
    if note.get("show"):
        metadata["show"] = note["show"]
    if note.get("pub_date"):
        metadata["pub_date"] = note["pub_date"]
    with open(os.path.join(out_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print("\n=== RAW TEXT ===")
    print(raw_text[:1000] + ("\n...[truncated]" if len(raw_text) > 1000 else ""))
    print(f"\n[done] {len(segments)} segments | source: {note['source_method']} "
          f"| asr: {asr_elapsed:.1f}s")
    print(f"[done] outputs in: {out_dir}")


if __name__ == "__main__":
    main()
