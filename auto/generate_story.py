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

RANDOM_STORY_SEEDS = [
    ("In my town, every word you speak costs ten dollars—and I accidentally started talking in my sleep!", ["Bedroom", "Street"]),
    ("In this world, whatever you draw on a chalkboard becomes real—and I drew a giant gold vault at school!", ["Classroom", "Office"]),
    ("In my house, whoever touches the floor after midnight gets frozen—and I woke up super thirsty!", ["Bedroom", "Kitchen"]),
    ("In this town, trash is worth millions while gold is worthless—so I brought a full trash bag to school!", ["Street", "Classroom"]),
    ("In my school, your battery percentage above your head decides your grades—and mine dropped to 1%!", ["Classroom", "LivingRoom"]),
    ("In my house, a secret lever behind the fridge opens an underground arcade—and I pulled it at 3 AM!", ["Kitchen", "LivingRoom"]),
    ("In this town, whoever wins the gym obstacle course becomes mayor—and I trained all night!", ["Gym", "TownPool"]),
    ("In this world, you only get three lies per day before your hair turns bright neon—and I used all three!", ["Street", "Park"]),
]

MAIN_HERO_CAST = {
    "Leo": {
        "height": 1.0,
        "gender": "male",
        "role": "main_character",
        "skin": "#f5c29b",
        "hair": "spiky",
        "hair_color": "#261b14",
        "shirt": "#1e73f2",
        "pants": "#1b2234",
        "shoes": "#f2f4f8",
        "extras": ["backpack"],
    }
}

VALID_CAMS = {"ecu", "cu", "mcu", "ms", "mls", "ws", "low", "high", "ots", "two", "ews", "ground", "pov", "ins"}
VALID_MOVES = {"crash_in", "push", "reveal_push", "creep", "drift", "lock"}
VALID_MOODS = {"sunny", "sunset", "storm", "night"}
VALID_ANIMS = {
    "idle", "talk", "walk", "run", "nod", "headshake", "flinch",
    "slump", "jump_joy", "shock", "surrender", "what", "facepalm", "clap",
    "point", "wave", "cheer", "shrug", "scared", "eat", "cross_arms",
    "think", "sad", "angry", "sit",
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
    "Bedroom": ("bedroom", "my room", "the room", "bed", "woke up", "sleep"),
    "Classroom": ("classroom", "school", "class", "desk", "chalkboard", "grades"),
    "LivingRoom": ("living room", "sofa", "couch", "tv", "my house", "arcade"),
    "Kitchen": ("kitchen", "fridge", "thirsty", "dinner", "cooking"),
    "Street": ("street", "road", "outside", "my town", "this town", "sidewalk"),
    "Park": ("park", "trees", "bench", "grass"),
    "Store": ("store", "shop", "mall", "cashier"),
    "Gym": ("gym", "obstacle", "weights", "court"),
    "Office": ("office", "principal", "mayor", "vault"),
    "Backyard": ("backyard", "yard", "garden"),
    "TownPool": ("pool", "swim", "water"),
    "Playground": ("playground", "slide", "swing"),
}

WALK_VERBS = ("walk", "went", "go to", "going to", "enter", "came in", "headed", "stepped", "sneak", "snuck")
RUN_VERBS = ("ran", "run", "running", "rushed", "fled", "sprinted", "bolted", "hurried")


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


def load_training_context() -> tuple[dict, str]:
    blueprints = sorted(glob.glob(os.path.join(BLUEPRINT_DIR, "*.json")))
    bp = json.load(open(random.choice(blueprints), encoding="utf-8")) if blueprints else {}

    corpus_block = ""
    if os.path.exists(CORPUS_PATH):
        corpus = json.load(open(CORPUS_PATH, encoding="utf-8"))
        scripts = corpus.get("scripts", [])
        hooks = corpus.get("all_hooks", [])
        sample_scripts = random.sample(scripts, min(5, len(scripts))) if scripts else []
        sample_hooks = random.sample(hooks, min(10, len(hooks))) if hooks else []
        corpus_block = (
            f"HARVESTED SOLO-NARRATOR STORYTELLING STYLE ({corpus.get('avg_words_per_sec', 4.75)} words/sec):\n"
            f"HOOK EXAMPLES:\n"
            + "\n".join(f"- {h}" for h in sample_hooks)
            + "\n\nSCRIPT EXAMPLES:\n"
            + "\n---\n".join(f"[{s['id']}]: {s['full_script'][:450]}" for s in sample_scripts)
        )
    return bp, corpus_block


