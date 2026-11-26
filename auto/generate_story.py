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

# Persistent family, school & friend cast universe (male & female) + bright sRGB colors
DEFAULT_CAST_UNIVERSE = {
    "Leo": {"height": 1.0, "gender": "male", "role": "main_character", "skin": "#f5c29b", "hair": "spiky", "hair_color": "#261b14", "shirt": "#1e73f2", "pants": "#1b2234"},
    "Maya": {"height": 0.94, "gender": "female", "role": "sister", "skin": "#f7c7a3", "hair": "pigtails", "hair_color": "#3b2316", "shirt": "#ff4f8b", "pants": "#2a2d43"},
    "Max": {"height": 1.05, "gender": "male", "role": "brother", "skin": "#e8b087", "hair": "curly", "hair_color": "#1e1612", "shirt": "#22b855", "pants": "#1d2432"},
    "Mom": {"height": 1.02, "gender": "female", "role": "mother", "skin": "#f5c29b", "hair": "bun", "hair_color": "#4a2c18", "shirt": "#9b51e0", "pants": "#25293a"},
    "Dad": {"height": 1.08, "gender": "male", "role": "father", "skin": "#eab38a", "hair": "short", "hair_color": "#2d221c", "shirt": "#2f80ed", "pants": "#1f2533"},
    "Uncle_Sam": {"height": 1.06, "gender": "male", "role": "uncle", "skin": "#e2a77d", "hair": "short", "hair_color": "#5c5856", "shirt": "#f2994a", "pants": "#2c3342"},
    "Ms_Clara": {"height": 1.02, "gender": "female", "role": "teacher", "skin": "#f6c9a6", "hair": "long", "hair_color": "#3d2516", "shirt": "#27ae60", "pants": "#1e2430"},
    "Zoe": {"height": 0.97, "gender": "female", "role": "friend_female", "skin": "#c68658", "hair": "long", "hair_color": "#191412", "shirt": "#f2c94c", "pants": "#232938"},
    "Sam": {"height": 1.0, "gender": "male", "role": "friend_male", "skin": "#8d5524", "hair": "curly", "hair_color": "#141110", "shirt": "#eb5757", "pants": "#1c2230"},
}

BACKGROUND_CROWD_NPCS = {
    "Townie_1": {"height": 1.0, "skin": "#f2be96", "hair": "short", "hair_color": "#2b1d14", "shirt": "#00a8ff", "pants": "#2f3640"},
    "Townie_2": {"height": 0.98, "skin": "#d99b6c", "hair": "long", "hair_color": "#3d2314", "shirt": "#fbc531", "pants": "#192a56"},
    "Townie_3": {"height": 1.03, "skin": "#f5c7a3", "hair": "curly", "hair_color": "#1e272e", "shirt": "#4cd137", "pants": "#2f3640"},
}

