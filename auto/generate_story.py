import glob
import json
import math
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VAULT_DIR = os.environ.get("REFERENCE_VAULT_DIR", os.path.join(ROOT_DIR, "reference-vault", "vault"))
BLUEPRINT_DIR = os.path.join(VAULT_DIR, "blueprints")
CORPUS_PATH = os.path.join(VAULT_DIR, "master_script_corpus.json")
VISUAL_BIBLE_PATH = os.path.join(VAULT_DIR, "visual_bible.json")

MODELS = [
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-4-hydrogen",
    "gemini-4-argon",
    "gemini-2.5-flash",
    "gemma-4-31b-it",
]

RICH_SETS = [
    "MusicRow", "TownPool", "Gym", "Street", "Park",
    "Store", "Classroom", "Office", "LivingRoom", "Kitchen", "Bedroom", "Backyard", "Playground",
]

DEFAULT_CAST_UNIVERSE = {
    "Leo": {"height": 1.0, "gender": "male", "role": "main_character", "skin": "#f5c29b", "hair": "spiky", "hair_color": "#261b14", "shirt": "#1e73f2", "pants": "#1b2234", "shoes": "#f2f4f8", "extras": []},
    "Maya": {"height": 0.93, "gender": "female", "role": "sister_or_best_friend", "skin": "#f7c7a3", "hair": "pigtails", "hair_color": "#3b2316", "shirt": "#ff4f8b", "pants": "#2a2d43", "shoes": "#ffffff", "extras": ["skirt"]},
    "Jake": {"height": 1.03, "gender": "male", "role": "rival_or_friend", "skin": "#e8b087", "hair": "short", "hair_color": "#1e1612", "shirt": "#e67e22", "pants": "#1d2432", "shoes": "#22262e", "extras": []},
    "Max": {"height": 1.05, "gender": "male", "role": "brother", "skin": "#e8b087", "hair": "curly", "hair_color": "#1e1612", "shirt": "#22b855", "pants": "#1d2432", "shoes": "#f2f4f8", "extras": ["cap"]},
    "Mom": {"height": 1.02, "gender": "female", "role": "mother", "skin": "#f5c29b", "hair": "bun", "hair_color": "#4a2c18", "shirt": "#9b51e0", "pants": "#25293a", "shoes": "#d8c3a5", "extras": ["cardigan"]},
    "Dad": {"height": 1.08, "gender": "male", "role": "father", "skin": "#eab38a", "hair": "short", "hair_color": "#2d221c", "shirt": "#2f80ed", "pants": "#1f2533", "shoes": "#3a2c22", "extras": ["tie"]},
    "Uncle_Sam": {"height": 1.06, "gender": "male", "role": "uncle", "skin": "#e2a77d", "hair": "short", "hair_color": "#5c5856", "shirt": "#f2994a", "pants": "#2c3342", "shoes": "#4a3728", "extras": ["glasses"]},
    "Ms_Clara": {"height": 1.02, "gender": "female", "role": "teacher", "skin": "#f6c9a6", "hair": "long", "hair_color": "#3d2516", "shirt": "#27ae60", "pants": "#1e2430", "shoes": "#2b2d42", "extras": ["glasses", "cardigan"]},
    "Zoe": {"height": 0.96, "gender": "female", "role": "best_friend_female", "skin": "#c68658", "hair": "long", "hair_color": "#191412", "shirt": "#f2c94c", "pants": "#232938", "shoes": "#ffffff", "extras": ["skirt"]},
    "Sam": {"height": 1.0, "gender": "male", "role": "best_friend_male", "skin": "#8d5524", "hair": "curly", "hair_color": "#141110", "shirt": "#eb5757", "pants": "#1c2230", "shoes": "#eeeeee", "extras": []},
}

