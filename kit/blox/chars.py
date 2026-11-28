"""Roblox-look blocky characters for Blender 5.x (rigid parts parented to bones).

Universal Defensive Biomechanical Rig:
  - Supports all canonical ANIMS plus infinite unknown human/cartoon actions via
    semantic biomechanical synthesis (`_synthesize_semantic_pose`) and direct
    `pose_spec` parameter dictionaries.
  - Supports `pose_mix` for smooth intra-shot transitions and cartoon `swell` scaling.

API:
  make_char(name, spec) -> armature
  place(arm, frame, loc, yaw_deg)
  pose(arm, frame, anim, phase=0.0, amount=1.0, pose_spec=None)
  pose_mix(arm, frame, anim_a, phase_a, anim_b, phase_b, mix=0.5, pose_spec=None)
  face(arm, frame, expr, viseme=None, blink=0.0, look=(0,0), mix_from=None, mix=1.0)
  body_parts(arm) -> [mesh objects]
Units: adult (height 1.0) is ~5.5 tall, feet on Z=0 at the armature origin, facing -Y.
Walk: 1.0 s cycle, stride 2.6*height per cycle. Run: 0.6 s cycle, stride 4.0*height per cycle.
"""
import bpy
import bmesh
import math
import re
from pathlib import Path as _Path
from mathutils import Matrix, Vector, Euler, Quaternion

ANIMS = [
    'idle', 'talk', 'walk', 'run', 'sneak', 'march', 'point', 'shrug', 'shock', 'scared',
    'cheer', 'eat', 'drink', 'cook', 'serve', 'cross_arms', 'think', 'sad', 'angry',
    'wave', 'beckon', 'sit', 'kneel', 'crouch', 'lie_down', 'hang', 'climb',
    'open_door', 'close_door', 'knock', 'push', 'pull', 'lift', 'throw', 'catch',
    'give', 'receive', 'inspect', 'phone_use', 'facepalm', 'laugh_body', 'whisper',
    'hold_hands', 'hold_hands_L', 'hold_hands_R',
    'nod', 'headshake', 'flinch', 'slump', 'jump_joy', 'surrender', 'what', 'clap',
    'grab', 'bend', 'write', 'read', 'exercise', 'swell',
]
EXPRS = [
    'neutral', 'smile', 'grin', 'scheming', 'laugh', 'shock', 'scared', 'wince',
    'sad', 'worried', 'angry', 'smug', 'think', 'blink', 'cry', 'blush',
]
VISEMES = ['A', 'O', 'E', 'M']
HAIR_STYLES = [
    'short', 'curly', 'spiky', 'pompadour', 'cap', 'long', 'pigtails', 'bald', 'bun', 'grey_old',
]

# ---------------------------------------------------------------- rig layout (adult, rest)
HEAD_C = Vector((0, 0, 4.66))
HEAD_R = 0.62
HEAD_H = 1.22
HEAD_BEV = 0.2
FACE_SX, FACE_SY = 1.45, 1.15
BONES = [
    ('root', (0, 0, 0), (0, 0, 0.5), None),
    ('torso', (0, 0, 2.0), (0, 0, 4.0), 'root'),
    ('head', (0, 0, 4.0), tuple(HEAD_C), 'torso'),
    ('upper_arm.L', (1.5, 0, 3.75), (1.5, 0, 3.0), 'torso'),
    ('lower_arm.L', (1.5, 0, 3.0), (1.5, 0, 2.3), 'upper_arm.L'),
    ('hand.L', (1.5, 0, 2.3), (1.5, 0, 2.0), 'lower_arm.L'),
    ('upper_arm.R', (-1.5, 0, 3.75), (-1.5, 0, 3.0), 'torso'),
    ('lower_arm.R', (-1.5, 0, 3.0), (-1.5, 0, 2.3), 'upper_arm.R'),
    ('hand.R', (-1.5, 0, 2.3), (-1.5, 0, 2.0), 'lower_arm.R'),
    ('upper_leg.L', (0.5, 0, 1.75), (0.5, 0, 1.0), 'root'),
    ('lower_leg.L', (0.5, 0, 1.0), (0.5, 0, 0.25), 'upper_leg.L'),
    ('foot.L', (0.5, 0, 0.25), (0.5, -0.5, 0.25), 'lower_leg.L'),
    ('upper_leg.R', (-0.5, 0, 1.75), (-0.5, 0, 1.0), 'root'),
    ('lower_leg.R', (-0.5, 0, 1.0), (-0.5, 0, 0.25), 'upper_leg.R'),
    ('foot.R', (-0.5, 0, 0.25), (-0.5, -0.5, 0.25), 'lower_leg.R'),
]
BONE_NAMES = [b[0] for b in BONES]
SHOULDER_Z, L_UP, L_LO = 3.75, 0.75, 0.7
HIP_Z = 1.75


# ---------------------------------------------------------------- color & materials
def _parse_rgb(col, default=(0.8, 0.8, 0.8)):
    _NAMED = {
        'red': (0.85, 0.2, 0.2), 'blue': (0.2, 0.45, 0.85), 'green': (0.2, 0.7, 0.3),
        'yellow': (0.95, 0.8, 0.2), 'gold': (0.95, 0.75, 0.15), 'white': (0.95, 0.95, 0.95),
        'black': (0.1, 0.1, 0.12), 'gray': (0.5, 0.5, 0.52), 'grey': (0.5, 0.5, 0.52),
        'brown': (0.45, 0.28, 0.16), 'orange': (0.95, 0.48, 0.15), 'purple': (0.55, 0.25, 0.75),
        'pink': (0.95, 0.55, 0.7), 'tan': (0.82, 0.68, 0.52), 'peach': (0.96, 0.76, 0.61),
    }
    try:
        if col is None:
            return default
        if isinstance(col, str):
            s = col.strip().lower()
            if s in _NAMED:
                return _NAMED[s]
            h = s.lstrip('#')
            if len(h) == 3:
                h = ''.join(ch * 2 for ch in h)
            if len(h) >= 6:
                return (
                    int(h[0:2], 16) / 255.0,
                    int(h[2:4], 16) / 255.0,
                    int(h[4:6], 16) / 255.0,
                )
            return default
        if isinstance(col, (list, tuple)) and len(col) >= 3:
            vals = [float(col[0]), float(col[1]), float(col[2])]
            if max(vals) > 1.0:
                vals = [v / 255.0 for v in vals]
            return tuple(max(0.0, min(1.0, v)) for v in vals)
    except Exception:
        pass
    return default


def _mat(name, rgb, rough=0.45, sheen=0.0, emit=False, emit_strength=1.0, coat=0.0, sss=0.0):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get('Principled BSDF')
    b.inputs['Base Color'].default_value = (*rgb, 1)
    b.inputs['Roughness'].default_value = rough
    for k, v in (('Specular IOR Level', 0.28), ('Coat Weight', coat), ('Coat Roughness', 0.35),
                 ('Sheen Weight', sheen), ('Subsurface Weight', sss)):
        if k in b.inputs:
            b.inputs[k].default_value = v
    if emit:
        b.inputs['Emission Color'].default_value = (*rgb, 1)
        b.inputs['Emission Strength'].default_value = emit_strength
    return m


def _lin(c):
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def _cmat(col, tag, **kw):
    rgb = _parse_rgb(col)
    return _mat('rbx_%s_%.3f_%.3f_%.3f' % (tag, *rgb), tuple(_lin(c) for c in rgb), **kw)


def _shade(me, ang=35):
    for p in me.polygons:
        p.use_smooth = True
    try:
        me.set_sharp_from_angle(angle=math.radians(ang))
    except Exception:
        pass


# ---------------------------------------------------------------- mesh builders
def _rbox(name, center, size, mat, bevel=0.1, seg=3):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2])) + Vector(center)
    bev = min(bevel, min(size) * 0.45)
    bmesh.ops.bevel(bm, geom=list(bm.edges) + list(bm.verts), offset=bev, segments=seg,
                    affect='EDGES', profile=0.5)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    _shade(me)
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _add_rbox(bm, center, size, bevel=0.1, seg=2, rot=None):
    tmp = bmesh.new()
    bmesh.ops.create_cube(tmp, size=1.0)
    for v in tmp.verts:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
    bmesh.ops.bevel(tmp, geom=list(tmp.edges) + list(tmp.verts), offset=min(bevel, min(size) * 0.45),
                    segments=seg, affect='EDGES', profile=0.5)
    M = Matrix.Translation(Vector(center)) @ (rot.to_matrix().to_4x4() if rot else Matrix())
    _merge(bm, tmp, M)


def _add_ico(bm, center, r, scale=(1, 1, 1), sub=1):
    tmp = bmesh.new()
    bmesh.ops.create_icosphere(tmp, subdivisions=sub, radius=r)
    M = Matrix.Translation(Vector(center)) @ Matrix.Diagonal((*scale, 1))
    _merge(bm, tmp, M)


def _add_cone(bm, base, tip_dir, r, length, seg=6):
    tmp = bmesh.new()
    bmesh.ops.create_cone(tmp, cap_ends=True, segments=seg, radius1=r, radius2=0.0, depth=length)
    d = Vector(tip_dir).normalized()
    q = Vector((0, 0, 1)).rotation_difference(d)
    M = Matrix.Translation(Vector(base) + d * length * 0.5) @ q.to_matrix().to_4x4()
    _merge(bm, tmp, M)


def _add_cyl(bm, center, r, depth, seg=24, bevel=0.0, scale=(1, 1, 1)):
    tmp = bmesh.new()
    bmesh.ops.create_cone(tmp, cap_ends=True, segments=seg, radius1=r, radius2=r, depth=depth)
    if bevel:
        cap_edges = [e for e in tmp.edges if abs(e.verts[0].co.z - e.verts[1].co.z) < 1e-6]
        bmesh.ops.bevel(tmp, geom=cap_edges, offset=bevel, segments=3, affect='EDGES', profile=0.5)
    M = Matrix.Translation(Vector(center)) @ Matrix.Diagonal((*scale, 1))
    _merge(bm, tmp, M)


def _merge(bm, tmp, M):
    tmp.transform(M)
    me = bpy.data.meshes.new('_tmp')
    tmp.to_mesh(me)
    tmp.free()
    bm.from_mesh(me)
    bpy.data.meshes.remove(me)


def _obj(name, me, mat, smooth=True, ang=35):
    if smooth:
        _shade(me, ang)
    if mat is not None:
        me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _head_mesh(name, mat):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=48, radius1=HEAD_R, radius2=HEAD_R, depth=HEAD_H)
    cap_edges = [e for e in bm.edges if abs(e.verts[0].co.z - e.verts[1].co.z) < 1e-6]
    bmesh.ops.bevel(bm, geom=cap_edges, offset=HEAD_BEV, segments=6, affect='EDGES', profile=0.5)
    for v in bm.verts:
        v.co += HEAD_C
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