VALID_CAMS = {"ecu", "cu", "mcu", "ms", "mls", "ws", "low", "high", "ots", "two", "ews", "ground", "pov", "ins"}
VALID_MOVES = {"crash_in", "push", "reveal_push", "creep", "drift", "lock"}
VALID_MOODS = {"sunny", "sunset", "storm", "night"}
VALID_ANIMS = {
    "idle", "talk", "walk", "run", "nod", "headshake", "flinch",
    "slump", "jump_joy", "shock", "surrender", "what", "facepalm", "clap",
    "point", "hold_hands", "wave", "cheer",
}
VALID_FACES = {"neutral", "smile", "angry", "scared", "worried", "think", "shock", "smug", "sad"}
FACE_ALIASES = {
    "happy": "smile", "joy": "smile", "excited": "smile", "laugh": "smile", "grin": "smile",
    "fear": "scared", "terrified": "scared", "surprised": "shock", "amazed": "shock",
    "mad": "angry", "furious": "angry", "upset": "sad", "crying": "sad",
    "confused": "think", "nervous": "worried",
}


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
            print(
                f"[Vault] Loaded visual_bible.json ({visual_bible.get('total_reels_trained_on', 0)} reels, "
                f"{visual_bible.get('total_frames_analyzed_by_vision', 0)} frames analyzed)",
                flush=True,
            )
        except Exception as e:
            print(f"[Vault WARN] Could not parse visual_bible.json: {e}", flush=True)

    corpus_block = ""
    if os.path.exists(CORPUS_PATH):
        corpus = json.load(open(CORPUS_PATH, encoding="utf-8"))
        scripts = corpus.get("scripts", [])
        hooks = corpus.get("all_hooks", [])
        sample_scripts = random.sample(scripts, min(8, len(scripts))) if scripts else []
        sample_hooks = random.sample(hooks, min(15, len(hooks))) if hooks else []
        corpus_block = (
            f"HARVESTED @craftee_films VAULT STATS ({corpus.get('total_scripts_collected', 0)} real Instagram scripts, "
            f"avg {corpus.get('avg_words_per_sec', 3.2)} words/sec, "
            f"avg {corpus.get('avg_cuts_per_video', 24)} camera cuts/video):\n"
            f"PROVEN 0-3s OPENING HOOKS FROM @craftee_films:\n"
            + "\n".join(f"- {h}" for h in sample_hooks)
            + "\n\nFULL HARVESTED @craftee_films SCRIPTS (MATCH THIS EXACT RHYTHM, TONE & TWIST PACING):\n"
            + "\n---\n".join(
                f"[{s['id']} | {s['total_cuts']} cuts | {s['words_per_sec']} wps]: {s['full_script'][:700]}"
                for s in sample_scripts
            )
        )
        print(
            f"[Vault] Loaded {len(scripts)} Instagram scripts & {len(blueprints)} camera blueprints from {VAULT_DIR}",
            flush=True,
        )
    else:
        print(f"[Vault WARN] {CORPUS_PATH} not found; proceeding with default style rules.", flush=True)

    return bp, corpus_block, visual_bible


def enforce_zero_clash_choreography(actors: list[dict], shot_set: str) -> list[dict]:
    """Guarantees zero character clipping, enforces 3.4-stud minimum separation, and sets exact 2.15-stud hand-holding offsets."""
    if not actors:
        return actors

    # 1. Handle hold_hands pairs first so they stand cleanly side-by-side at 2.15 studs facing the same direction
    holding = [a for a in actors if a.get("anim") == "hold_hands"]
    if len(holding) >= 2:
        a1, a2 = holding[0], holding[1]
        cx = (float(a1.get("at", [-1.1, 0])[0]) + float(a2.get("at", [1.1, 0])[0])) / 2.0
        cy = float(a1.get("at", [0, 0])[1])
        a1["at"] = [round(cx - 1.075, 2), round(cy, 2)]
        a2["at"] = [round(cx + 1.075, 2), round(cy, 2)]
        shared_yaw = float(a1.get("yaw", 0))
        a1["yaw"] = shared_yaw
        a2["yaw"] = shared_yaw

    # 2. Enforce >= 3.4 studs minimum Euclidean distance between all non-hand-holding actors
    min_dist = 3.4
    for i in range(len(actors)):
        pos_i = actors[i].get("at", [0.0, 0.0])
        xi, yi = float(pos_i[0]), float(pos_i[1])
        for j in range(i):
            if actors[i].get("anim") == "hold_hands" and actors[j].get("anim") == "hold_hands":
                continue
            pos_j = actors[j].get("at", [0.0, 0.0])
            xj, yj = float(pos_j[0]), float(pos_j[1])
            dx, dy = xi - xj, yi - yj
            dist = math.hypot(dx, dy)
            if dist < min_dist:
                if dist < 0.01:
                    dx, dy, dist = 1.0, 0.15, 1.011
                push = (min_dist - dist) + 0.25
                xi = round(xi + (dx / dist) * push, 2)
                yi = round(yi + (dy / dist) * push, 2)
                # Keep inside safe clear zone
                xi = max(-6.2, min(6.2, xi))
                yi = max(-3.2, min(5.5, yi))
                actors[i]["at"] = [xi, yi]

    # 3. Auto-orient speakers/listeners toward each other when facing each other in two-shots
    if len(actors) >= 2 and actors[0].get("anim") != "hold_hands":
        p0 = actors[0]["at"]
        p1 = actors[1]["at"]
        # In Blox Studio, yaw 0 faces -Y (towards camera). Compute natural angled turn towards partner.
        dx01 = p1[0] - p0[0]
        dy01 = p1[1] - p0[1]
        if abs(dx01) > 0.5:
            # Face partially toward camera (-Y) and partially toward the other character
            yaw0 = round(math.degrees(math.atan2(dx01, max(1.2, -dy01 + 1.8))), 1)
            yaw1 = round(math.degrees(math.atan2(-dx01, max(1.2, dy01 + 1.8))), 1)
            actors[0]["yaw"] = max(-65.0, min(65.0, yaw0))
            actors[1]["yaw"] = max(-65.0, min(65.0, yaw1))

    return actors


