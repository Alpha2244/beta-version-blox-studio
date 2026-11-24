import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request

VALID_SETS = {
    "Street", "Kitchen", "Gym", "MusicRow", "TownPool",
    "Bedroom", "Hallway", "Classroom", "LivingRoom",
    "Store", "Office", "Bathroom", "Park", "Backyard", "Playground",
}
VALID_CAMS = {
    "ews", "ws", "mls", "ms", "two", "mcu", "cu", "ecu",
    "ots", "low", "worm", "ground", "high", "top", "pov", "ins",
}
VALID_MOODS = {"sunny", "storm", "night"}
VALID_MOVES = {"creep", "push", "reveal_push", "crash_in", "drift", "lock"}
VALID_ANIMS = {
    "idle", "talk", "walk", "run", "point", "shrug", "shock", "scared",
    "cheer", "eat", "cross_arms", "think", "sad", "angry", "wave", "sit", "facepalm",
}
VALID_FACES = {
    "neutral", "smile", "grin", "laugh", "shock", "scared",
    "sad", "worried", "angry", "smug", "think", "blink",
}
VALID_HAIR = {"short", "curly", "spiky", "cap", "long", "pigtails", "bald", "bun", "grey_old"}
VALID_EXTRAS = {"glasses", "collar", "tie", "pocket", "apron", "cardigan"}
VALID_FX = {"drizzle", "raincloud", "storm", "bigstorm", "bolt", "smoke", "crumbs", "money", "sparkle", "glow"}
VALID_SFX = {
    "whoosh", "whoosh_up", "whoosh_down", "pop", "boing", "ding", "impact", "boom",
    "riser", "scratch", "bell", "thunder", "rain", "correct", "cash", "heartbeat",
    "glitch", "tick", "snap", "squeak", "drop", "click", "stamp",
}
VALID_MUSIC = {"playful", "warm", "triumph", "suspense", "dark", "sad", "hit", "none"}

PRIORITY_MODELS = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]