# ---------------------------------------------------------------- face geometry
NCOL = 14
EPS_FACE, EPS_GLINT, EPS_FX = 0.012, 0.022, 0.016
EYE_X, EYE_Y, MOUTH_Y = 0.2, 0.04, -0.27


def _us():
    return [-math.cos(math.pi * i / (NCOL - 1)) for i in range(NCOL)]


def _sq(u):
    return math.sqrt(max(0.0, 1 - u * u))


def _eye(side, kind='oval', w=0.06, h=0.085, dx=0.0, dy=0.0, lid=None, lslant=0.0):
    cx, cy = side * EYE_X + dx, EYE_Y + dy
    top, bot = [], []
    for u in _us():
        x = cx + side * u * w
        s = _sq(u)
        if kind == 'oval':
            t, b = h * s, -h * s
            if lid is not None:
                t = max(b, min(t, lid * h + lslant * u * h))
        elif kind == 'happy':
            c = h * 0.9 * (1 - u * u) - h * 0.2
            th = 0.026 * (0.55 + 0.45 * s)
            t, b = c + th, c - th
        elif kind == 'wince':
            c = -0.045 * abs(u) + 0.022
            th = 0.022
            t, b = c + th, c - th
        else:
            th = 0.017 * (0.6 + 0.4 * s)
            t, b = th, -th
        top.append((x, cy + t))
        bot.append((x, cy + b))
    gtop, gbot = [], []
    open_ = kind == 'oval'
    g = 0.022 if open_ else 0.0
    if open_ and lid is not None and lid < 0.6:
        g = 0.0
    gx, gy = cx + w * 0.32, cy + (h * 0.38 if open_ else 0)
    for u in _us():
        s = _sq(u)
        gtop.append((gx + u * g, gy + g * s))
        gbot.append((gx + u * g, gy - g * s))
    return (top, bot), (gtop, gbot)


def _brow(side, by=0.27, tilt=0.0, curve=0.012, bw=0.075):
    top, bot = [], []
    cx = side * (EYE_X + 0.005)
    for u in _us():
        x = cx + side * u * bw
        c = by + tilt * (u + 1) / 2 - tilt / 2 + curve * (1 - u * u)
        th = 0.031 * (0.65 + 0.35 * _sq(u))
        top.append((x, c + th))
        bot.append((x, c - th))
    return top, bot


def _mouth(kind, w=0.13, cx=0.0, cy=MOUTH_Y, a=0.0, d=0.0, t=0.018):
    top, bot = [], []
    for u in _us():
        x = cx + u * w
        s = _sq(u)
        if kind == 'line':
            c = a * u
            th = t * (0.6 + 0.4 * s)
            T, B = c + th, c - th
        elif kind == 'arc':
            c = a * u * u - a * 0.35
            th = t * (0.5 + 0.5 * s)
            T, B = c + th, c - th
        elif kind == 'D':
            T = a * u * u + 0.012 * s
            B = a * u * u - d * s
        elif kind == 'O':
            T, B = d * s, -d * s
        elif kind == 'open':
            T, B = a * s, -d * s
        elif kind == 'wave':
            c = a * math.sin(2.5 * math.pi * u)
            th = t * (0.6 + 0.4 * s)
            T, B = c + th, c - th
        elif kind == 'lop':
            c = a * ((u + 1) / 2) ** 2 - a * 0.3
            th = t * (0.55 + 0.45 * s)
            T, B = c + th, c - th
        elif kind == 'scheming':
            T = 0.045 * u * u + 0.025 * s - 0.015
            B = 0.065 * u * u - 0.085 * s - 0.015
        top.append((x, cy + T))
        bot.append((x, cy + B))
    return top, bot


def _tear_stream(side, active=False):
    cx = side * (EYE_X + 0.018)
    cy = EYE_Y - 0.145
    hw = 0.024 if active else 0.0
    hh = 0.105 if active else 0.0
    top, bot = [], []
    for u in _us():
        x = cx + u * hw
        s = _sq(u)
        wobble = 0.008 * math.sin(math.pi * u) if active else 0.0
        top.append((x + wobble, cy + hh * s))
        bot.append((x - wobble, cy - hh * s))
    return top, bot


def _blush_cheek(side, active=False):
    cx = side * (EYE_X + 0.065)
    cy = EYE_Y - 0.125
    hw = 0.072 if active else 0.0
    hh = 0.036 if active else 0.0
    top, bot = [], []
    for u in _us():
        x = cx + u * hw
        s = _sq(u)
        top.append((x, cy + hh * s))
        bot.append((x, cy - hh * s))
    return top, bot


def _expr_shapes(e):
    E = lambda **k: (_eye(1, **k), _eye(-1, **k))
    show_tears = (e == 'cry')
    show_blush = (e == 'blush')

    if e == 'neutral':
        eyes = E()
        br = dict()
        m = _mouth('line', w=0.11)
    elif e == 'smile':
        eyes = E(h=0.08)
        br = dict(by=0.28, curve=0.02)
        m = _mouth('arc', w=0.15, a=0.055, t=0.02)
    elif e == 'grin':
        eyes = E(kind='happy', w=0.072, h=0.05)
        br = dict(by=0.3, curve=0.025)
        m = _mouth('D', w=0.17, cy=-0.215, a=0.025, d=0.13)
    elif e == 'scheming':
        eyes = E(w=0.068, h=0.086, lid=0.72, lslant=0.28)
        br = dict(by=0.255, tilt=0.075, curve=0.015)
        m = _mouth('scheming', w=0.175, cy=-0.245)
    elif e == 'laugh':
        eyes = E(kind='happy', w=0.078, h=0.058)
        br = dict(by=0.32, curve=0.03)
        m = _mouth('D', w=0.2, cy=-0.195, a=0.03, d=0.175)
    elif e == 'shock':
        eyes = E(w=0.078, h=0.112)
        br = dict(by=0.36, curve=0.03)
        m = _mouth('O', w=0.065, cy=-0.29, d=0.085)
    elif e == 'wince':
        eyes = E(kind='wince', w=0.075, h=0.06)
        br = dict(by=0.24, tilt=0.06, curve=-0.01)
        m = _mouth('wave', w=0.14, cy=-0.28, a=0.022, t=0.022)
    elif e == 'scared':
        eyes = E(w=0.072, h=0.1)
        br = dict(by=0.34, tilt=-0.06, curve=0.01)
        m = _mouth('open', w=0.15, cy=-0.29, a=0.025, d=0.05)
    elif e == 'sad':
        eyes = E(h=0.072, lid=0.75, lslant=-0.35)
        br = dict(by=0.29, tilt=-0.075, curve=0.0)
        m = _mouth('arc', w=0.12, cy=-0.29, a=-0.045, t=0.02)
    elif e == 'cry':
        eyes = E(kind='happy', w=0.068, h=0.048)
        br = dict(by=0.30, tilt=-0.09, curve=0.0)
        m = _mouth('open', w=0.14, cy=-0.285, a=0.02, d=0.075)
    elif e == 'blush':
        eyes = E(h=0.082, dx=0.012)
        br = dict(by=0.29, tilt=-0.03, curve=0.02)
        m = _mouth('wave', w=0.11, cy=-0.275, a=0.014, t=0.018)
    elif e == 'worried':
        eyes = E(w=0.064, h=0.09)
        br = dict(by=0.31, tilt=-0.06, curve=0.005)
        m = _mouth('wave', w=0.12, cy=-0.28, a=0.012, t=0.017)
    elif e == 'angry':
        eyes = E(w=0.064, h=0.075, lid=0.55, lslant=0.45)
        br = dict(by=0.225, tilt=0.09, curve=-0.005)
        m = _mouth('arc', w=0.12, cy=-0.29, a=-0.04, t=0.027)
    elif e == 'smug':
        eyes = E(w=0.064, h=0.075, lid=0.3, lslant=0.0)
        br = {'L': dict(by=0.31, tilt=0.02, curve=0.02), 'R': dict(by=0.255, tilt=0.0, curve=0.0)}
        m = _mouth('lop', w=0.12, cx=0.02, a=0.06, t=0.02)
    elif e == 'think':
        eyes = E(dx=0.025, dy=0.025)
        br = {'L': dict(by=0.33, tilt=0.0, curve=0.02), 'R': dict(by=0.255, tilt=0.03, curve=0.0)}
        m = _mouth('line', w=0.075, cx=0.05, a=0.018)
    elif e == 'blink':
        eyes = E(kind='line', w=0.062)
        br = dict()
        m = _mouth('line', w=0.11)
    else:
        raise ValueError(e)

    if 'L' in br:
        bl, brr = _brow(1, **br['L']), _brow(-1, **br['R'])
    else:
        bl, brr = _brow(1, **br), _brow(-1, **br)
    (eL, gL), (eR, gR) = eyes
    return {
        'eyes': [eL, eR],
        'glint': [gL, gR],
        'brows': [bl, brr],
        'mouth': [m],
        'tears': [_tear_stream(1, show_tears), _tear_stream(-1, show_tears)],
        'blush': [_blush_cheek(1, show_blush), _blush_cheek(-1, show_blush)],
    }


def _vis_mouth(v):
    return {
        'A': _mouth('D', w=0.13, cy=-0.225, a=0.008, d=0.13),
        'O': _mouth('O', w=0.06, cy=-0.28, d=0.075),
        'E': _mouth('open', w=0.16, cy=-0.27, a=0.025, d=0.045),
        'M': _mouth('line', w=0.1, t=0.024),
    }[v]


REGION_ORDER = ['eyes', 'brows', 'mouth', 'glint', 'tears', 'blush']


def _wrap(p, eps):
    x, z = p[0] * FACE_SX, p[1] * FACE_SY
    zs = HEAD_H / 2 - HEAD_BEV
    r = HEAD_R
    if abs(z) > zs:
        dz = min(abs(z) - zs, HEAD_BEV * 0.97)
        r = HEAD_R - HEAD_BEV + math.sqrt(HEAD_BEV ** 2 - dz * dz)
        eps = eps / max(0.25, (r - HEAD_R + HEAD_BEV) / HEAD_BEV)
    r += eps
    th = x / r
    return Vector((r * math.sin(th), -r * math.cos(th), z)) + HEAD_C


def _flatten(shapes):
    out = []
    for reg in REGION_ORDER:
        eps = EPS_GLINT if reg == 'glint' else (EPS_FX if reg in ('tears', 'blush') else EPS_FACE)
        for top, bot in shapes[reg]:
            for i in range(NCOL):
                out.append((top[i], eps))
                out.append((bot[i], eps))
    return out


