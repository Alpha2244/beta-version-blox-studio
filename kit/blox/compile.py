"""Compile an episode (timed.json) into a keyframed .blend.
blender -b --factory-startup -P compile.py -- EPDIR [--frames a,b,c --still OUT_DIR]
Writes EPDIR/scene.blend (render with render_par.py) and EPDIR/clash.txt (body/prop overlap gate).
"""
import bpy
import sys
import os
import json
import math
import random
import re
from mathutils import Vector, Matrix, Euler
from mathutils.bvhtree import BVHTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sets
import chars
import props
import assets_loader

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
EP = os.path.abspath(argv[0])
SPEC = json.load(open(os.path.join(EP, 'timed.json'), encoding='utf8'))
WORDS = json.load(open(os.path.join(EP, 'words.json'), encoding='utf8'))
FPS = 30
N = max(1, int(math.ceil(SPEC['dur'] * FPS)))

import places as _places
_places.register_things(SPEC.get('things', {}))
PLACES = SPEC.get('places', {})
_used = []
for _s in SPEC['shots']:
    st = _s.get('set') or 'Street'
    _s['set'] = st
    if st not in _used:
        _used.append(st)
if not _used:
    _used = ['Street']

ORIG = {nm: Vector((i * 400, 0, 0)) for i, nm in enumerate(_used)}
OFF = Vector((0, 0, -2000))
H = chars.HEAD_C[2] if hasattr(chars, 'HEAD_C') else 4.66


def ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def lerp(a, b, x):
    return a + (b - a) * x


def yawdir(yaw):
    r = math.radians(yaw)
    return Vector((math.sin(r), -math.cos(r), 0))


# ---------- scene ----------
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
sc = bpy.context.scene
sets.setup_render(sc)
sc.render.fps = FPS
sc.frame_start = 0
sc.frame_end = N - 1
for nm, o in ORIG.items():
    sets.build_set(nm, origin=tuple(o), spec=PLACES.get(nm))

# ---------- cast ----------
CAST = {}
for nm, raw_spec in SPEC.get('cast', {}).items():
    spec = dict(raw_spec or {})
    spec['skin'] = tuple(spec.get('skin') or (0.98, 0.78, 0.62))
    spec['shirt'] = tuple(spec.get('shirt') or (0.20, 0.55, 0.95))
    spec['pants'] = tuple(spec.get('pants') or (0.18, 0.24, 0.36))
    spec['shoes'] = tuple(spec.get('shoes') or (0.92, 0.92, 0.94))
    spec['hair_color'] = tuple(spec.get('hair_color') or (0.20, 0.12, 0.06))
    CAST[nm] = chars.make_char(nm, spec)

# ---------- props (episode-level & shot-level via assets_loader + universal props fallback) ----------
PROPC = bpy.data.collections.new('Props')
sc.collection.children.link(PROPC)
SPAWNED_PROPS = {}
PROP_WINDOWS = {}


def _spawn_safe_prop(pname, pspec, set_nm):
    o = ORIG.get(set_nm, Vector((0, 0, 0)))
    pspec = dict(pspec)
    base_loc = tuple(pspec.get('loc') or (0.0, -1.2, 0.0))
    if not pspec.get('hold') and not pspec.get('pedestal'):
        pspec['loc'] = tuple(o + Vector(base_loc))
    ob = None
    try:
        ob = assets_loader.spawn_prop(pname, pspec, chars=CAST, coll=PROPC)
    except Exception:
        ob = None
    if ob is None:
        kind = pspec.get('kind') or pspec.get('type') or pspec.get('asset') or pname
        loc = pspec.get('loc') or tuple(o + Vector((0.0, -1.2, 0.0)))
        rotz = float(pspec.get('rotz') or pspec.get('yaw') or 0.0)
        scale = float(pspec.get('scale') or 1.0)
        ob = props.spawn_prop(PROPC, kind, pname, loc, rotz=rotz, scale=scale)
    if ob is not None and 'showAt' in pspec and 'hideAt' in pspec:
        PROP_WINDOWS[ob] = (float(pspec['showAt']), float(pspec['hideAt']), Vector(ob.location))
    return ob


for p_idx, pspec in enumerate(SPEC.get('props', [])):
    set_nm = pspec.get('set', _used[0])
    pname = pspec.get('name', f'ep_prop_{p_idx}')
    SPAWNED_PROPS[pname] = _spawn_safe_prop(pname, pspec, set_nm)

