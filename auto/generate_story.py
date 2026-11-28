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
    "gemini-2.5-flash",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemma-4-31b-it",
]

RICH_SETS = [
    "MusicRow", "TownPool", "Gym", "Street", "Park",
    "Store", "Classroom", "Office", "LivingRoom", "Kitchen", "Bedroom", "Backyard", "Playground",
]

DEFAULT_CAST_UNIVERSE = {
    "Leo": {"height": 1.0, "gender": "male", "role": "main_character", "skin": "#f5c29b", "hair": "spiky", "hair_color": "#261b14", "shirt": "#1e73f2", "pants": "#1b2234", "shoes": "#f2f4f8", "extras": ["backpack"]},
    "Maya": {"height": 0.93, "gender": "female", "role": "sister_or_best_friend", "skin": "#f7c7a3", "hair": "pigtails", "hair_color": "#3b2316", "shirt": "#ff4f8b", "pants": "#2a2d43", "shoes": "#ffffff", "extras": ["skirt"]},
    "Jake": {"height": 1.04, "gender": "male", "role": "rival_or_friend", "skin": "#e8b087", "hair": "short", "hair_color": "#1e1612", "shirt": "#e67e22", "pants": "#1d2432", "shoes": "#22262e", "extras": []},
    "Max": {"height": 1.06, "gender": "male", "role": "brother", "skin": "#d99b6c", "hair": "curly", "hair_color": "#1e1612", "shirt": "#22b855", "pants": "#1d2432", "shoes": "#f2f4f8", "extras": ["cap"]},
    "Mom": {"height": 1.02, "gender": "female", "role": "mother", "skin": "#f5c29b", "hair": "bun", "hair_color": "#4a2c18", "shirt": "#9b51e0", "pants": "#25293a", "shoes": "#d8c3a5", "extras": ["cardigan"]},
    "Dad": {"height": 1.08, "gender": "male", "role": "father", "skin": "#eab38a", "hair": "short", "hair_color": "#2d221c", "shirt": "#2f80ed", "pants": "#1f2533", "shoes": "#3a2c22", "extras": ["tie"]},
    "Uncle_Sam": {"height": 1.06, "gender": "male", "role": "uncle", "skin": "#e2a77d", "hair": "short", "hair_color": "#5c5856", "shirt": "#f2994a", "pants": "#2c3342", "shoes": "#4a3728", "extras": ["glasses"]},
    "Ms_Clara": {"height": 1.02, "gender": "female", "role": "teacher", "skin": "#f6c9a6", "hair": "long", "hair_color": "#3d2516", "shirt": "#27ae60", "pants": "#1e2430", "shoes": "#2b2d42", "extras": ["glasses", "cardigan"]},
    "Zoe": {"height": 0.96, "gender": "female", "role": "best_friend_female", "skin": "#c68658", "hair": "long", "hair_color": "#191412", "shirt": "#f2c94c", "pants": "#232938", "shoes": "#ffffff", "extras": ["skirt", "headphones"]},
    "Sam": {"height": 1.0, "gender": "male", "role": "best_friend_male", "skin": "#8d5524", "hair": "curly", "hair_color": "#141110", "shirt": "#eb5757", "pants": "#1c2230", "shoes": "#eeeeee", "extras": []},
}