def call_gemini_json_defensive(api_key: str, prompt: str, stage_label: str = "Stage") -> dict:
    last_err = None
    for model in MODELS:
        gen_cfg = {"temperature": 0.85}
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


def build_solo_hero_cast() -> dict:
    spec = dict(MAIN_HERO_CAST["Leo"])
    spec["skin"] = hex_to_rgb01(spec["skin"], (0.96, 0.76, 0.61))
    spec["shirt"] = hex_to_rgb01(spec["shirt"], (0.12, 0.45, 0.95))
    spec["pants"] = hex_to_rgb01(spec["pants"], (0.11, 0.14, 0.21))
    spec["shoes"] = hex_to_rgb01(spec["shoes"], (0.93, 0.94, 0.96))
    spec["hair_color"] = hex_to_rgb01(spec["hair_color"], (0.16, 0.11, 0.08))
    spec["hair_style"] = spec["hair"]
    return {"Leo": spec}


def infer_set_from_text(text: str, current_set: str, available_sets: list[str]) -> str:
    low = text.lower()
    for set_name, kws in SET_KEYWORDS.items():
        if set_name in available_sets and any(k in low for k in kws):
            return set_name
    return current_set


def choreograph_solo_storyteller(shots: list[dict], available_sets: list[str]) -> list[dict]:
    """
    Single-Narrator Flow Continuity:
    - Keeps Leo as the ONLY speaker and sole character on stage.
    - Switches `set` automatically when the story moves to a new room.
    - Generates smooth `walkTo` paths across the room so Leo never stands frozen in one spot.
    """
    last_pos = [0.0, 0.0]
    last_set: str | None = None

    stage_waypoints = [
        [-1.4, -0.4],
        [0.4, 0.2],
        [1.6, 0.8],
        [-0.6, 1.2],
        [1.2, -0.5],
    ]

    for idx, sh in enumerate(shots):
        txt = sh.get("text", "")
        low_txt = txt.lower()
        dur = max(1.25, float(sh.get("t1", 1.4)) - float(sh.get("t0", 0.0)))

        inferred_set = infer_set_from_text(txt, sh.get("set", available_sets[0]), available_sets)
        if inferred_set in available_sets:
            sh["set"] = inferred_set

        cur_set = sh["set"]
        room_just_changed = cur_set != last_set
        if room_just_changed:
            last_pos = [-2.6, -0.4]
            last_set = cur_set

        sh["subject"] = "Leo"
        sh["side"] = 1 if idx % 2 == 0 else -1

        raw_act = (sh.get("actors") or [{}])[0]
        cur_anim = raw_act.get("anim") if raw_act.get("anim") in VALID_ANIMS else "talk"
        cur_face = sanitize_face(raw_act.get("face"))

        wants_run = any(v in low_txt for v in RUN_VERBS)
        wants_walk = room_just_changed or any(v in low_txt for v in WALK_VERBS)

        if wants_run:
            cur_anim = "run"
        elif wants_walk:
            cur_anim = "walk"
        elif cur_anim == "idle":
            cur_anim = "talk"

        start_pt = list(last_pos)
        act: dict = {
            "who": "Leo",
            "at": [round(start_pt[0], 2), round(start_pt[1], 2)],
            "yaw": 18.0 if idx % 2 == 0 else -18.0,
            "anim": cur_anim,
            "face": cur_face,
            "talk": [0.0, round(dur, 2)],
        }

        if cur_anim in ("walk", "run") or isinstance(raw_act.get("walkTo"), list):
            if isinstance(raw_act.get("walkTo"), list) and len(raw_act["walkTo"]) >= 2 and not room_just_changed:
                end_pt = [float(raw_act["walkTo"][0]), float(raw_act["walkTo"][1])]
            else:
                end_pt = list(stage_waypoints[idx % len(stage_waypoints)])
            act["walkTo"] = [round(end_pt[0], 2), round(end_pt[1], 2)]
            act["yaw"] = 35.0 if end_pt[0] >= start_pt[0] else -35.0
            last_pos = list(act["walkTo"])
        else:
            last_pos = list(start_pt)

        sh["actors"] = [act]

    return shots