for s_idx, s in enumerate(SPEC['shots']):
    for p_idx, pspec in enumerate(s.get('props', [])):
        pspec = dict(pspec)
        pspec.setdefault('showAt', s['t0'])
        pspec.setdefault('hideAt', s['t1'])
        pname = pspec.get('name', f's{s_idx}_prop_{p_idx}')
        SPAWNED_PROPS[pname] = _spawn_safe_prop(pname, pspec, s['set'])


# ---------- materials / fx objects ----------
def mat(name, col, emit=0.0, alpha=1.0, rough=0.5):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get('Principled BSDF')
    b.inputs['Base Color'].default_value = (*col, 1)
    b.inputs['Roughness'].default_value = rough
    if emit:
        b.inputs['Emission Color'].default_value = (*col, 1)
        b.inputs['Emission Strength'].default_value = emit
    if alpha < 1:
        b.inputs['Alpha'].default_value = alpha
        try:
            m.surface_render_method = 'BLENDED'
        except Exception:
            pass
    return m


FXC = bpy.data.collections.new('FX')
sc.collection.children.link(FXC)


def link(o):
    FXC.objects.link(o)
    return o


def sphere(name, r, m, loc=(0, 0, 0), parent=None):
    me = bpy.data.meshes.new(name)
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=3, radius=r)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    o = link(bpy.data.objects.new(name, me))
    o.data.materials.append(m)
    o.location = loc
    if parent:
        o.parent = parent
    return o


def make_cloud(name, col):
    root = link(bpy.data.objects.new(name, None))
    m = mat(name + '_m', col, rough=0.9)
    for i, (x, y, z, r) in enumerate([
        (0, 0, 0, 1.0), (-1.1, 0, -0.15, 0.8), (1.1, 0, -0.1, 0.85),
        (-0.5, 0.35, 0.45, 0.75), (0.55, -0.2, 0.4, 0.7),
        (-1.8, 0.1, -0.35, 0.55), (1.85, 0.05, -0.3, 0.55),
        (0, -0.55, -0.2, 0.75), (0.1, 0.6, -0.1, 0.7),
    ]):
        sphere(f'{name}_p{i}', r, m, (x, y, z), root)
    root.location = OFF
    return root


def make_rain(name, n):
    m = mat('rain_m', (0.6, 0.8, 1.0), emit=0.6, alpha=0.75)
    out = []
    for i in range(n):
        me = bpy.data.meshes.new(f'{name}{i}')
        import bmesh
        bm = bmesh.new()
        bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=0.035, radius2=0.035, depth=0.55)
        bm.to_mesh(me)
        bm.free()
        o = link(bpy.data.objects.new(f'{name}{i}', me))
        o.data.materials.append(m)
        o.location = OFF
        out.append(o)
    return out


def make_bolt(name):
    rnd = random.Random(7)
    pts = [Vector((0, 0, 0))]
    for _ in range(9):
        pts.append(pts[-1] + Vector((rnd.uniform(-0.7, 0.7), rnd.uniform(-0.2, 0.2), -1.3)))
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    cu.bevel_depth = 0.11
    cu.bevel_resolution = 2
    sp = cu.splines.new('POLY')
    sp.points.add(len(pts) - 1)
    for p, v in zip(sp.points, pts):
        p.co = (*v, 1)
    o = link(bpy.data.objects.new(name, cu))
    o.data.materials.append(mat('bolt_m', (1.0, 0.95, 0.55), emit=40))
    o.location = OFF
    return o, (pts[0] - pts[-1]).length


CLOUD_W = make_cloud('cloud_white', (0.92, 0.94, 1.0))
CLOUD_G = make_cloud('cloud_grey', (0.45, 0.48, 0.56))
CLOUD_D = make_cloud('cloud_dark', (0.12, 0.13, 0.17))
RAIN = make_rain('rain', 46)
BOLT, BOLT_LEN = make_bolt('bolt')
fl = bpy.data.lights.new('flash', 'POINT')
fl.energy = 0
fl.shadow_soft_size = 3
fl.color = (0.85, 0.9, 1.0)
FLASH = link(bpy.data.objects.new('flash', fl))
FLASH.location = OFF
SMOKE = [sphere(f'smoke{i}', 0.5, mat('smoke_m', (0.3, 0.3, 0.32), alpha=0.6, rough=1)) for i in range(6)]
for s in SMOKE:
    s.location = OFF
