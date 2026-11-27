"""3-Stage AI Story Director for Blox Studio (@craftee_films Visual & Narrative Standard).

Converts any story prompt or premise into a validated, production-ready `timed.json`
compatible with `kit/blox/compile.py`, `kit/blox/chars.py`, `kit/blox/sets.py`, and
`kit/blox/assets_loader.py`.

Stages:
  1. Narrative Architect: builds cast archetypes, set selection, and 7-beat story arc.
  2. Cinematographer & Choreographer: assigns anti-crop cameras, spatial blocking,
     hand-parented/pedestal/hinged props, and timed faceAt/animAt reaction beats.
  3. Quality Gate & Auto-Repair: validates timing, spacing, valid animations/expressions,
     and catalog prop resolution before writing `timed.json`.

Usage:
    python auto/story_director.py --prompt "Sam brings a magic pen to class" --out episodes/ep01/timed.json
"""
import argparse
import json
import math
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT_BLOX = ROOT / 'kit' / 'blox'
if str(KIT_BLOX) not in sys.path:
    sys.path.insert(0, str(KIT_BLOX))
if str(ROOT / 'auto') not in sys.path:
    sys.path.insert(0, str(ROOT / 'auto'))

import fetch_master_assets

VALID_ANIMS = {
    'idle', 'talk', 'walk', 'run', 'point', 'shrug', 'shock', 'scared', 'cheer', 'eat',
    'cross_arms', 'think', 'sad', 'angry', 'wave', 'sit', 'facepalm',
    'hold_hands', 'hold_hands_L', 'hold_hands_R',
    'nod', 'headshake', 'flinch', 'slump', 'jump_joy', 'surrender', 'what', 'clap',
    'grab', 'bend', 'write', 'read', 'exercise',
}
VALID_EXPRS = {
    'neutral', 'smile', 'grin', 'scheming', 'laugh', 'shock', 'scared', 'wince',
    'sad', 'worried', 'angry', 'smug', 'think', 'blink', 'cry', 'blush',
}
VALID_CAMS = {
    'ecu', 'cu', 'mcu', 'ms', 'mls', 'ws', 'ews', 'ots',
    'low', 'worm', 'ground', 'high', 'top', 'ins', 'pov', 'two',
}
VALID_SETS = {'Street', 'Classroom', 'Bedroom', 'LivingRoom', 'Kitchen', 'Park', 'Gym'}

# ---------------------------------------------------------------- 4 Studio Character Archetypes
ARCHETYPES = {
    'hero': {
        'gender': 'male',
        'skin': [0.96, 0.78, 0.62],
        'shirt': [0.16, 0.48, 0.94],
        'pants': [0.15, 0.20, 0.34],
        'shoes': [0.92, 0.22, 0.22],
        'hair': 'pompadour',
        'hair_color': [0.24, 0.14, 0.08],
        'height': 1.0,
        'extras': ['collar'],
    },
    'girl': {
        'gender': 'female',
        'skin': [0.95, 0.76, 0.62],
        'shirt': [0.98, 0.45, 0.66],
        'pants': [0.22, 0.24, 0.36],
        'shoes': [0.95, 0.95, 0.96],
        'hair': 'long',
        'hair_color': [0.16, 0.10, 0.07],
        'height': 0.95,
        'extras': ['skirt'],
    },
    'rival': {
        'gender': 'male',
        'skin': [0.88, 0.68, 0.52],
        'shirt': [0.90, 0.22, 0.20],
        'pants': [0.14, 0.14, 0.18],
        'shoes': [0.16, 0.16, 0.20],
        'hair': 'spiky',
        'hair_color': [0.12, 0.10, 0.10],
        'height': 1.02,
        'extras': ['pocket'],
    },
    'elder': {
        'gender': 'male',
        'skin': [0.92, 0.74, 0.60],
        'shirt': [0.88, 0.88, 0.90],
        'pants': [0.22, 0.24, 0.28],
        'shoes': [0.18, 0.15, 0.12],
        'hair': 'grey_old',
        'hair_color': [0.76, 0.76, 0.78],
        'height': 1.04,
        'extras': ['glasses', 'tie', 'grey_beard'],
    },
}