def run_gemini_solo_director(api_key: str, theme: str, bp: dict, corpus_block: str) -> dict:
    random_seed_idea, random_seed_sets = random.choice(RANDOM_STORY_SEEDS)
    chosen_theme = theme or random_seed_idea

    # =========================================================================
    # STAGE 1: Solo First-Person Narrator Script ("In my town / world / school / house...")
    # =========================================================================
    stage1_prompt = f"""You are a viral solo-narrator 3D Roblox Reels storyteller (first-person "I" storytelling).
{corpus_block}

STORY PREMISE / USER PROMPT:
"{chosen_theme}"

STRICT SOLO STORYTELLING RULES:
1. **ONE SPEAKER ONLY (`Leo`)**: There are NO other characters in this video! Every single line is narrated in first-person (`"I"`, `"my"`) by `Leo` telling his crazy story directly to the viewer.
2. **SIGNATURE WORLD INTRO (BEAT 1)**: Beat 1 MUST begin with one of these iconic hooks:
   - `"In my town, ..."`
   - `"In this town, ..."`
   - `"In this world, ..."`
   - `"In my school, ..."`
   - `"In my house, ..."`
3. **ACTION & ROOM MOVEMENT**: Write 16–20 punchy first-person beats (6–9 words per beat, ~45s total) where `Leo` moves across 2–3 distinct locations from {json.dumps(RICH_SETS)} (e.g. `Bedroom` -> `Street` -> `Classroom`), interacts with custom props, reacts emotionally, and ends with a clever twist!

Return ONLY valid JSON:
{{
  "title": "In My Town...",
  "caption": "First-person story caption with 5 hashtags",
  "keys": ["6", "IMPACT", "WORDS", "IN", "CAPS", "HERE"],
  "required_sets": {json.dumps(random_seed_sets)},
  "required_custom_props": [
    {{"name": "GiantPriceMeter", "set": "{random_seed_sets[0]}", "at": [0.0, 2.8, 0], "description": "Glowing prop central to the story"}}
  ],
  "beats": [
    {{
      "beat": 1,
      "set": "{random_seed_sets[0]}",
      "line": "In my town, every word you speak costs ten dollars!",
      "action": "point",
      "emotion": "shock",
      "camera_shot": "mcu"
    }}
  ]
}}"""

    bible = call_gemini_json_defensive(api_key, stage1_prompt, stage_label="Stage1-SoloStory")

    # =========================================================================
    # STAGE 2: Rich 3D Room Sets (`places`) & Custom Story Props (`things`)
    # =========================================================================
    stage2_prompt = f"""You are the 3D Environment & Prop Architect.
Build rich, fully furnished 3D rooms (`places`) and custom props (`things`) for this solo story so the background looks vibrant and detailed.

STORY BIBLE:
{json.dumps(bible, indent=2)}

RULES:
1. Define every item in `required_custom_props` inside `things` using primitives:
   - `["block", "#hex", [width_x, depth_y, height_z], [x, y, z], {{"metal": false, "glow": 0.0}}]`
   - `["tube", "#hex", radius, height, [x, y, z]]`
   - `["ball", "#hex", radius, [x, y, z]]`
2. Define every room in `required_sets` inside `places` with 6–10 props around the perimeter (`x` outside `-2.2..2.2` or `y > 2.2`) so the center floor stays clear for Leo to walk across.

Return ONLY valid JSON:
{{
  "things": {{
    "GiantPriceMeter": [
      ["block", "#f1c40f", [1.2, 0.4, 2.0], [0, 0, 1.0], {{"metal": true, "glow": 0.4}}]
    ]
  }},
  "places": {{
    "Street": {{
      "kind": "outdoor",
      "wall": "#74b9ff",
      "lower": "#dfe6e9",
      "floor": "asphalt",
      "floor_color": "#3d3d3d",
      "props": [
        ["GiantPriceMeter", 0.0, 2.8, 0, {{"name": "GiantPriceMeter"}}],
        ["bench", -2.8, 2.2, 0],
        ["lamp_post", 3.2, 2.5, 0],
        ["tree", -3.8, 3.2, 0],
        ["tree", 3.8, 3.4, 0]
      ]
    }}
  }}
}}"""

    assets = call_gemini_json_defensive(api_key, stage2_prompt, stage_label="Stage2-Locations")

    # =========================================================================
    # STAGE 3: Solo Blocking, Walking Paths & Dynamic Camera Cuts
    # =========================================================================
    stage3_prompt = f"""You are the Lead 3D Animator & Cinematographer for this solo storytelling video.
Convert EVERY beat in the Story Bible into a dynamic shot starring ONLY `Leo` (`subject: "Leo"`), with real walking trajectories (`at` -> `walkTo`), expressive animations, and varied camera cuts.

STORY BIBLE:
{json.dumps(bible, indent=2)}

CUSTOM PROPS:
{json.dumps(list((assets.get("things") or {}).keys()))}

RULES:
1. Only include `"Leo"` in `"actors"` and always set `"subject": "Leo"`.
2. Whenever `Leo` moves, sneaks, walks, runs, or enters a new room, set `"anim": "walk"` or `"run"` AND distinct `"at": [x1, y1]` and `"walkTo": [x2, y2]` coordinates!
3. Alternate `"cam"` across consecutive shots (`mcu`, `cu`, `ws`, `low`, `ms`, `ins`).
4. ALLOWED ANIMS: {json.dumps(sorted(VALID_ANIMS))}.
5. ALLOWED FACES: {json.dumps(sorted(VALID_FACES))}.

Return ONLY valid JSON:
{{
  "music": [[0, "playful"], [0.45, "suspense"], [0.75, "hit"], [0.85, "triumph"]],
  "shots": [
    {{
      "set": "{random_seed_sets[0]}",
      "mood": "sunny",
      "cam": "mcu",
      "move": "crash_in",
      "subject": "Leo",
      "text": "In my town, every word you speak costs ten dollars!",
      "sfx": ["whoosh@0.0"],
      "actors": [
        {{"who": "Leo", "at": [-1.2, 0.0], "walkTo": [0.2, 0.3], "yaw": 20, "anim": "walk", "face": "shock", "talk": [0.0, 1.6]}}
      ]
    }}
  ]
}}"""

    choreography = call_gemini_json_defensive(api_key, stage3_prompt, stage_label="Stage3-SoloBlocking")

    return {
        "title": bible.get("title", "In My Town Every Word Costs $10!"),
        "caption": bible.get("caption", "In my town talking makes you broke! #roblox #storytime #shorts #reels #fyp"),
        "keys": bible.get("keys", ["TOWN", "WORDS", "COST", "BROKE", "SILENT", "MILLION"]),
        "music": choreography.get("music", [[0, "playful"], [0.45, "suspense"], [0.75, "hit"], [0.85, "triumph"]]),
        "things": assets.get("things") or {},
        "places": assets.get("places") or {},
        "cast": build_solo_hero_cast(),
        "shots": choreography.get("shots") or [],
        "model_used": choreography.get("_model_used", "gemini-solo-director"),
    }