BACKGROUND_CROWD_NPCS = {
    "Townie_1": {"height": 1.0, "gender": "male", "skin": "#f2be96", "hair": "short", "hair_color": "#2b1d14", "shirt": "#00a8ff", "pants": "#2f3640", "shoes": "#ffffff"},
    "Townie_2": {"height": 0.96, "gender": "female", "skin": "#d99b6c", "hair": "long", "hair_color": "#3d2314", "shirt": "#fbc531", "pants": "#192a56", "shoes": "#ffffff", "extras": ["skirt"]},
    "Townie_3": {"height": 1.03, "gender": "male", "skin": "#f5c7a3", "hair": "curly", "hair_color": "#1e272e", "shirt": "#4cd137", "pants": "#2f3640", "shoes": "#dddddd"},
}

VALID_CAMS = {"ecu", "cu", "mcu", "ms", "mls", "ws", "low", "high", "ots", "two", "ews", "ground", "pov", "ins"}
VALID_MOVES = {"crash_in", "push", "reveal_push", "creep", "drift", "lock"}
VALID_MOODS = {"sunny", "sunset", "storm", "night"}
VALID_ANIMS = {
    "idle", "talk", "walk", "run", "nod", "headshake", "flinch",
    "slump", "jump_joy", "shock", "surrender", "what", "facepalm", "clap",
    "point", "hold_hands", "hold_hands_L", "hold_hands_R", "wave", "cheer",
    "shrug", "scared", "eat", "cross_arms", "think", "sad", "angry", "sit",
}
VALID_FACES = {
    "neutral", "smile", "grin", "laugh", "angry", "scared", "worried",
    "think", "shock", "smug", "sad", "cry", "blush", "embarrassed",
}
FACE_ALIASES = {
    "happy": "smile", "joy": "grin", "excited": "grin", "fear": "scared",
    "terrified": "scared", "surprised": "shock", "amazed": "shock",
    "mad": "angry", "furious": "angry", "upset": "sad",
    "crying": "cry", "tears": "cry", "weeping": "cry", "sobbing": "cry",
    "blushing": "blush", "shy": "blush", "flustered": "blush",
    "confused": "think", "nervous": "worried",
}


def hex_to_rgb01(val, fallback=(0.5, 0.5, 0.5)) -> list[float]:
    """Convert '#rrggbb' or 3-tuple/list into linear-ready 0..1 RGB floats for Blender."""
    if isinstance(val, (list, tuple)) and len(val) >= 3:
        return [round(float(val[0]), 4), round(float(val[1]), 4), round(float(val[2]), 4)]
    s = str(val or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) >= 6:
        try:
            r = int(s[0:2], 16) / 255.0
            g = int(s[2:4], 16) / 255.0
            b = int(s[4:6], 16) / 255.0
            return [round(r, 4), round(g, 4), round(b, 4)]
        except ValueError:
            pass
    return list(fallback)


def sanitize_face(val) -> str:
    raw = str(val or "neutral").lower().strip()
    mapped = FACE_ALIASES.get(raw, raw)
    return mapped if mapped in VALID_FACES else "neutral"


def extract_json_safely(raw_text: str) -> dict:
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def load_training_context() -> tuple[dict, str, dict]:
    blueprints = sorted(glob.glob(os.path.join(BLUEPRINT_DIR, "*.json")))
    bp = json.load(open(random.choice(blueprints), encoding="utf-8")) if blueprints else {}

    visual_bible = {}
    if os.path.exists(VISUAL_BIBLE_PATH):
        try:
            visual_bible = json.load(open(VISUAL_BIBLE_PATH, encoding="utf-8"))
        except Exception as e:
            print(f"[Vault WARN] Could not parse visual_bible.json: {e}", flush=True)

    corpus_block = ""
    if os.path.exists(CORPUS_PATH):
        corpus = json.load(open(CORPUS_PATH, encoding="utf-8"))
        scripts = corpus.get("scripts", [])
        hooks = corpus.get("all_hooks", [])
        sample_scripts = random.sample(scripts, min(6, len(scripts))) if scripts else []
        sample_hooks = random.sample(hooks, min(12, len(hooks))) if hooks else []
        corpus_block = (
            f"HARVESTED @craftee_films VAULT STATS ({corpus.get('total_scripts_collected', 0)} real scripts, "
            f"avg {corpus.get('avg_words_per_sec', 4.75)} words/sec):\n"
            f"PROVEN OPENING HOOKS:\n"
            + "\n".join(f"- {h}" for h in sample_hooks)
            + "\n\nEXAMPLE SCRIPTS:\n"
            + "\n---\n".join(f"[{s['id']}]: {s['full_script'][:550]}" for s in sample_scripts)
        )
    return bp, corpus_block, visual_bible