CRUMB = [sphere(f'crumb{i}', 0.028, mat('crumb_m', (0.62, 0.4, 0.18), rough=0.9)) for i in range(3)]
for c in CRUMB:
    c.location = OFF
    c.visible_shadow = False

cam_data = bpy.data.cameras.new('cam')
cam_data.sensor_fit = 'VERTICAL'
cam_data.sensor_height = 24.0
cam_data.clip_start = 0.1
cam_data.clip_end = 900
CAM = bpy.data.objects.new('cam', cam_data)
sc.collection.objects.link(CAM)
sc.camera = CAM


# ---------- helpers ----------
VOW = {'a': 'A', 'e': 'E', 'i': 'E', 'o': 'O', 'u': 'O', 'y': 'E'}
MOUTH = []
for w, a, b in WORDS:
    ww = re.sub(r'[^a-z]', '', w.lower()) or 'm'
    syl = re.findall(r'[^aeiouy]*[aeiouy]+', ww) or [ww]
    n = max(1, min(len(syl), int((b - a) * FPS // 4)))
    groups = [syl[i * len(syl) // n:(i + 1) * len(syl) // n] for i in range(n)]
    for i, g in enumerate(groups):
        s_ = ''.join(g)
        v = re.search(r'[aeiouy]', s_)
        shp = 'M' if s_[:1] in ('m', 'b', 'p') and i == 0 and len(groups) > 1 else VOW.get(v.group(0) if v else 'a', 'A')
        MOUTH.append((a + (b - a) * i / n, a + (b - a) * (i + 1) / n, shp))


def viseme(t):
    for a, b, shp in MOUTH:
        if a <= t < b:
            return shp
    return None


def at_list(base, lst, tl):
    cur = base
    for tt, v in (lst or []):
        if tl >= tt:
            cur = v
    return cur


def fx_list(a):
    out = []
    for f in a.get('fx', []):
        nm, _, t = f.partition('@')
        out.append((nm, float(t) if t else 0.0))
    return out


def shot_at(t):
    for s in SPEC['shots']:
        if s['t0'] <= t < s['t1']:
            return s
    return SPEC['shots'][-1]


def actor_pos(s, a, tl):
    o = ORIG[s['set']]
    at_xy = a.get('at') or (0.0, 0.0)
    p0 = Vector((at_xy[0], at_xy[1], 0))
    yaw = a.get('yaw', 0)
    if a.get('walkTo'):
        p1 = Vector((a['walkTo'][0], a['walkTo'][1], 0))
        x = tl / max(s['t1'] - s['t0'], 0.1)
        p = p0.lerp(p1, x)
        d = p1 - p0
        if d.length > 0.05:
            yaw = math.degrees(math.atan2(d.x, -d.y))
        return o + p, yaw, d.length / max(s['t1'] - s['t0'], 0.1)
    return o + p0, yaw, 0


def _resolve_stage_positions(s, tl):
    """Ensure minimum 2.2-stud actor separation so characters never clip into each other."""
    raw = {}
    for a in s.get('actors', []):
        if a['who'] not in CAST:
            continue
        p, yaw, v = actor_pos(s, a, tl)
        raw[a['who']] = [p, yaw, v]
    names = list(raw.keys())
    min_sep = 2.20
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            p1 = raw[names[i]][0]
            p2 = raw[names[j]][0]
            delta = Vector((p2.x - p1.x, p2.y - p1.y, 0.0))
            dist = delta.length
            if dist < min_sep:
                push_dir = delta.normalized() if dist > 1e-4 else Vector((1.0, 0.0, 0.0))
                shift = push_dir * ((min_sep - dist) * 0.52)
                raw[names[i]][0] = p1 - shift
                raw[names[j]][0] = p2 + shift
    return raw


# ---------------------------------------------------------------- Anti-Crop Camera Grammar
# kind -> (frame_width_studs, side_deg, eye_dz, eye_line_from_top, lens_mm, fstop, default_move, full_body_guard)
CAMS = {
    'ecu': (1.75, 28, -0.15, 0.44, 48, 1.0, 'lock', False),
    'cu': (2.65, 28, -0.35, 0.40, 35, 1.2, 'lock', False),
    'mcu': (3.50, 30, -0.85, 0.36, 30, 1.6, 'creep', False),
    'ms': (5.10, 32, -1.45, 0.30, 26, 2.2, 'creep', False),
    'mls': (6.80, 35, -2.10, 0.24, 22, 3.0, 'lock', True),
    'ws': (11.50, 22, 0.20, 0.28, 20, 4.2, 'lock', True),
    'ews': (15.50, 20, 'ground:0.8', 0.42, 18, 5.6, 'creep', True),
    'ots': (3.90, 148, -0.65, 0.36, 30, 1.6, 'lock', False),
    'low': (4.80, 28, -2.75, 0.26, 24, 2.0, 'lock', True),
    'worm': (4.20, 12, 'ground:0.5', 0.26, 20, 1.8, 'lock', True),
    'ground': (5.40, 28, 'ground:0.5', 0.42, 20, 1.8, 'lock', True),
    'high': (8.40, 20, 3.80, 0.36, 20, 3.5, 'lock', True),
    'top': (10.50, 0, 9.00, 0.48, 18, 4.0, 'lock', True),
    'ins': (1.45, 20, 'obj', 0.50, 48, 0.9, 'lock', False),
    'pov': (3.80, 180, 0.0, 0.40, 24, 1.8, 'drift', False),
    'two': (6.40, 28, -1.35, 0.26, 24, 2.4, 'creep', True),
}
SET_FRONT = {'ws', 'ews', 'top', 'high'}
CLOUDY = ('raincloud', 'drizzle', 'storm', 'bigstorm')


def bell(x):
    return (1 - math.cos(math.pi * max(0, min(1, x)))) / 2


def _enforce_anticrop(eye, tgt, lens, heads, full_body_guard):
    """Guarantee top of hair/hat (Z=5.75*k) and shoes (Z=0) never clip off the 9:16 vertical frame."""
    if not heads:
        return eye
    view = (tgt - eye).normalized()
    dist = (tgt - eye).length
    tan_half_v = 12.0 / max(10.0, lens)
    margin = 0.84 if full_body_guard else 0.88

    req_dist = dist
    for hp, _, k in heads.values():
        foot_z = hp.z - H * k
        crown_z = foot_z + 5.75 * k
        z_checks = [crown_z, foot_z] if full_body_guard else [crown_z, hp.z - 1.2 * k]
        for z_pt in z_checks:
            pt = Vector((hp.x, hp.y, z_pt))
            along = max(1.5, (pt - eye).dot(view))
            dz = abs((pt.z - eye.z) - view.z * along)
            needed = (dz / (tan_half_v * margin)) + (dist - along)
            if needed > req_dist:
                req_dist = needed
    if req_dist > dist:
        eye = tgt - view * req_dist
    return eye


def solve_cam(s, tl, heads):
    """returns eye, target, lens, focus point, fstop"""
    dur = s['t1'] - s['t0']
    kind = s.get('cam', 'ms')
    kind = kind if kind in CAMS else 'ms'
    fw, sdeg, edz, eyy, lens, fst, mv0, full_guard = CAMS[kind]
    side = s.get('side', 1)
    o = ORIG[s['set']]

    if kind == 'ins' or not heads:
        anc = sets.ANCHORS.get(s['set'], {}).get(s.get('focus', ''), (0, 0, 2.6))
        foc = o + Vector(anc)
        F = Vector((0, -1, 0))
        hp = foc
        k = max(1.0, _places.SIZES.get((s['set'], s.get('focus', '')), 0) * 1.4 / fw)
    elif kind == 'two':
        pts = [h[0] for h in heads.values()]
        foc = sum(pts, Vector()) / len(pts)
        spread = max((p - foc).length for p in pts) if len(pts) > 1 else 1.0
        hp = foc
        k = max(h[2] for h in heads.values())
        F = Vector((0, -1, 0))
        fw = max(fw * k, spread * 2.3 + 2.8) / k
        sub = s.get('subject')
        if sub in heads:
            foc = heads[sub][0]
    else:
        sub = s.get('subject') if s.get('subject') in heads else next(iter(heads))
        hp, yaw, k = heads[sub]
        foc = hp
        F = Vector((0, -1, 0)) if kind in SET_FRONT else yawdir(yaw)

    fw *= k
    fh = fw * 16.0 / 9.0
    d = (fw / 2.0) / (6.75 / lens)
    cloud = s.get('aimUp') or any(f.split('@')[0] in CLOUDY for a in s.get('actors', []) for f in a.get('fx', []))
    r = math.radians(sdeg * side)
    dirv = Vector((F.x * math.cos(r) - F.y * math.sin(r), F.x * math.sin(r) + F.y * math.cos(r), 0))
    tgt = hp - Vector((0, 0, (0.5 - eyy) * fh))
    if cloud and kind != 'ins':
        tgt = tgt + Vector((0, 0, 1.6 * k))
        d *= 1.3
    eye = tgt + dirv * d

    if isinstance(edz, str) and edz.startswith('ground'):
        eye.z = o.z + float(edz.split(':')[1])
    elif edz == 'obj':
        eye.z = foc.z + d * 0.55
    else:
        eye.z = hp.z + edz * k

    def blocked(e):
        vec = e - tgt
        dn = vec.normalized()
        orig = tgt.copy()
        left = vec.length
        for _ in range(8):
            ok, loc, nrm, idx, ob, mtx = sc.ray_cast(DG, orig, dn, distance=left)
            if not ok:
                return None
            col_name = ob.users_collection[0].name if ob.users_collection else ''
            if (ob.name.split('_')[0] in CAST or col_name in ('FX', 'Props') or
                    (s.get('focus') and ob.name.split('.')[:2] == [s['set'], s['focus']])):
                st = (loc - orig).length + 0.05
                orig = orig + dn * st
                left -= st
                continue
            return (loc - tgt).length
        return None

    if blocked(eye) is not None:
        for up in (0.8, 1.6, 2.4, 3.2):
            e2 = eye + Vector((0, 0, up))
            e2 = tgt + (e2 - tgt).normalized() * (eye - tgt).length
            if blocked(e2) is None:
                eye = e2
                break
        else:
            h = blocked(eye)
            eye = tgt + (eye - tgt).normalized() * max(1.2 if kind == 'ins' else 3.0, h - 0.7)

    if kind not in ('ins', 'ecu'):
        sub_heads = {s.get('subject'): heads[s.get('subject')]} if (s.get('subject') in heads and kind != 'two') else heads
        eye = _enforce_anticrop(eye, tgt, lens, sub_heads, full_guard)

    mv = s.get('move', mv0)
    x = tl / max(dur, 0.1)
    sc_ = 1.0
    if mv == 'creep':
        sc_ = 1 + 0.05 * x
    elif mv == 'push':
        sc_ = 1 + 0.14 * min(1, tl / min(1.2, dur))
    elif mv == 'reveal_push':
        sc_ = 1 + 0.38 * bell(x)
    elif mv == 'crash_in':
        ti = s.get('impact', 0.0) + 1 / FPS
        u = max(0, min(1, (tl - ti) / (4 / FPS)))
        sc_ = 1 + 0.14 * (1 - (1 - u) ** 2)
    elif mv == 'drift':
        tgt = tgt + Vector((math.sin(tl * 3.1) * 0.006 * fw, 0, math.sin(tl * 2.3 + 1) * 0.006 * fw))
    eye = tgt + (eye - tgt) / sc_

    if s.get('flash') or mv == 'crash_in':
        bolts = [float(f.split('@')[1]) for a in s.get('actors', []) for f in a.get('fx', []) if f.startswith('bolt@')]
        ti = s.get('impact', min(bolts) if bolts else 0.0) + 1 / FPS
        fi = int(round((tl - ti) * FPS))
        if 0 <= fi < 4:
            off = [0.016, -0.009, 0.004, 0][fi] * fw
            Rv = Vector((dirv.y, -dirv.x, 0))
            eye = eye + Rv * off
            tgt = tgt + Rv * off

    return eye, tgt, lens, foc, s.get('fstop', fst)


def key_obj(o, f, loc=None, scale=None):
    if loc is not None:
        o.location = loc
        o.keyframe_insert('location', frame=f)
    if scale is not None:
        o.scale = (scale, scale, scale)
        o.keyframe_insert('scale', frame=f)


# ---------- acting schedulers ----------
SHOTS = SPEC['shots']
CUTF = [int(round(s_['t0'] * FPS)) for s_ in SHOTS] + [N]
BLINK = {nm: set() for nm in CAST}
for si, s_ in enumerate(SHOTS):
    for a in s_.get('actors', []):
        if a['who'] not in BLINK:
            continue
        for tt, _ in a.get('faceAt', []):
            f0 = int(round((s_['t0'] + tt) * FPS)) - 1
            BLINK[a['who']].update(range(f0, f0 + 3))
for nm in CAST:
    r = random.Random('blink' + nm)
    tb = r.uniform(0.6, 2.5)
    while tb < SPEC['dur']:
        f0 = int(tb * FPS)
        if all(abs(f0 - c) > 6 and abs(f0 + 2 - c) > 6 for c in CUTF):
            BLINK[nm].update(range(f0, f0 + 3))
        tb += r.uniform(2.5, 5.0)

DART_FACES = {'scared', 'worried', 'think', 'shock'}


def dart(nm, si, fl):
    r = random.Random(f'dart{nm}{si}')
    acc = r.randint(4, 13)
    dx = dy = 0.0
    while acc <= fl:
        dx, dy = r.uniform(-0.35, 0.35), r.uniform(-0.12, 0.15)
        acc += r.randint(4, 13)
    return dx, dy


BLEND_W = [0.3, 0.62, 0.86, 1.06, 1.0]


def safe_pose(arm, f, anim, phase, amt=1.0):
    try:
        chars.pose(arm, f, anim, phase, amt)
    except Exception:
        chars.pose(arm, f, 'idle', phase, amt)
        MISSING.add(anim)


MISSING = set()
ONE_SHOT = {
    'nod', 'headshake', 'flinch', 'slump', 'jump_joy', 'shock', 'surrender',
    'head_tilt', 'what', 'facepalm', 'clap', 'grab', 'bend', 'highfive', 'hug',
}
cam_data.dof.use_dof = True
try:
    sc.render.motion_blur_position = 'START'
except Exception:
    pass


# ---------- per-frame keying ----------
DG = bpy.context.evaluated_depsgraph_get()
CLASH = []
for f in range(N):
    t = f / FPS
    s = shot_at(t)
    tl = t - s['t0']
    dur = s['t1'] - s['t0']
    si = SHOTS.index(s)
    lf = f - CUTF[si]
    inshot = {a['who']: a for a in s.get('actors', []) if a['who'] in CAST}
    stage_pos = _resolve_stage_positions(s, tl)
    heads = {}

    for ob, (t_show, t_hide, home_loc) in PROP_WINDOWS.items():
        key_obj(ob, f, home_loc if (t_show <= t < t_hide) else OFF)

    for nm, arm in CAST.items():
        a = inshot.get(nm)
        if not a:
            chars.place(arm, f, tuple(OFF), 0)
            continue
        p, yaw, v = stage_pos[nm]
        k = SPEC['cast'][nm].get('height', 1.0)
        chars.place(arm, f, tuple(p), yaw)

        def eff(x):
            an = at_list(a.get('anim', 'idle'), a.get('animAt'), x)
            if an == 'idle' and a.get('talk') and a['talk'][0] <= x <= a['talk'][1]:
                an = 'talk'
            return an

        anim = eff(tl)
        talking = a.get('talk') and a['talk'][0] <= tl <= a['talk'][1]
        if anim in ('walk', 'run'):
            phase = (v * tl) / ((2.6 if anim == 'walk' else 4.0) * k) * (1.0 if anim == 'walk' else 0.6)
        else:
            phase = t + (sum(map(ord, nm)) % 7) * 0.31
        if anim in ONE_SHOT:
            st = 0.0
            for tt, an in (a.get('animAt') or []):
                if tt <= tl and an == anim:
                    st = tt
            phase = tl - st

        prev = None
        for j in range(1, len(BLEND_W) + 1):
            if lf - j < 0:
                break
            if eff(tl - j / FPS) != anim:
                prev = eff(tl - j / FPS)
                w = BLEND_W[j - 1]
                break
        if prev and hasattr(chars, 'pose_mix'):
            try:
                chars.pose_mix(arm, f, prev, phase, anim, phase, w)
            except Exception:
                safe_pose(arm, f, anim, phase)
                MISSING.add('mix:' + prev + '>' + anim)
        else:
            safe_pose(arm, f, anim, phase)

        expr = at_list(a.get('face', 'neutral'), a.get('faceAt'), tl)
        vis = viseme(t) if talking else None
        lk = tuple(a.get('look', (0, 0)))
        if expr in DART_FACES:
            dx, dy = dart(nm, si, lf)
            lk = (max(-1, min(1, lk[0] + dx)), max(-1, min(1, lk[1] + dy)))
        chars.face(arm, f, expr, viseme=vis, blink=1.0 if f in BLINK[nm] else 0.0, look=lk)
        heads[nm] = (p + Vector((0, 0, H * k)), yaw, k)

    # fx
    cloud_on = {}
    rain_on = None
    bolt_on = None
    smoke_on = None
    crumbs_on = None
    for a in s.get('actors', []):
        if a['who'] not in heads:
            continue
        hp, yaw, k = heads[a['who']]
        for nm, t0 in fx_list(a):
            if tl < t0:
                continue
            age = tl - t0
            if nm in ('raincloud', 'drizzle', 'storm', 'bigstorm'):
                big = {'drizzle': 0.55, 'raincloud': 0.8, 'storm': 1.15, 'bigstorm': 2.6}[nm]
                pop = min(1.0, age / 0.22)
                pop = pop * (1 + 0.18 * math.sin(pop * math.pi))
                obj = {'drizzle': CLOUD_W, 'raincloud': CLOUD_G, 'storm': CLOUD_D, 'bigstorm': CLOUD_D}[nm]
                zc = hp.z + (2.6 if nm != 'bigstorm' else 4.2) * max(k, 0.8)
                c = Vector((hp.x + 0.15 * math.sin(t * 1.7), hp.y + 0.1 * math.cos(t * 1.3), zc))
                cloud_on[obj] = (c, big * max(pop, 0.01))
                if age > 0.25:
                    rain_on = (c, big, {'drizzle': 0.35, 'raincloud': 0.7, 'storm': 1.0, 'bigstorm': 1.0}[nm], hp.z - 4.9 * k)
            elif nm == 'bolt' and age < 0.32:
                bolt_on = (hp, age)
            elif nm == 'smoke':
                smoke_on = (hp, age)
            elif nm == 'crumbs':
                crumbs_on = (hp, yaw, k)

    for obj in (CLOUD_W, CLOUD_G, CLOUD_D):
        if obj in cloud_on:
            key_obj(obj, f, cloud_on[obj][0], cloud_on[obj][1])
        else:
            key_obj(obj, f, OFF, 0.01)

    rnd = random.Random(3)
    for i, r in enumerate(RAIN):
        sx, sy, sp = rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(0, 1)
        if rain_on and i < int(len(RAIN) * rain_on[2]):
            c, big, dens, floor = rain_on
            fall = c.z - 0.6 - floor
            z = c.z - 0.6 - ((t * 11 + sp * fall) % max(fall, 0.5))
            key_obj(r, f, Vector((c.x + sx * 1.5 * big, c.y + sy * 0.9 * big, z)))
        else:
            key_obj(r, f, OFF)

    if bolt_on:
        hp, age = bolt_on
        on = age < 0.08 or 0.14 < age < 0.22
        key_obj(BOLT, f, hp + Vector((0.1, 0, BOLT_LEN + 0.2)) if on else OFF)
        FLASH.location = hp + Vector((1.5, -3, 3))
        fl.energy = 2500 if on else 0
    else:
        key_obj(BOLT, f, OFF)
        FLASH.location = OFF
        fl.energy = 0
    FLASH.keyframe_insert('location', frame=f)
    fl.keyframe_insert('energy', frame=f)

    for i, sm in enumerate(SMOKE):
        if smoke_on:
            hp, age = smoke_on
            a2 = (age + i * 0.12) % 1.2
            key_obj(sm, f, hp + Vector((math.sin(i * 2.1) * 0.6, math.cos(i * 1.7) * 0.4, 0.9 + a2 * 2.2)), 0.4 + a2 * 0.7)
        else:
            key_obj(sm, f, OFF, 0.4)

    for i, cb in enumerate(CRUMB):
        if crumbs_on:
            hp, yaw, k = crumbs_on
            F = yawdir(yaw)
            R = Vector((F.y, -F.x, 0))
            ox, oz = [(-0.17, -0.24), (0.15, -0.3), (0.03, -0.36)][i]
            key_obj(cb, f, hp + F * 0.64 * k + R * ox * k + Vector((0, 0, oz * k)))
        else:
            key_obj(cb, f, OFF)

    # mood
    mx = s.get('moodx', [1.0, 1.0])
    sets.set_mood(s.get('mood', 'sunny'), lerp(mx[0], mx[1], ease(tl / max(dur, 0.1))))
    try:
        w = sc.world
        w.keyframe_insert('color', frame=f)
        if w.use_nodes:
            for nd in w.node_tree.nodes:
                for inp in nd.inputs:
                    if hasattr(inp, 'default_value') and not inp.is_linked:
                        try:
                            inp.keyframe_insert('default_value', frame=f)
                        except Exception:
                            pass
        for lo in bpy.data.objects:
            if lo.type == 'LIGHT' and lo is not FLASH:
                lo.data.keyframe_insert('energy', frame=f)
                lo.data.keyframe_insert('color', frame=f)
                lo.data.keyframe_insert('rotation_euler', frame=f)
    except Exception:
        pass

    # camera
    eye, tgt, lens, foc, fst = solve_cam(s, tl, heads)
    CAM.location = eye
    CAM.rotation_euler = (tgt - eye).to_track_quat('-Z', 'Y').to_euler()
    CAM.keyframe_insert('location', frame=f)
    CAM.keyframe_insert('rotation_euler', frame=f)
    cam_data.lens = lens
    cam_data.keyframe_insert('lens', frame=f)
    cam_data.dof.focus_distance = (foc - eye).length
    cam_data.dof.aperture_fstop = fst
    cam_data.dof.keyframe_insert('focus_distance', frame=f)
    cam_data.dof.keyframe_insert('aperture_fstop', frame=f)


# Linear interpolation inside shots, constant on cut frames
LASTF = set(c - 1 for c in CUTF[1:])


def all_fcurves(ad):
    act = ad.action
    if hasattr(act, 'fcurves') and len(act.fcurves):
        return list(act.fcurves)
    out = []
    for ly in getattr(act, 'layers', []):
        for st in ly.strips:
            for cb in st.channelbags:
                out += list(cb.fcurves)
    return out


ids = list(bpy.data.objects) + list(bpy.data.lights) + list(bpy.data.cameras) + list(bpy.data.worlds) + list(bpy.data.materials) + list(bpy.data.node_groups)
ids += [w.node_tree for w in bpy.data.worlds if w.node_tree]
for o in ids:
    ad = getattr(o, 'animation_data', None)
    if ad and ad.action:
        try:
            for fc in all_fcurves(ad):
                for kp in fc.keyframe_points:
                    kp.interpolation = 'CONSTANT' if int(round(kp.co.x)) in LASTF else 'LINEAR'
        except Exception as e:
            print('interp', o.name, e)
print('MISSING anims', sorted(MISSING))


# ---------- clash gate ----------
def aabb(o):
    cs = [o.matrix_world @ Vector(c) for c in o.bound_box]
    lo = Vector((min(c.x for c in cs), min(c.y for c in cs), min(c.z for c in cs)))
    hi = Vector((max(c.x for c in cs), max(c.y for c in cs), max(c.z for c in cs)))
    m = (hi - lo) * 0.1
    return lo + m, hi - m


def hit(a, b):
    return all(a[0][i] < b[1][i] and b[0][i] < a[1][i] for i in range(3))


step = 2
for f in range(0, N, step):
    sc.frame_set(f)
    s = shot_at(f / FPS)
    names = [a['who'] for a in s.get('actors', []) if a['who'] in CAST]
    boxes = {nm: [(o, aabb(o)) for o in chars.body_parts(CAST[nm]) if o.type == 'MESH' and max(o.dimensions) > 0.3] for nm in names}
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            pairs = [(x, y) for x in boxes[names[i]] for y in boxes[names[j]] if hit(x[1], y[1])]
            if pairs:
                dg = bpy.context.evaluated_depsgraph_get()
                for x, y in pairs:
                    if BVHTree.FromObject(x[0], dg).overlap(BVHTree.FromObject(y[0], dg)):
                        CLASH.append(f'{f}:{x[0].name}/{y[0].name}')
                        break
open(os.path.join(EP, 'clash.txt'), 'w').write('\n'.join(CLASH))
print('CLASH frames', len(CLASH))

sc.render.filepath = os.path.join(EP, 'frames', '#####')
sc.render.image_settings.file_format = 'JPEG'
sc.render.image_settings.quality = 92
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(EP, 'scene.blend'))
print('saved', os.path.join(EP, 'scene.blend'), 'frames', N)
