import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import numpy as np
from scipy.io import wavfile

SR = 24000
PAD_IN = 0.02
PAD_OUT = 0.05
VOICE_SPEED = float(os.environ.get("VOICE_SPEED", "1.20"))


def spoken(text: str) -> str:
    return re.sub(r"\([^)]*\)|\[[^\]]*\]", "", text).strip()


def alignment_to_words(alignment: dict) -> list:
    chars = alignment.get("characters") or []
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    words = []
    cur_chars, w_start, w_end = [], None, None

    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if cur_chars:
                word = "".join(cur_chars).strip()
                if word:
                    words.append([word, round(float(w_start), 3), round(float(w_end), 3)])
                cur_chars, w_start, w_end = [], None, None
        else:
            if w_start is None:
                w_start = s
            w_end = e
            cur_chars.append(ch)

    if cur_chars:
        word = "".join(cur_chars).strip()
        if word:
            words.append([word, round(float(w_start), 3), round(float(w_end), 3)])
    return words


def synthesize_line(api_key: str, voice_id: str, text: str):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps?output_format=pcm_24000"
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.40,
            "similarity_boost": 0.80,
            "style": 0.45,
            "speed": max(0.7, min(1.2, VOICE_SPEED)),
            "use_speaker_boost": True,
        },
    }

    last_err = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            audio_bytes = base64.b64decode(data["audio_base64"])
            samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            nonzero = np.nonzero(np.abs(samples) > 0.01)[0]
            if len(nonzero):
                end_idx = min(len(samples), int(nonzero[-1]) + int(0.03 * SR))
                samples = samples[:end_idx]

            alignment = data.get("alignment") or data.get("normalized_alignment") or {}
            words = alignment_to_words(alignment)

            if not words:
                ws = [w for w in text.split() if re.search(r"\w", w)]
                dur = max(0.1, len(samples) / SR)
                words = [[w, round(dur * i / len(ws), 3), round(dur * (i + 1) / len(ws), 3)] for i, w in enumerate(ws)]

            return samples, words
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")[:300]
            last_err = f"HTTP {e.code}: {err_body}"
            print(f"[ElevenLabs] Attempt {attempt} failed: {last_err}", flush=True)
            if e.code in (401, 403, 422):
                break
            time.sleep(2 * attempt)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            print(f"[ElevenLabs] Attempt {attempt} error: {last_err}", flush=True)
            time.sleep(2 * attempt)

    raise RuntimeError(f"ElevenLabs TTS failed for '{text[:40]}...': {last_err}")


def run_free_kokoro(project_dir: str):
    print("[Voice] Using 100% FREE Kokoro offline TTS (0 ElevenLabs credits used)...", flush=True)
    subprocess.run([sys.executable, "kit/run.py", project_dir, "voice"], check=True)


def main(project_dir: str):
    engine = os.environ.get("VOICE_ENGINE", "kokoro").strip().lower()
    if engine == "kokoro":
        run_free_kokoro(project_dir)
        return

    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
    if not api_key or not voice_id:
        print("[WARN] ElevenLabs secrets missing -> falling back to free Kokoro TTS.", flush=True)
        run_free_kokoro(project_dir)
        return

    tp = os.path.join(project_dir, "timed.json")
    spec = json.load(open(tp, encoding="utf-8"))

    # Check local/cached audio backup first so retries NEVER spend extra credits
    cache_root = os.path.expanduser("~/.cache/blox_tts_cache")
    os.makedirs(cache_root, exist_ok=True)
    story_sig = hashlib.sha256(
        json.dumps([spoken(s["text"]) for s in spec["shots"]] + [voice_id, VOICE_SPEED]).encode("utf-8")
    ).hexdigest()[:16]
    cached_dir = os.path.join(cache_root, story_sig)

    if os.path.exists(os.path.join(cached_dir, "vo.wav")) and os.path.exists(os.path.join(cached_dir, "words.json")):
        import shutil
        shutil.copy2(os.path.join(cached_dir, "vo.wav"), os.path.join(project_dir, "vo.wav"))
        shutil.copy2(os.path.join(cached_dir, "words.json"), os.path.join(project_dir, "words.json"))
        shutil.copy2(os.path.join(cached_dir, "timed.json"), tp)
        print(f"[ElevenLabs] Reused cached voiceover ({story_sig}) -> 0 credits spent!", flush=True)
        return

    lines = []
    for i, s in enumerate(spec["shots"]):
        txt = spoken(s["text"])
        if not txt:
            lines.append(None)
            continue
        audio, words = synthesize_line(api_key, voice_id, txt)
        lines.append((audio, words))
        print(f"  [TTS {i:02d}] {len(audio)/SR:5.2f}s | {txt[:55]}", flush=True)

    t, moved = 0.0, 0
    for s, ln in zip(spec["shots"], lines):
        need = (PAD_IN + len(ln[0]) / SR + PAD_OUT) if ln else 1.0
        nd = max(0.8, round(need, 3))
        if abs(s["t0"] - t) > 1e-3 or abs((s["t1"] - s["t0"]) - nd) > 1e-3:
            moved += 1
        s["t0"], s["t1"] = round(t, 3), round(t + nd, 3)
        t += nd

    spec["dur"] = round(t, 3)

    total = np.zeros(int(np.ceil(spec["dur"] * SR)) + SR, dtype=np.float32)
    all_words = []
    for s, ln in zip(spec["shots"], lines):
        if not ln:
            continue
        a, w = ln
        offset = s["t0"] + PAD_IN
        k = int(offset * SR)
        total[k : k + len(a)] += a[: len(total) - k]
        all_words += [[word, round(offset + s0, 3), round(offset + s1, 3)] for word, s0, s1 in w]

    total = total[: int(np.ceil(spec["dur"] * SR))]
    pk = float(np.abs(total).max() or 1.0)
    total = total / pk * 0.89

    vo_path = os.path.join(project_dir, "vo.wav")
    words_path = os.path.join(project_dir, "words.json")
    wavfile.write(vo_path, SR, (total * 32767).astype(np.int16))
    with open(words_path, "w", encoding="utf-8") as f:
        json.dump(all_words, f)
    with open(tp, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2)

    # Save backup into cache immediately
    import shutil
    os.makedirs(cached_dir, exist_ok=True)
    shutil.copy2(vo_path, os.path.join(cached_dir, "vo.wav"))
    shutil.copy2(words_path, os.path.join(cached_dir, "words.json"))
    shutil.copy2(tp, os.path.join(cached_dir, "timed.json"))

    kokoro_flag = os.path.join(project_dir, ".voice_kokoro")
    if os.path.exists(kokoro_flag):
        os.remove(kokoro_flag)

    wpm = (len(all_words) / max(spec["dur"], 1.0)) * 60
    print(f"[ElevenLabs] Wrote vo.wav + words.json ({len(all_words)} words in {spec['dur']:.2f}s = {wpm:.0f} WPM)", flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python auto/elevenlabs_voice.py kit/projects/<name>")
    main(os.path.abspath(sys.argv[1]))