def build_offline_solo_story() -> dict:
    beats = [
        ("Street", "sunny", "mcu", "crash_in", "In my town, every word you speak costs ten dollars!", "point", "shock", ["whoosh@0.0"], None),
        ("Street", "sunny", "ws", "push", "I checked my wallet and only had five bucks left!", "facepalm", "worried", ["pop@0.0"], None),
        ("Classroom", "sunny", "ws", "reveal_push", "So I walked into school without saying a single word!", "walk", "think", ["whoosh@0.0"], None),
        ("Classroom", "sunny", "cu", "push", "Everyone tried to trick me into answering questions!", "headshake", "smug", ["ding@0.1"], None),
        ("Bedroom", "sunny", "ms", "crash_in", "I went back to my room and won a million dollars!", "jump_joy", "laugh", ["cash@0.0"], None),
    ]
    shots = []
    for st, md, cm, mv, txt, anim, face, sfx, focus_thing in beats:
        sh = {
            "set": st, "mood": md, "cam": cm, "move": mv, "subject": "Leo", "text": txt, "sfx": sfx,
            "actors": [{"who": "Leo", "at": [-1.2, 0.0], "walkTo": [0.3, 0.2], "yaw": 18, "anim": anim, "face": face, "talk": [0.0, 1.6]}],
        }
        if focus_thing:
            sh["focus"] = focus_thing
        shots.append(sh)

    return {
        "title": "In My Town Every Word Costs $10!",
        "caption": "In my town talking makes you broke! #roblox #storytime #shorts #reels #fyp",
        "keys": ["TOWN", "WORDS", "COST", "SCHOOL", "SILENT", "MILLION"],
        "music": [[0, "playful"], [0.4, "suspense"], [0.75, "hit"], [0.85, "triumph"]],
        "things": {},
        "places": {
            "Street": {
                "kind": "outdoor",
                "wall": "#74b9ff",
                "lower": "#dfe6e9",
                "floor": "asphalt",
                "floor_color": "#3d3d3d",
                "props": [
                    ["bench", -2.8, 2.2, 0],
                    ["lamp_post", 3.2, 2.5, 0],
                    ["tree", -3.8, 3.2, 0],
                    ["tree", 3.8, 3.4, 0],
                ],
            },
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
                    ["bed", -3.4, 3.2, 90],
                    ["desk", 3.5, 2.5, -90],
                    ["rug", 0.0, 0.5, 0],
                    ["floor_lamp", -4.1, -1.0, 0],
                ],
            },
        },
        "shots": shots,
        "cast": build_solo_hero_cast(),
    }


