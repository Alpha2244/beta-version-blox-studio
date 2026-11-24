import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

DEFAULT_VOICE_ID = "pNInz6obpgDQGcFmaJgB"  # Adam
DEFAULT_MODEL_ID = "eleven_multilingual_v2"
CACHE_DIR = os.path.expanduser("~/.cache/blox_tts_cache")


def normalize_word(w: str) -> str:
    return re.sub(r"[^a-z0-9']", "", w.lower())


def chars_to_words(chars: list[str], starts: list[float], ends: list[float]) -> list[dict]:
    words = []
    buf = []
    w_start = None
    w_end = None

    for ch, st, en in zip(chars, starts, ends):
        if ch.isspace():
            if buf:
                words.append({"w": "".join(buf), "t0": round(w_start, 3), "t1": round(w_end, 3)})
                buf = []
                w_start = None
                w_end = None
        else:
            if w_start is None:
                w_start = st
            w_end = en
            buf.append(ch)

    if buf:
        words.append({"w": "".join(buf), "t0": round(w_start, 3), "t1": round(w_end, 3)})
    return words


def call_elevenlabs_tts(api_key: str, voice_id: str, text: str, speed: float) -> tuple[bytes, list[dict]]:
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_key = hashlib.sha256(f"el|{voice_id}|{speed}|{text}".encode("utf-8")).hexdigest()[:24]
    cached_mp3 = os.path.join(CACHE_DIR, f"{cache_key}.mp3")
    cached_words = os.path.join(CACHE_DIR, f"{cache_key}.json")

    if os.path.exists(cached_mp3) and os.path.exists(cached_words):
        print(f"[TTS] Cache hit ({cache_key}) — 0 credits used.", flush=True)
        with open(cached_mp3, "rb") as f:
            audio_bytes = f.read()
        with open(cached_words, "r", encoding="utf-8") as f:
            words = json.load(f)
        return audio_bytes, words

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps?output_format=mp3_44100_128"
    payload = {
        "text": text,
        "model_id": DEFAULT_MODEL_ID,
        "voice_settings": {
            "stability": 0.42,
            "similarity_boost": 0.80,
            "style": 0.35,
            "use_speaker_boost": True,
            "speed": speed,
        },
    }
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
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="ignore")
        sys.exit(f"FATAL: ElevenLabs API HTTP {e.code}: {err_msg}")

    audio_b64 = data.get("audio_base64")
    if not audio_b64:
        sys.exit(f"FATAL: ElevenLabs response missing audio_base64: {list(data.keys())}")

    audio_bytes = base64.b64decode(audio_b64)
    align = data.get("alignment") or data.get("normalized_alignment") or {}
    chars = align.get("characters") or []
    starts = align.get("character_start_times_seconds") or []
    ends = align.get("character_end_times_seconds") or []
    words = chars_to_words(chars, starts, ends)

    with open(cached_mp3, "wb") as f:
        f.write(audio_bytes)
    with open(cached_words, "w", encoding="utf-8") as f:
        json.dump(words, f)

    return audio_bytes, words


