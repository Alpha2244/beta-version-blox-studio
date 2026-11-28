"""Voice for a project with Kokoro TTS (free, Apache 2.0, runs on CPU or GPU).

  python kit/blox/voice.py PROJECTDIR

Reads PROJECTDIR/timed.json, speaks each shot's `text` (words in brackets are skipped),
routes distinct Kokoro voices per speaking character if not explicitly overridden,
syncs actor `talk` windows to exact speech duration, and fits shots to the voice.
"""
import hashlib
import json
import os
import re
import sys
import numpy as np

SR = 24000
PAD_IN, PAD_OUT = 0.08, 0.22  # silence before each line inside its shot, and pause after it

# Default character voice mapping so different speakers sound distinct automatically
DEFAULT_CHAR_VOICES = {
    'maya': 'af_bella',
    'zoe': 'af_nicole',
    'mom': 'af_heart',
    'ms_clara': 'bf_emma',
    'ms. clara': 'bf_emma',
    'leo': 'am_michael',
    'sam': 'am_puck',
    'jake': 'am_fenrir',
    'max': 'am_puck',
    'dad': 'bm_george',
    'mr. reed': 'bm_george',
    'uncle_sam': 'bm_fable',
}


def spoken(text):
    return re.sub(r'\([^)]*\)|\[[^\]]*\]', '', text or '').strip()


def resolve_shot_voice(shot, cast, base_voice):
    if shot.get('voice'):
        return shot['voice']
    subj = str(shot.get('subject') or '').strip()
    key = subj.lower()
    if key in DEFAULT_CHAR_VOICES:
        return DEFAULT_CHAR_VOICES[key]
    cspec = (cast or {}).get(subj) or {}
    gender = str(cspec.get('gender') or '').lower()
    if gender == 'female' or any(w in key for w in ('girl', 'sister', 'mom', 'ms', 'mrs', 'queen')):
        return 'af_bella'
    return base_voice


def line_audio(pipes, text, voice, speed, cache):
    key = hashlib.sha1(f'{voice}|{speed}|{text}'.encode('utf8')).hexdigest()[:16]
    wp, jp = os.path.join(cache, key + '.npy'), os.path.join(cache, key + '.json')
    if os.path.exists(wp) and os.path.exists(jp):
        return np.load(wp), json.load(open(jp, encoding='utf8'))

    lang = voice[0] if voice and voice[0] in 'ab' else 'a'
    try:
        if lang not in pipes:
            from kokoro import KPipeline
            pipes[lang] = KPipeline(lang_code=lang)
    except Exception as exc:
        # Fallback timing buffer if Kokoro runtime is unavailable
        ws = [w for w in text.split() if re.search(r'\w', w)]
        dur = max(0.8, len(ws) / 3.8)
        audio = np.zeros(int(dur * SR), np.float32)
        words = [[w, round(dur * i / max(1, len(ws)), 3), round(dur * (i + 1) / max(1, len(ws)), 3)] for i, w in enumerate(ws)]
        print(f'[voice WARN] Kokoro unavailable ({exc}); generated {dur:.2f}s timing track.', flush=True)
        return audio, words

    chunks, words, t = [], [], 0.0
    for r in pipes[lang](text, voice=voice, speed=speed):
        a = r.audio
        if a is None:
            continue
        a = a.detach().cpu().numpy() if hasattr(a, 'detach') else np.asarray(a)
        a = a.astype(np.float32).reshape(-1)
        toks = getattr(r, 'tokens', None) or []
        got = False
        for tk in toks:
            w = (tk.text or '').strip()
            if not w or not re.search(r'\w', w):
                continue
            if tk.start_ts is None or tk.end_ts is None:
                continue
            words.append([w, round(t + tk.start_ts, 3), round(t + tk.end_ts, 3)])
            got = True
        if not got:
            ws = [w for w in (getattr(r, 'graphemes', '') or '').split() if re.search(r'\w', w)]
            d = len(a) / SR
            for i, w in enumerate(ws):
                words.append([w, round(t + d * i / len(ws), 3), round(t + d * (i + 1) / len(ws), 3)])
        chunks.append(a)
        t += len(a) / SR

    audio = np.concatenate(chunks) if chunks else np.zeros(1, np.float32)
    src = text.split()
    if len(src) == len(words):
        for i, w in enumerate(src):
            words[i][0] = w
    np.save(wp, audio)
    json.dump(words, open(jp, 'w', encoding='utf8'))
    return audio, words


def main(d):
    tp = os.path.join(d, 'timed.json')
    sp = json.load(open(tp, encoding='utf8'))
    base_voice = sp.get('voice', 'am_michael')
    speed = float(sp.get('voice_speed', 1.05))
    cast = sp.get('cast') or {}
    cache = os.path.join(d, 'voice')
    os.makedirs(cache, exist_ok=True)

    pipes, lines = {}, []
    for i, s in enumerate(sp['shots']):
        txt = spoken(s.get('text', ''))
        if not txt:
            lines.append(None)
            continue
        v_id = resolve_shot_voice(s, cast, base_voice)
        a, w = line_audio(pipes, txt, v_id, speed, cache)
        lines.append((a, w))
        print(f'  {i:3d} [{v_id}] {len(a) / SR:5.2f} s  {txt[:50]}', flush=True)

    # Re-time shots to fit speech + pauses and sync speaker `talk` windows
    t, moved = 0.0, 0
    for s, ln in zip(sp['shots'], lines):
        dur = float(s.get('t1', 0.0)) - float(s.get('t0', 0.0))
        speech_dur = (len(ln[0]) / SR) if ln else 0.0
        need = (PAD_IN + speech_dur + PAD_OUT) if ln else max(1.0, dur)
        nd = max(1.1, need)
        if abs(nd - dur) > 1e-3 or abs(float(s.get('t0', 0.0)) - t) > 1e-3:
            moved += 1
        s['t0'], s['t1'] = round(t, 3), round(t + nd, 3)

        # Sync speaking actor's mouth window to exact audio duration
        subj = s.get('subject')
        for act in s.get('actors') or []:
            if ln and act.get('who') == subj:
                act['talk'] = [round(PAD_IN, 3), round(PAD_IN + speech_dur, 3)]
        t += nd

    sp['dur'] = round(max(float(sp.get('dur', 0.0)), t) if moved == 0 else t, 3)
    total = np.zeros(int(np.ceil(sp['dur'] * SR)) + SR, np.float32)
    words = []
    for s, ln in zip(sp['shots'], lines):
        if not ln:
            continue
        a, w = ln
        o = s['t0'] + PAD_IN
        k = int(o * SR)
        total[k:k + len(a)] += a[:len(total) - k]
        words += [[x, round(o + a0, 3), round(o + a1, 3)] for x, a0, a1 in w]

    total = total[:int(np.ceil(sp['dur'] * SR))]
    pk = float(np.abs(total).max() or 1.0)
    total = total / pk * 0.89

    from scipy.io import wavfile
    wavfile.write(os.path.join(d, 'vo.wav'), SR, (total * 32767).astype(np.int16))
    json.dump(words, open(os.path.join(d, 'words.json'), 'w', encoding='utf8'))
    json.dump(sp, open(tp, 'w', encoding='utf8'), indent=1)
    open(os.path.join(d, '.voice_kokoro'), 'w').write(base_voice)
    print(f'voice: {len(words)} words, {sp["dur"]:.2f} s, {moved} shots re-timed to fit the voice', flush=True)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(os.path.abspath(sys.argv[1]))