def _load_catalog():
    cat_path = ROOT / 'master_assets' / 'catalog.json'
    if not cat_path.exists():
        return fetch_master_assets.build_catalog(online=False)
    return json.loads(cat_path.read_text(encoding='utf-8'))


def _extract_nouns_and_setting(prompt, catalog):
    text = prompt.lower()
    tags = catalog.get('tag_index', {})
    items = catalog.get('items', {})

    # Detect setting
    setting = 'Street'
    if any(k in text for k in ('class', 'school', 'exam', 'teacher', 'homework', 'desk')):
        setting = 'Classroom'
    elif any(k in text for k in ('bedroom', 'bed', 'closet', 'wardrobe', 'sleep', 'room')):
        setting = 'Bedroom'
    elif any(k in text for k in ('kitchen', 'pizza', 'cake', 'cook', 'eat', 'fridge', 'burger')):
        setting = 'Kitchen'
    elif any(k in text for k in ('gym', 'dumbbell', 'workout', 'muscle', 'lift')):
        setting = 'Gym'
    elif any(k in text for k in ('park', 'tree', 'bench', 'sand', 'outside')):
        setting = 'Park'
    elif any(k in text for k in ('living', 'sofa', 'tv', 'couch')):
        setting = 'LivingRoom'

    # Detect props mentioned in prompt
    found_props = []
    words = re.findall(r'[a-z_]+', text)
    for w in words:
        if w in tags:
            item_id = tags[w]
            if item_id not in [p['id'] for p in found_props]:
                found_props.append(items[item_id])
    if not found_props:
        found_props.append(items.get('gift', {'id': 'gift', 'placement': 'pedestal'}))
    return setting, found_props


def _extract_names(prompt):
    # Find capitalized character names excluding sentence-start filler words
    stop = {
        'The', 'A', 'An', 'In', 'On', 'At', 'When', 'Why', 'How', 'Then', 'One',
        'My', 'His', 'Her', 'Never', 'Always', 'Make', 'Create', 'Write', 'Story',
    }
    caps = [w for w in re.findall(r'\b[A-Z][a-z]{2,12}\b', prompt) if w not in stop]
    unique = []
    for c in caps:
        if c not in unique:
            unique.append(c)
    hero = unique[0] if len(unique) >= 1 else 'Sam'
    friend = unique[1] if len(unique) >= 2 else 'Zoe'
    rival = unique[2] if len(unique) >= 3 else 'Max'
    return hero, friend, rival