def call_gemini_json_defensive(api_key: str, prompt: str, stage_label: str = "Stage") -> dict:
    last_err = None
    for model in MODELS:
        gen_cfg = {"temperature": 0.72}
        if not model.startswith("gemma-"):
            gen_cfg["responseMimeType"] = "application/json"

        body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen_cfg}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        for attempt in range(2):
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=110) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                txt = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = extract_json_safely(txt)
                parsed["_model_used"] = model
                print(f"[{stage_label}] Completed via {model}", flush=True)
                return parsed
            except urllib.error.HTTPError as e:
                last_err = f"{model} HTTP {e.code}"
                if e.code == 429 and attempt == 0:
                    print(f"[RateLimit] {model} hit 429 on {stage_label}; waiting 6s...", flush=True)
                    time.sleep(6)
                    continue
                break
            except Exception as e:
                last_err = f"{model} {e}"
                break

    raise RuntimeError(f"{stage_label} failed across all models ({last_err})")


def apply_wardrobe_and_gender_locks(cast: dict, story_bible: dict) -> dict:
    """Enforces distinct male/female hair & silhouettes, school uniform locks, and RGB 0..1 tuples."""
    uniform_rule = story_bible.get("wardrobe_lock") or {}
    is_school_uniform = bool(uniform_rule.get("is_school_uniform", False))
    u_shirt = uniform_rule.get("shirt_hex", "#f2f4f8")
    u_pants = uniform_rule.get("pants_hex", "#1e2a44")
    u_tie = uniform_rule.get("tie_hex", "#b8293d")

    student_roles = {
        "main_character", "sister", "brother", "sister_or_best_friend",
        "rival_or_friend", "best_friend_female", "best_friend_male", "student",
    }

    for name, spec in cast.items():
        if not isinstance(spec, dict):
            continue
        gender = str(spec.get("gender", "")).lower()
        extras = list(spec.get("extras") or [])

        # Clear visual gender differentiation (hair + height + outfit silhouette)
        if gender == "female" or name in ("Maya", "Zoe", "Mom", "Ms_Clara", "Townie_2"):
            spec["gender"] = "female"
            spec["height"] = min(float(spec.get("height", 0.94)), 0.96) if name not in ("Mom", "Ms_Clara") else 1.01
            if spec.get("hair") in (None, "short", "spiky"):
                spec["hair"] = "pigtails" if name == "Maya" else "long"
            if "skirt" not in extras and name not in ("Mom", "Ms_Clara"):
                extras.append("skirt")
        else:
            spec["gender"] = "male"
            spec["height"] = max(float(spec.get("height", 1.02)), 1.0)
            if spec.get("hair") in (None, "pigtails", "bun"):
                spec["hair"] = "spiky" if name == "Leo" else "short"

        # Lock school uniform across ALL students if story takes place at school
        role = str(spec.get("role", "")).lower()
        if is_school_uniform and (role in student_roles or name in ("Leo", "Maya", "Jake", "Max", "Zoe", "Sam", "Townie_1", "Townie_2", "Townie_3")):
            spec["shirt"] = u_shirt
            spec["pants"] = u_pants
            spec["tie_color"] = u_tie
            if "tie" not in extras:
                extras.append("tie")

        # Normalize colors to 0..1 RGB lists so compile.py & chars.py render exact shades
        spec["skin"] = hex_to_rgb01(spec.get("skin"), (0.96, 0.76, 0.61))
        spec["shirt"] = hex_to_rgb01(spec.get("shirt"), (0.12, 0.45, 0.95))
        spec["pants"] = hex_to_rgb01(spec.get("pants"), (0.11, 0.14, 0.21))
        spec["shoes"] = hex_to_rgb01(spec.get("shoes"), (0.93, 0.94, 0.96))
        spec["hair_color"] = hex_to_rgb01(spec.get("hair_color"), (0.16, 0.11, 0.08))
        if "tie_color" in spec:
            spec["tie_color"] = hex_to_rgb01(spec.get("tie_color"), (0.72, 0.16, 0.24))

        spec["hair_style"] = spec.get("hair", "short")
        spec["extras"] = list(dict.fromkeys(extras))
    return cast