def generate_with_kokoro(text: str, raw_mp3: str) -> list[dict]:
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    print("[TTS] Running free offline Kokoro TTS...", flush=True)
    pipe = KPipeline(lang_code="a")
    chunks = []
    words = []
    t_offset = 0.0
    sr = 24000

    for result in pipe(text, voice="am_adam", speed=1.20):
        audio = result.audio
        if hasattr(audio, "numpy"):
            audio = audio.numpy()
        audio = np.asarray(audio, dtype=np.float32)
        chunks.append(audio)
        seg_dur = len(audio) / sr

        seg_words = [w for w in result.graphemes.strip().split() if w]
        if seg_words:
            step = seg_dur / len(seg_words)
            for i, w in enumerate(seg_words):
                words.append({
                    "w": w,
                    "t0": round(t_offset + i * step, 3),
                    "t1": round(t_offset + (i + 1) * step, 3),
                })
        t_offset += seg_dur

    full_audio = np.concatenate(chunks) if chunks else np.zeros(sr, dtype=np.float32)
    tmp_wav = raw_mp3 + ".wav"
    sf.write(tmp_wav, full_audio, sr)
    subprocess.run(
        ["ffmpeg", "-y", "-i", tmp_wav, "-codec:a", "libmp3lame", "-b:a", "192k", raw_mp3],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.remove(tmp_wav)
    return words


def apply_fast_tempo(raw_mp3: str, final_mp3: str, words: list[dict], tempo: float) -> list[dict]:
    if tempo <= 1.01:
        shutil.move(raw_mp3, final_mp3)
        return words

    subprocess.run(
        [
            "ffmpeg", "-y", "-i", raw_mp3,
            "-filter:a", f"atempo={tempo:.3f}",
            "-codec:a", "libmp3lame", "-b:a", "192k",
            final_mp3,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.remove(raw_mp3)

    scaled = []
    for w in words:
        scaled.append({
            "w": w["w"],
            "t0": round(w["t0"] / tempo, 3),
            "t1": round(w["t1"] / tempo, 3),
        })
    return scaled


def probe_duration(media_path: str) -> float:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            media_path,
        ],
        text=True,
    ).strip()
    return float(out)


def align_shots_to_words(shots: list[dict], words: list[dict], total_dur: float) -> list[dict]:
    w_cursor = 0
    n_words = len(words)
    aligned = []

    for idx, sh in enumerate(shots):
        shot_tokens = [t for t in sh["text"].split() if normalize_word(t)]
        count = max(1, len(shot_tokens))

        if w_cursor < n_words:
            start_t = words[w_cursor]["t0"] if idx > 0 else 0.0
            end_idx = min(n_words - 1, w_cursor + count - 1)
            end_t = words[end_idx]["t1"]
            w_cursor = end_idx + 1
        else:
            start_t = aligned[-1]["t1"] if aligned else 0.0
            end_t = min(total_dur, start_t + 1.4)

        if idx == len(shots) - 1:
            end_t = total_dur

        if end_t - start_t < 0.85:
            end_t = min(total_dur, start_t + 0.85)

        sh_copy = dict(sh)
        sh_copy["t0"] = round(start_t, 3)
        sh_copy["t1"] = round(end_t, 3)
        aligned.append(sh_copy)

    for i in range(len(aligned) - 1):
        if aligned[i + 1]["t0"] > aligned[i]["t1"]:
            aligned[i]["t1"] = aligned[i + 1]["t0"]

    return aligned


def main(project_dir: str):
    timed_path = os.path.join(project_dir, "timed.json")
    with open(timed_path, "r", encoding="utf-8") as f:
        spec = json.load(f)

    shots = spec["shots"]
    full_text = " ".join(sh["text"].strip() for sh in shots)
    engine = os.environ.get("VOICE_ENGINE", "kokoro").strip().lower()
    tempo = max(1.0, min(1.65, float(os.environ.get("VOICE_TEMPO", "1.42"))))

    raw_mp3 = os.path.join(project_dir, "voice_raw.mp3")
    voice_mp3 = os.path.join(project_dir, "voice.mp3")

    if engine == "elevenlabs":
        api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        if not api_key:
            sys.exit("ERROR: ELEVENLABS_API_KEY is missing from GitHub Secrets.")
        voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "").strip() or DEFAULT_VOICE_ID
        speed = max(0.70, min(1.20, float(os.environ.get("VOICE_SPEED", "1.20"))))
        print(f"[ElevenLabs] Synthesizing {len(full_text)} chars with voice={voice_id}, speed={speed}...", flush=True)
        audio_bytes, words = call_elevenlabs_tts(api_key, voice_id, full_text, speed)
        with open(raw_mp3, "wb") as f:
            f.write(audio_bytes)
    else:
        words = generate_with_kokoro(full_text, raw_mp3)

    words = apply_fast_tempo(raw_mp3, voice_mp3, words, tempo)
    audio_dur = round(probe_duration(voice_mp3), 3)
    spec["words"] = words
    spec["shots"] = align_shots_to_words(shots, words, audio_dur)
    spec["dur"] = audio_dur

    with open(timed_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2)

    wps = len(words) / max(audio_dur, 0.1)
    print(f"[TTS] DONE ({engine} @ {tempo}x): {len(words)} words in {audio_dur}s ({wps:.2f} words/sec).", flush=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python auto/elevenlabs_voice.py kit/projects/<name>")
    main(os.path.abspath(sys.argv[1]))