def main(project_dir: str):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    os.makedirs(project_dir, exist_ok=True)
    bp, corpus_block = load_training_context()
    theme = os.environ.get("STORY_THEME", "").strip()

    try:
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY empty")
        story = run_gemini_solo_director(api_key, theme, bp, corpus_block)
    except Exception as e:
        print(f"[WARN] Gemini Solo Director fallback engaged ({e}); using offline solo story.", flush=True)
        story = build_offline_solo_story()

    story["cast"] = build_solo_hero_cast()
    custom_things = set((story.get("things") or {}).keys())
    shots = story.get("shots")
    if not isinstance(shots, list) or len(shots) < 4:
        story = build_offline_solo_story()
        shots = story["shots"]

    available_sets = list(dict.fromkeys(list((story.get("places") or {}).keys()) + RICH_SETS))

    t_cursor = 0.0
    prev_cam = None
    cam_cycle = ["mcu", "cu", "ws", "ms", "low", "cu", "ws", "mcu"]

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
        sh["subject"] = "Leo"

        words_cnt = len(re.findall(r"\w+", sh.get("text", "")))
        beat_dur = max(1.25, min(2.5, round(words_cnt / 4.2, 2)))
        sh["t0"] = round(t_cursor, 2)
        t_cursor += beat_dur
        sh["t1"] = round(t_cursor, 2)

    story["shots"] = choreograph_solo_storyteller(shots, available_sets)
    story["dur"] = round(t_cursor, 2)

    with open(os.path.join(project_dir, "timed.json"), "w", encoding="utf-8") as f:
        json.dump(story, f, indent=2)

    with open(os.path.join(project_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "title": story.get("title", "In My Town Story"),
                "caption": story.get("caption", "#roblox #storytime #shorts #reels"),
                "reference_blueprint": bp.get("reel_id", "none"),
                "custom_things_built": sorted(custom_things),
                "model_used": story.get("model_used", "offline_fallback"),
            },
            f,
            indent=2,
        )

    print(
        f"[SoloDirector] Built {len(story['shots'])} shots across {sorted({s['set'] for s in story['shots']})} | "
        f"speaker=Leo (solo) | model={story.get('model_used')}",
        flush=True,
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python auto/generate_story.py <PROJECT_DIR>")
    main(os.path.abspath(sys.argv[1]))