def _face_object(name, mats):
    base = _expr_shapes('neutral')
    flat = _flatten(base)
    verts = [_wrap(p, e) for p, e in flat]
    faces, fmat = [], []
    k = 0
    mat_map = {'eyes': 0, 'brows': 0, 'mouth': 1, 'glint': 2, 'tears': 3, 'blush': 4}
    for reg in REGION_ORDER:
        mi = mat_map[reg]
        for _ in base[reg]:
            for i in range(NCOL - 1):
                a = k + 2 * i
                faces.append((a, a + 2, a + 3, a + 1))
                fmat.append(mi)
            k += 2 * NCOL
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    for p, mi in zip(me.polygons, fmat):
        p.material_index = mi
    for m in mats:
        me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.shape_key_add(name='Basis', from_mix=False)
    ranges, k = {}, 0
    for reg in REGION_ORDER:
        n = len(base[reg]) * 2 * NCOL
        ranges[reg] = (k, k + n)
        k += n

    def add_key(kname, shapes, regions):
        sk = ob.shape_key_add(name=kname, from_mix=False)
        fl = _flatten(shapes)
        for reg in regions:
            a, b = ranges[reg]
            for i in range(a, b):
                sk.data[i].co = _wrap(fl[i][0], fl[i][1])
        return sk

    for e in EXPRS:
        if e == 'neutral':
            continue
        sh = _expr_shapes(e)
        add_key('eyes_' + e, sh, ['eyes', 'glint'])
        add_key('brows_' + e, sh, ['brows'])
        add_key('mouth_' + e, sh, ['mouth'])
        if e == 'cry':
            add_key('fx_cry', sh, ['tears'])
        if e == 'blush':
            add_key('fx_blush', sh, ['blush'])

    for v in VISEMES:
        sh = dict(base)
        sh['mouth'] = [_vis_mouth(v)]
        add_key('vis_' + v, sh, ['mouth'])
    for axis, d in (('look_x', (0.032, 0)), ('look_y', (0, 0.026))):
        sh = {}
        for reg in REGION_ORDER:
            if reg in ('eyes', 'glint'):
                sh[reg] = [([(p[0] + d[0], p[1] + d[1]) for p in t], [(p[0] + d[0], p[1] + d[1]) for p in b])
                           for t, b in base[reg]]
            else:
                sh[reg] = base[reg]
        sk = add_key(axis, sh, ['eyes', 'glint'])
        sk.slider_min = -1.0
    return ob


def _female_cosmetics(name, ink_mat, lip_mat, cheek_mat):
    bm = bmesh.new()
    mats = [ink_mat, lip_mat, cheek_mat]
    eps = 0.015
    for side in (1, -1):
        for k, (dx, dy, ang) in enumerate(((0.068, 0.072, 24), (0.078, 0.048, 12))):
            cx = side * (EYE_X + dx)
            cy = EYE_Y + dy
            p0 = _wrap((cx - side * 0.012, cy - 0.008), eps)
            p1 = _wrap((cx + side * 0.028, cy + 0.014), eps)
            p2 = _wrap((cx + side * 0.024, cy - 0.004), eps)
            p3 = _wrap((cx - side * 0.012, cy - 0.022), eps)
            vs = [bm.verts.new(p) for p in (p0, p1, p2, p3)]
            f = bm.faces.new(vs if side > 0 else list(reversed(vs)))
            f.material_index = 0
        cx = side * (EYE_X + 0.062)
        cy = EYE_Y - 0.118
        ring = []
        for i in range(12):
            th = 2 * math.pi * i / 12
            ring.append(bm.verts.new(_wrap((cx + 0.055 * math.cos(th), cy + 0.026 * math.sin(th)), 0.011)))
        f = bm.faces.new(ring)
        f.material_index = 2
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _facial_hair(name, style, mat):
    bm = bmesh.new()
    if style in ('mustache', 'beard', 'grey_beard'):
        for side in (1, -1):
            _add_rbox(
                bm,
                (side * 0.11, -HEAD_R - 0.015, HEAD_C.z - 0.21),
                (0.20, 0.06, 0.075),
                bevel=0.025,
                seg=2,
                rot=Euler((0, math.radians(-12 * side), 0)),
            )
    if style in ('beard', 'grey_beard'):
        _add_rbox(bm, (0, -HEAD_R - 0.012, HEAD_C.z - 0.42), (0.64, 0.08, 0.28), bevel=0.035, seg=2)
        for side in (1, -1):
            _add_rbox(bm, (side * 0.34, -HEAD_R + 0.08, HEAD_C.z - 0.32), (0.08, 0.24, 0.36), bevel=0.03, seg=2)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return _obj(name, me, mat)


def _glasses(name, mat):
    bm = bmesh.new()
    eps = 0.05
    rects = []
    for side in (1, -1):
        cx, cy, hw, hh, t = side * EYE_X, EYE_Y, 0.125, 0.105, 0.025
        rects += [((cx - hw, cy + hh - t), (cx + hw, cy + hh)), ((cx - hw, cy - hh), (cx + hw, cy - hh + t)),
                  ((cx - hw, cy - hh), (cx - hw + t, cy + hh)), ((cx + hw - t, cy - hh), (cx + hw, cy + hh))]
    rects.append(((-0.08, EYE_Y + 0.03), (0.08, EYE_Y + 0.055)))
    for (x0, y0), (x1, y1) in rects:
        n = max(2, int((x1 - x0) / 0.02) + 1)
        vs = []
        for i in range(n):
            x = x0 + (x1 - x0) * i / (n - 1)
            for y in (y0, y1):
                for e in (eps, eps + 0.03):
                    vs.append(bm.verts.new(_wrap((x, y), e)))
        for i in range(n - 1):
            a = [vs[4 * i + j] for j in range(4)]
            b = [vs[4 * (i + 1) + j] for j in range(4)]
            bm.faces.new((a[1], b[1], b[3], a[3]))
            bm.faces.new((a[0], a[2], b[2], b[0]))
            bm.faces.new((a[0], b[0], b[1], a[1]))
            bm.faces.new((a[2], a[3], b[3], b[2]))
    for side in (1, -1):
        _add_rbox(bm, (side * (HEAD_R * 0.93 + 0.03), -0.2, HEAD_C.z + EYE_Y + 0.06), (0.03, 0.5, 0.03), bevel=0.01, seg=1)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return _obj(name, me, mat, smooth=False)


# ---------------------------------------------------------------- hair
def _hair(name, style, mat, mat2=None):
    if style == 'bald':
        return []
    H = HEAD_C
    P = lambda x, y, z: (H.x + x, H.y + y, H.z + z)
    obs = []
    bm = bmesh.new()

    def base(top=0.4):
        _add_rbox(bm, P(0, 0.03, 0.66), (1.36, 1.34, 0.4), bevel=0.16, seg=3)
        _add_rbox(bm, P(0, 0.42, 0.22), (1.34, 0.5, 0.78), bevel=0.15, seg=3)
        for s in (1, -1):
            _add_rbox(bm, P(s * 0.6, 0.12, 0.33), (0.18, 0.95, 0.58), bevel=0.07, seg=2)
        _add_rbox(bm, P(0.08, -0.6, 0.55), (1.1, 0.16, 0.16), bevel=0.07, seg=2)

    if style == 'short':
        base()
        for i, x in enumerate((-0.42, -0.14, 0.14, 0.42)):
            _add_rbox(bm, P(x, -0.38 + 0.05 * (i % 2), 0.82), (0.36, 0.42, 0.18), bevel=0.08, seg=2,
                      rot=Euler((math.radians(-15), 0, math.radians(8 * (i - 1.5)))))
    elif style == 'pompadour':
        base()
        _add_rbox(bm, P(0.0, -0.25, 0.88), (1.12, 0.86, 0.34), bevel=0.15, seg=3,
                  rot=Euler((math.radians(-18), 0, math.radians(6))))
        _add_rbox(bm, P(-0.08, -0.58, 0.78), (0.86, 0.36, 0.26), bevel=0.11, seg=3,
                  rot=Euler((math.radians(-26), 0, math.radians(10))))
    elif style == 'curly':
        base()
        for el, n, rr in ((20, 12, 0.27), (46, 10, 0.28), (70, 6, 0.27), (90, 1, 0.28)):
            for k in range(n):
                az = 2 * math.pi * k / n + el * 0.05
                e = math.radians(el)
                v = Vector((math.cos(e) * math.sin(az), -math.cos(e) * math.cos(az), math.sin(e)))
                c = Vector((0, 0.05, 0.3)) + Vector((v.x * 0.66, v.y * 0.68, v.z * 0.52))
                if c.y < -0.2 and c.z - rr < 0.42:
                    continue
                _add_ico(bm, P(*c), rr, scale=(1, 1, 0.8), sub=1)
    elif style == 'spiky':
        base()
        for k in range(9):
            az = 2 * math.pi * k / 9
            d = Vector((0.45 * math.sin(az), -0.45 * math.cos(az) * 0.9 + 0.05, 1.0))
            b = Vector((0.42 * math.sin(az), -0.42 * math.cos(az) + 0.05, 0.7))
            _add_cone(bm, P(*b), d, 0.2, 0.5)
        _add_cone(bm, P(0, 0.05, 0.75), (0, -0.2, 1), 0.24, 0.55)
    elif style == 'cap':
        for s in (1, -1):
            _add_rbox(bm, P(s * 0.6, 0.12, 0.3), (0.18, 0.9, 0.5), bevel=0.07, seg=2)
        _add_rbox(bm, P(0, 0.42, 0.22), (1.3, 0.5, 0.6), bevel=0.15, seg=3)
        cb = bmesh.new()
        _add_cyl(cb, P(0, 0.02, 0.6), HEAD_R + 0.07, 0.48, seg=32, bevel=0.2)
        _add_rbox(cb, P(0, -0.86, 0.43), (1.0, 0.62, 0.07), bevel=0.03, seg=2)
        _add_cyl(cb, P(0, 0.02, 0.85), 0.07, 0.05, seg=12)
        me = bpy.data.meshes.new(name + '_cap')
        cb.to_mesh(me)
        cb.free()
        obs.append(_obj(name + '_cap', me, mat2 or mat))
    elif style == 'long':
        base()
        _add_rbox(bm, P(0, 0.6, -0.25), (1.34, 0.3, 1.4), bevel=0.12, seg=3)
        for s in (1, -1):
            _add_rbox(bm, P(s * 0.66, 0.15, -0.02), (0.16, 0.85, 1.05), bevel=0.07, seg=2)
    elif style == 'pigtails':
        base()
        for s in (1, -1):
            _add_ico(bm, P(s * 0.8, 0.25, 0.1), 0.26, scale=(0.9, 0.9, 1.25), sub=2)
            _add_ico(bm, P(s * 0.68, 0.22, 0.32), 0.1, sub=1)
    elif style == 'bun':
        base()
        _add_ico(bm, P(0, 0.42, 0.88), 0.32, sub=2)
    elif style == 'grey_old':
        _add_rbox(bm, P(0, 0.42, 0.18), (1.34, 0.5, 0.55), bevel=0.15, seg=3)
        for s in (1, -1):
            _add_rbox(bm, P(s * 0.6, 0.15, 0.22), (0.18, 0.8, 0.45), bevel=0.07, seg=2)
    else:
        raise ValueError(style)
    if len(bm.verts):
        me = bpy.data.meshes.new(name)
        bm.to_mesh(me)
        obs.append(_obj(name, me, mat, smooth=style not in ('curly', 'spiky'), ang=40))
    bm.free()
    return obs