# ---------------------------------------------------------------- Stage 1 & 2: Deterministic Story & Shot Generator
def _build_procedural_episode(prompt, dur=18.0, voice='am_michael'):
    catalog = _load_catalog()
    setting, props = _extract_nouns_and_setting(prompt, catalog)
    hero, friend, rival = _extract_names(prompt)
    text_low = prompt.lower()

    has_elder = any(k in text_low for k in ('teacher', 'dad', 'father', 'professor', 'principal', 'boss', 'old'))
    third_name = 'Mr. Reed' if has_elder else rival
    third_arch = 'elder' if has_elder else 'rival'

    cast = {
        hero: dict(ARCHETYPES['hero']),
        friend: dict(ARCHETYPES['girl']),
        third_name: dict(ARCHETYPES[third_arch]),
    }

    primary_prop = props[0]
    p_id = primary_prop['id']
    p_place = primary_prop.get('placement', 'hand')

    # Build prop attachment spec for shot choreography
    def make_prop_spec(holder, t_start, t_end, sparkle=False, open_t=None):
        spec = {'name': f'story_{p_id}', 'type': p_id, 'showAt': t_start, 'hideAt': t_end}
        if sparkle:
            spec['sparkleAt'] = round(t_start + 0.15, 2)
        if p_place == 'hinged':
            spec['loc'] = [0.0, 2.6, 0.0]
            if open_t is not None:
                spec['openAt'] = open_t
        elif p_place == 'pedestal':
            spec['pedestal'] = holder
        elif p_place == 'floor':
            spec['loc'] = [0.0, -0.4, 0.0]
        else:
            spec['hold'] = holder
        return spec

    # 7-beat Craftee-style vertical Reel structure (Hook -> Setup -> Escalation -> Twist -> Climax -> Punchline)
    b = round(dur / 7.0, 2)
    t = [round(i * b, 2) for i in range(7)] + [round(dur, 2)]

    shots = [
        # Beat 1: Hook (Wide/MLS establishing entry with clear head-to-toe framing)
        {
            't0': t[0], 't1': t[1],
            'text': f'{hero} had a plan that nobody expected.',
            'set': setting, 'cam': 'mls', 'subject': hero, 'mood': 'sunny', 'move': 'creep',
            'actors': [
                {'who': hero, 'at': [-3.6, -0.3], 'walkTo': [-1.4, -0.3], 'anim': 'walk', 'face': 'scheming', 'yaw': 85},
                {'who': friend, 'at': [1.6, -0.2], 'anim': 'wave', 'face': 'smile', 'yaw': -45},
            ],
            'props': [make_prop_spec(hero, t[0], t[1], sparkle=True)],
        },
        # Beat 2: Setup (Two-shot dialogue introducing the core object)
        {
            't0': t[1], 't1': t[2],
            'text': f'Look what I found, {friend}!',
            'set': setting, 'cam': 'two', 'subject': hero, 'mood': 'sunny', 'move': 'creep',
            'actors': [
                {'who': hero, 'at': [-1.4, -0.3], 'anim': 'talk', 'face': 'grin', 'talk': [0.0, b * 0.9], 'yaw': 55},
                {'who': friend, 'at': [1.6, -0.2], 'anim': 'idle', 'face': 'smile', 'yaw': -55,
                 'faceAt': [[b * 0.45, 'shock']], 'animAt': [[b * 0.45, 'nod']]},
            ],
            'props': [make_prop_spec(hero, t[1], t[2], sparkle=True)],
        },
        # Beat 3: Rising Action (Rival/Authority enters and notices)
        {
            't0': t[2], 't1': t[3],
            'text': f'Wait a second... what is going on here?',
            'set': setting, 'cam': 'ms', 'subject': third_name, 'mood': 'sunny', 'move': 'push',
            'actors': [
                {'who': third_name, 'at': [3.8, 0.2], 'walkTo': [1.8, 0.1], 'anim': 'walk',
                 'face': 'angry' if third_arch == 'rival' else 'think', 'yaw': -85,
                 'animAt': [[b * 0.6, 'cross_arms']]},
                {'who': hero, 'at': [-1.5, -0.3], 'anim': 'idle', 'face': 'worried', 'yaw': 65},
            ],
            'props': [make_prop_spec(hero, t[2], t[3])],
        },
        # Beat 4: Escalation / Confrontation
        {
            't0': t[3], 't1': t[4],
            'text': 'Hand it over right now!',
            'set': setting, 'cam': 'two', 'subject': third_name, 'mood': 'overcast',
            'actors': [
                {'who': hero, 'at': [-1.5, -0.3], 'anim': 'scared', 'face': 'scared', 'yaw': 65,
                 'animAt': [[b * 0.5, 'surrender']]},
                {'who': third_name, 'at': [1.8, 0.1], 'anim': 'point', 'face': 'scheming', 'talk': [0.0, b * 0.85], 'yaw': -70},
            ],
            'props': [make_prop_spec(hero, t[3], t[4], open_t=round(b * 0.4, 2))],
        },
        # Beat 5: Dramatic Close-Up Reaction
        {
            't0': t[4], 't1': t[5],
            'text': 'No way... not today!',
            'set': setting, 'cam': 'cu', 'subject': hero, 'mood': 'storm', 'move': 'creep', 'aimUp': True,
            'actors': [
                {'who': hero, 'at': [-1.5, -0.3], 'anim': 'think', 'face': 'wince', 'yaw': 25,
                 'faceAt': [[b * 0.45, 'scheming']], 'animAt': [[b * 0.45, 'grab']], 'fx': ['storm@0.1']},
            ],
            'props': [make_prop_spec(hero, t[4], t[5], sparkle=True)],
        },
        # Beat 6: Twist / Climax Impact
        {
            't0': t[5], 't1': t[6],
            'text': 'BOOM! That completely backfired!',
            'set': setting, 'cam': 'ws', 'subject': third_name, 'mood': 'sunny', 'flash': True, 'impact': 0.25,
            'actors': [
                {'who': hero, 'at': [-1.6, -0.3], 'anim': 'laugh', 'face': 'laugh', 'yaw': 45},
                {'who': friend, 'at': [-0.2, 1.3], 'anim': 'cheer', 'face': 'grin', 'yaw': 20},
                {'who': third_name, 'at': [1.8, 0.1], 'anim': 'shock', 'face': 'shock', 'yaw': -60,
                 'faceAt': [[b * 0.4, 'cry']], 'animAt': [[b * 0.4, 'facepalm']], 'fx': ['bolt@0.2', 'smoke@0.25']},
            ],
            'props': [make_prop_spec(third_name, t[5], t[6], sparkle=True, open_t=0.15)],
        },
        # Beat 7: Punchline Outro
        {
            't0': t[6], 't1': t[7],
            'text': 'Moral of the story: never underestimate the quiet kid.',
            'set': setting, 'cam': 'ms', 'subject': hero, 'mood': 'sunny', 'move': 'creep',
            'actors': [
                {'who': hero, 'at': [-1.3, -0.3], 'anim': 'talk', 'face': 'smug', 'talk': [0.0, b * 0.9], 'yaw': 15},
                {'who': friend, 'at': [1.3, -0.2], 'anim': 'clap', 'face': 'smile', 'yaw': -25},
            ],
            'props': [make_prop_spec(hero, t[6], t[7], sparkle=True)],
        },
    ]

    return {
        'dur': round(dur, 2),
        'voice': voice,
        'keys': [p_id, hero.lower(), 'twist'],
        'music': [[0.0, 'playful'], [round(t[3] / dur, 2), 'suspense'], [round(t[5] / dur, 2), 'playful']],
        'cast': cast,
        'shots': shots,
    }