BACKGROUND_CROWD_NPCS = {
    "Townie_1": {"height": 1.0, "gender": "male", "skin": "#f2be96", "hair": "short", "hair_color": "#2b1d14", "shirt": "#00a8ff", "pants": "#2f3640", "shoes": "#ffffff", "extras": []},
    "Townie_2": {"height": 0.96, "gender": "female", "skin": "#d99b6c", "hair": "long", "hair_color": "#3d2314", "shirt": "#fbc531", "pants": "#192a56", "shoes": "#ffffff", "extras": ["skirt"]},
    "Townie_3": {"height": 1.03, "gender": "male", "skin": "#f5c7a3", "hair": "curly", "hair_color": "#1e272e", "shirt": "#4cd137", "pants": "#2f3640", "shoes": "#dddddd", "extras": []},
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

SET_KEYWORDS = {
    "Bedroom": ("bedroom", "my room", "his room", "her room", "the room", "closet", "bed"),
    "Classroom": ("classroom", "school", "class", "desk", "teacher", "locker", "hallway"),
    "LivingRoom": ("living room", "sofa", "couch", "tv", "home", "house"),
    "Kitchen": ("kitchen", "fridge", "table", "dinner", "cooking"),
    "Street": ("street", "road", "outside", "town", "car", "sidewalk"),
    "Park": ("park", "trees", "bench", "grass"),
    "Store": ("store", "shop", "mall", "buy", "cashier"),
    "Gym": ("gym", "workout", "weights", "court"),
    "Office": ("office", "principal", "boss", "meeting"),
    "Backyard": ("backyard", "yard", "fence", "garden"),
}

WALK_VERBS = ("walk", "went", "go to", "going to", "enter", "came in", "headed", "stepped", "approached", "follow")
RUN_VERBS = ("ran", "run", "running", "rushed", "chased", "fled", "sprinted", "bolted", "crowded")


def hex_to_rgb01(val, fallback=(0.5, 0.5, 0.5)) -> list[float]:
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
        sample_scripts = random.sample(scripts, min(5, len(scripts))) if scripts else []
        sample_hooks = random.sample(hooks, min(10, len(hooks))) if hooks else []
        corpus_block = (
            f"HARVESTED VAULT PACING ({corpus.get('avg_words_per_sec', 4.75)} words/sec):\n"
            f"HOOK EXAMPLES:\n"
            + "\n".join(f"- {h}" for h in sample_hooks)
            + "\n\nSCRIPT EXAMPLES:\n"
            + "\n---\n".join(f"[{s['id']}]: {s['full_script'][:450]}" for s in sample_scripts)
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


def apply_wardrobe_and_gender_locks(cast: dict) -> dict:
    """Locks distinct signature colors, hairstyles, silhouettes & accessories for every character."""
    distinct_palettes = [
        ("#1e73f2", "#1b2234", "spiky", ["backpack"]),
        ("#ff4f8b", "#2a2d43", "pigtails", ["skirt"]),
        ("#e67e22", "#1d2432", "short", []),
        ("#22b855", "#1d2432", "curly", ["cap"]),
        ("#9b51e0", "#25293a", "bun", ["cardigan"]),
        ("#f2c94c", "#232938", "long", ["skirt", "headphones"]),
        ("#eb5757", "#1c2230", "curly", ["glasses"]),
    ]

    for idx, (name, spec) in enumerate(cast.items()):
        if not isinstance(spec, dict):
            continue
        base = DEFAULT_CAST_UNIVERSE.get(name) or BACKGROUND_CROWD_NPCS.get(name)
        pal_shirt, pal_pants, pal_hair, pal_extras = distinct_palettes[idx % len(distinct_palettes)]

        gender = str(spec.get("gender") or (base or {}).get("gender") or "male").lower()
        if gender == "female" or name in ("Maya", "Zoe", "Mom", "Ms_Clara", "Townie_2"):
            spec["gender"] = "female"
            spec["height"] = min(float(spec.get("height", 0.94)), 0.96) if name not in ("Mom", "Ms_Clara") else 1.01
            raw_hair = spec.get("hair") or (base or {}).get("hair") or "long"
            spec["hair"] = raw_hair if raw_hair in ("pigtails", "long", "bun") else "long"
            extras = list(spec.get("extras") or (base or {}).get("extras") or ["skirt"])
            if "skirt" not in extras and name not in ("Mom", "Ms_Clara"):
                extras.append("skirt")
        else:
            spec["gender"] = "male"
            spec["height"] = max(float(spec.get("height", 1.02)), 1.0)
            raw_hair = spec.get("hair") or (base or {}).get("hair") or pal_hair
            spec["hair"] = raw_hair if raw_hair in ("spiky", "short", "curly", "cap", "bald") else "spiky"
            extras = list(spec.get("extras") or (base or {}).get("extras") or pal_extras)

        # Preserve distinct character colors rather than forcing identical clothes
        spec["skin"] = hex_to_rgb01(spec.get("skin") or (base or {}).get("skin"), (0.96, 0.76, 0.61))
        spec["shirt"] = hex_to_rgb01(spec.get("shirt") or (base or {}).get("shirt") or pal_shirt, (0.12, 0.45, 0.95))
        spec["pants"] = hex_to_rgb01(spec.get("pants") or (base or {}).get("pants") or pal_pants, (0.11, 0.14, 0.21))
        spec["shoes"] = hex_to_rgb01(spec.get("shoes") or (base or {}).get("shoes"), (0.93, 0.94, 0.96))
        spec["hair_color"] = hex_to_rgb01(spec.get("hair_color") or (base or {}).get("hair_color"), (0.16, 0.11, 0.08))
        spec["hair_style"] = spec["hair"]
        spec["extras"] = list(dict.fromkeys(extras))
    return cast


def infer_set_from_text(text: str, current_set: str, available_sets: list[str]) -> str:
    low = text.lower()
    for set_name, kws in SET_KEYWORDS.items():
        if set_name in available_sets and any(k in low for k in kws):
            return set_name
    return current_set


def choreograph_flow_continuity(shots: list[dict], cast: dict, available_sets: list[str]) -> list[dict]:
    """
    Flow-style Continuity & Action Director:
    1. Switches `set` automatically when dialogue says characters go to a new room.
    2. Keeps 2–4 characters on stage together so scenes feel alive, never empty.
    3. Converts movement cues in text ('we go to room', 'ran', 'crowded') into real `walkTo` paths.
    4. Tracks continuous XY positions from shot N to shot N+1 so characters actually move across the room.
    """
    main_trio = [c for c in ("Leo", "Maya", "Jake") if c in cast] or list(cast.keys())[:3]
    last_pos: dict[str, list[float]] = {}
    last_set: str | None = None

    stage_slots = [
        [-1.3, -0.3],
        [1.3, 0.1],
        [-0.2, 1.4],
        [2.2, 1.3],
    ]

    for idx, sh in enumerate(shots):
        txt = sh.get("text", "")
        low_txt = txt.lower()
        dur = max(1.15, float(sh.get("t1", 1.4)) - float(sh.get("t0", 0.0)))

        # 1. Detect location transitions from narration text ("we go to the room")
        inferred_set = infer_set_from_text(txt, sh.get("set", available_sets[0]), available_sets)
        if inferred_set in available_sets:
            sh["set"] = inferred_set

        cur_set = sh["set"]
        room_just_changed = cur_set != last_set
        if room_just_changed:
            last_pos.clear()
            last_set = cur_set

        speaker = sh.get("subject") if sh.get("subject") in cast else main_trio[0]
        sh["subject"] = speaker
        sh["side"] = 1 if idx % 2 == 0 else -1

        # 2. Ensure multi-character staging (speaker + 1 to 2 co-stars in the scene)
        actors = list(sh.get("actors") or [])
        present_names = {a.get("who") for a in actors if a.get("who") in cast}
        if speaker not in present_names:
            actors.insert(0, {"who": speaker, "anim": "talk", "face": "neutral"})
            present_names.add(speaker)

        for companion in main_trio:
            if len(actors) >= 3:
                break
            if companion not in present_names:
                actors.append({"who": companion, "anim": "idle", "face": "neutral"})
                present_names.add(companion)

        # Detect movement intent from dialogue or explicit anim
        wants_run = any(v in low_txt for v in RUN_VERBS)
        wants_walk = room_just_changed or any(v in low_txt for v in WALK_VERBS)

        # 3. Assign continuous positions, facing angles, and walkTo trajectories
        for a_idx, act in enumerate(actors[:4]):
            who = act["who"]
            is_speaker = (who == speaker)
            h = float((cast.get(who) or {}).get("height", 1.0))

            # Starting position: enter from doorway (-3.2) on room switch, otherwise continue from last_pos
            if room_just_changed:
                start_pt = [-3.0 + a_idx * 0.7, -0.5 + a_idx * 0.6]
            elif who in last_pos:
                start_pt = list(last_pos[who])
            elif isinstance(act.get("at"), list) and len(act["at"]) >= 2:
                start_pt = [float(act["at"][0]), float(act["at"][1])]
            else:
                start_pt = list(stage_slots[a_idx % len(stage_slots)])

            act["at"] = [round(start_pt[0], 2), round(start_pt[1], 2)]

            # Determine animation
            cur_anim = act.get("anim", "idle")
            if wants_run and (is_speaker or "everyone" in low_txt or "we" in low_txt):
                cur_anim = "run"
            elif wants_walk and (is_speaker or "we" in low_txt or "us" in low_txt):
                cur_anim = "walk"
            elif is_speaker and cur_anim in ("idle", None):
                cur_anim = "talk"
            elif not is_speaker and cur_anim in ("talk", None):
                # Reactive listener poses instead of stiff idle
                react_cycle = ["nod", "shock", "think", "point", "shrug"]
                cur_anim = react_cycle[(idx + a_idx) % len(react_cycle)]

            act["anim"] = cur_anim

            if is_speaker:
                act["talk"] = [0.0, round(dur, 2)]
                act["yaw"] = 18.0 if start_pt[0] < 0 else -18.0
            else:
                act.pop("talk", None)
                # Face toward the speaker
                sp_x = last_pos.get(speaker, stage_slots[0])[0]
                act["yaw"] = 45.0 if start_pt[0] < sp_x else -45.0

            # Compute real `walkTo` destination so Blender animates full locomotion across the floor
            if cur_anim in ("walk", "run") or isinstance(act.get("walkTo"), list):
                if isinstance(act.get("walkTo"), list) and len(act["walkTo"]) >= 2 and not room_just_changed:
                    end_pt = [float(act["walkTo"][0]), float(act["walkTo"][1])]
                else:
                    target_slot = stage_slots[a_idx % len(stage_slots)]
                    if room_just_changed:
                        end_pt = target_slot
                    else:
                        step = (3.4 if cur_anim == "run" else 2.2) * h * min(dur, 2.0) * 0.65
                        dir_x = 1.0 if start_pt[0] <= 0.5 else -1.0
                        dir_y = 0.4 if (idx % 2 == 0) else -0.4
                        end_pt = [
                            max(-4.5, min(4.5, start_pt[0] + dir_x * step)),
                            max(-2.2, min(3.2, start_pt[1] + dir_y * step)),
                        ]
                act["walkTo"] = [round(end_pt[0], 2), round(end_pt[1], 2)]
                last_pos[who] = list(act["walkTo"])
            else:
                act.pop("walkTo", None)
                last_pos[who] = list(act["at"])

        sh["actors"] = actors[:4]

    return shots


def run_gemini_director_pipeline(api_key: str, theme: str, bp: dict, corpus_block: str, visual_bible: dict) -> dict:
    cast_universe = visual_bible.get("canonical_cast_universe") or DEFAULT_CAST_UNIVERSE

    # =========================================================================
    # STAGE 1: Flow-Style Showrunner & Prompt Expander (Story + Location Bible)
    # =========================================================================
    stage1_prompt = f"""You are a Google Flow-style AI Video Showrunner & Prompt Expander for a 3D Roblox Reels engine.
{corpus_block}

USER THEME / PROMPT:
"{theme or 'Leo, Maya, and Jake discover a glowing secret box in the classroom, rush into Maya bedroom to open it, and get shocked by what is inside.'}"

CANONICAL CAST (keep each character's distinct signature colors, hair & personality):
{json.dumps(cast_universe, indent=2)}

TASK — EXPAND PROMPT INTO CONTINUOUS MULTI-LOCATION STORY:
1. Write a fast, high-energy 16-to-20-beat spoken script (6–9 words per beat, ~45 seconds total) with a viral 3-second hook, physical movement across at least 2 distinct rooms (e.g. Classroom -> Bedroom or LivingRoom -> Backyard), rich actions, and a twist ending.
2. For EVERY beat, specify:
   - `set`: the exact room name from {json.dumps(RICH_SETS)} (MUST change when characters go to another room!).
   - `speaker`: who is talking.
   - `line`: spoken dialogue.
   - `action_direction`: explicit physical movement & multi-character blocking (e.g. "Leo and Maya walk quickly toward the door while Jake points in shock").
   - `emotion`: facial expression.
   - `camera_shot`: dynamic angle (`mcu`, `cu`, `two`, `ws`, `ots`, `low`, `ins`).

Return ONLY valid JSON:
{{
  "title": "Viral title",
  "caption": "Caption with 5 hashtags",
  "keys": ["6", "IMPACT", "WORDS", "IN", "CAPS", "HERE"],
  "required_sets": ["Classroom", "Bedroom"],
  "required_custom_props": [
    {{"name": "GlowingMysteryBox", "set": "Bedroom", "at": [0.0, 1.5, 0], "description": "Golden glowing mystery box on the bedroom floor"}}
  ],
  "active_cast": ["Leo", "Maya", "Jake"],
  "beats": [
    {{
      "beat": 1,
      "set": "Classroom",
      "speaker": "Leo",
      "line": "Guys, look what I just found under my desk!",
      "action_direction": "Leo holds up a glowing box while Maya and Jake rush over to see it",
      "emotion": "shock",
      "camera_shot": "two"
    }}
  ]
}}"""

    bible = call_gemini_json_defensive(api_key, stage1_prompt, stage_label="Stage1-FlowExpander")

    # =========================================================================
    # STAGE 2: Flow Location Profiles (`places`) & Custom Props (`things`)
    # =========================================================================
    stage2_prompt = f"""You are the 3D Environment & Prop Architect.
Build rich, fully furnished 3D Location Profiles (`places`) and custom props (`things`) for this Story Bible so backgrounds stay spatially consistent across cuts.

STORY BIBLE:
{json.dumps(bible, indent=2)}

RULES:
1. Define every item in `required_custom_props` inside `things` using primitives:
   - `["block", "#hex", [width_x, depth_y, height_z], [x, y, z], {{"metal": false, "glow": 0.0}}]`
   - `["tube", "#hex", radius, height, [x, y, z]]`
   - `["ball", "#hex", radius, [x, y, z]]`
2. Define every room in `required_sets` inside `places` with 6–10 props placed around the perimeter (`x` outside `-2.2..2.2` or `y > 2.2`) so the center floor stays open for walking and group action.

Return ONLY valid JSON:
{{
  "things": {{
    "GlowingMysteryBox": [
      ["block", "#d4af37", [0.8, 0.8, 0.6], [0, 0, 0.3], {{"metal": true, "glow": 0.6}}],
      ["block", "#ff3b30", [0.84, 0.84, 0.12], [0, 0, 0.58], {{"metal": false, "glow": 0.2}}]
    ]
  }},
  "places": {{
    "Classroom": {{
      "kind": "indoor",
      "wall": "#dfe6e9",
      "lower": "#74b9ff",
      "floor": "wood",
      "floor_color": "#b28253",
      "props": [
        ["blackboard", 0.0, 4.2, 0],
        ["desk", -2.8, 1.8, 0],
        ["desk", 2.8, 1.8, 0],
        ["chair", -2.8, 0.9, 0],
        ["chair", 2.8, 0.9, 0],
        ["bookshelf", -4.2, 3.5, 90],
        ["plant", 4.1, 3.6, 0]
      ]
    }},
    "Bedroom": {{
      "kind": "indoor",
      "wall": "#f5ebe0",
      "lower": "#d5bdaf",
      "floor": "wood",
      "floor_color": "#8c5e35",
      "props": [
        ["GlowingMysteryBox", 0.0, 2.2, 0, {{"name": "GlowingMysteryBox"}}],
        ["bed", -3.4, 3.2, 90],
        ["desk", 3.5, 2.5, -90],
        ["chair", 2.6, 2.5, 90],
        ["rug", 0.0, 0.4, 0],
        ["floor_lamp", -4.1, -1.0, 0],
        ["poster", 1.2, 4.3, 0]
      ]
    }}
  }}
}}"""

    assets = call_gemini_json_defensive(api_key, stage2_prompt, stage_label="Stage2-Locations")

    # =========================================================================
    # STAGE 3: Flow Scene-by-Scene Blocking, Walking Paths & Camera Cuts
    # =========================================================================
    stage3_prompt = f"""You are the Lead 3D Choreographer & Cinematographer.
Convert EVERY beat in the Story Bible into an action-packed 3D shot with 2–3 characters on stage, real XY walking trajectories (`at` -> `walkTo`), and dynamic camera angles.

STORY BIBLE:
{json.dumps(bible, indent=2)}

CUSTOM PROPS:
{json.dumps(list((assets.get("things") or {}).keys()))}

CHOREOGRAPHY RULES:
1. Keep 2–3 characters visible in EVERY shot (`actors` list). Never leave a single character standing alone unless it is an `ecu` reaction!
2. Whenever characters move, walk, run, or enter a room, set `"anim": "walk"` or `"run"` AND provide distinct `"at": [x1, y1]` and `"walkTo": [x2, y2]` coordinates!
3. When `"set"` changes from the previous beat, place characters entering from `[-2.8, -0.4]` walking toward `[0.0, 0.2]`.
4. Alternate `"cam"` across consecutive shots (`ws`, `two`, `mcu`, `ots`, `cu`, `low`, `ins`).
5. ALLOWED ANIMS: {json.dumps(sorted(VALID_ANIMS))}.
6. ALLOWED FACES: {json.dumps(sorted(VALID_FACES))}.

Return ONLY valid JSON:
{{
  "music": [[0, "playful"], [0.45, "suspense"], [0.75, "hit"], [0.85, "triumph"]],
  "shots": [
    {{
      "set": "Classroom",
      "mood": "sunny",
      "cam": "two",
      "move": "push",
      "subject": "Leo",
      "text": "Guys, look what I just found under my desk!",
      "sfx": ["whoosh@0.0"],
      "actors": [
        {{"who": "Leo", "at": [-1.2, 0.0], "walkTo": [-0.4, 0.2], "yaw": 25, "anim": "walk", "face": "grin", "talk": [0.0, 1.5]}},
        {{"who": "Maya", "at": [1.8, 0.4], "walkTo": [0.8, 0.2], "yaw": -45, "anim": "walk", "face": "shock"}},
        {{"who": "Jake", "at": [2.4, -0.6], "yaw": -35, "anim": "point", "face": "surprised"}}
      ]
    }}
  ]
}}"""

    choreography = call_gemini_json_defensive(api_key, stage3_prompt, stage_label="Stage3-Blocking")

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
    cast_out = apply_wardrobe_and_gender_locks(cast_out)

    return {
        "title": bible.get("title", "The Secret Glowing Box!"),
        "caption": bible.get("caption", "Wait until they open it in the bedroom! #roblox #storytime #shorts #reels #fyp"),
        "keys": bible.get("keys", ["SECRET", "BOX", "BEDROOM", "LEO", "MAYA", "SHOCKED"]),
        "music": choreography.get("music", [[0, "playful"], [0.45, "suspense"], [0.75, "hit"], [0.85, "triumph"]]),
        "things": assets.get("things") or {},
        "places": assets.get("places") or {},
        "cast": cast_out,
        "shots": choreography.get("shots") or [],
        "model_used": choreography.get("_model_used", "gemini-flow-director"),
    }


def build_offline_fast_story(cast_universe: dict) -> dict:
    beats = [
        ("Classroom", "sunny", "two", "crash_in", "Leo", "Guys, look what I found in the classroom!", "point", "grin", ["whoosh@0.0"], None),
        ("Classroom", "sunny", "ws", "push", "Maya", "Quick, let's go to my bedroom before anyone sees!", "walk", "worried", ["pop@0.0"], None),
        ("Bedroom", "sunny", "ws", "reveal_push", "Leo", "We ran into the room and locked the door!", "walk", "shock", ["whoosh@0.0"], None),
        ("Bedroom", "sunny", "ins", "push", "Maya", "The golden box started glowing on the floor!", "shock", "shock", ["ding@0.1"], "GlowingMysteryBox"),
        ("Bedroom", "sunny", "two", "crash_in", "Jake", "No way, it's filled with unlimited robux!", "jump_joy", "laugh", ["cash@0.0"], None),
    ]
    shots = []
    for idx, (st, md, cm, mv, subj, txt, anim, face, sfx, focus_thing) in enumerate(beats):
        sh = {
            "set": st, "mood": md, "cam": cm, "move": mv, "subject": subj, "text": txt, "sfx": sfx,
            "actors": [
                {"who": "Leo", "at": [-1.2, 0.0], "walkTo": [-0.3, 0.2], "yaw": 20, "anim": anim, "face": face, "talk": [0.0, 1.5]},
                {"who": "Maya", "at": [1.4, 0.3], "walkTo": [0.7, 0.1], "yaw": -35, "anim": "walk" if "go" in txt or "ran" in txt else "shock", "face": "shock"},
                {"who": "Jake", "at": [2.1, -0.5], "yaw": -45, "anim": "point", "face": "grin"},
            ],
        }
        if focus_thing:
            sh["focus"] = focus_thing
        shots.append(sh)

    raw_cast = {k: dict(v) for k, v in cast_universe.items()}
    raw_cast.update({k: dict(v) for k, v in BACKGROUND_CROWD_NPCS.items()})
    cast_out = apply_wardrobe_and_gender_locks(raw_cast)

    return {
        "title": "What We Found Inside The Classroom!",
        "caption": "We rushed to the bedroom to open it! #roblox #storytime #shorts #reels #fyp",
        "keys": ["SECRET", "CLASSROOM", "BEDROOM", "GLOWING", "SHOCKED", "TWIST"],
        "music": [[0, "playful"], [0.4, "suspense"], [0.75, "hit"], [0.85, "triumph"]],
        "things": {
            "GlowingMysteryBox": [
                ["block", "#d4af37", [0.8, 0.8, 0.6], [0, 0, 0.3], {"metal": True, "glow": 0.6}],
                ["block", "#ff3b30", [0.84, 0.84, 0.12], [0, 0, 0.58], {"metal": False, "glow": 0.2}],
            ]
        },
        "places": {
            "Classroom": {
                "kind": "indoor",
                "wall": "#dfe6e9",
                "lower": "#74b9ff",
                "floor": "wood",
                "floor_color": "#b28253",
                "props": [
                    ["blackboard", 0.0, 4.2, 0],
                    ["desk", -2.8, 1.8, 0],
                    ["desk", 2.8, 1.8, 0],
                    ["bookshelf", -4.2, 3.5, 90],
                ],
            },
            "Bedroom": {
                "kind": "indoor",
                "wall": "#e8dfd1",
                "lower": "#c9b99f",
                "floor": "wood",
                "floor_color": "#8c5e35",
                "props": [
                    ["GlowingMysteryBox", 0.0, 2.2, 0, {"name": "GlowingMysteryBox"}],
                    ["bed", -3.4, 3.2, 90],
                    ["desk", 3.5, 2.5, -90],
                    ["rug", 0.0, 0.5, 0],
                    ["floor_lamp", -4.1, -1.0, 0],
                ],
            },
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
        print(f"[WARN] Gemini Director fallback engaged ({e}); using offline multi-room story.", flush=True)
        story = build_offline_fast_story(cast_universe)

    cast_names = list(story["cast"].keys())
    custom_things = set((story.get("things") or {}).keys())
    shots = story.get("shots")
    if not isinstance(shots, list) or len(shots) < 4:
        story = build_offline_fast_story(cast_universe)
        shots = story["shots"]

    available_sets = list(dict.fromkeys(list((story.get("places") or {}).keys()) + RICH_SETS))

    t_cursor = 0.0
    prev_cam = None
    cam_cycle = ["two", "mcu", "ws", "ots", "cu", "low", "ms", "cu"]

    for idx, sh in enumerate(shots):
        if sh.get("set") not in available_sets:
            sh["set"] = available_sets[0]
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
            sh["subject"] = "Leo" if "Leo" in cast_names else cast_names[0]

        words_cnt = len(re.findall(r"\w+", sh.get("text", "")))
        beat_dur = max(1.25, min(2.5, round(words_cnt / 4.2, 2)))
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

    story["shots"] = choreograph_flow_continuity(shots, story["cast"], available_sets)
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
        f"[FlowDirector] Built {len(story['shots'])} shots across {sorted({s['set'] for s in story['shots']})} | "
        f"custom_things={sorted(custom_things)} | model={story.get('model_used')}",
        flush=True,
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python auto/generate_story.py <PROJECT_DIR>")
    main(os.path.abspath(sys.argv[1]))