def build_offline_fast_story(cast_universe: dict) -> dict:
    beats = [
        ("Street", "sunny", "mcu", "crash_in", "Leo", "STOP scrolling! Look at this glowing golden crown!", "shock", "shock", ["whoosh@0.0"], None),
        ("Street", "sunny", "ins", "push", "Leo", "It was sitting right on the sidewalk!", "talk", "shock", ["ding@0.1"], "GoldenCrown"),
        ("Street", "sunny", "two", "push", "Maya", "Maya warned me it belonged to the Mayor!", "talk", "worried", [], None),
        ("Street", "sunny", "low", "crash_in", "Max", "Max dared me to put it on anyway!", "point", "smug", ["pop@0.0"], None),
        ("Street", "sunny", "ws", "drift", "Leo", "The second I touched it, sirens echoed!", "what", "shock", ["boom@0.0"], None),
        ("Classroom", "sunny", "mcu", "crash_in", "Ms_Clara", "Ms. Clara spotted the crown in my backpack!", "shock", "angry", ["impact@0.0"], None),
        ("Classroom", "sunny", "two", "push", "Leo", "I told her I was returning it!", "surrender", "scared", [], None),
        ("Park", "sunny", "ws", "reveal_push", "Uncle_Sam", "Then Uncle Sam showed up with a map!", "wave", "smile", ["whoosh@0.0"], None),
        ("Park", "sunny", "two", "push", "Maya", "Maya and I held hands crossing the bridge.", "hold_hands", "smile", [], None),
        ("Park", "sunny", "low", "creep", "Sam", "Sam yelled that the Mayor was right behind us!", "flinch", "scared", ["riser@0.0"], None),
        ("MusicRow", "sunny", "ws", "crash_in", "Leo", "We handed the Golden Crown straight back!", "jump_joy", "smile", ["boom@0.0"], None),
        ("MusicRow", "sunny", "two", "push", "Zoe", "The whole town cheered for our honesty!", "cheer", "smile", ["cash@0.0"], None),
    ]
    shots = []
    for st, md, cm, mv, subj, txt, anim, face, sfx, focus_thing in beats:
        actors = [
            {"who": subj, "at": [-1.8, 0.0], "yaw": 20, "anim": anim, "face": face, "talk": [0.0, 1.6]},
            {"who": "Maya" if subj != "Maya" else "Leo", "at": [1.8, 0.2], "yaw": -20, "anim": "hold_hands" if anim == "hold_hands" else "idle", "face": "smile" if anim == "hold_hands" else "shock"},
        ]
        if cm == "ws":
            actors.append({"who": "Townie_1", "at": [-4.5, 4.6], "yaw": 0, "anim": "idle", "face": "neutral"})
            actors.append({"who": "Townie_2", "at": [4.5, 4.8], "yaw": 0, "anim": "idle", "face": "smile"})
        sh = {
            "set": st,
            "mood": md,
            "cam": cm,
            "move": mv,
            "subject": subj,
            "text": txt,
            "sfx": sfx,
            "actors": actors,
        }
        if focus_thing:
            sh["focus"] = focus_thing
        shots.append(sh)

    cast_out = {k: {kk: vv for kk, vv in v.items() if kk in ("height", "skin", "shirt", "pants", "hair", "hair_color", "extras")} for k, v in cast_universe.items()}
    cast_out.update(BACKGROUND_CROWD_NPCS)

    return {
        "title": "I Found the Mayor's Lost Golden Crown!",
        "caption": "We returned it in front of the whole town! #roblox #storytime #shorts #reels #fyp",
        "keys": ["STOP", "CROWN", "MAYOR", "SIRENS", "HONESTY", "TOWN"],
        "music": [[0, "playful"], [0.4, "suspense"], [0.75, "hit"], [0.85, "triumph"]],
        "things": {
            "GoldenCrown": [
                ["tube", "#ffd700", 0.55, 0.35, [0, 0, 0.2], {"metal": True, "glow": 0.4}],
                ["cone", "#ffd700", 0.16, 0.35, [0.42, 0, 0.52], {"metal": True}],
                ["cone", "#ffd700", 0.16, 0.35, [-0.42, 0, 0.52], {"metal": True}],
                ["cone", "#ffd700", 0.16, 0.35, [0, -0.42, 0.52], {"metal": True}],
                ["ball", "#ff2e63", 0.12, [0, -0.55, 0.22], {"glow": 1.5}],
            ]
        },
        "places": {
            "Street": {
                "kind": "outdoor",
                "ground": "asphalt",
                "backdrop": "city",
                "props": [
                    ["GoldenCrown", 0.0, 1.5, 0, {"name": "GoldenCrown", "in_clear": True}],
                    ["car", -9.5, 5.5, 0],
                    ["lamp_post", 9.0, 4.0, 0],
                ],
            }
        },
        "shots": shots,
        "cast": cast_out,
    }