def enforce_speaker_focus_and_continuity(shots: list[dict], cast: dict) -> list[dict]:
    """
    1. Isolates the active speaker (`subject`) in close/medium shots so the camera cuts/rotates cleanly to the speaker.
    2. Alternates camera side (-1 / +1) on cuts for smooth 3D spatial camera flow.
    3. Chains character positions & `walkTo` trajectories continuously from shot N to shot N+1.
    """
    last_known_pos: dict[str, list[float]] = {}
    last_known_yaw: dict[str, float] = {}
    last_set: str | None = None

    for idx, sh in enumerate(shots):
        cur_set = sh.get("set", "LivingRoom")
        if cur_set != last_set:
            last_known_pos.clear()
            last_known_yaw.clear()
            last_set = cur_set

        speaker = sh.get("subject", "Leo")
        cam = sh.get("cam", "mcu")
        dur = max(1.0, float(sh.get("t1", 1.35)) - float(sh.get("t0", 0.0)))
        actors = sh.get("actors") or []

        # Alternate camera angle side so cuts flow dynamically around the speaker
        sh["side"] = 1 if idx % 2 == 0 else -1

        if not any(a.get("who") == speaker for a in actors):
            actors.insert(0, {"who": speaker, "at": [0.0, 0.0], "yaw": 0.0, "anim": "talk", "face": "neutral", "talk": [0.0, round(dur, 2)]})

        speaker_actor = next(a for a in actors if a.get("who") == speaker)
        other_actors = [a for a in actors if a.get("who") != speaker]

        if cam in ("cu", "ecu", "mcu", "low", "high"):
            kept_actors = [speaker_actor]
            speaker_actor["at"] = last_known_pos.get(speaker, [0.0, 0.0])
            speaker_actor["yaw"] = 14.0 if idx % 2 == 0 else -14.0
            speaker_actor["talk"] = [0.0, round(dur, 2)]
        else:
            kept_actors = [speaker_actor] + other_actors[:2]
            sp_x = -1.6 if idx % 2 == 0 else 1.6
            speaker_actor["at"] = [sp_x, 0.0]
            speaker_actor["yaw"] = 24.0 if sp_x < 0 else -24.0
            speaker_actor["talk"] = [0.0, round(dur, 2)]

            for o_idx, oa in enumerate(other_actors[:2]):
                side_sign = 1.0 if sp_x < 0 else -1.0
                ox = round(side_sign * (3.4 + o_idx * 1.4), 2)
                oy = round(0.7 + o_idx * 1.5, 2)
                oa["at"] = [ox, oy]
                oa["yaw"] = round(-side_sign * 48.0, 1)
                oa.pop("talk", None)

        # Chain walk / run movement speed accurately across shots using `walkTo` (read by compile.py)
        for act in kept_actors:
            who = act.get("who", speaker)
            anim = act.get("anim", "idle")
            h = float((cast.get(who) or {}).get("height", 1.0))
            if anim in ("walk", "run"):
                speed = (4.0 if anim == "run" else 2.6) * h
                dist = round(min(4.5, speed * dur * 0.65), 2)
                start_pt = list(act.get("at", [0.0, 0.0]))
                rad = math.radians(float(act.get("yaw", 0.0)))
                end_pt = [
                    round(max(-6.0, min(6.0, start_pt[0] + math.sin(rad) * dist)), 2),
                    round(max(-3.0, min(5.0, start_pt[1] - math.cos(rad) * dist)), 2),
                ]
                act["walkTo"] = end_pt
                last_known_pos[who] = end_pt
            else:
                act.pop("walkTo", None)
                last_known_pos[who] = list(act.get("at", [0.0, 0.0]))
            last_known_yaw[who] = float(act.get("yaw", 0.0))

        sh["actors"] = kept_actors

    return shots