# ---------------------------------------------------------------- build
def _parent(ob, arm, bname):
    bone = arm.data.bones[bname]
    mw = ob.matrix_basis.copy()
    ob.parent = arm
    ob.parent_type = 'BONE'
    ob.parent_bone = bname
    ob.matrix_parent_inverse = (bone.matrix_local @ Matrix.Translation((0, bone.length, 0))).inverted()
    ob.matrix_basis = mw


def _shade_col(col, f):
    rgb = _parse_rgb(col)
    return tuple(max(0.0, min(1.0, c * f)) for c in rgb)


_WM = _Path(__file__).resolve().parents[1] / 'assets' / 'brand' / 'bv-wordmark-transparent.png'
_WMB = "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"


def _wm_image():
    im = bpy.data.images.get('bv_print')
    if im:
        return im
    if _WM.exists():
        im = bpy.data.images.load(str(_WM))
        im.name = 'bv_print'
    else:
        import base64
        import tempfile
        import os
        p = os.path.join(tempfile.gettempdir(), 'bv_print.png')
        open(p, 'wb').write(base64.b64decode(_WMB))
        im = bpy.data.images.load(p)
        im.name = 'bv_print'
    im.pack()
    return im


def _print_mat(plate):
    nm = 'rbx_print_plate' if plate else 'rbx_print'
    m = bpy.data.materials.get(nm)
    if m:
        return m
    m = bpy.data.materials.new(nm)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes.get('Principled BSDF')
    tx = nt.nodes.new('ShaderNodeTexImage')
    tx.image = _wm_image()
    tx.interpolation = 'Cubic'
    b.inputs['Roughness'].default_value = 0.6
    if plate:
        mx = nt.nodes.new('ShaderNodeMix')
        mx.data_type = 'RGBA'
        mx.inputs[6].default_value = (0.012, 0.016, 0.03, 1)
        nt.links.new(tx.outputs['Alpha'], mx.inputs[0])
        nt.links.new(tx.outputs['Color'], mx.inputs[7])
        nt.links.new(mx.outputs[2], b.inputs['Base Color'])
    else:
        nt.links.new(tx.outputs['Color'], b.inputs['Base Color'])
        nt.links.new(tx.outputs['Alpha'], b.inputs['Alpha'])
        try:
            m.surface_render_method = 'BLENDED'
        except Exception:
            pass
    return m