def call_gemini_json_defensive(api_key: str, prompt: str) -> dict:
    last_err = None
    for model in MODELS:
        gen_cfg = {"temperature": 0.82}
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
                parsed["model_used"] = model
                return parsed
            except urllib.error.HTTPError as e:
                last_err = f"{model} HTTP {e.code}"
                if e.code == 429 and attempt == 0:
                    print(f"[RateLimit] {model} hit 429; waiting 8s then trying next...", flush=True)
                    time.sleep(8)
                    continue
                break
            except Exception as e:
                last_err = f"{model} {e}"
                break

    raise RuntimeError(f"All models exhausted ({last_err})")


def main(project_dir: str):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    os.makedirs(project_dir, exist_ok=True)
    bp, corpus_block, visual_bible = load_training_context()
    theme = os.environ.get("STORY_THEME", "").strip()

    cast_universe = visual_bible.get("canonical_cast_universe") or DEFAULT_CAST_UNIVERSE
    anti_clash_rules = visual_bible.get("anti_clash_and_choreography_rules", {})
    vision_standards = visual_bible.get("vision_distilled_standards", {})

    prompt = f"""You are the Showrunner & 3D Roblox Reels Director trained on our harvested @craftee_films Instagram video & frame vault.

{corpus_block}

MASTER VISUAL BIBLE DISTILLED FROM HARVESTED @craftee_films FRAMES:
{json.dumps(vision_standards, indent=2) if vision_standards else "Bright sRGB daytime colors, clean side-by-side character spacing, rapid 1.75s cuts, rich town/school/home sets, and dramatic prop close-ups."}

SELECTED REEL BLUEPRINT:
{json.dumps(bp, indent=2) if bp else "24-to-28-shot high-energy Roblox story with punchy 3-second hook and twist payoff."}

USER STORY SITUATION / THEME:
"{theme or 'Write a brand-new viral family & school twist Reel starring Leo (main character), his sister Maya, brother Max, Mom, Dad, Uncle_Sam, teacher Ms_Clara, and friends Zoe & Sam, plus any needed situational roles (Officer, Mayor, Chef).'}"

MANDATORY CAST UNIVERSE & CUSTOM CHARACTER RULES:
1. RECURRING FAMILY & SCHOOL UNIVERSE (use bright sRGB hex colors so skin/clothes never render dark or muddy):
{json.dumps(cast_universe, indent=2)}
2. SITUATIONAL / DYNAMIC ROLES: If the story needs an extra character (e.g. Police Officer, Judge, Chef, Principal, Billionaire), add them to `cast` with bright sRGB hex colors, distinct `hair` ("short"|"spiky"|"curly"|"long"|"pigtails"|"bun"), and `gender`.
3. BACKGROUND CROWDS: Include `Townie_1`, `Townie_2`, `Townie_3` in `cast` and place 2-3 of them in wide shots (`cam: "ws"`) at `y >= 4.5` (behind the main characters) so towns, parks, and schools look bustling!

MANDATORY ZERO-CLIPPING & CHOREOGRAPHY RULES:
1. MINIMUM SEPARATION: Keep foreground actors at least 3.6 studs apart (e.g., actor 1 at `[-1.9, 0.0]`, actor 2 at `[1.9, 0.2]`) so arms and heads NEVER clip inside each other!
2. HOLDING HANDS (`anim: "hold_hands"`): When two characters walk or stand holding hands, place them side-by-side at `x = -1.08` and `x = +1.08` (2.15 studs apart) with matching `yaw: 0`.
3. ALLOWED FACES ONLY: {json.dumps(sorted(VALID_FACES))} (NEVER use "happy" — use "smile").
4. ALLOWED ANIMS ONLY: {json.dumps(sorted(VALID_ANIMS))}.

SELF-BUILT 3D ROBLOX PROPS (`things` + `places` + `cam: "ins"`):
Whenever the story features a key object (e.g. GoldenCrown, MagicChest, SportsCar, Trophy, GiantPizza, SecretPortal, MysteryBox), construct it out of blocky Roblox parts in `things` using:
- `["block", "#hex", [w, d, h], [x, y, z], {{"metal": true, "glow": 0.5}}]`
- `["tube", "#hex", radius, height, [x, y, z]]`
- `["cone", "#hex", radius, height, [x, y, z]]`
- `["ball", "#hex", radius, [x, y, z]]`
Place that prop in `places` under the matching set name (with `"in_clear": true` if in the foreground), and use `"cam": "ins", "focus": "<ThingName>"` on the shot where the narrator reveals or zooms in on it!

Return ONLY valid JSON matching:
{{
  "title": "Catchy viral title",
  "caption": "Short Instagram Reels caption with 5 viral hashtags",
  "keys": ["UPPERCASE", "IMPACT", "WORDS", "TO", "HIGHLIGHT", "YELLOW"],
  "music": [[0, "playful"], [0.45, "suspense"], [0.75, "hit"], [0.85, "triumph"]],
  "things": {{
    "ExampleProp": [
      ["block", "#ffd700", [1.0, 1.0, 0.6], [0, 0, 0.3], {{"metal": true}}]
    ]
  }},
  "places": {{
    "Street": {{
      "kind": "outdoor",
      "ground": "asphalt",
      "backdrop": "city",
      "props": [
        ["ExampleProp", 0.0, 1.8, 0, {{"name": "ExampleProp", "in_clear": true}}],
        ["car", -9.5, 5.5, 0]
      ]
    }}
  }},
  "cast": {{
    "Leo": {{"height": 1.0, "skin": "#f5c29b", "hair": "spiky", "hair_color": "#261b14", "shirt": "#1e73f2", "pants": "#1b2234"}},
    "Maya": {{"height": 0.94, "skin": "#f7c7a3", "hair": "pigtails", "hair_color": "#3b2316", "shirt": "#ff4f8b", "pants": "#2a2d43"}}
  }},
  "shots": [
    {{
      "set": "Street",
      "mood": "sunny",
      "cam": "mcu",
      "move": "crash_in",
      "subject": "Leo",
      "text": "Punchy hook line under 10 words!",
      "sfx": ["whoosh@0.0"],
      "actors": [
        {{"who": "Leo", "at": [-1.9, 0.0], "yaw": 20, "anim": "shock", "face": "shock", "talk": [0.0, 1.75]}},
        {{"who": "Maya", "at": [1.9, 0.2], "yaw": -20, "anim": "idle", "face": "worried"}}
      ]
    }}
  ]
}}"""

    try:
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY empty")
        story = call_gemini_json_defensive(api_key, prompt)
    except Exception as e:
        print(f"[WARN] Story LLM fallback engaged ({e}); using offline family/town story.", flush=True)
        story = build_offline_fast_story(cast_universe)

    # Merge canonical cast + background townies so every character referenced is guaranteed valid
    if not isinstance(story.get("cast"), dict):
        story["cast"] = {}
    for cname, cdata in cast_universe.items():
        if cname not in story["cast"]:
            story["cast"][cname] = {
                k: v for k, v in cdata.items()
                if k in ("height", "skin", "shirt", "pants", "hair", "hair_color", "extras")
            }
    for tname, tdata in BACKGROUND_CROWD_NPCS.items():
        if tname not in story["cast"]:
            story["cast"][tname] = dict(tdata)

    cast_names = list(story["cast"].keys())
    custom_things = set((story.get("things") or {}).keys())

    shots = story.get("shots")
    if not isinstance(shots, list) or len(shots) < 4:
        story = build_offline_fast_story(cast_universe)
        shots = story["shots"]

    t_cursor = 0.0
    prev_cam = None
    cam_cycle = ["mcu", "ws", "low", "cu", "two", "ots", "ecu", "ms"]

    for idx, sh in enumerate(shots):
        if sh.get("set") not in set(RICH_SETS) and sh.get("set") not in (story.get("places") or {}):
            sh["set"] = ["Street", "Classroom", "Park", "LivingRoom"][(idx // 6) % 4]
        if sh.get("mood") not in VALID_MOODS:
            sh["mood"] = "sunny"

        # Preserve `cam: "ins"` when targeting a custom prop in `focus`
        if sh.get("cam") == "ins" and sh.get("focus"):
            pass
        elif sh.get("cam") not in VALID_CAMS or sh.get("cam") == prev_cam:
            sh["cam"] = cam_cycle[idx % len(cam_cycle)]
        prev_cam = sh["cam"]

        if sh.get("move") not in VALID_MOVES:
            sh["move"] = "crash_in" if idx % 4 == 0 else "push"
        if sh.get("subject") not in cast_names:
            sh["subject"] = "Leo" if "Leo" in cast_names else cast_names[0]

        sh["t0"] = round(t_cursor, 2)
        t_cursor += 1.80
        sh["t1"] = round(t_cursor, 2)

        actors = sh.get("actors")
        if not isinstance(actors, list) or not actors:
            sh["actors"] = [
                {"who": sh["subject"], "at": [-1.8, 0.0], "yaw": 18, "anim": "talk", "face": "neutral", "talk": [0.0, 1.6]},
            ]
        else:
            for act in actors:
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
            # Automatically inject 2 background crowd NPCs in wide outdoor shots if not already present
            if sh["cam"] == "ws" and sh["set"] in ("Street", "Park", "TownPool", "MusicRow", "Playground"):
                existing_whos = {a.get("who") for a in actors}
                if "Townie_1" not in existing_whos and len(actors) < 5:
                    actors.append({"who": "Townie_1", "at": [-4.8, 4.8], "yaw": 10, "anim": "idle", "face": "neutral"})
                if "Townie_2" not in existing_whos and len(actors) < 5:
                    actors.append({"who": "Townie_2", "at": [4.8, 5.0], "yaw": -10, "anim": "idle", "face": "smile"})

            sh["actors"] = enforce_zero_clash_choreography(actors, sh["set"])

    story["dur"] = round(t_cursor, 2)

    with open(os.path.join(project_dir, "timed.json"), "w", encoding="utf-8") as f:
        json.dump(story, f, indent=2)

    with open(os.path.join(project_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "title": story.get("title", "Blox Story"),
                "caption": story.get("caption", "#roblox #storytime #shorts #reels"),
                "reference_blueprint": bp.get("reel_id", "none"),
                "visual_bible_reels": visual_bible.get("total_reels_trained_on", 0),
                "custom_things_built": sorted(custom_things),
                "model_used": story.get("model_used", "offline_fallback"),
            },
            f,
            indent=2,
        )

    print(
        f"[CloneStory] Generated {len(story['shots'])} rapid-cut shots "
        f"(bible_reels={visual_bible.get('total_reels_trained_on', 0)}, "
        f"custom_things={sorted(custom_things)}, model={story.get('model_used', 'offline')})",
        flush=True,
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python auto/generate_story.py <PROJECT_DIR>")
    main(os.path.abspath(sys.argv[1]))