def run_gemini_director_pipeline(api_key: str, theme: str, bp: dict, corpus_block: str, visual_bible: dict) -> dict:
    cast_universe = visual_bible.get("canonical_cast_universe") or DEFAULT_CAST_UNIVERSE

    # =========================================================================
    # STAGE 1: Gemini Script & Continuity Breakdown (Story Bible, Locks, Sets)
    # =========================================================================
    stage1_prompt = f"""You are the Head Showrunner & Continuity Supervisor for a 3D Roblox Reels studio.
{corpus_block}

USER THEME / IDEA:
"{theme or 'A dramatic, emotional, fast-paced story starring Leo, Maya, and Jake with a hidden secret inside a bedroom closet and a school twist.'}"

AVAILABLE CANONICAL CHARACTERS (keep their names, genders, hair & personalities locked!):
{json.dumps(cast_universe, indent=2)}

TASK — STAGE 1 (SCRIPT & CONTINUITY BIBLE):
1. Write a tight 24-to-28-beat spoken script (max 8 words per beat) with a viral 3-second hook, rising tension, emotional climax (crying/blushing/shock), and twist ending.
2. Extract EVERY prop, room, closet, door, pencil, letter, or object mentioned ANYWHERE in the script so it can be placed in the 3D set from Shot 1!
3. Decide wardrobe locks: if ANY beat happens at school/classroom, set `"is_school_uniform": true` with exact `shirt_hex`, `pants_hex`, `tie_hex` so EVERY student wears the exact same school uniform in every shot.
4. Interlink the first beat and final beat visually and narratively so the ending loops or resolves cleanly.

Return ONLY valid JSON:
{{
  "title": "Viral title",
  "caption": "Caption with 5 hashtags",
  "keys": ["6", "IMPACT", "WORDS", "IN", "CAPS", "HERE"],
  "wardrobe_lock": {{
    "is_school_uniform": false,
    "shirt_hex": "#f2f4f8",
    "pants_hex": "#1e2a44",
    "tie_hex": "#b8293d"
  }},
  "required_sets": ["Bedroom", "Classroom"],
  "required_custom_props": [
    {{"name": "WoodenCloset", "set": "Bedroom", "at": [2.8, 3.6, 0], "description": "Tall brown double-door bedroom closet with brass handles, visible from Shot 1"}}
  ],
  "active_cast": ["Leo", "Maya", "Jake"],
  "beats": [
    {{
      "beat": 1,
      "set": "Bedroom",
      "speaker": "Maya",
      "line": "Jake swore nobody knew what was inside my closet!",
      "emotion": "worried",
      "action": "talk",
      "camera_goal": "Medium close-up on Maya speaking while the WoodenCloset is visible behind her"
    }}
  ]
}}"""

    bible = call_gemini_json_defensive(api_key, stage1_prompt, stage_label="Stage1-Bible")

    # =========================================================================
    # STAGE 2: Gemini Custom 3D Asset & Rich Room Builder (`things` + `places`)
    # =========================================================================
    stage2_prompt = f"""You are the 3D Roblox Environment & Prop Modeler for Blender.
Based on this Story Bible, build rich, fully furnished 3D rooms (`places`) and every custom 3D prop (`things`) so NO room ever looks empty or plain!

STORY BIBLE:
{json.dumps(bible, indent=2)}

RULES FOR 3D MODELING IN `things` AND `places`:
1. Every item in `required_custom_props` MUST be built in `things` using blocky Roblox primitives:
  - `["block", "#hex", [width_x, depth_y, height_z], [x, y, z], {{"metal": false, "glow": 0.0}}]`
  - `["tube", "#hex", radius, height, [x, y, z]]`
  - `["cone", "#hex", radius, height, [x, y, z]]`
  - `["ball", "#hex", radius, [x, y, z]]`
2. Every set in `required_sets` MUST be defined in `places` with rich furniture density (at least 6–10 props per room).
3. Keep the center stage (`x` between `-2.5` and `+2.5`, `y` between `-1.5` and `+2.2`) clear for characters to walk and act.

Return ONLY valid JSON:
{{
  "things": {{
    "WoodenCloset": [
      ["block", "#7a4b2a", [2.2, 1.1, 3.6], [0, 0, 1.8]],
      ["block", "#5c361c", [0.06, 1.14, 3.5], [0, 0, 1.8]],
      ["ball", "#e6b830", 0.09, [-0.18, -0.58, 1.75], {{"metal": true}}],
      ["ball", "#e6b830", 0.09, [0.18, -0.58, 1.75], {{"metal": true}}]
    ]
  }},
  "places": {{
    "Bedroom": {{
      "kind": "indoor",
      "wall": "#e8dfd1",
      "lower": "#c9b99f",
      "floor": "wood",
      "floor_color": "#8c5e35",
      "props": [
        ["WoodenCloset", 2.8, 3.8, 0, {{"name": "WoodenCloset"}}],
        ["bed", -3.4, 3.2, 90],
        ["desk", -3.6, -0.8, 90],
        ["office_chair", -2.7, -0.8, -90],
        ["rug", 0.0, 0.5, 0],
        ["floor_lamp", 4.2, 3.6, 0],
        ["poster", -1.2, 4.3, 0],
        ["plant", 4.1, -1.5, 0]
      ]
    }}
  }}
}}"""

    assets = call_gemini_json_defensive(api_key, stage2_prompt, stage_label="Stage2-Assets")

    # =========================================================================
    # STAGE 3: Gemini Master Choreography, Camera Cuts & Emotion Timeline
    # =========================================================================
    stage3_prompt = f"""You are the Lead Animator & Cinematographer for this Roblox Reel.
Combine the Story Bible and 3D Sets into the final shot-by-shot `shots` timeline.

STORY BIBLE:
{json.dumps(bible, indent=2)}

3D ASSETS BUILT:
{json.dumps(list((assets.get("things") or {}).keys()))}

STRICT CINEMATOGRAPHY & EMOTION RULES:
1. **SPEAKER CAMERA LOCK**: Whoever is speaking (`subject`) in that beat MUST be the focus of the camera! Use `"mcu"`, `"cu"`, or `"ots"` when one person is speaking.
2. **DYNAMIC CAMERA VARIETY**: Alternate camera angles every shot (`mcu` -> `cu` -> `ins` -> `two` -> `low` -> `ots` -> `ws`) and moves (`crash_in`, `push`, `reveal_push`, `creep`, `drift`). Use `"cam": "ins", "focus": "<CustomPropName>"` whenever a key prop is revealed!
3. **FULL EMOTIONAL RANGE**: Use `"cry"`, `"blush"`, `"shock"`, `"angry"`, `"scared"`, `"worried"`, `"laugh"`, `"smug"`, `"sad"`, `"smile"`.
4. **ALLOWED ANIMS**: {json.dumps(sorted(VALID_ANIMS))}.
5. **ALLOWED FACES**: {json.dumps(sorted(VALID_FACES))}.

Return ONLY valid JSON:
{{
  "music": [[0, "playful"], [0.4, "suspense"], [0.75, "hit"], [0.85, "triumph"]],
  "shots": [
    {{
      "set": "Bedroom",
      "mood": "sunny",
      "cam": "mcu",
      "move": "push",
      "subject": "Maya",
      "text": "Jake swore nobody knew what was inside my closet!",
      "sfx": ["whoosh@0.0"],
      "actors": [
        {{"who": "Maya", "at": [0.0, 0.0], "yaw": -12, "anim": "talk", "face": "worried", "talk": [0.0, 1.3]}}
      ]
    }}
  ]
}}"""

    choreography = call_gemini_json_defensive(api_key, stage3_prompt, stage_label="Stage3-Choreography")

    cast_out = {}
    active_names = set(bible.get("active_cast") or []) | {"Leo", "Maya", "Jake"}
    for cname in active_names:
        if cname in cast_universe:
            cast_out[cname] = dict(cast_universe[cname])
        else:
            is_fem = any(w in cname.lower() for w in ("maya", "zoe", "clara", "mom", "girl", "sister", "queen", "miss", "ms"))
            cast_out[cname] = {
                "height": 0.94 if is_fem else 1.03,
                "gender": "female" if is_fem else "male",
                "role": "supporting",
                "skin": "#f5c29b",
                "hair": "long" if is_fem else "short",
                "hair_color": "#2b1d14",
                "shirt": "#e84393" if is_fem else "#0984e3",
                "pants": "#2d3436",
                "shoes": "#ffffff",
                "extras": ["skirt"] if is_fem else [],
            }

    for tname, tdata in BACKGROUND_CROWD_NPCS.items():
        cast_out[tname] = dict(tdata)
    cast_out = apply_wardrobe_and_gender_locks(cast_out, bible)

    return {
        "title": bible.get("title", "The Secret Inside Maya's Closet!"),
        "caption": bible.get("caption", "Wait until you see what Jake hid inside! #roblox #storytime #shorts #reels #fyp"),
        "keys": bible.get("keys", ["SECRET", "CLOSET", "JAKE", "MAYA", "SHOCKED", "TRUTH"]),
        "music": choreography.get("music", [[0, "playful"], [0.45, "suspense"], [0.75, "hit"], [0.85, "triumph"]]),
        "things": assets.get("things") or {},
        "places": assets.get("places") or {},
        "cast": cast_out,
        "shots": choreography.get("shots") or [],
        "model_used": choreography.get("_model_used", "gemini-director"),
    }


