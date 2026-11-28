"""Render EPDIR/scene.blend in K parallel Blender processes (interleaved chunks so all finish together).
python render_par.py EPDIR [K=4] [--frames 0,30,60|10..40] [--out frames] [--mux]
"""
import glob
import json
import math
import os
import subprocess
import sys
import time

BL = os.environ.get('BLENDER') or 'blender'  # kit/run.py sets BLENDER
FFMPEG = os.environ.get('FFMPEG') or 'ffmpeg'

ep = os.path.abspath(sys.argv[1])
K = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 4
blend = os.path.join(ep, 'scene.blend')
t0 = time.time()


def _mux_with_transitions(ep_dir, fps=30):
    """Assemble EPDIR/frames/*.jpg + audio into EPDIR/render_raw.mp4 with shot-boundary flash/zoom transitions."""
    timed_path = os.path.join(ep_dir, 'timed.json')
    if not os.path.exists(timed_path):
        return
    spec = json.load(open(timed_path, encoding='utf-8'))
    shots = spec.get('shots', [])
    frames_pat = os.path.join(ep_dir, 'frames', '%05d.jpg')
    out_mp4 = os.path.join(ep_dir, 'render_raw.mp4')

    # Build lightweight flash-dip expression at shot cut boundaries (2-frame punch on high-impact cuts)
    cut_frames = []
    for s in shots[1:]:
        cf = int(round(float(s.get('t0', 0)) * fps))
        if s.get('move') == 'crash_in' or s.get('flash') or s.get('cam') in ('cu', 'ecu', 'ws'):
            cut_frames.append(cf)

    vf_filters = ['scale=1080:1920:flags=lanczos']
    if cut_frames:
        cond = '+'.join(f'between(n,{cf},{cf + 1})' for cf in cut_frames[:24])
        vf_filters.append(f"eq=brightness=0.14:enable='{cond}'")

    cmd = [
        FFMPEG, '-y',
        '-framerate', str(fps),
        '-start_number', '0',
        '-i', frames_pat,
        '-vf', ','.join(vf_filters),
        '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p',
        '-crf', '18',
        '-preset', 'fast',
        out_mp4,
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode == 0:
        print(f'[mux] Assembled {out_mp4} with {len(cut_frames)} impact cut transitions', flush=True)
    else:
        print(f'[mux WARN] FFmpeg exited {res.returncode}: {res.stderr[-300:]}', flush=True)


if '--frames' in sys.argv:
    fr = []
    for x in sys.argv[sys.argv.index('--frames') + 1].split(','):
        a, _, b = x.partition('..')
        fr += [str(i) for i in range(int(a), int(b or a) + 1)]
    sub = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else 'stills'
    os.makedirs(os.path.join(ep, sub), exist_ok=True)
    out = os.path.join(ep, sub, '#####')
    groups = [fr[i::K] for i in range(K)]
    cmds = [[BL, '-b', blend, '-o', out, '-F', 'JPEG', '-f', ','.join(g)] for g in groups if g]
else:
    n = int(math.ceil(json.load(open(os.path.join(ep, 'timed.json'), encoding='utf-8'))['dur'] * 30))
    os.makedirs(os.path.join(ep, 'frames'), exist_ok=True)
    out = os.path.join(ep, 'frames', '#####')
    CH = -(-n // K)
    chunks = [(a, min(a + CH, n) - 1) for a in range(0, n, CH)]
    groups = [chunks[i::K] for i in range(K)]
    cmds = []
    for g in groups:
        args = [BL, '-b', blend, '-o', out, '-F', 'JPEG']
        for a, b in g:
            args += ['-s', str(a), '-e', str(b), '-a']
        cmds.append(args)

ps = [subprocess.Popen(c, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True) for c in cmds]
failed = []
for idx, p in enumerate(ps):
    _, err = p.communicate()
    if p.returncode != 0:
        failed.append((idx, p.returncode, (err or '').strip()[-400:]))

if failed:
    for idx, rc, msg in failed:
        print(f'[render_par ERROR] worker {idx} exited {rc}:\n{msg}', file=sys.stderr, flush=True)
    sys.exit(1)

print(
    'rendered with', len(ps), 'procs in', round(time.time() - t0, 1),
    's; frames on disk', len(glob.glob(os.path.join(ep, 'frames', '*.jpg'))),
    flush=True,
)

if '--mux' in sys.argv and '--frames' not in sys.argv:
    _mux_with_transitions(ep, fps=30)