STYLE_GUIDE = """
You are an elite viral short-form story writer and 3D Roblox-style animation director.
Write a BRAND-NEW, 100% ORIGINAL 60-to-75 second fast-paced first-person story (240 to 290 words total, split across 22 to 28 rapid-fire shots of 9 to 12 words each).

EXACT STORYTELLING STYLE & STRUCTURE (DO NOT copy any plot or character names from the 5 examples below—invent a completely original world rule and twist with the EXACT SAME narrative rhythm):
1. **Hook & World Rule (Shots 1-4):** Open immediately with "In this world..." or "In this town..." explaining one bizarre, visual rule that controls everyone's survival, status, or family.
2. **Personal Setup & Escalation (Shots 5-14):** Introduce our protagonist, their contrasting friend/sibling/rival, and a sudden high-stakes test, inspection, midnight curfew, or rule reversal where everyone panics.
3. **The Clever/Chilling Climax (Shots 15-21):** Show the protagonist using logic, observation, or a hidden loophole when everyone else fails—or uncovering a chilling impostor/trap right before the deadline.
4. **Ironic Twist & Viewer Hook (Shots 22-26):** End with a sharp final twist in the last 2 shots and a direct question/choice for viewers.

REFERENCE EXAMPLES FOR TONE, TWIST QUALITY & PACING ONLY (INVENT A BRAND NEW STORY):
- Example A: A town where people can only eat foods starting with their first initial, until the mayor calls an inspection and the boy exposes that the mayor faked his name.
- Example B: A towering castle where hundreds fall trying to climb a princess's hair, until one boy walks around the back and knocks on the unlocked front door.
- Example C: A city split into Blue and Pink sides under a giant balance scale, where opposite colored balloons pop on one boy simultaneously and create a third Purple world.
- Example D: A desert world where gold is worthless trash and wet mud is currency, until a heatwave dries the bank vault and a gold roof saves it right before rain ruins mud's value.
- Example E: "Copy Night" where lake mimics copy family members until sunrise, ending with a sister hugging the wrong brother because the real one would never yell at her.

STRICT VISUAL & MOTION RULES (CRITICAL — EVERY SHOT MUST SHOW WHAT THE NARRATOR SAYS):
- **Never leave characters standing still in empty rooms!**
- Build **2 to 3 custom `places`** packed with props (`table`, `chair`, `door`, `window`, `bed`, `desk`, `shelf`, `lamp`, `tree`, `bush`, `bench`, `fountain`, `fence`, `box`, `crate`, `barrel`, `counter`, `tv`, `rug`) and combine them with built-in sets (`Street`, `TownPool`, `Park`, `Classroom`, `Store`, `Office`, `Kitchen`, `LivingRoom`, `Backyard`).
- **Active Motion in Every Shot:** Use `walkTo: [x2, y2]` on characters walking/running across scenes, switch animations (`run`, `point`, `shock`, `scared`, `cheer`, `eat`, `angry`, `facepalm`, `think`, `wave`), and attach particle `fx` (`money`, `bolt`, `smoke`, `sparkle`, `glow`, `crumbs`, `drizzle`, `storm`) whenever objects, magic, weather, or money are mentioned!
- **Dynamic Camera & Lighting:** Change `cam` (`ws` -> `ms` -> `two` -> `cu` -> `low` -> `high` -> `ots`) and `move` (`push`, `crash_in`, `reveal_push`, `drift`) every shot, and shift `mood` (`sunny` -> `storm` -> `night`) as tension rises.

STRICT JSON SCHEMA (return ONLY raw JSON, no markdown):
{
  "title": "Short catchy title",
  "caption": "Instagram Reels caption with 4 relevant hashtags",
  "keys": ["power_words_to_pop_in_yellow"],
  "music": [[0, "playful"], [0.45, "suspense"], [0.80, "dark"]],
  "cast": {
    "HeroName": {
      "skin": [0.92, 0.76, 0.62],
      "shirt": [0.18, 0.48, 0.92],
      "pants": [0.16, 0.18, 0.26],
      "shoes": [0.95, 0.95, 0.95],
      "hair": "short",
      "hair_color": [0.15, 0.1, 0.08],
      "height": 1.0
    },
    "RivalName": {
      "skin": [0.85, 0.68, 0.54],
      "shirt": [0.88, 0.2, 0.22],
      "pants": [0.15, 0.15, 0.2],
      "shoes": [0.1, 0.1, 0.1],
      "hair": "spiky",
      "hair_color": [0.85, 0.7, 0.2],
      "height": 1.05,
      "extras": ["tie"],
      "tie_color": [0.1, 0.1, 0.1]
    }
  },
  "places": {
    "VaultHall": {
      "kind": "room",
      "wall": "#2c3e50",
      "lower": "#1a252f",
      "floor": "tiles",
      "light": "warm",
      "props": [
        ["door", -8, 7.7, 0, {"open": true}],
        ["table", 0, 3.5, 0],
        ["crate", -4.5, 4.0, 15],
        ["crate", 4.5, 4.0, -15],
        ["lamp", 6.5, 5.5, 0]
      ]
    }
  },
  "shots": [
    {
      "text": "Spoken narration line for this shot (9-12 words).",
      "set": "VaultHall",
      "cam": "ws",
      "subject": "HeroName",
      "mood": "sunny",
      "move": "push",
      "sfx": ["whoosh@0.0"],
      "actors": [
        {"who": "HeroName", "at": [-3.5, -0.5], "walkTo": [-1.2, -0.2], "anim": "walk", "face": "smile", "yaw": 25},
        {"who": "RivalName", "at": [2.8, 0.2], "anim": "point", "face": "smug", "yaw": -35, "fx": ["sparkle@0.1"]}
      ]
    }
  ]
}

ALLOWED VALUES ONLY:
- set: "Street", "Kitchen", "Gym", "MusicRow", "TownPool", "Bedroom", "Hallway", "Classroom", "LivingRoom", "Store", "Office", "Bathroom", "Park", "Backyard", "Playground", or a key in your "places" dict.
- cam: "ews", "ws", "mls", "ms", "two", "mcu", "cu", "ecu", "ots", "low", "high"
- mood: "sunny", "storm", "night"
- move: "creep", "push", "reveal_push", "crash_in", "drift", "lock"
- anim: "idle", "talk", "walk", "run", "point", "shrug", "shock", "scared", "cheer", "eat", "cross_arms", "think", "sad", "angry", "wave", "sit", "facepalm"
- face: "neutral", "smile", "grin", "laugh", "shock", "scared", "sad", "worried", "angry", "smug", "think"
- fx: "drizzle", "raincloud", "storm", "bigstorm", "bolt", "smoke", "crumbs", "money", "sparkle", "glow"
- sfx: "whoosh@0.0", "pop@0.0", "ding@0.0", "impact@0.0", "boom@0.0", "riser@0.0", "heartbeat@0.0", "tick@0.0", "glitch@0.0", "cash@0.0", "bell@0.0"
- Keep actors at least 2.8 units apart in `at: [x, y]` with `-6 <= x <= 6` and `-3 <= y <= 2.5`.
"""


