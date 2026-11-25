import glob
import json
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
    "Store", "Classroom", "Office", "LivingRoom", "Kitchen", "Bedroom",
]

OUTFIT_PALETTES = [
    {"skin": [0.95, 0.78, 0.62], "shirt": [0.12, 0.45, 0.95], "pants": [0.15, 0.18, 0.25], "hair_color": [0.12, 0.08, 0.05]},
    {"skin": [0.88, 0.68, 0.50], "shirt": [0.92, 0.22, 0.25], "pants": [0.12, 0.14, 0.20], "hair_color": [0.08, 0.06, 0.05]},
    {"skin": [0.55, 0.36, 0.24], "shirt": [0.15, 0.78, 0.42], "pants": [0.20, 0.22, 0.28], "hair_color": [0.06, 0.05, 0.05]},
    {"skin": [0.96, 0.82, 0.68], "shirt": [0.95, 0.72, 0.12], "pants": [0.18, 0.25, 0.45], "hair_color": [0.45, 0.25, 0.10]},
    {"skin": [0.76, 0.54, 0.38], "shirt": [0.62, 0.20, 0.88], "pants": [0.14, 0.14, 0.18], "hair_color": [0.10, 0.07, 0.05]},
]

VALID_CAMS = {"ecu", "cu", "mcu", "ms", "mls", "ws", "low", "high", "ots", "two", "ews", "ground", "pov"}
VALID_MOVES = {"crash_in", "push", "reveal_push", "creep", "drift", "lock"}
VALID_MOODS = {"sunny", "sunset", "storm", "night"}
VALID_ANIMS = {
    "idle", "talk", "walk", "run", "nod", "headshake", "flinch",
    "slump", "jump_joy", "shock", "surrender", "what", "facepalm", "clap",
}
# Exact shape-key expressions supported by kit/blox/chars.py
VALID_FACES = {"neutral", "smile", "angry", "scared", "worried", "think", "shock", "smug", "sad"}
FACE_ALIASES = {
    "happy": "smile",
    "joy": "smile",
    "excited": "smile",
    "laugh": "smile",
    "grin": "smile",
    "fear": "scared",
    "terrified": "scared",
    "surprised": "shock",
    "amazed": "shock",
    "mad": "angry",
    "furious": "angry",
    "upset": "sad",
    "crying": "sad",
    "confused": "think",
    "nervous": "worried",
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


def load_training_context() -> tuple[dict, str]:
    blueprints = sorted(glob.glob(os.path.join(BLUEPRINT_DIR, "*.json")))
    bp = json.load(open(random.choice(blueprints), encoding="utf-8")) if blueprints else {}

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

    return bp, corpus_block


def build_offline_fast_story(palettes: list[dict]) -> dict:
    beats = [
        ("Street", "sunny", "mcu", "crash_in", "Alex", "STOP scrolling! Never touch a parked supercar!", "shock", "shock", ["whoosh@0.0"]),
        ("Street", "sunny", "two", "push", "Jax", "Jax dared me to open the door.", "talk", "smug", []),
        ("Street", "sunny", "cu", "creep", "Alex", "He said the owner was miles away.", "talk", "angry", []),
        ("Street", "sunny", "low", "crash_in", "Alex", "The second I touched it, alarms screamed!", "what", "shock", ["boom@0.0"]),
        ("Street", "sunny", "ws", "drift", "Maya", "Maya yelled from across the town square!", "run", "scared", []),
        ("Street", "storm", "mcu", "crash_in", "Alex", "Dark storm clouds rolled in instantly!", "flinch", "scared", ["impact@0.0"]),
        ("Street", "storm", "ecu", "push", "Alex", "Footsteps echoed right behind my back!", "run", "worried", []),
        ("TownPool", "sunny", "ws", "reveal_push", "Alex", "I sprinted straight past the town pool!", "run", "shock", ["whoosh@0.0"]),
        ("TownPool", "sunny", "mcu", "push", "Jax", "Jax laughed thinking I was busted now.", "clap", "smug", []),
        ("TownPool", "sunny", "low", "creep", "Alex", "Then a mystery man stepped forward.", "slump", "worried", []),
        ("TownPool", "sunny", "cu", "crash_in", "Maya", "Wait—that wasn't even the car's owner!", "shock", "shock", ["ding@0.1"]),
        ("TownPool", "sunny", "two", "push", "Alex", "Jax hired an actor to prank me!", "angry", "angry", []),
        ("MusicRow", "sunny", "ws", "reveal_push", "Alex", "So I turned the tables on Music Row!", "walk", "angry", ["whoosh@0.0"]),
        ("MusicRow", "sunny", "mcu", "push", "Jax", "Jax froze when the real owner arrived.", "headshake", "scared", []),
        ("MusicRow", "sunny", "low", "crash_in", "Alex", "He saw Jax holding the fake keys!", "run", "shock", ["riser@0.0"]),
        ("MusicRow", "sunny", "ecu", "crash_in", "Jax", "Jax tried to explain, completely trapped!", "surrender", "scared", []),
        ("MusicRow", "sunny", "ws", "crash_in", "Alex", "The owner handed ME the VIP pass!", "jump_joy", "smile", ["boom@0.0"]),
        ("MusicRow", "sunny", "mcu", "push", "Jax", "Jax dropped his jaw in total shock.", "facepalm", "sad", ["pop@0.0"]),
        ("MusicRow", "sunny", "two", "drift", "Maya", "Maya couldn't stop laughing at his face.", "clap", "smile", ["cash@0.0"]),
        ("MusicRow", "sunny", "cu", "push", "Alex", "Never prank someone smarter than you!", "nod", "smile", ["ding@0.1"]),
    ]
    shots = []
    for st, md, cm, mv, subj, txt, anim, face, sfx in beats:
        other = "Jax" if subj != "Jax" else "Alex"
        actors = [
            {"who": subj, "at": [-1.4, 0], "yaw": 15, "anim": anim, "face": face, "talk": [0.0, 1.6]},
            {"who": other, "at": [1.6, 0.4], "yaw": -20, "anim": "idle", "face": "smug" if other == "Jax" else "neutral"},
        ]
        if st in ("Street", "TownPool", "MusicRow"):
            actors.append({"who": "Maya", "at": [3.2, -0.8], "yaw": -35, "anim": "idle", "face": "shock"})
        shots.append({
            "set": st,
            "mood": md,
            "cam": cm,
            "move": mv,
            "subject": subj,
            "text": txt,
            "sfx": sfx,
            "actors": actors,
        })
    return {
        "title": "I Touched a Parked Supercar in Town!",
        "caption": "He tried to prank me in front of the whole town! #roblox #storytime #shorts #reels #fyp",
        "keys": ["STOP", "SUPERCAR", "ALARMS", "PRANK", "TRAPPED", "NEVER"],
        "music": [[0, "playful"], [0.35, "suspense"], [0.75, "hit"], [0.85, "triumph"]],
        "cast": {
            "Alex": {"height": 1.0, **palettes[0]},
            "Jax": {"height": 1.05, **palettes[1]},
            "Maya": {"height": 0.96, **palettes[2]},
        },
        "shots": shots,
    }


def call_gemini_json_defensive(api_key: str, prompt: str) -> dict:
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
                with urllib.request.urlopen(req, timeout=90) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                txt = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = extract_json_safely(txt)
                parsed["model_used"] = model
                return parsed
            except urllib.error.HTTPError as e:
                last_err = f"{model} HTTP {e.code}"
                if e.code == 429 and attempt == 0:
                    print(f"[RateLimit] {model} hit 429; waiting 6s then trying next...", flush=True)
                    time.sleep(6)
                    continue
                break
            except Exception as e:
                last_err = f"{model} {e}"
                break

    raise RuntimeError(f"All models exhausted ({last_err})")


def main(project_dir: str):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    os.makedirs(project_dir, exist_ok=True)
    bp, corpus_block = load_training_context()
    theme = os.environ.get("STORY_THEME", "").strip()
    palettes = random.sample(OUTFIT_PALETTES, 3)

    prompt = f"""You are a viral Roblox 3D Reels director trained on our harvested @craftee_films Instagram script & visual vault.

{corpus_block}

SELECTED VISUAL & CAMERA BLUEPRINT FROM @craftee_films:
{json.dumps(bp, indent=2) if bp else "Fast-paced 24-to-28-shot Roblox comedic/dramatic twist Reel with 1.6s cuts, punchy 3-second hook, escalating stakes, and rich town/street sets."}

OPTIONAL USER THEME: "{theme or 'Write a brand-new original viral town/street twist story matching the exact hook punchiness, fast dialogue rhythm, and rapid visual cuts of the @craftee_films scripts above (never copy any script word-for-word).'}"

STRICT PRODUCTION RULES:
1. TOTAL LENGTH: 210 to 250 words across 24 to 28 rapid shots (each shot is 1 short punchy sentence, ~8-10 words, cutting every ~1.6 to 1.85 seconds).
2. RICH TOWN & MULTI-LOCATION SETS: Use 2 to 3 DIFFERENT lively town sets from: {json.dumps(RICH_SETS)} (prefer "Street", "TownPool", "MusicRow", "Park", "Store" for outdoor town cars, buildings, and crowds).
3. DYNAMIC CAMERA WORK: Never repeat the same angle twice in a row! Alternate cam ({json.dumps(sorted(VALID_CAMS))}) and move ({json.dumps(sorted(VALID_MOVES))}).
4. ALLOWED ACTOR FACES ONLY: {json.dumps(sorted(VALID_FACES))} (NEVER output "happy" — use "smile").
5. 3-CHARACTER TOWN CAST: Use Alex, Jax, and Maya with 2-3 actors visible in wide/two shots so the town feels alive:
   - Alex: {json.dumps(palettes[0])}
   - Jax: {json.dumps(palettes[1])}
   - Maya: {json.dumps(palettes[2])}

Return ONLY valid JSON matching:
{{
  "title": "Catchy viral title",
  "caption": "Short Instagram Reels caption with 5 viral hashtags",
  "keys": ["UPPERCASE", "IMPACT", "WORDS", "TO", "HIGHLIGHT", "YELLOW"],
  "music": [[0, "playful"], [0.45, "suspense"], [0.75, "hit"], [0.85, "triumph"]],
  "cast": {{
    "Alex": {{"height": 1.0, "skin": {json.dumps(palettes[0]['skin'])}, "shirt": {json.dumps(palettes[0]['shirt'])}, "pants": {json.dumps(palettes[0]['pants'])}, "hair_color": {json.dumps(palettes[0]['hair_color'])}}},
    "Jax": {{"height": 1.05, "skin": {json.dumps(palettes[1]['skin'])}, "shirt": {json.dumps(palettes[1]['shirt'])}, "pants": {json.dumps(palettes[1]['pants'])}, "hair_color": {json.dumps(palettes[1]['hair_color'])}}},
    "Maya": {{"height": 0.96, "skin": {json.dumps(palettes[2]['skin'])}, "shirt": {json.dumps(palettes[2]['shirt'])}, "pants": {json.dumps(palettes[2]['pants'])}, "hair_color": {json.dumps(palettes[2]['hair_color'])}}}
  }},
  "shots": [
    {{
      "set": "Street",
      "mood": "sunny",
      "cam": "mcu",
      "move": "crash_in",
      "subject": "Alex",
      "text": "Punchy hook line under 10 words!",
      "sfx": ["whoosh@0.0"],
      "actors": [
        {{"who": "Alex", "at": [-1.5, 0], "yaw": 15, "anim": "shock", "face": "shock", "talk": [0.0, 1.8]}},
        {{"who": "Jax", "at": [1.8, 0.5], "yaw": -25, "anim": "idle", "face": "smug"}}
      ]
    }}
  ]
}}"""

    try:
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY empty")
        story = call_gemini_json_defensive(api_key, prompt)
    except Exception as e:
        print(f"[WARN] Story LLM fallback engaged ({e}); using offline 20-shot fast-cut story.", flush=True)
        story = build_offline_fast_story(palettes)

    valid_sets = set(RICH_SETS)
    cast = story.get("cast")
    if not isinstance(cast, dict) or not cast:
        story["cast"] = {
            "Alex": {"height": 1.0, **palettes[0]},
            "Jax": {"height": 1.05, **palettes[1]},
            "Maya": {"height": 0.96, **palettes[2]},
        }
    cast_names = list(story["cast"].keys())

    shots = story.get("shots")
    if not isinstance(shots, list) or len(shots) < 4:
        story = build_offline_fast_story(palettes)
        shots = story["shots"]

    t_cursor = 0.0
    prev_cam = None
    cam_cycle = ["mcu", "ws", "low", "cu", "two", "ots", "ecu", "ms"]
    for idx, sh in enumerate(shots):
        if sh.get("set") not in valid_sets:
            sh["set"] = ["Street", "TownPool", "MusicRow"][(idx // 8) % 3]
        if sh.get("mood") not in VALID_MOODS:
            sh["mood"] = "sunny"
        if sh.get("cam") not in VALID_CAMS or sh.get("cam") == prev_cam:
            sh["cam"] = cam_cycle[idx % len(cam_cycle)]
        prev_cam = sh["cam"]
        if sh.get("move") not in VALID_MOVES:
            sh["move"] = "crash_in" if idx % 4 == 0 else "push"
        if sh.get("subject") not in cast_names:
            sh["subject"] = cast_names[0]

        sh["t0"] = round(t_cursor, 2)
        t_cursor += 1.85
        sh["t1"] = round(t_cursor, 2)

        actors = sh.get("actors")
        if not isinstance(actors, list) or not actors:
            sh["actors"] = [
                {"who": cast_names[0], "at": [-1.4, 0], "yaw": 15, "anim": "talk", "face": "neutral", "talk": [0.0, 1.6]},
            ]
        else:
            for act in actors:
                if act.get("who") not in cast_names:
                    act["who"] = cast_names[0]
                if act.get("anim") not in VALID_ANIMS:
                    act["anim"] = "talk"
                act["face"] = sanitize_face(act.get("face"))
                if isinstance(act.get("faceAt"), list):
                    act["faceAt"] = [[pair[0], sanitize_face(pair[1])] for pair in act["faceAt"] if isinstance(pair, list) and len(pair) >= 2]

    story["dur"] = round(t_cursor, 2)

    with open(os.path.join(project_dir, "timed.json"), "w", encoding="utf-8") as f:
        json.dump(story, f, indent=2)

    with open(os.path.join(project_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "title": story.get("title", "Blox Story"),
                "caption": story.get("caption", "#roblox #storytime #shorts #reels"),
                "reference_blueprint": bp.get("reel_id", "none"),
                "model_used": story.get("model_used", "offline_fallback"),
            },
            f,
            indent=2,
        )

    print(
        f"[CloneStory] Generated {len(story['shots'])} rapid-cut shots "
        f"(blueprint={bp.get('reel_id', 'default')}, model={story.get('model_used', 'offline')})",
        flush=True,
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python auto/generate_story.py <PROJECT_DIR>")
    main(os.path.abspath(sys.argv[1]))