def _print_plane(name, center, width, back=False, plate=False):
    im = _wm_image()
    w = width
    h = width * im.size[1] / max(1, im.size[0])
    if plate:
        w, h = w * 1.08, h * 1.25
    me = bpy.data.meshes.new(name)
    x0, x1, z0, z1 = -w / 2, w / 2, -h / 2, h / 2
    if back:
        vs = [(x1, 0, z0), (x0, 0, z0), (x0, 0, z1), (x1, 0, z1)]
    else:
        vs = [(x0, 0, z0), (x1, 0, z0), (x1, 0, z1), (x0, 0, z1)]
    me.from_pydata(vs, [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new()
    su = 0.04 if plate else 0.0
    sv = 0.1 if plate else 0.0
    for i, (u, v) in enumerate(((0 - su, 0 - sv), (1 + su, 0 - sv), (1 + su, 1 + sv), (0 - su, 1 + sv))):
        uv.data[i].uv = (u, v)
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.data.materials.append(_print_mat(plate))
    ob.location = center
    for img_node in ob.data.materials[0].node_tree.nodes:
        if img_node.type == 'TEX_IMAGE':
            img_node.extension = 'CLIP'
    return ob


def make_char(name, spec):
    sc = bpy.context.scene
    skin = _parse_rgb(spec.get('skin'), (0.96, 0.76, 0.61))
    shirt = _parse_rgb(spec.get('shirt'), (0.12, 0.45, 0.95))
    pants = _parse_rgb(spec.get('pants'), (0.12, 0.16, 0.25))
    shoes = _parse_rgb(spec.get('shoes'), (0.12, 0.12, 0.14))
    hcol = _parse_rgb(spec.get('hair_color'), (0.20, 0.13, 0.08))
    extras = list(spec.get('extras') or [])
    gender = str(spec.get('gender', '')).lower()
    is_fem = (gender == 'female') or ('skirt' in extras) or ('dress' in extras)
    sleeves = spec.get('sleeves', 'long' if ('cardigan' in extras or 'suit' in extras) else 'short')

    ad = bpy.data.armatures.new(name + '_rig')
    arm = bpy.data.objects.new(name, ad)
    sc.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    for o in bpy.context.selected_objects:
        o.select_set(False)
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    for bn, h, t, p in BONES:
        eb = ad.edit_bones.new(bn)
        eb.head, eb.tail = h, t
        if p:
            eb.parent = ad.edit_bones[p]
            eb.use_connect = False
    bpy.ops.object.mode_set(mode='OBJECT')
    for pb in arm.pose.bones:
        pb.rotation_mode = 'QUATERNION'
    ad.display_type = 'STICK'
    arm.show_in_front = False
    arm.hide_render = True

    M_skin = _cmat(skin, 'skin', rough=0.38, coat=0.0, sss=0.06)
    M_shirt = _cmat(shirt, 'cloth', rough=0.46, sheen=0.22, coat=0.0)
    M_pants = _cmat(pants, 'cloth', rough=0.46, sheen=0.22, coat=0.0)
    M_shoes = _cmat(shoes, 'shoe', rough=0.40, coat=0.08)
    M_hair = _cmat(hcol, 'hair', rough=0.45, sheen=0.25, coat=0.05)
    M_seam = _cmat(_shade_col(shirt, 0.68), 'seam', rough=0.55)
    M_pseam = _cmat(_shade_col(pants, 0.65), 'pseam', rough=0.55)
    M_sole = _mat('rbx_shoe_sole', (0.94, 0.94, 0.96), rough=0.45)
    parts = []

    def add(ob, bone, role):
        ob['rbx_role'] = role
        _parent(ob, arm, bone)
        parts.append(ob)

    torso_w = 1.76 if is_fem else 2.04
    torso_d = 0.92 if is_fem else 1.02
    arm_w = 0.84 if is_fem else 0.98
    arm_x = 1.34 if is_fem else 1.52
    fy = -0.465 if is_fem else -0.515

    add(_rbox(name + '_torso', (0, 0, 3.2), (torso_w, torso_d, 1.6), M_shirt, bevel=0.12 if is_fem else 0.1), 'torso', 'torso')
    add(_rbox(name + '_hips', (0, 0, 2.2), (1.92 if is_fem else 1.98, 0.96, 0.42), M_pants, bevel=0.1), 'torso', 'torso')
    add(_head_mesh(name + '_head', M_skin), 'head', 'head')

    add(_rbox(name + '_vneck_L', (-0.16, fy, 3.84), (0.34, 0.025, 0.055), M_seam, bevel=0.01), 'torso', 'acc')
    add(_rbox(name + '_vneck_R', (0.16, fy, 3.84), (0.34, 0.025, 0.055), M_seam, bevel=0.01), 'torso', 'acc')
    if not is_fem or 'cardigan' in extras or 'suit' in extras:
        add(_rbox(name + '_placket', (0.0, fy, 3.15), (0.045, 0.025, 1.35), M_seam, bevel=0.01), 'torso', 'acc')
        for bz in (3.55, 3.22, 2.88):
            add(_rbox(name + f'_sbtn_{bz:.2f}', (0.0, fy - 0.008, bz), (0.075, 0.03, 0.075), M_seam, bevel=0.02), 'torso', 'acc')

    for s, sd in ((1, 'L'), (-1, 'R')):
        add(_rbox(name + '_upper_arm.' + sd, (arm_x * s, 0, 3.5), (arm_w, arm_w, 1.0), M_shirt, bevel=0.1), 'upper_arm.' + sd, 'arm')
        add(_rbox(name + '_lower_arm.' + sd, (arm_x * s, 0, 2.66), (arm_w * 0.96, arm_w * 0.96, 0.68),
                  M_shirt if sleeves == 'long' else M_skin, bevel=0.1), 'lower_arm.' + sd, 'arm')
        add(_rbox(name + '_hand.' + sd, (arm_x * s, 0, 2.15), (arm_w * 0.92, arm_w * 0.92, 0.3), M_skin, bevel=0.1), 'hand.' + sd, 'arm')
        add(_rbox(name + '_upper_leg.' + sd, (0.5 * s, 0, 1.5), (0.94 if is_fem else 0.98, 0.94 if is_fem else 0.98, 1.0), M_pants, bevel=0.1), 'upper_leg.' + sd, 'leg')
        add(_rbox(name + '_lower_leg.' + sd, (0.5 * s, 0, 0.64), (0.92 if is_fem else 0.96, 0.92 if is_fem else 0.96, 0.72), M_pants, bevel=0.1), 'lower_leg.' + sd, 'leg')
        add(_rbox(name + '_leg_seam.' + sd, (0.5 * s, -0.47, 1.15), (0.04, 0.02, 1.45), M_pseam, bevel=0.005), 'upper_leg.' + sd, 'acc')
        add(_rbox(name + '_foot.' + sd, (0.5 * s, -0.06, 0.15), (0.94, 1.08, 0.22), M_shoes, bevel=0.07), 'foot.' + sd, 'leg')
        add(_rbox(name + '_sole.' + sd, (0.5 * s, -0.07, 0.045), (0.96, 1.12, 0.08), M_sole, bevel=0.03), 'foot.' + sd, 'leg')
        add(_rbox(name + '_toecap.' + sd, (0.5 * s, -0.49, 0.11), (0.86, 0.24, 0.13), M_sole, bevel=0.04), 'foot.' + sd, 'leg')
        for lz in (0.24, 0.20):
            add(_rbox(name + f'_lace_{lz:.2f}.' + sd, (0.5 * s, -0.34, lz), (0.36, 0.08, 0.025), M_sole, bevel=0.01), 'foot.' + sd, 'leg')

    M_ink = _mat('rbx_face_ink', (0.015, 0.015, 0.02), rough=0.55)
    M_mouth = _mat('rbx_face_mouth', (0.06, 0.012, 0.015), rough=0.55)
    M_glint = _mat('rbx_face_glint', (1, 1, 1), rough=0.4, emit=True)
    M_tears = _mat('rbx_face_tears', (0.18, 0.68, 1.0), rough=0.2, emit=True, emit_strength=0.6)
    M_blush = _mat('rbx_face_blush', (0.96, 0.34, 0.46), rough=0.5, emit=True, emit_strength=0.25)
    fo = _face_object(name + '_face', [M_ink, M_mouth, M_glint, M_tears, M_blush])
    fo['rbx_role'] = 'face'
    _parent(fo, arm, 'head')

    if is_fem:
        M_lip = _cmat(spec.get('lip_color', (0.88, 0.35, 0.48)), 'lip', rough=0.35)
        M_cheek = _mat('rbx_fem_cheek', (0.98, 0.56, 0.64), rough=0.55)
        cos = _female_cosmetics(name + '_cosmetics', M_ink, M_lip, M_cheek)
        cos['rbx_role'] = 'face'
        _parent(cos, arm, 'head')

    hair_style = spec.get('hair', 'long' if is_fem else 'pompadour')
    if hair_style not in HAIR_STYLES:
        hair_style = 'long' if is_fem else 'short'
    for ob in _hair(name + '_hair', hair_style, M_hair,
                    _cmat(spec.get('cap_color', (0.1, 0.3, 0.85)), 'cap', rough=0.5)):
        ob['rbx_role'] = 'hair'
        _parent(ob, arm, 'head')

    for fh in ('mustache', 'beard', 'grey_beard'):
        if fh in extras:
            fh_mat = _cmat((0.72, 0.72, 0.75) if fh == 'grey_beard' else hcol, 'fhair', rough=0.5)
            fob = _facial_hair(name + '_' + fh, fh, fh_mat)
            fob['rbx_role'] = 'hair'
            _parent(fob, arm, 'head')

    if 'glasses' in extras:
        g = _glasses(name + '_glasses', _mat('rbx_glasses', (0.05, 0.05, 0.06), rough=0.35))
        g['rbx_role'] = 'acc'
        _parent(g, arm, 'head')

    acc = []
    if 'collar' in extras or 'tie' in extras or 'suit' in extras:
        cc = _cmat(_shade_col(shirt, 0.92), 'collar', rough=0.5)
        for s in (1, -1):
            bmc = bmesh.new()
            _add_rbox(bmc, (0.25 * s, -0.47 if is_fem else -0.51, 3.86), (0.42, 0.08, 0.2), bevel=0.03, seg=2,
                      rot=Euler((0, math.radians(-28 * s), 0)))
            me = bpy.data.meshes.new(name + '_collar' + str(s))
            bmc.to_mesh(me)
            bmc.free()
            acc.append(_obj(name + '_collar' + str(s), me, cc))
    if 'tie' in extras:
        tc = _cmat(spec.get('tie_color', (0.8, 0.08, 0.08)), 'tie', rough=0.45)
        y_off = -0.49 if is_fem else -0.53
        acc.append(_rbox(name + '_tieknot', (0, y_off, 3.85), (0.2, 0.08, 0.17), tc, bevel=0.03))
        acc.append(_rbox(name + '_tie', (0, y_off + 0.005, 3.25), (0.24, 0.06, 1.0), tc, bevel=0.03))
    if 'pocket' in extras:
        acc.append(_rbox(name + '_pocket', (0.48, -0.47 if is_fem else -0.51, 3.45), (0.36, 0.04, 0.34),
                         _cmat(_shade_col(shirt, 0.82), 'pocket', rough=0.5), bevel=0.03))
    if 'apron' in extras:
        ac = _cmat(spec.get('apron_color', (0.97, 0.97, 0.95)), 'apron', rough=0.55)
        acc.append(_rbox(name + '_apron', (0, -0.525, 2.75), (1.4, 0.06, 1.5), ac, bevel=0.04))
        acc.append(_rbox(name + '_apron_bib', (0, -0.525, 3.65), (0.9, 0.06, 0.45), ac, bevel=0.04))
        acc.append(_rbox(name + '_apron_pocket', (0, -0.565, 2.45), (0.7, 0.04, 0.32),
                         _cmat((0.9, 0.55, 0.6), 'apronpk', rough=0.5), bevel=0.03))
    if 'cardigan' in extras or 'suit' in extras:
        inner = _cmat(spec.get('inner_color', (0.96, 0.95, 0.92)), 'inner', rough=0.5)
        acc.append(_rbox(name + '_inner', (0, -0.47 if is_fem else -0.505, 3.35), (0.44, 0.04, 1.32), inner, bevel=0.02))
    if 'skirt' in extras or 'dress' in extras:
        sc_col = _cmat(spec.get('skirt_color', shirt if 'dress' in extras else pants), 'skirt', rough=0.46)
        acc.append(_rbox(name + '_skirt_top', (0, 0, 1.92), (1.96, 1.02, 0.44), sc_col, bevel=0.09))
        acc.append(_rbox(name + '_skirt_flare', (0, 0, 1.54), (2.22, 1.16, 0.46), sc_col, bevel=0.10))
        acc.append(_rbox(name + '_skirt_hem', (0, 0, 1.30), (2.28, 1.20, 0.07),
                         _cmat(_shade_col(spec.get('skirt_color', shirt if 'dress' in extras else pants), 0.75), 'hem', rough=0.5), bevel=0.02))
    for ob in acc:
        ob['rbx_role'] = 'acc'
        _parent(ob, arm, 'torso')
        parts.append(ob)

    prints = [_print_plane(name + '_print_back', (0, 0.475 if is_fem else 0.512, 3.35), 1.45 if is_fem else 1.6, back=True, plate=False)]
    for ob in prints:
        ob['rbx_role'] = 'acc'
        _parent(ob, arm, 'torso')
        parts.append(ob)
    if hair_style == 'cap':
        cp = _print_plane(name + '_print_cap', (HEAD_C.x, HEAD_C.y - 0.735, HEAD_C.z + 0.62), 0.62, plate=False)
        cp['rbx_role'] = 'hair'
        _parent(cp, arm, 'head')

    h = float(spec.get('height', 1.0))
    arm.scale = (h, h, h)
    arm['rbx_height'] = h
    arm['rbx_face'] = fo.name
    arm.rotation_mode = 'XYZ'
    return arm


def body_parts(arm):
    return [c for c in arm.children if c.type == 'MESH']


# ---------------------------------------------------------------- Universal Biomechanical Pose Synthesizer
def place(arm, frame, loc, yaw_deg):
    arm.location = loc
    arm.rotation_euler = (0, 0, math.radians(yaw_deg))
    arm.keyframe_insert('location', frame=frame)
    arm.keyframe_insert('rotation_euler', frame=frame)


def _R(x=0, y=0, z=0):
    return Euler((math.radians(x), math.radians(y), math.radians(z)), 'XYZ').to_matrix()


def _arm_fk(side, fwd=0, out=0, elbow=0, spread=0, wrist=0):
    s = 'L' if side > 0 else 'R'
    return {
        'upper_arm.' + s: _R(-fwd, -side * out, 0),
        'lower_arm.' + s: _R(-elbow, 0, side * spread),
        'hand.' + s: _R(-wrist, 0, 0),
    }


def _leg(side, fwd=0, knee=0, foot=0, out=0):
    s = 'L' if side > 0 else 'R'
    return {
        'upper_leg.' + s: _R(-fwd, -side * out, 0),
        'lower_leg.' + s: _R(knee, 0, 0),
        'foot.' + s: _R(foot, 0, 0),
    }


def _arm_from_target(side, target_name, t, tempo=1.2):
    """Map high-level biomechanical arm reach targets into realistic 3D joint angles."""
    osc = math.sin(2 * math.pi * tempo * t)
    pulse = 0.5 + 0.5 * osc
    tg = str(target_name or 'rest').lower().strip()

    if tg in ('mouth', 'eat', 'drink', 'sip', 'taste', 'whisper'):
        return _arm_fk(side, fwd=74 + 38 * pulse, out=16 * pulse, elbow=56 + 14 * pulse, spread=-96 + 10 * pulse)
    if tg in ('overhead', 'hang', 'reach_up', 'sky', 'cheer', 'celebrate'):
        return _arm_fk(side, fwd=12, out=158 + 8 * osc, elbow=10 + 8 * (1 - pulse))
    if tg in ('front_reach', 'give', 'offer', 'pass', 'push', 'open', 'grab', 'take', 'point', 'knock'):
        k_knock = 18 * osc if tg == 'knock' else 10 * pulse
        return _arm_fk(side, fwd=68 + k_knock, out=6, elbow=16 - 8 * pulse, spread=-6)
    if tg in ('pull', 'yank', 'drag', 'row'):
        return _arm_fk(side, fwd=42 + 34 * pulse, out=8, elbow=68 - 44 * pulse)
    if tg in ('floor_reach', 'pick_up', 'drop', 'tie', 'dig', 'scoop'):
        return _arm_fk(side, fwd=54 + 14 * pulse, out=6, elbow=16 + 10 * pulse)
    if tg in ('eye_inspect', 'read', 'phone', 'inspect', 'write', 'look_at', 'cook', 'serve'):
        jitter = 7 * osc if tg in ('write', 'cook') else 2 * osc
        return _arm_fk(side, fwd=56, out=5, elbow=62 + jitter, spread=-28 + jitter * 0.6)
    if tg in ('chest_cross', 'hug', 'guard', 'shield', 'scared'):
        return _arm_fk(side, fwd=74, out=-4, elbow=72, spread=-88)
    if tg in ('hip', 'akimbo', 'sassy', 'proud'):
        return _arm_fk(side, fwd=-10, out=34, elbow=68, spread=-45)
    if tg in ('head', 'facepalm', 'think', 'scratch_head'):
        return _arm_fk(side, fwd=118, out=18, elbow=56, spread=-82)
    if tg in ('wave', 'beckon'):
        return _arm_fk(side, fwd=14, out=142 + 16 * osc, elbow=20 + 10 * osc)
    if tg in ('curl', 'lift', 'exercise'):
        return _arm_fk(side, fwd=22, out=12, elbow=28 + 84 * pulse)
    if tg in ('swing', 'walk_swing'):
        return _arm_fk(side, fwd=22 * osc, out=4, elbow=14 + 10 * max(0.0, osc))
    # Natural micro-breathing rest
    return _arm_fk(side, fwd=3 + 2 * pulse, out=4 + 1.5 * osc, elbow=8 + 3 * pulse)


def _synthesize_from_spec(spec, t):
    """Build a full-body R6 pose directly from parametric biomechanical parameters."""
    tempo = float(spec.get('tempo', 1.2))
    osc = math.sin(2 * math.pi * tempo * t)
    pulse = 0.5 + 0.5 * osc
    br = math.sin(2 * math.pi * t / 3.2)

    torso_pitch = float(spec.get('torso_pitch', 0.0)) + 2.5 * osc * float(spec.get('torso_bob', 0.3))
    torso_roll = float(spec.get('torso_roll', 0.0)) + 2.0 * math.sin(2 * math.pi * t / 5.4)
    torso_yaw = float(spec.get('torso_yaw', 0.0))
    hip_z = float(spec.get('hip_z', 0.0))
    hip_y = float(spec.get('hip_y', 0.0))
    head_pitch = float(spec.get('head_pitch', 0.0)) - 1.2 * br
    head_yaw = float(spec.get('head_yaw', 0.0)) + 2.5 * math.sin(2 * math.pi * t / 4.7)
    leg_mode = str(spec.get('leg_mode', 'stand')).lower().strip()

    P = {
        'torso': _R(torso_pitch, torso_roll, torso_yaw),
        'head': _R(head_pitch, 0.0, head_yaw),
    }
    P.update(_arm_from_target(-1, spec.get('arm_R', 'rest'), t, tempo))
    P.update(_arm_from_target(1, spec.get('arm_L', 'rest'), t, tempo))

    if leg_mode in ('walk', 'run', 'sneak', 'march'):
        run = (leg_mode == 'run')
        sneak = (leg_mode == 'sneak')
        march = (leg_mode == 'march')
        A = 38 if run else (26 if march else (18 if sneak else 21.8))
        K = 95 if run else (72 if march else (52 if sneak else 45))
        w = 2 * math.pi * tempo * t
        for s, ph in ((1, 0.0), (-1, math.pi)):
            thl = A * math.sin(w + ph)
            sw = max(0.0, math.cos(w + ph))
            knee = K * (sw ** 1.25) + (18 if sneak else 4)
            P.update(_leg(s, fwd=thl, knee=knee, foot=0.8 * (thl - knee)))
        if sneak:
            hip_z -= 0.24
            P['torso'] = _R(16, torso_roll, torso_yaw)
    elif leg_mode in ('sit', 'sit_90'):
        for s in (1, -1):
            P.update(_leg(s, fwd=90, knee=90, out=3))
        hip_z = 1.6 + 0.485 - HIP_Z
    elif leg_mode in ('kneel', 'crouch'):
        bend = 55 if leg_mode == 'crouch' else 82
        for s in (1, -1):
            P.update(_leg(s, fwd=bend, knee=bend * 1.45, foot=-bend * 0.45, out=4))
        hip_z -= 0.55 if leg_mode == 'crouch' else 0.72
    elif leg_mode in ('hang', 'hang_dangle', 'float'):
        for s, ph in ((1, 0.0), (-1, math.pi * 0.7)):
            sway = 14 * math.sin(2 * math.pi * 0.85 * t + ph)
            P.update(_leg(s, fwd=sway, knee=16 + 10 * pulse, out=4))
        hip_z += 0.35 + 0.08 * osc
    elif leg_mode in ('lie', 'lie_down', 'fall'):
        P['torso'] = _R(-86, torso_roll, torso_yaw)
        for s in (1, -1):
            P.update(_leg(s, fwd=-86, knee=6, out=3))
        hip_z = -1.25
    elif leg_mode == 'kick':
        P.update(_leg(-1, fwd=68 * pulse, knee=14 * (1 - pulse), foot=-12))
        P.update(_leg(1, fwd=-8, knee=6))
    else:
        # Grounded alive weight-shift stance
        sh = math.sin(2 * math.pi * t / 5.8)
        dx = 0.04 * sh
        beta = math.degrees(math.asin(max(-0.5, min(0.5, dx / HIP_Z))))
        for s in (1, -1):
            P['upper_leg.' + ('L' if s > 0 else 'R')] = _R(0, beta, 0)
        return P, Vector((dx, hip_y, hip_z + 0.012 * br - 0.012))

    return P, Vector((0.0, hip_y, hip_z))


def _synthesize_semantic_pose(anim_name, t):
    """Defensive universal resolver: decomposes ANY unknown human/cartoon verb into full-body motion."""
    tokens = set(re.findall(r'[a-z]+', str(anim_name or 'idle').lower()))
    spec = {
        'torso_pitch': 0.0,
        'torso_roll': 0.0,
        'torso_yaw': 0.0,
        'hip_z': 0.0,
        'hip_y': 0.0,
        'head_pitch': 0.0,
        'head_yaw': 0.0,
        'arm_R': 'rest',
        'arm_L': 'rest',
        'leg_mode': 'stand',
        'tempo': 1.2,
        'torso_bob': 0.3,
    }

    # 1. Locomotion & Posture cues
    if tokens & {'run', 'sprint', 'dash', 'flee', 'chase', 'rush'}:
        spec['leg_mode'] = 'run'
        spec['tempo'] = 1.65
        spec['arm_R'] = 'walk_swing'
        spec['arm_L'] = 'walk_swing'
    elif tokens & {'sneak', 'tiptoe', 'creep', 'stalk'}:
        spec['leg_mode'] = 'sneak'
        spec['tempo'] = 0.95
        spec['arm_R'] = 'guard'
        spec['arm_L'] = 'guard'
    elif tokens & {'walk', 'stroll', 'step', 'pace', 'march', 'enter', 'leave', 'approach'}:
        spec['leg_mode'] = 'march' if 'march' in tokens else 'walk'
        spec['tempo'] = 1.05
        spec['arm_R'] = 'walk_swing'
        spec['arm_L'] = 'walk_swing'
    elif tokens & {'sit', 'seated', 'chair', 'bench'}:
        spec['leg_mode'] = 'sit'
        spec['arm_R'] = 'eye_inspect' if (tokens & {'read', 'eat', 'write', 'phone', 'type'}) else 'rest'
    elif tokens & {'kneel', 'crouch', 'duck', 'hide', 'squat'}:
        spec['leg_mode'] = 'crouch'
        spec['torso_pitch'] = 18.0
        spec['arm_R'] = 'guard'
        spec['arm_L'] = 'guard'
    elif tokens & {'hang', 'dangle', 'swing', 'climb', 'suspend', 'pullup'}:
        spec['leg_mode'] = 'hang'
        spec['arm_R'] = 'overhead'
        spec['arm_L'] = 'overhead'
        spec['head_pitch'] = -16.0
        spec['tempo'] = 0.9
    elif tokens & {'lie', 'sleep', 'faint', 'collapse', 'fall', 'trip'}:
        spec['leg_mode'] = 'lie'
        spec['arm_R'] = 'overhead'
        spec['arm_L'] = 'rest'
    elif tokens & {'kick', 'stomp'}:
        spec['leg_mode'] = 'kick'
        spec['torso_pitch'] = -8.0
        spec['tempo'] = 1.5

    # 2. Hand & Upper-Body Interaction cues
    if tokens & {'eat', 'bite', 'chew', 'drink', 'sip', 'gulp', 'taste', 'lick', 'feed', 'swallow'}:
        spec['arm_R'] = 'mouth'
        spec['arm_L'] = 'eye_inspect'
        spec['head_pitch'] = 6.0
        spec['tempo'] = 0.85
    elif tokens & {'whisper', 'secret', 'mutter'}:
        spec['arm_R'] = 'mouth'
        spec['torso_pitch'] = 10.0
        spec['torso_yaw'] = -12.0
    elif tokens & {'give', 'hand', 'offer', 'pass', 'present', 'deliver', 'trade', 'pay'}:
        spec['arm_R'] = 'front_reach'
        spec['arm_L'] = 'front_reach'
        spec['torso_pitch'] = 8.0
    elif tokens & {'receive', 'accept', 'catch', 'grab', 'take', 'snatch', 'steal', 'reach'}:
        spec['arm_R'] = 'front_reach'
        spec['torso_pitch'] = 9.0
    elif tokens & {'open', 'close', 'shut', 'knock', 'tap', 'push', 'press', 'unlock', 'turn'}:
        spec['arm_R'] = 'front_reach'
        spec['torso_pitch'] = 7.0
        spec['tempo'] = 1.8 if 'knock' in tokens else 1.0
    elif tokens & {'pull', 'yank', 'drag', 'tug', 'open_fridge'}:
        spec['arm_R'] = 'pull'
        spec['arm_L'] = 'pull'
        spec['torso_pitch'] = -12.0
    elif tokens & {'pick', 'pickup', 'drop', 'place', 'put', 'tie', 'dig', 'scoop', 'sweep', 'clean'}:
        spec['arm_R'] = 'floor_reach'
        spec['torso_pitch'] = 34.0
        spec['head_pitch'] = 16.0
        spec['hip_z'] = -0.32
    elif tokens & {'read', 'inspect', 'examine', 'check', 'phone', 'text', 'type', 'write', 'draw', 'cook', 'stir', 'pour', 'serve'}:
        spec['arm_R'] = 'eye_inspect'
        spec['arm_L'] = 'eye_inspect'
        spec['head_pitch'] = 14.0
        spec['torso_pitch'] = 6.0
    elif tokens & {'lift', 'carry', 'hold', 'heavy', 'box', 'tray'}:
        spec['arm_R'] = 'eye_inspect'
        spec['arm_L'] = 'eye_inspect'
        spec['torso_pitch'] = -5.0
    elif tokens & {'throw', 'toss', 'hurl', 'launch'}:
        spec['arm_R'] = 'overhead'
        spec['torso_pitch'] = -12.0
        spec['tempo'] = 1.8
    elif tokens & {'wave', 'greet', 'hello', 'bye', 'beckon', 'call'}:
        spec['arm_R'] = 'wave'
        spec['tempo'] = 1.8
    elif tokens & {'cheer', 'celebrate', 'victory', 'win', 'hurray', 'yay', 'up'}:
        spec['arm_R'] = 'overhead'
        spec['arm_L'] = 'overhead'
        spec['head_pitch'] = -10.0
        spec['hip_z'] = 0.25 * (0.5 + 0.5 * math.sin(2 * math.pi * 1.8 * t))
    elif tokens & {'laugh', 'giggle', 'chuckle', 'haha'}:
        spec['arm_R'] = 'chest_cross'
        spec['torso_pitch'] = -8.0
        spec['torso_bob'] = 1.6
        spec['tempo'] = 2.6
    elif tokens & {'dodge', 'recoil', 'startle', 'gasp', 'avoid'}:
        spec['arm_R'] = 'guard'
        spec['arm_L'] = 'guard'
        spec['torso_pitch'] = -14.0
        spec['hip_y'] = 0.14
    elif tokens & {'proud', 'boss', 'mayor', 'command', 'pose', 'hero'}:
        spec['arm_R'] = 'hip'
        spec['arm_L'] = 'hip'
        spec['torso_pitch'] = -5.0

    return _synthesize_from_spec(spec, t)


def _idle(t, talk=False):
    br = math.sin(2 * math.pi * t / 3.2)
    sh = math.sin(2 * math.pi * t / 6.0)
    dx = 0.045 * sh
    beta = math.degrees(math.asin(dx / HIP_Z))
    P = {
        'torso': _R(0.8 * br, -1.2 * sh, 1.5 * math.sin(2 * math.pi * t / 7.3)),
        'head': _R(
            -1.0 * br + (2 * math.sin(2 * math.pi * t * 0.7) if talk else 0),
            1.5 * sh,
            3 * math.sin(2 * math.pi * t / 5.1) + (4 * math.sin(2 * math.pi * t * 0.31) if talk else 0),
        ),
    }
    P.update(_arm_fk(1, fwd=2, out=3 + 1.2 * br, elbow=6))
    P.update(_arm_fk(-1, fwd=2, out=3 + 1.2 * br, elbow=6))
    for s in (1, -1):
        P['upper_leg.' + ('L' if s > 0 else 'R')] = _R(0, beta, 0)
    root = Vector((dx, 0, 0.012 * br - 0.012))
    if talk:
        g1 = 0.5 + 0.5 * math.sin(2 * math.pi * 0.85 * t)
        g2 = 0.5 + 0.5 * math.sin(2 * math.pi * 0.6 * t + 1.3)
        P.update(_arm_fk(-1, fwd=14 + 10 * g1, out=6, elbow=30 + 35 * g1, spread=12 * g2))
        P.update(_arm_fk(1, fwd=6 + 6 * g2, out=5, elbow=12 + 30 * g2 * (1 - g1 * 0.5), spread=8 * g1))
    return P, root


def _walk(t, run=False):
    T = 0.6 if run else 1.0
    c = (t / T) % 1.0
    w = 2 * math.pi * c
    A = 38 if run else 21.8
    K = 95 if run else 45
    B = 50 if run else 24
    th = A * math.sin(w)
    P = {}
    for s, ph in ((1, 0), (-1, math.pi)):
        thl = A * math.sin(w + ph)
        sw = max(0.0, math.cos(w + ph))
        knee = K * sw ** 1.3 + (8 if run else 3)
        P.update(_leg(s, fwd=thl, knee=knee, foot=0.85 * (thl - knee)))
        aphase = -math.sin(w + ph)
        P.update(_arm_fk(s, fwd=B * aphase, out=4, elbow=(80 if run else 14) + (10 if run else 12) * max(0, aphase)))
    lean = 12 if run else 2
    P['torso'] = _R(lean + (2 if run else 1) * math.cos(2 * w), 0, (8 if run else 5) * math.sin(w))
    P['head'] = _R(-lean * 0.6, 0, -(6 if run else 4) * math.sin(w))
    dz = HIP_Z * math.cos(math.radians(th)) - HIP_Z
    if run:
        dz += 0.18 * abs(math.sin(w)) - 0.1
    return P, Vector((0, 0, dz))


def _static(anim, t):
    P, root = {}, Vector()
    if anim == 'point':
        P.update(_arm_fk(-1, fwd=88, out=6, elbow=0))
        P.update(_arm_fk(1, fwd=3, out=4, elbow=10))
        P['torso'] = _R(2, 0, -6)
        P['head'] = _R(0, 0, -4)
    elif anim in ('grab', 'give', 'receive', 'open_door', 'close_door'):
        k = 0.5 + 0.5 * math.sin(2 * math.pi * 0.9 * t)
        P.update(_arm_fk(-1, fwd=64 + 22 * k, out=8, elbow=22 - 14 * k))
        P.update(_arm_fk(1, fwd=24 if anim in ('give', 'receive') else 10, out=5, elbow=16))
        P['torso'] = _R(8 + 4 * k, 0, -6)
        P['head'] = _R(4, 0, -4)
    elif anim == 'knock':
        kn = math.sin(2 * math.pi * 2.6 * t)
        P.update(_arm_fk(-1, fwd=62 + 18 * kn, out=6, elbow=52 - 22 * kn))
        P.update(_arm_fk(1, fwd=4, out=4, elbow=10))
        P['torso'] = _R(6, 0, -4)
        P['head'] = _R(2, 0, -4)
    elif anim in ('push', 'pull', 'lift'):
        osc = math.sin(2 * math.pi * 0.9 * t)
        fwd_a = 45 + 25 * osc if anim == 'pull' else 74 + 12 * osc
        elb_a = 65 - 42 * osc if anim == 'pull' else 18 - 8 * osc
        for s in (1, -1):
            P.update(_arm_fk(s, fwd=fwd_a, out=6, elbow=elb_a))
        P['torso'] = _R(-12 if anim == 'pull' else 14, 0, 0)
        P['head'] = _R(-4 if anim == 'pull' else 6, 0, 0)
    elif anim == 'hang':
        sway = 12 * math.sin(2 * math.pi * 0.85 * t)
        for s in (1, -1):
            P.update(_arm_fk(s, fwd=10, out=162, elbow=8))
            P.update(_leg(s, fwd=sway * s, knee=18, out=4))
        P['torso'] = _R(-4, 0, sway * 0.4)
        P['head'] = _R(-18, 0, 0)
        root = Vector((0, 0, 0.38 + 0.05 * math.sin(2 * math.pi * 0.85 * t)))
    elif anim == 'climb':
        w = 2 * math.pi * 1.2 * t
        for s, ph in ((1, 0), (-1, math.pi)):
            p = 0.5 + 0.5 * math.sin(w + ph)
            P.update(_arm_fk(s, fwd=35, out=120 + 40 * p, elbow=60 - 45 * p))
            P.update(_leg(s, fwd=45 * (1 - p), knee=65 * (1 - p)))
        P['torso'] = _R(10, 0, 6 * math.sin(w))
        P['head'] = _R(-14, 0, 0)
    elif anim == 'bend':
        k = 0.5 + 0.5 * math.sin(2 * math.pi * 0.7 * t)
        P['torso'] = _R(34 + 8 * k, 0, 0)
        P['head'] = _R(12, 0, 0)
        for s in (1, -1):
            P.update(_leg(s, fwd=18, knee=34, foot=-16))
        P.update(_arm_fk(-1, fwd=48 + 14 * k, out=6, elbow=18))
        P.update(_arm_fk(1, fwd=24, out=8, elbow=22))
        root = Vector((0, -0.15, -0.35))
    elif anim in ('write', 'cook', 'serve'):
        sc = math.sin(2 * math.pi * 3.0 * t)
        P.update(_arm_fk(-1, fwd=56, out=6, elbow=58 + 10 * sc, spread=-24 + 6 * sc))
        P.update(_arm_fk(1, fwd=48, out=5, elbow=66, spread=-26))
        P['torso'] = _R(8, 0, -4)
        P['head'] = _R(14, 0, -4)
    elif anim in ('read', 'inspect', 'phone_use'):
        P.update(_arm_fk(-1, fwd=56, out=4, elbow=64, spread=-28))
        P.update(_arm_fk(1, fwd=54 if anim == 'read' else 10, out=4, elbow=62 if anim == 'read' else 14, spread=-24 if anim == 'read' else 0))
        P['torso'] = _R(4, 0, 0)
        P['head'] = _R(14, 0, 3 * math.sin(2 * math.pi * 0.6 * t))
    elif anim == 'exercise':
        pump = 0.5 + 0.5 * math.sin(2 * math.pi * 1.6 * t)
        for s in (1, -1):
            P.update(_arm_fk(s, fwd=18, out=14, elbow=25 + 85 * pump))
        P['torso'] = _R(4 * pump, 0, 0)
        P['head'] = _R(-3 * pump, 0, 0)
        root = Vector((0, 0, 0.04 * pump))
    elif anim in ('shrug', 'what'):
        for s in (1, -1):
            P.update(_arm_fk(s, fwd=10, out=24, elbow=78, spread=42))
        P['head'] = _R(-4, 10, 0)
        P['torso'] = _R(-3, 0, 0)
    elif anim == 'shock':
        for s in (1, -1):
            P.update(_arm_fk(s, fwd=90, out=10, elbow=130, spread=30))
        P['torso'] = _R(-9, 0, 0)
        P['head'] = _R(-8, 0, 0)
        root = Vector((0, 0.08, 0))
    elif anim == 'scared':
        for s in (1, -1):
            P.update(_arm_fk(s, fwd=80, out=-10, elbow=130, spread=-30))
        tr = 0.6 * math.sin(2 * math.pi * 9 * t)
        P['torso'] = _R(6 + tr, 0, tr)
        P['head'] = _R(6, 0, 0)
        root = Vector((0, 0, -0.04))
    elif anim in ('cheer', 'jump_joy'):
        pump = 0.5 + 0.5 * math.sin(2 * math.pi * 1.8 * t)
        for s in (1, -1):
            P.update(_arm_fk(s, fwd=12, out=150 + 12 * pump, elbow=12 + 15 * (1 - pump)))
        P['torso'] = _R(-4, 0, 0)
        P['head'] = _R(-10, 0, 0)
        root = Vector((0, 0, (0.35 if anim == 'jump_joy' else 0.14) * pump))
    elif anim in ('eat', 'drink'):
        k = 0.5 - 0.5 * math.cos(2 * math.pi * 0.75 * t)
        P.update(_arm_fk(-1, fwd=70 + 50 * k, out=20 * k, elbow=50 + 10 * k, spread=-100 + 10 * k))
        P.update(_arm_fk(1, fwd=42, out=6, elbow=50, spread=-10))
        P['head'] = _R(8 - 10 * k if anim == 'drink' else 8 - 6 * k, 0, -4 * k)
    elif anim == 'whisper':
        P.update(_arm_fk(-1, fwd=98, out=14, elbow=68, spread=-85))
        P.update(_arm_fk(1, fwd=6, out=4, elbow=10))
        P['torso'] = _R(12, 0, -14)
        P['head'] = _R(6, 0, -10)
    elif anim == 'laugh_body':
        bob = math.sin(2 * math.pi * 2.8 * t)
        for s in (1, -1):
            P.update(_arm_fk(s, fwd=64, out=-6, elbow=72, spread=-85))
        P['torso'] = _R(-10 + 4 * bob, 0, 0)
        P['head'] = _R(-14 + 5 * bob, 0, 0)
    elif anim == 'cross_arms':
        P.update(_arm_fk(1, fwd=70, out=0, elbow=60, spread=-90))
        P.update(_arm_fk(-1, fwd=80, out=0, elbow=72, spread=-90))
        P['torso'] = _R(-2, 0, 0)
        P['head'] = _R(-3, 4, 0)
    elif anim == 'think':
        P.update(_arm_fk(-1, fwd=120, out=20, elbow=60, spread=-90))
        P.update(_arm_fk(1, fwd=70, out=0, elbow=60, spread=-90))
        P['head'] = _R(-6, -6, -10 + 3 * math.sin(2 * math.pi * 0.3 * t))
    elif anim in ('sad', 'slump'):
        for s in (1, -1):
            P.update(_arm_fk(s, fwd=6, out=1, elbow=6))
        P['torso'] = _R(15 if anim == 'slump' else 13, 0, 0)
        P['head'] = _R(20 if anim == 'slump' else 18, 0, 0)
        root = Vector((0, 0, -0.05))
    elif anim == 'angry':
        sh = math.sin(2 * math.pi * 6 * t) * 1.2
        for s in (1, -1):
            P.update(_arm_fk(s, fwd=-6, out=14 + sh, elbow=40, spread=-8))
        P['torso'] = _R(9, 0, sh)
        P['head'] = _R(6, 0, 0)
    elif anim in ('wave', 'beckon'):
        P.update(_arm_fk(-1, fwd=10, out=145 + 15 * math.sin(2 * math.pi * 1.8 * t), elbow=18))
        P.update(_arm_fk(1, fwd=2, out=4, elbow=8))
        P['torso'] = _R(0, -4, 0)
        P['head'] = _R(-3, 5, 0)
    elif anim == 'sit':
        for s in (1, -1):
            P.update(_leg(s, fwd=90, knee=90, out=2))
            P.update(_arm_fk(s, fwd=28, out=4, elbow=38))
        P['torso'] = _R(-3, 0, 0)
        root = Vector((0, 0, 1.6 + 0.485 - HIP_Z))
    elif anim in ('kneel', 'crouch'):
        for s in (1, -1):
            P.update(_leg(s, fwd=62, knee=95, foot=-32, out=3))
            P.update(_arm_fk(s, fwd=34, out=6, elbow=42))
        P['torso'] = _R(12, 0, 0)
        root = Vector((0, 0, -0.58))
    elif anim == 'lie_down':
        P['torso'] = _R(-88, 0, 0)
        for s in (1, -1):
            P.update(_leg(s, fwd=-88, knee=4, out=2))
            P.update(_arm_fk(s, fwd=4, out=8, elbow=10))
        root = Vector((0, 0, -1.25))
    elif anim == 'facepalm':
        P.update(_arm_fk(-1, fwd=120, out=20, elbow=50, spread=-70))
        P.update(_arm_fk(1, fwd=4, out=3, elbow=10))
        P['torso'] = _R(8, 0, -6)
        P['head'] = _R(14, 8, -10)
    elif anim == 'nod':
        P, root = _idle(t, talk=False)
        P['head'] = _R(14 * math.sin(2 * math.pi * 1.8 * t), 0, 0)
    elif anim == 'headshake':
        P, root = _idle(t, talk=False)
        P['head'] = _R(0, 0, 18 * math.sin(2 * math.pi * 1.8 * t))
    elif anim == 'flinch':
        k = math.exp(-3.5 * (t % 1.0))
        for s in (1, -1):
            P.update(_arm_fk(s, fwd=55 * k, out=18 * k, elbow=85 * k))
        P['torso'] = _R(-10 * k, 0, 0)
        P['head'] = _R(-12 * k, 0, 0)
        root = Vector((0, 0.15 * k, -0.04 * k))
    elif anim == 'surrender':
        for s in (1, -1):
            P.update(_arm_fk(s, fwd=15, out=145, elbow=45, spread=-15))
        P['torso'] = _R(-4, 0, 0)
        P['head'] = _R(4, 0, 0)
    elif anim == 'clap':
        cl = 0.5 + 0.5 * math.sin(2 * math.pi * 2.5 * t)
        for s in (1, -1):
            P.update(_arm_fk(s, fwd=52, out=-8, elbow=55, spread=-38 - 18 * cl))
        P['head'] = _R(-2, 0, 4 * math.sin(2 * math.pi * 1.2 * t))
    elif anim == 'swell':
        for s in (1, -1):
            P.update(_arm_fk(s, fwd=10, out=48, elbow=24))
        P['torso'] = _R(-8, 0, 0)
        P['head'] = _R(-12, 0, 0)
        root = Vector((0, 0, 0.45 + 0.18 * math.sin(2 * math.pi * 0.9 * t)))
    elif anim in ('hold_hands', 'hold_hands_L', 'hold_hands_R'):
        P, root = _idle(t, talk=False)
        sway = 3.0 * math.sin(2 * math.pi * 0.9 * t)
        if anim == 'hold_hands_R':
            P.update(_arm_fk(-1, fwd=16, out=24, elbow=16))
            P.update(_arm_fk(1, fwd=2 + sway, out=4, elbow=8))
        else:
            P.update(_arm_fk(1, fwd=16, out=24, elbow=16))
            P.update(_arm_fk(-1, fwd=2 - sway, out=4, elbow=8))
    else:
        return _synthesize_semantic_pose(anim, t)
    return P, root


def _pose_dict(anim, phase, pose_spec=None):
    if pose_spec:
        return _synthesize_from_spec(pose_spec, phase)
    if anim in ('idle', 'talk'):
        return _idle(phase, anim == 'talk')
    if anim in ('walk', 'run'):
        return _walk(phase, anim == 'run')
    if anim == 'sneak':
        return _synthesize_semantic_pose('sneak', phase)
    if anim == 'march':
        return _synthesize_semantic_pose('march', phase)
    P, root = _static(anim, phase)
    br = math.sin(2 * math.pi * phase / 3.2)
    if 'head' in P:
        P['head'] = _R(-0.8 * br) @ P['head']
    return P, root


def _apply_pose_dict(arm, frame, P, root, amount=1.0, swell=1.0):
    I = Quaternion()
    for bn in BONE_NAMES:
        pb = arm.pose.bones[bn]
        bone = arm.data.bones[bn]
        r3 = bone.matrix_local.to_3x3()
        if bn == 'root':
            pb.location = r3.inverted() @ (root * amount)
            pb.rotation_quaternion = I
            pb.keyframe_insert('location', frame=frame)
        else:
            R = P.get(bn, Matrix.Identity(3))
            q = (r3.inverted() @ R @ r3).to_quaternion()
            if amount != 1.0:
                q = I.slerp(q, amount)
            if q.w < 0:
                q.negate()
            pb.rotation_quaternion = q
        if bn == 'torso':
            pb.scale = (swell, swell, 1.0 + (swell - 1.0) * 0.45)
            pb.keyframe_insert('scale', frame=frame)
        pb.keyframe_insert('rotation_quaternion', frame=frame)


def pose(arm, frame, anim, phase=0.0, amount=1.0, pose_spec=None):
    P, root = _pose_dict(anim, phase, pose_spec=pose_spec)
    swell = float((pose_spec or {}).get('swell', 1.65 if anim == 'swell' else 1.0))
    _apply_pose_dict(arm, frame, P, root, amount=amount, swell=swell)


def pose_mix(arm, frame, anim_a, phase_a, anim_b, phase_b, mix=0.5, pose_spec=None):
    """Smooth quaternion slerp + root blend between two poses inside a shot."""
    m = max(0.0, min(1.0, float(mix)))
    Pa, ra = _pose_dict(anim_a, phase_a)
    Pb, rb = _pose_dict(anim_b, phase_b, pose_spec=pose_spec)
    P_blend = {}
    for bn in BONE_NAMES:
        if bn == 'root':
            continue
        qa = Pa.get(bn, Matrix.Identity(3)).to_quaternion()
        qb = Pb.get(bn, Matrix.Identity(3)).to_quaternion()
        if qa.dot(qb) < 0:
            qb.negate()
        P_blend[bn] = qa.slerp(qb, m).to_matrix()
    r_blend = ra.lerp(rb, m)
    swell = float((pose_spec or {}).get('swell', 1.65 if anim_b == 'swell' else 1.0))
    _apply_pose_dict(arm, frame, P_blend, r_blend, amount=1.0, swell=1.0 + (swell - 1.0) * m)


_EXPR_ALIASES = {
    'happy': 'smile',
    'joy': 'grin',
    'excited': 'grin',
    'evil': 'scheming',
    'mischievous': 'scheming',
    'devious': 'scheming',
    'sneaky': 'scheming',
    'fear': 'scared',
    'terrified': 'scared',
    'surprised': 'shock',
    'amazed': 'shock',
    'mad': 'angry',
    'furious': 'angry',
    'upset': 'sad',
    'disappointed': 'sad',
    'crying': 'cry',
    'tears': 'cry',
    'weeping': 'cry',
    'sobbing': 'cry',
    'blushing': 'blush',
    'shy': 'blush',
    'flustered': 'blush',
    'embarrassed': 'blush',
    'confused': 'think',
    'curious': 'think',
    'nervous': 'worried',
    'anxious': 'worried',
    'cringe': 'wince',
    'pain': 'wince',
    'hurt': 'wince',
}


def face(arm, frame, expr, viseme=None, blink=0.0, look=(0, 0), mix_from=None, mix=1.0):
    fo = bpy.data.objects[arm['rbx_face']]
    kb = fo.data.shape_keys.key_blocks
    w = {e: 0.0 for e in EXPRS}
    expr_key = _EXPR_ALIASES.get(str(expr).lower().strip(), str(expr).lower().strip())
    if expr_key not in w:
        expr_key = 'neutral'
    w[expr_key] += mix
    if mix_from is not None:
        mf_key = _EXPR_ALIASES.get(str(mix_from).lower().strip(), str(mix_from).lower().strip())
        if mf_key not in w:
            mf_key = 'neutral'
        w[mf_key] += 1.0 - mix
    else:
        w['neutral'] += 1.0 - mix
    blink = max(0.0, min(1.0, blink))
    vs = 0.8 if viseme else 0.0
    for e in EXPRS:
        if e == 'neutral':
            continue
        ew = w[e] * (1 - blink) + (blink if e == 'blink' else 0.0)
        kb['eyes_' + e].value = ew
        kb['brows_' + e].value = w[e]
        kb['mouth_' + e].value = w[e] * (1 - vs)
    if 'fx_cry' in kb:
        kb['fx_cry'].value = w.get('cry', 0.0)
    if 'fx_blush' in kb:
        kb['fx_blush'].value = w.get('blush', 0.0)
    for v in VISEMES:
        kb['vis_' + v].value = vs if v == viseme else 0.0
    kb['look_x'].value = max(-1, min(1, look[0]))
    kb['look_y'].value = max(-1, min(1, look[1]))
    for k in kb[1:]:
        k.keyframe_insert('value', frame=frame)


def set_linear(*ids):
    for idb in ids:
        ad = getattr(idb, 'animation_data', None)
        if not ad or not ad.action:
            continue
        for fc in _fcurves(ad.action):
            for kp in fc.keyframe_points:
                kp.interpolation = 'LINEAR'


def _fcurves(action):
    try:
        return list(action.fcurves)
    except Exception:
        out = []
        for layer in action.layers:
            for strip in layer.strips:
                for cb in strip.channelbags:
                    out += list(cb.fcurves)
        return out


try:
    bpy.context.preferences.edit.keyframe_new_interpolation_type = 'LINEAR'
except Exception:
    pass