def _clamp_rgb(c, default):
    if not isinstance(c, (list, tuple)) or len(c) < 3:
        return default
    return [round(max(0.0, min(1.0, float(v))), 3) for v in c[:3]]


def _clamp_xy(pt, default=(0.0, 0.0)):
    if not isinstance(pt, (list, tuple)) or len(pt) < 2:
        return list(default)
    x = max(-6.5, min(6.5, float(pt[0])))
    y = max(-3.5, min(2.8, float(pt[1])))
    return [round(x, 2), round(y, 2)]


def sanitize_spec(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Generated spec is not a JSON object")

    raw_cast = raw.get("cast") or {}
    if not isinstance(raw_cast, dict) or not raw_cast:
        raw_cast = {
            "Narrator": {
                "skin": [0.92, 0.76, 0.62],
                "shirt": [0.2, 0.45, 0.85],
                "pants": [0.18, 0.2, 0.28],
                "shoes": [0.9, 0.9, 0.9],
                "hair": "short",
                "hair_color": [0.18, 0.12, 0.08],
                "height": 1.0,
            }
        }

    cast = {}
    for name, look in list(raw_cast.items())[:6]:
        clean_name = re.sub(r"[^A-Za-z0-9_]", "", str(name)) or f"Char{len(cast)+1}"
        look = look if isinstance(look, dict) else {}
        c = {
            "skin": _clamp_rgb(look.get("skin"), [0.92, 0.76, 0.62]),
            "shirt": _clamp_rgb(look.get("shirt"), [0.25, 0.45, 0.85]),
            "pants": _clamp_rgb(look.get("pants"), [0.2, 0.22, 0.3]),
            "shoes": _clamp_rgb(look.get("shoes"), [0.2, 0.2, 0.2]),
            "hair": look.get("hair") if look.get("hair") in VALID_HAIR else "short",
            "hair_color": _clamp_rgb(look.get("hair_color"), [0.15, 0.1, 0.08]),
            "height": round(max(0.75, min(1.15, float(look.get("height", 1.0)))), 2),
        }
        if look.get("cap_color"):
            c["cap_color"] = _clamp_rgb(look.get("cap_color"), [0.2, 0.3, 0.8])
        if look.get("tie_color"):
            c["tie_color"] = _clamp_rgb(look.get("tie_color"), [0.8, 0.15, 0.15])
        if look.get("apron_color"):
            c["apron_color"] = _clamp_rgb(look.get("apron_color"), [0.95, 0.95, 0.95])
        if look.get("sleeves") in ("short", "long"):
            c["sleeves"] = look["sleeves"]
        extras = [e for e in (look.get("extras") or []) if e in VALID_EXTRAS]
        if extras:
            c["extras"] = extras
        cast[clean_name] = c

    cast_names = list(cast.keys())
    default_actor = cast_names[0]

    places = {}
    if isinstance(raw.get("places"), dict):
        for pname, pspec in raw["places"].items():
            clean_p = re.sub(r"[^A-Za-z0-9_]", "", str(pname))
            if clean_p and isinstance(pspec, dict):
                places[clean_p] = pspec

    things = {}
    if isinstance(raw.get("things"), dict):
        for tname, tparts in raw["things"].items():
            clean_t = re.sub(r"[^A-Za-z0-9_]", "", str(tname))
            if clean_t and isinstance(tparts, list) and 1 <= len(tparts) <= 14:
                things[clean_t] = tparts

    allowed_sets = VALID_SETS | set(places.keys())

    raw_shots = raw.get("shots") or []
    if len(raw_shots) < 8:
        raise ValueError(f"Too few shots generated: {len(raw_shots)}")

    shots = []
    t_cursor = 0.0
    for idx, sh in enumerate(raw_shots):
        if not isinstance(sh, dict):
            continue
        text = re.sub(r"\s+", " ", str(sh.get("text") or "")).strip()
        if not text:
            continue

        est_dur = max(1.1, round(len(text.split()) / 4.6, 2))
        t0 = round(t_cursor, 3)
        t1 = round(t0 + est_dur, 3)
        t_cursor = t1

        s_set = sh.get("set") if sh.get("set") in allowed_sets else "Street"
        cam = sh.get("cam") if sh.get("cam") in VALID_CAMS else ("ws" if idx == 0 else "ms")
        mood = sh.get("mood") if sh.get("mood") in VALID_MOODS else "sunny"
        move = sh.get("move") if sh.get("move") in VALID_MOVES else "push"

        raw_actors = sh.get("actors") or []
        actors = []
        used_positions = []
        for a_idx, act in enumerate(raw_actors[:3]):
            if not isinstance(act, dict):
                continue
            who = act.get("who") if act.get("who") in cast else cast_names[min(a_idx, len(cast_names) - 1)]
            if any(existing["who"] == who for existing in actors):
                continue

            pos = _clamp_xy(act.get("at"), default=(-1.8 + a_idx * 3.4, -0.3 + (a_idx % 2) * 0.4))
            for prev in used_positions:
                if math.dist(pos, prev) < 2.6:
                    pos[0] = max(-6.2, min(6.2, prev[0] + (2.8 if prev[0] <= 0 else -2.8)))
            used_positions.append(pos)

            anim = act.get("anim") if act.get("anim") in VALID_ANIMS else ("talk" if a_idx == 0 else "idle")
            face = act.get("face") if act.get("face") in VALID_FACES else "neutral"
            yaw = max(-180.0, min(180.0, float(act.get("yaw", 15 if pos[0] < 0 else -15))))

            clean_act = {
                "who": who,
                "at": pos,
                "anim": anim,
                "face": face,
                "yaw": round(yaw, 1),
            }
            if a_idx == 0:
                clean_act["talk"] = [0, 99]

            if act.get("walkTo"):
                wto = _clamp_xy(act["walkTo"], pos)
                if math.dist(pos, wto) >= 0.7:
                    clean_act["walkTo"] = wto
                    if clean_act["anim"] not in ("walk", "run"):
                        clean_act["anim"] = "walk"

            if isinstance(act.get("fx"), list):
                clean_fx = []
                for item in act["fx"]:
                    nm, _, off = str(item).partition("@")
                    if nm in VALID_FX:
                        try:
                            clean_fx.append(f"{nm}@{float(off):.2f}" if off else nm)
                        except ValueError:
                            clean_fx.append(nm)
                if clean_fx:
                    clean_act["fx"] = clean_fx

            actors.append(clean_act)

        if not actors:
            actors = [{"who": default_actor, "at": [0.0, -0.3], "anim": "talk", "face": "neutral", "yaw": 0.0, "talk": [0, 99]}]

        subject = sh.get("subject") if any(a["who"] == sh.get("subject") for a in actors) else actors[0]["who"]

        clean_shot = {
            "t0": t0,
            "t1": t1,
            "text": text,
            "set": s_set,
            "cam": cam,
            "subject": subject,
            "mood": mood,
            "move": move,
            "actors": actors,
        }
        if sh.get("side") in (-1, 1):
            clean_shot["side"] = sh["side"]
        if sh.get("aimUp") is True:
            clean_shot["aimUp"] = True
        if sh.get("flash") is True:
            clean_shot["flash"] = True
            clean_shot["impact"] = round(float(sh.get("impact", 0.2)), 2)

        if isinstance(sh.get("sfx"), list):
            clean_sfx = []
            for s_item in sh["sfx"]:
                nm, _, dt = str(s_item).partition("@")
                if nm in VALID_SFX:
                    try:
                        clean_sfx.append(f"{nm}@{float(dt):.2f}" if dt else nm)
                    except ValueError:
                        clean_sfx.append(nm)
            if clean_sfx:
                clean_shot["sfx"] = clean_sfx

        shots.append(clean_shot)

    music = []
    for seg in (raw.get("music") or [[0, "playful"], [0.45, "suspense"], [0.80, "dark"]]):
        if isinstance(seg, (list, tuple)) and len(seg) >= 2:
            pos_val = max(0.0, min(0.95, float(seg[0])))
            m_mood = seg[1] if seg[1] in VALID_MUSIC else "suspense"
            music.append([round(pos_val, 2), m_mood])
    if not music or music[0][0] != 0:
        music.insert(0, [0, "playful"])

    keys = [re.sub(r"[^a-zA-Z0-9']", "", str(k)).lower() for k in (raw.get("keys") or []) if str(k).strip()][:20]

    out = {
        "dur": round(t_cursor, 3),
        "keys": keys,
        "music": music,
        "cast": cast,
        "shots": shots,
    }
    if places:
        out["places"] = places
    if things:
        out["things"] = things
    return out


def discover_all_gemini_models(api_key: str) -> list[str]:
    discovered = []
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for m in data.get("models", []):
            methods = m.get("supportedGenerationMethods") or []
            name = (m.get("name") or "").replace("models/", "")
            if "generateContent" in methods and "gemini" in name.lower():
                if any(x in name.lower() for x in ("embedding", "imagen", "veo", "tts", "audio", "robotics", "computer-use")):
                    continue
                discovered.append(name)
    except Exception as e:
        print(f"[WARN] Could not list models dynamically ({e}); using priority list.", flush=True)

    ordered = []
    for m in PRIORITY_MODELS + discovered:
        if m not in ordered:
            ordered.append(m)
    return ordered


def call_gemini(api_key: str, model: str, prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.95,
            "topP": 0.95,
            "maxOutputTokens": 8192,
            "responseMimeType": "application/json",
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    candidates = body.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Empty candidates from {model}: {body}")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise RuntimeError(f"Empty text from {model}")
    return text


def extract_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def main(project_dir: str):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        sys.exit("ERROR: GEMINI_API_KEY is missing from GitHub Secrets.")

    os.makedirs(project_dir, exist_ok=True)
    seed_topic = os.environ.get("STORY_THEME", "").strip()
    user_prompt = STYLE_GUIDE + (f"\nOptional theme seed: {seed_topic}\n" if seed_topic else "\nInvent a completely fresh, gripping high-concept premise.\n")

    models = discover_all_gemini_models(api_key)
    print(f"[Gemini] Fallback chain ({len(models)} models): {models}", flush=True)

    last_err = None
    for model in models:
        for attempt in range(1, 3):
            try:
                print(f"[Gemini] Trying {model} (attempt {attempt})...", flush=True)
                raw_text = call_gemini(api_key, model, user_prompt)
                raw_obj = extract_json(raw_text)
                spec = sanitize_spec(raw_obj)

                meta = {
                    "title": str(raw_obj.get("title") or "Untitled Twist Short").strip(),
                    "caption": str(raw_obj.get("caption") or "#storytime #plottwist #shorts #animation").strip(),
                    "model_used": model,
                }
                with open(os.path.join(project_dir, "timed.json"), "w", encoding="utf-8") as f:
                    json.dump(spec, f, indent=2)
                with open(os.path.join(project_dir, "meta.json"), "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)

                print(f"[Gemini] SUCCESS with {model}: {len(spec['shots'])} shots, est {spec['dur']}s | Title: {meta['title']}", flush=True)
                return
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")[:300]
                last_err = f"HTTP {e.code} on {model}: {err_body}"
                print(f"[Gemini] {last_err}", flush=True)
                if e.code in (400, 404):
                    break
                time.sleep(2 * attempt)
            except Exception as e:
                last_err = f"{type(e).__name__} on {model}: {e}"
                print(f"[Gemini] {last_err}", flush=True)
                time.sleep(2 * attempt)

    sys.exit(f"FATAL: All Gemini models failed. Last error: {last_err}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python auto/generate_story.py kit/projects/<name>")
    main(os.path.abspath(sys.argv[1]))