def _try_llm_story(prompt, dur, voice):
    """Optional Stage 1+2 LLM director when OPENAI_API_KEY is configured."""
    api_key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not api_key:
        return None
    sys_prompt = (
        "You are a 3D Roblox Reels director (@craftee_films style). Return ONLY valid JSON for timed.json "
        f"with keys: dur ({dur}), voice ('{voice}'), keys (list), music (list), cast (dict of 2-4 characters using "
        "hair in ['pompadour','long','spiky','curly','cap','pigtails','bun','grey_old','short','bald']), and shots "
        "(list of 6-9 shots with t0, t1, text, set in ['Street','Classroom','Bedroom','LivingRoom','Kitchen','Park','Gym'], "
        "cam in ['mls','ws','two','ms','cu','mcu'], subject, mood, actors, props). Keep actor x coordinates >= 2.3 studs apart."
    )
    payload = json.dumps({
        'model': os.environ.get('BLOX_DIRECTOR_MODEL', 'gpt-4o-mini'),
        'response_format': {'type': 'json_object'},
        'messages': [
            {'role': 'system', 'content': sys_prompt},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0.7,
    }).encode('utf-8')
    req = urllib.request.Request(
        'https://api.openai.com/v1/chat/completions',
        data=payload,
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return json.loads(data['choices'][0]['message']['content'])
    except Exception as exc:
        print(f'[story_director] LLM fallback to procedural director ({exc})')
        return None


# ---------------------------------------------------------------- Stage 3: Quality Gate & Auto-Repair
def validate_and_repair(episode):
    """Audit and auto-repair timing, character specs, animations, expressions, spacing, and props."""
    catalog = _load_catalog()
    cast = episode.get('cast') or {'Sam': dict(ARCHETYPES['hero'])}
    episode['cast'] = cast

    for nm, cspec in cast.items():
        cspec.setdefault('skin', [0.96, 0.78, 0.62])
        cspec.setdefault('shirt', [0.16, 0.48, 0.94])
        cspec.setdefault('pants', [0.15, 0.20, 0.34])
        cspec.setdefault('shoes', [0.94, 0.94, 0.96])
        cspec.setdefault('hair', 'pompadour')
        cspec.setdefault('hair_color', [0.22, 0.13, 0.08])
        cspec.setdefault('height', 1.0)

    shots = episode.get('shots', [])
    cursor = 0.0
    for idx, s in enumerate(shots):
        dur_s = max(1.2, float(s.get('t1', cursor + 2.5)) - float(s.get('t0', cursor)))
        s['t0'] = round(cursor, 2)
        s['t1'] = round(cursor + dur_s, 2)
        cursor = s['t1']

        if s.get('set') not in VALID_SETS:
            s['set'] = 'Street'
        if s.get('cam') not in VALID_CAMS:
            s['cam'] = 'mls' if idx == 0 else 'ms'

        actors = s.get('actors', [])
        if not actors:
            first_actor = next(iter(cast))
            actors = [{'who': first_actor, 'at': [0.0, -0.3], 'anim': 'idle', 'face': 'smile', 'yaw': 0}]
            s['actors'] = actors

        # Clamp animations/expressions & enforce >= 2.3-stud horizontal separation
        for a in actors:
            if a.get('who') not in cast:
                a['who'] = next(iter(cast))
            if a.get('anim', 'idle') not in VALID_ANIMS:
                a['anim'] = 'idle'
            if a.get('face', 'neutral') not in VALID_EXPRS:
                a['face'] = 'neutral'
            a['animAt'] = [[t, an if an in VALID_ANIMS else 'idle'] for t, an in (a.get('animAt') or [])]
            a['faceAt'] = [[t, ex if ex in VALID_EXPRS else 'neutral'] for t, ex in (a.get('faceAt') or [])]
            a.setdefault('at', [0.0, -0.3])

        for i in range(len(actors)):
            for j in range(i + 1, len(actors)):
                p1 = actors[i]['at']
                p2 = actors[j]['at']
                dx = p2[0] - p1[0]
                dy = p2[1] - p1[1]
                dist = math.hypot(dx, dy)
                if dist < 2.3:
                    shift = (2.3 - dist) * 0.55
                    if dx >= 0:
                        actors[i]['at'][0] = round(p1[0] - shift, 2)
                        actors[j]['at'][0] = round(p2[0] + shift, 2)
                    else:
                        actors[i]['at'][0] = round(p1[0] + shift, 2)
                        actors[j]['at'][0] = round(p2[0] - shift, 2)

        # Normalize prop references against catalog
        repaired_props = []
        for p in s.get('props', []):
            noun = p.get('type') or p.get('asset') or p.get('noun') or p.get('name', 'box')
            resolved = catalog.get('tag_index', {}).get(str(noun).lower(), None)
            if resolved:
                p['type'] = resolved
            repaired_props.append(p)
        if repaired_props:
            s['props'] = repaired_props

    episode['dur'] = round(cursor, 2)
    return episode


def generate_episode(prompt, dur=18.0, voice='am_michael'):
    ep = _try_llm_story(prompt, dur, voice) or _build_procedural_episode(prompt, dur=dur, voice=voice)
    return validate_and_repair(ep)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='3-Stage AI Story Director for Blox Studio')
    ap.add_argument('--prompt', required=True, help='One-line story premise or script idea')
    ap.add_argument('--out', required=True, help='Output path for timed.json')
    ap.add_argument('--dur', type=float, default=18.0, help='Target episode duration in seconds')
    ap.add_argument('--voice', default='am_michael', help='TTS narrator/character voice ID')
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    episode = generate_episode(args.prompt, dur=args.dur, voice=args.voice)
    out_path.write_text(json.dumps(episode, indent=2), encoding='utf-8')
    print(f"[story_director] Wrote {out_path} ({len(episode['shots'])} shots, {episode['dur']}s)")