def build_offline_fast_story(cast_universe: dict) -> dict:
    beats = [
        ("Bedroom", "sunny", "mcu", "crash_in", "Maya", "Jake swore nobody knew what was in my closet!", "talk", "worried", ["whoosh@0.0"], None),
        ("Bedroom", "sunny", "ins", "push", "Maya", "Then I saw the wooden closet door shaking!", "shock", "shock", ["ding@0.1"], "WoodenCloset"),
        ("Bedroom", "sunny", "cu", "push", "Jake", "Jake turned bright red and tried to block me!", "surrender", "blush", ["pop@0.0"], None),
        ("Bedroom", "sunny", "cu", "crash_in", "Maya", "Tears rolled down my face when I opened it!", "sad", "cry", ["boom@0.0"], None),
        ("Bedroom", "sunny", "two", "reveal_push", "Jake", "He had built a giant surprise birthday trophy!", "jump_joy", "smile", ["cash@0.0"], None),
    ]
    shots = []
    for st, md, cm, mv, subj, txt, anim, face, sfx, focus_thing in beats:
        sh = {
            "set": st, "mood": md, "cam": cm, "move": mv, "subject": subj, "text": txt, "sfx": sfx,
            "actors": [{"who": subj, "at": [0.0, 0.0], "yaw": 12, "anim": anim, "face": face, "talk": [0.0, 1.3]}],
        }
        if focus_thing:
            sh["focus"] = focus_thing
        shots.append(sh)

    raw_cast = {k: dict(v) for k, v in cast_universe.items()}
    raw_cast.update({k: dict(v) for k, v in BACKGROUND_CROWD_NPCS.items()})
    cast_out = apply_wardrobe_and_gender_locks(raw_cast, {})

    return {
        "title": "What Jake Hid Inside Maya's Closet!",
        "caption": "She cried when she opened the door! #roblox #storytime #shorts #reels #fyp",
        "keys": ["CLOSET", "JAKE", "MAYA", "BLUSHED", "TEARS", "SURPRISE"],
        "music": [[0, "playful"], [0.4, "suspense"], [0.75, "hit"], [0.85, "triumph"]],
        "things": {
            "WoodenCloset": [
                ["block", "#7a4b2a", [2.2, 1.1, 3.6], [0, 0, 1.8]],
                ["ball", "#e6b830", 0.09, [-0.18, -0.58, 1.75], {"metal": True}],
                ["ball", "#e6b830", 0.09, [0.18, -0.58, 1.75], {"metal": True}],
            ]
        },
        "places": {
            "Bedroom": {
                "kind": "indoor",
                "wall": "#e8dfd1",
                "lower": "#c9b99f",
                "floor": "wood",
                "floor_color": "#8c5e35",
                "props": [
                    ["WoodenCloset", 2.8, 3.8, 0, {"name": "WoodenCloset"}],
                    ["bed", -3.4, 3.2, 90],
                    ["desk", -3.6, -0.8, 90],
                    ["rug", 0.0, 0.5, 0],
                    ["floor_lamp", 4.2, 3.6, 0],
                    ["poster", -1.2, 4.3, 0],
                ],
            }
        },
        "shots": shots,
        "cast": cast_out,
    }


def main(project_dir: str):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    os.makedirs(project_dir, exist_ok=True)
    bp, corpus_block, visual_bible = load_training_context()
    theme = os.environ.get("STORY_THEME", "").strip()
    cast_universe = visual_bible.get("canonical_cast_universe") or DEFAULT_CAST_UNIVERSE

    try:
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY empty")
        story = run_gemini_director_pipeline(api_key, theme, bp, corpus_block, visual_bible)
    except Exception as e:
        print(f"[WARN] Gemini Director fallback engaged ({e}); using offline closet story.", flush=True)
        story = build_offline_fast_story(cast_universe)

    cast_names = list(story["cast"].keys())
    custom_things = set((story.get("things") or {}).keys())
    shots = story.get("shots")
    if not isinstance(shots, list) or len(shots) < 4:
        story = build_offline_fast_story(cast_universe)
        shots = story["shots"]

    t_cursor = 0.0
    prev_cam = None
    cam_cycle = ["mcu", "cu", "ots", "mcu", "two", "low", "cu", "ws"]

    for idx, sh in enumerate(shots):
        if sh.get("set") not in set(RICH_SETS) and sh.get("set") not in (story.get("places") or {}):
            sh["set"] = list((story.get("places") or {}).keys())[0] if story.get("places") else "Bedroom"
        if sh.get("mood") not in VALID_MOODS:
            sh["mood"] = "sunny"

        if sh.get("cam") == "ins" and sh.get("focus"):
            pass
        elif sh.get("cam") not in VALID_CAMS or sh.get("cam") == prev_cam:
            sh["cam"] = cam_cycle[idx % len(cam_cycle)]
        prev_cam = sh["cam"]

        if sh.get("move") not in VALID_MOVES:
            sh["move"] = "crash_in" if idx % 3 == 0 else "push"
        if sh.get("subject") not in cast_names:
            sh["subject"] = "Maya" if "Maya" in cast_names else cast_names[0]

        words_cnt = len(re.findall(r"\w+", sh.get("text", "")))
        beat_dur = max(1.15, min(2.4, round(words_cnt / 4.2, 2)))
        sh["t0"] = round(t_cursor, 2)
        t_cursor += beat_dur
        sh["t1"] = round(t_cursor, 2)

        for act in sh.get("actors") or []:
            if act.get("who") not in cast_names:
                act["who"] = sh["subject"]
            if act.get("anim") not in VALID_ANIMS:
                act["anim"] = "talk"
            act["face"] = sanitize_face(act.get("face"))
            if isinstance(act.get("faceAt"), list):
                act["faceAt"] = [
                    [pair[0], sanitize_face(pair[1])]
                    for pair in act["faceAt"]
                    if isinstance(pair, list) and len(pair) >= 2
                ]

    story["shots"] = enforce_speaker_focus_and_continuity(shots, story["cast"])
    story["dur"] = round(t_cursor, 2)

    with open(os.path.join(project_dir, "timed.json"), "w", encoding="utf-8") as f:
        json.dump(story, f, indent=2)

    with open(os.path.join(project_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "title": story.get("title", "Blox Story"),
                "caption": story.get("caption", "#roblox #storytime #shorts #reels"),
                "reference_blueprint": bp.get("reel_id", "none"),
                "custom_things_built": sorted(custom_things),
                "model_used": story.get("model_used", "offline_fallback"),
            },
            f,
            indent=2,
        )

    print(
        f"[Director] Built {len(story['shots'])} shots | custom_things={sorted(custom_things)} | model={story.get('model_used')}",
        flush=True,
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python auto/generate_story.py <PROJECT_DIR>")
    main(os.path.abspath(sys.argv[1]))
