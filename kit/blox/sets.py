"""Beta Version Blox Studio sets: Roblox-style worlds with bright warm studio global illumination.

Self-contained: textures are the CC0 Poly Haven sets in kit/assets/textures, every prop is code-built in props.py,
and the Beta Version brand is placed in-world as real signage (props.brand_plate / props.atlas_decal).

Universal Defensive Set Synthesizer:
  - Supports canonical sets (`Street`, `Kitchen`), `places_built.BUILT`, `places.PRESETS`, AND
    any arbitrary location name (e.g., `Rooftop`, `Classroom`, `LivingRoom`, `Gym`, `Park`, `Cafe`,
    `Supermarket`, `Hospital`, `Bedroom`, `Library`, `Forest`, `Office`) via `_build_semantic_set`.

API
    build_set(name, origin=(0,0,0), spec=None) -> bpy.types.Collection
    set_mood(mood, x=1.0)        mood in sunny / storm / night (x blends sunny -> mood, 0..1)
    setup_render(scene)          1080x1920, 30 fps, EEVEE, AgX, DOF/motion blur/raytracing/volumes/bloom
    ANCHORS                      {set: {anchor: (x,y,z) relative to origin}}
    dof(cam_obj, focus, fstop)   optional helper (compile.py sets DOF itself)

1 unit = 1 Roblox stud, Z up, characters stand at origin facing -Y, cameras on the -Y side.
Clear zone |x|<7, -4<y<3 stays empty except floor (+ Kitchen.table, Street.sign).
"""
import math
import os
import random
import re
from pathlib import Path

import bpy
import bmesh
from mathutils import Matrix, Vector

import props

TEX = str(Path(__file__).resolve().parents[1] / 'assets' / 'textures')


# ------------------------------------------------------------------ colour helpers
def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _col(h, a=1.0):
    h = h.lstrip('#')
    return (*(_lin(int(h[i:i + 2], 16) / 255.0) for i in (0, 2, 4)), a)


def _sock(socks, ident):
    for s in socks:
        if s.identifier == ident:
            return s
    return socks[ident]


# ------------------------------------------------------------------ world / control nodes
CTL = ('fog', 'wet', 'win', 'lamp', 'neon', 'prac', 'expo', 'cloud')


def _world():
    sc = bpy.context.scene
    w = bpy.data.worlds.get('RobloxSky')
    if w is None:
        w = bpy.data.worlds.new('RobloxSky')
    sc.world = w
    w.use_nodes = True
    nt = w.node_tree
    if 'bg_cam' in nt.nodes:
        return nt
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    N, L = nt.nodes.new, nt.links.new
    ctl = {}
    for i, k in enumerate(CTL):
        n = N('ShaderNodeMath')
        n.operation = 'ADD'
        n.name = n.label = 'ctl_' + k
        n.inputs[0].default_value = 0.0
        n.inputs[1].default_value = 0.0
        n.location = (-900, 400 - i * 60)
        ctl[k] = n
    tc = N('ShaderNodeTexCoord')
    sep = N('ShaderNodeSeparateXYZ')
    L(tc.outputs['Generated'], sep.inputs[0])
    grad = N('ShaderNodeMapRange')
    grad.name = 'sky_grad'
    grad.inputs['From Min'].default_value = -0.02
    grad.inputs['From Max'].default_value = 0.55
    L(sep.outputs['Z'], grad.inputs['Value'])
    sky = N('ShaderNodeMix')
    sky.data_type = 'RGBA'
    sky.name = 'sky_col'
    L(grad.outputs['Result'], _sock(sky.inputs, 'Factor_Float'))

    zz = N('ShaderNodeMath')
    zz.operation = 'ADD'
    zz.inputs[1].default_value = 0.12
    L(sep.outputs['Z'], zz.inputs[0])
    dx = N('ShaderNodeMath')
    dx.operation = 'DIVIDE'
    L(sep.outputs['X'], dx.inputs[0])
    L(zz.outputs[0], dx.inputs[1])
    dy = N('ShaderNodeMath')
    dy.operation = 'DIVIDE'
    L(sep.outputs['Y'], dy.inputs[0])
    L(zz.outputs[0], dy.inputs[1])
    cv = N('ShaderNodeCombineXYZ')
    L(dx.outputs[0], cv.inputs[0])
    L(dy.outputs[0], cv.inputs[1])
    nz = N('ShaderNodeTexNoise')
    nz.inputs['Scale'].default_value = 0.9
    nz.inputs['Detail'].default_value = 6
    nz.inputs['Roughness'].default_value = 0.55
    L(cv.outputs[0], nz.inputs['Vector'])
    thr = N('ShaderNodeMath')
    thr.operation = 'MULTIPLY_ADD'
    L(ctl['cloud'].outputs[0], thr.inputs[0])
    thr.inputs[1].default_value = -0.24
    thr.inputs[2].default_value = 0.66
    df = N('ShaderNodeMath')
    df.operation = 'SUBTRACT'
    L(nz.outputs['Fac'], df.inputs[0])
    L(thr.outputs[0], df.inputs[1])
    cf = N('ShaderNodeMath')
    cf.operation = 'MULTIPLY'
    cf.use_clamp = True
    cf.inputs[1].default_value = 5.0
    L(df.outputs[0], cf.inputs[0])
    hm = N('ShaderNodeMapRange')
    hm.inputs['From Min'].default_value = 0.0
    hm.inputs['From Max'].default_value = 0.12
    L(sep.outputs['Z'], hm.inputs['Value'])
    cm = N('ShaderNodeMath')
    cm.operation = 'MULTIPLY'
    L(cf.outputs[0], cm.inputs[0])
    L(hm.outputs['Result'], cm.inputs[1])
    cl = N('ShaderNodeMix')
    cl.data_type = 'RGBA'
    cl.name = 'cloud_col'
    L(cm.outputs[0], _sock(cl.inputs, 'Factor_Float'))
    L(_sock(sky.outputs, 'Result_Color'), _sock(cl.inputs, 'A_Color'))
    bgc = N('ShaderNodeBackground')
    bgc.name = 'bg_cam'
    L(_sock(cl.outputs, 'Result_Color'), bgc.inputs['Color'])

    lg = N('ShaderNodeMapRange')
    lg.inputs['From Min'].default_value = -0.25
    lg.inputs['From Max'].default_value = 0.25
    L(sep.outputs['Z'], lg.inputs['Value'])
    lit = N('ShaderNodeMix')
    lit.data_type = 'RGBA'
    lit.name = 'lit_col'
    L(lg.outputs['Result'], _sock(lit.inputs, 'Factor_Float'))
    bgl = N('ShaderNodeBackground')
    bgl.name = 'bg_lit'
    L(_sock(lit.outputs, 'Result_Color'), bgl.inputs['Color'])
    lp = N('ShaderNodeLightPath')
    ms = N('ShaderNodeMixShader')
    L(lp.outputs['Is Camera Ray'], ms.inputs['Fac'])
    L(bgl.outputs[0], ms.inputs[1])
    L(bgc.outputs[0], ms.inputs[2])
    out = N('ShaderNodeOutputWorld')
    L(ms.outputs[0], out.inputs['Surface'])
    return nt


def _ctl_path(k):
    return f'node_tree.nodes["ctl_{k}"].inputs[0].default_value'


def _drive(owner, path, expr, keys):
    w = bpy.data.worlds['RobloxSky']
    try:
        owner.driver_remove(path)
    except Exception:
        pass
    fc = owner.driver_add(path)
    for m in list(fc.modifiers):
        fc.modifiers.remove(m)
    d = fc.driver
    d.type = 'SCRIPTED'
    for k in keys:
        v = d.variables.new()
        v.name = k
        v.type = 'SINGLE_PROP'
        t = v.targets[0]
        t.id_type = 'WORLD'
        t.id = w
        t.data_path = _ctl_path(k)
    d.expression = expr
    return fc


def _drv_value(nt, name, expr, keys):
    n = nt.nodes.get(name)
    if n is None:
        n = nt.nodes.new('ShaderNodeValue')
        n.name = n.label = name
        _drive(nt, f'nodes["{name}"].outputs[0].default_value', expr, keys)
    return n


# ------------------------------------------------------------------ materials
def _new_mat(name):
    m = bpy.data.materials.get('set_' + name)
    if m:
        return m, False
    m = bpy.data.materials.new('set_' + name)
    m.use_nodes = True
    return m, True


def _bsdf(m):
    return m.node_tree.nodes.get('Principled BSDF')


def _vec(nt, tile, rot=None):
    tc = nt.nodes.new('ShaderNodeTexCoord')
    mp = nt.nodes.new('ShaderNodeMapping')
    mp.inputs['Scale'].default_value = (1.0 / tile, 1.0 / tile, 1.0 / tile)
    if rot:
        mp.inputs['Rotation'].default_value = rot
    nt.links.new(tc.outputs['Object'], mp.inputs['Vector'])
    return mp.outputs['Vector']


def _img(nt, path, noncolor, vec):
    n = nt.nodes.new('ShaderNodeTexImage')
    n.image = bpy.data.images.load(path, check_existing=True)
    if noncolor:
        n.image.colorspace_settings.name = 'Non-Color'
    n.projection = 'BOX'
    n.projection_blend = 0.2
    nt.links.new(vec, n.inputs['Vector'])
    return n


def _mix(nt, a, b, fac, blend='MIX', data='RGBA'):
    n = nt.nodes.new('ShaderNodeMix')
    n.data_type = data
    if data == 'RGBA':
        n.blend_type = blend
        sa, sb, so = 'A_Color', 'B_Color', 'Result_Color'
    else:
        sa, sb, so = 'A_Float', 'B_Float', 'Result_Float'
    for sock, v in ((_sock(n.inputs, 'Factor_Float'), fac), (_sock(n.inputs, sa), a), (_sock(n.inputs, sb), b)):
        if isinstance(v, bpy.types.NodeSocket):
            nt.links.new(v, sock)
        else:
            sock.default_value = v
    return _sock(n.outputs, so)


def _math(nt, op, a, b=0.0, clamp=False):
    n = nt.nodes.new('ShaderNodeMath')
    n.operation = op
    n.use_clamp = clamp
    for s, v in ((n.inputs[0], a), (n.inputs[1], b)):
        if isinstance(v, bpy.types.NodeSocket):
            nt.links.new(v, s)
        else:
            s.default_value = v
    return n.outputs[0]


def _maprange(nt, v, a, b, c=0.0, d=1.0):
    n = nt.nodes.new('ShaderNodeMapRange')
    for k, x in (('From Min', a), ('From Max', b), ('To Min', c), ('To Max', d)):
        if isinstance(x, bpy.types.NodeSocket):
            nt.links.new(x, n.inputs[k])
        else:
            n.inputs[k].default_value = x
    nt.links.new(v, n.inputs['Value'])
    return n.outputs['Result']


def _noise(nt, scale, detail=4.0, rough=0.55, vec=None):
    n = nt.nodes.new('ShaderNodeTexNoise')
    n.inputs['Scale'].default_value = scale
    n.inputs['Detail'].default_value = detail
    n.inputs['Roughness'].default_value = rough
    if vec is not None:
        nt.links.new(vec, n.inputs['Vector'])
    else:
        tc = nt.nodes.new('ShaderNodeTexCoord')
        nt.links.new(tc.outputs['Object'], n.inputs['Vector'])
    return n.outputs['Fac']


def _wear(nt, col, rough, grime, floor=False, rough_amt=0.06):
    if grime <= 0:
        return col, rough
    patch = _maprange(nt, _noise(nt, 0.12, 4.0, 0.55), 0.48, 0.78)
    if floor:
        mask = _math(nt, 'MULTIPLY', patch, 0.45)
    else:
        geo = nt.nodes.new('ShaderNodeNewGeometry')
        sep = nt.nodes.new('ShaderNodeSeparateXYZ')
        nt.links.new(geo.outputs['Position'], sep.inputs[0])
        base = _maprange(nt, sep.outputs['Z'], 0.0, 2.5, 0.65, 0.0)
        mask = _math(nt, 'MAXIMUM', _math(nt, 'MULTIPLY', base, 0.5), _math(nt, 'MULTIPLY', patch, 0.35))
    mask = _math(nt, 'MULTIPLY', mask, grime * 0.65, clamp=True)
    col = _mix(nt, col, _col('#786c60'), mask, 'MULTIPLY')
    rough = _math(nt, 'ADD', rough, _math(nt, 'MULTIPLY', mask, rough_amt), clamp=True)
    return col, rough


def _wet(nt, col, rough, nstr_sock=None):
    w = _drv_value(nt, 'drv_wet', 'wet', ['wet']).outputs[0]
    puddle = _noise(nt, 0.11, 3.0, 0.5)
    t0 = _math(nt, 'MULTIPLY_ADD', w, -0.10)
    t0.node.inputs[2].default_value = 0.66
    t1 = _math(nt, 'ADD', t0, 0.025)
    pm = _maprange(nt, puddle, t0, t1)
    pf = _math(nt, 'MULTIPLY', pm, w)
    damp = _math(nt, 'MULTIPLY', w, 0.55)
    dark = _math(nt, 'ADD', damp, _math(nt, 'MULTIPLY', pf, 0.35), clamp=True)
    col = _mix(nt, col, (0.45, 0.45, 0.45, 1), dark, 'MULTIPLY')
    rough = _mix(nt, rough, 0.28, _math(nt, 'MULTIPLY', w, 0.75), data='FLOAT')
    rough = _mix(nt, rough, 0.03, pf, data='FLOAT')
    flat = _math(nt, 'SUBTRACT', 1.0, pf)
    return col, rough, flat


def pbr(name, slug, tile, tint='#ffffff', sat=0.95, val=1.08, rough_mul=0.95, nstr=0.85, grime=0.15, floor=False,
        wet=False, paint=None, paint_keep=0.22, metal=0.0, spec=0.5, ramp=None, rot=None):
    m, new = _new_mat(name)
    if not new:
        return m
    nt = m.node_tree
    b = _bsdf(m)
    b.inputs['Specular IOR Level'].default_value = spec
    b.inputs['Metallic'].default_value = metal
    if 'Coat Weight' in b.inputs:
        b.inputs['Coat Weight'].default_value = 0.0
    d = os.path.join(TEX, slug)
    f = lambda k: os.path.join(d, f'{slug}_{k}_1k.jpg')
    if not os.path.exists(f('diff')):
        b.inputs['Base Color'].default_value = _col(paint or tint)
        b.inputs['Roughness'].default_value = 0.65 * rough_mul
        m.diffuse_color = _col(paint or tint)
        return m
    vec = _vec(nt, tile, rot)
    di = _img(nt, f('diff'), False, vec)
    col = di.outputs['Color']
    if paint or ramp:
        bw = nt.nodes.new('ShaderNodeRGBToBW')
        nt.links.new(col, bw.inputs[0])
        det = _math(nt, 'MULTIPLY_ADD', bw.outputs[0], paint_keep / 0.45)
        det.node.inputs[2].default_value = 1.0 - paint_keep
        if ramp:
            at = nt.nodes.new('ShaderNodeAttribute')
            at.attribute_name = 'rnd'
            at.attribute_type = 'GEOMETRY'
            cr = nt.nodes.new('ShaderNodeValToRGB')
            cr.color_ramp.interpolation = 'CONSTANT'
            els = cr.color_ramp.elements
            for i, h in enumerate(ramp):
                e = els[i] if i < 2 else els.new(0.0)
                e.position = i / len(ramp)
                e.color = _col(h)
            nt.links.new(at.outputs['Fac'], cr.inputs['Fac'])
            pc = cr.outputs['Color']
        else:
            pc = _col(paint)
        col = _mix(nt, pc, det, 1.0, 'MULTIPLY')
    else:
        hs = nt.nodes.new('ShaderNodeHueSaturation')
        hs.inputs['Saturation'].default_value = sat
        hs.inputs['Value'].default_value = val
        nt.links.new(col, hs.inputs['Color'])
        col = _mix(nt, hs.outputs['Color'], _col(tint), 1.0, 'MULTIPLY')
    ri = _img(nt, f('rough'), True, vec)
    rough = _math(nt, 'MULTIPLY', ri.outputs['Color'], rough_mul, clamp=True)
    col, rough = _wear(nt, col, rough, grime, floor)
    nm = nt.nodes.new('ShaderNodeNormalMap')
    nm.inputs['Strength'].default_value = nstr
    ni = _img(nt, f('nor_gl'), True, vec)
    nt.links.new(ni.outputs['Color'], nm.inputs['Color'])
    if wet:
        col, rough, flat = _wet(nt, col, rough)
        nt.links.new(_math(nt, 'MULTIPLY', flat, nstr), nm.inputs['Strength'])
    nt.links.new(col, b.inputs['Base Color'])
    nt.links.new(rough, b.inputs['Roughness'])
    nt.links.new(nm.outputs['Normal'], b.inputs['Normal'])
    m.diffuse_color = _col(paint or (ramp[0] if ramp else tint))
    return m


def flat(name, hexcol, rough=0.62, metal=0.0, spec=0.5, emit=0.0, emit_col=None, alpha=1.0, coat=0.0, var=0.08,
         grime=0.0, ramp=None, drv=None):
    m, new = _new_mat(name)
    if not new:
        return m
    nt = m.node_tree
    b = _bsdf(m)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    b.inputs['Specular IOR Level'].default_value = spec
    if 'Coat Weight' in b.inputs:
        b.inputs['Coat Weight'].default_value = coat
        b.inputs['Coat Roughness'].default_value = 0.2
    if ramp:
        at = nt.nodes.new('ShaderNodeAttribute')
        at.attribute_name = 'rnd'
        at.attribute_type = 'GEOMETRY'
        cr = nt.nodes.new('ShaderNodeValToRGB')
        cr.color_ramp.interpolation = 'CONSTANT'
        for i, h in enumerate(ramp):
            e = cr.color_ramp.elements[i] if i < 2 else cr.color_ramp.elements.new(0.0)
            e.position = i / len(ramp)
            e.color = _col(h)
        nt.links.new(at.outputs['Fac'], cr.inputs['Fac'])
        col = cr.outputs['Color']
    else:
        col = _col(hexcol)
    if var > 0:
        nz = _maprange(nt, _noise(nt, 0.6, 3.0, 0.5), 0.3, 0.7, 1.0 - var, 1.0)
        cnode = nt.nodes.new('ShaderNodeCombineColor')
        for i in range(3):
            nt.links.new(nz, cnode.inputs[i])
        col = _mix(nt, col, cnode.outputs[0], 1.0, 'MULTIPLY')
    rr = rough
    if grime:
        col, rr = _wear(nt, col, rough, grime)
    if isinstance(col, bpy.types.NodeSocket):
        nt.links.new(col, b.inputs['Base Color'])
    else:
        b.inputs['Base Color'].default_value = col
    if isinstance(rr, bpy.types.NodeSocket):
        nt.links.new(rr, b.inputs['Roughness'])
    if emit or drv:
        b.inputs['Emission Color'].default_value = _col(emit_col or hexcol)
        b.inputs['Emission Strength'].default_value = emit
        if drv:
            v = _drv_value(nt, 'drv_emit', drv[0], drv[1])
            nt.links.new(v.outputs[0], b.inputs['Emission Strength'])
    if alpha < 1:
        b.inputs['Alpha'].default_value = alpha
        try:
            m.surface_render_method = 'BLENDED'
        except Exception:
            pass
    m.diffuse_color = _col(hexcol)
    return m


def skywin(name, base='#34495e', lit_frac=0.45, drv_expr='win'):
    m, new = _new_mat(name)
    if not new:
        return m
    nt = m.node_tree
    b = _bsdf(m)
    b.inputs['Base Color'].default_value = _col(base)
    b.inputs['Roughness'].default_value = 0.12
    b.inputs['Specular IOR Level'].default_value = 0.65
    at = nt.nodes.new('ShaderNodeAttribute')
    at.attribute_name = 'rnd'
    at.attribute_type = 'GEOMETRY'
    lit = _math(nt, 'LESS_THAN', at.outputs['Fac'], lit_frac)
    cool = _math(nt, 'LESS_THAN', at.outputs['Fac'], lit_frac * 0.25)
    ec = _mix(nt, _col('#ffd49e'), _col('#bfe0ff'), cool)
    b.inputs['Emission Strength'].default_value = 0.25
    nt.links.new(ec, b.inputs['Emission Color'])
    v = _drv_value(nt, 'drv_emit', '0.25+' + drv_expr + '*0.85' if drv_expr == 'win' else drv_expr, ['win'])
    nt.links.new(_math(nt, 'MULTIPLY', lit, v.outputs[0]), b.inputs['Emission Strength'])
    m.diffuse_color = _col(base)
    return m


# ------------------------------------------------------------------ builder
ARCH, PROP = 0.025, 0.06


class _B:
    def __init__(self, setname, coll, origin):
        self.set, self.coll, self.o = setname, coll, Vector(origin)
        self.parts = {}
        self.rng = random.Random(setname)

    def _bm(self, g, m, bev):
        bev = PROP if bev is True else (0.0 if bev is False else bev)
        k = (g, m.name, bev)
        if k not in self.parts:
            bm = bmesh.new()
            bm.faces.layers.float.new('rnd')
            self.parts[k] = (bm, m)
        return self.parts[k][0]

    def _tag(self, bm, verts, rnd, smooth=False):
        lay = bm.faces.layers.float['rnd']
        r = self.rng.random() if rnd is None else rnd
        for f in {f for v in verts for f in v.link_faces}:
            f[lay] = r
            if smooth and len(f.verts) == 4:
                f.smooth = True

    def box(self, g, m, size, loc, bev=True, rnd=None, rot=0.0):
        bm = self._bm(g, m, bev)
        M = Matrix.Translation(loc) @ Matrix.Rotation(rot, 4, 'Z') @ Matrix.Diagonal((*size, 1))
        res = bmesh.ops.create_cube(bm, size=1.0, matrix=M)
        self._tag(bm, res['verts'], rnd)

    def boxr(self, g, m, x0, x1, y0, y1, z0, z1, bev=True, rnd=None):
        self.box(g, m, (x1 - x0, y1 - y0, z1 - z0), ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2), bev, rnd)

    def cyl(self, g, m, r, depth, loc, axis='Z', seg=16, r2=None, bev=True, rnd=None):
        bm = self._bm(g, m, bev)
        R = {'Z': Matrix(), 'X': Matrix.Rotation(math.pi / 2, 4, 'Y'),
             'Y': Matrix.Rotation(math.pi / 2, 4, 'X')}[axis]
        M = Matrix.Translation(loc) @ R
        res = bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r,
                                    radius2=r if r2 is None else r2, depth=depth, matrix=M)
        self._tag(bm, res['verts'], rnd, smooth=True)

    def ball(self, g, m, r, loc, scale=(1, 1, 1), sub=3, rnd=None):
        bm = self._bm(g, m, False)
        M = Matrix.Translation(loc) @ Matrix.Diagonal((*scale, 1))
        res = bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=r, matrix=M)
        self._tag(bm, res['verts'], rnd)
        for f in {f for v in res['verts'] for f in v.link_faces}:
            f.smooth = True

    def finish(self):
        objs = []
        for (g, mname, bev), (bm, m) in self.parts.items():
            me = bpy.data.meshes.new(f'{self.set}.{g}')
            bm.to_mesh(me)
            bm.free()
            me.materials.append(m)
            ob = bpy.data.objects.new(f'{self.set}.{g}.{m.name[4:]}', me)
            ob.location = self.o
            self.coll.objects.link(ob)
            if bev:
                md = ob.modifiers.new('bevel', 'BEVEL')
                md.width = bev
                md.segments = 1 if bev <= ARCH else 2
                md.limit_method = 'ANGLE'
                md.angle_limit = math.radians(40)
                md.harden_normals = False
            objs.append(ob)
        return objs


def _anchor(coll, setname, name, origin, loc):
    e = bpy.data.objects.new(f'{setname}.{name}', None)
    e.empty_display_type = 'ARROWS'
    e.location = Vector(origin) + Vector(loc)
    coll.objects.link(e)
    return e


# ------------------------------------------------------------------ lights
def _light(coll, setname, name, kind, O, loc, aim, ch, base, colch=None, color=(1, 1, 1), size=2.0, size_y=None,
           spot=70, blend=0.5, cutoff=70.0, shadow=True, volume=1.0):
    ld = bpy.data.lights.new(f'{setname}.{name}', kind)
    ld.color = color
    ld.energy = base
    ld.use_shadow = shadow
    if hasattr(ld, 'use_shadow_jitter'):
        ld.use_shadow_jitter = False
    ld.volume_factor = volume
    ld.use_custom_distance = True
    ld.cutoff_distance = cutoff
    if kind == 'AREA':
        ld.shape = 'RECTANGLE' if size_y else 'SQUARE'
        ld.size = size
        if size_y:
            ld.size_y = size_y
    elif kind == 'SPOT':
        ld.spot_size = math.radians(spot)
        ld.spot_blend = blend
        ld.shadow_soft_size = size
    else:
        ld.shadow_soft_size = size
    ob = bpy.data.objects.new(f'{setname}.{name}', ld)
    p = Vector(O) + Vector(loc)
    ob.location = p
    if aim is not None:
        ob.rotation_euler = (Vector(O) + Vector(aim) - p).to_track_quat('-Z', 'Y').to_euler()
    ob['ch'] = ch
    ob['base'] = base
    if colch:
        ob['colch'] = colch
    coll.objects.link(ob)
    return ob


def _fog(coll, setname, O, lo, hi, mult=1.0, col='#d8dde8'):
    m, new = _new_mat(f'fog_{setname}')
    if new:
        nt = m.node_tree
        nt.nodes.remove(_bsdf(m))
        pv = nt.nodes.new('ShaderNodeVolumePrincipled')
        pv.inputs['Color'].default_value = _col(col)
        pv.inputs['Anisotropy'].default_value = 0.45
        v = _drv_value(nt, 'drv_fog', f'fog*{mult:.3f}', ['fog'])
        geo = nt.nodes.new('ShaderNodeNewGeometry')
        sep = nt.nodes.new('ShaderNodeSeparateXYZ')
        nt.links.new(geo.outputs['Position'], sep.inputs[0])
        hgt = _maprange(nt, sep.outputs['Z'], 0.0, hi[2] * 0.9, 1.3, 0.5)
        nt.links.new(_math(nt, 'MULTIPLY', v.outputs[0], hgt), pv.inputs['Density'])
        out = nt.nodes.get('Material Output')
        nt.links.new(pv.outputs[0], out.inputs['Volume'])
    me = bpy.data.meshes.new(f'{setname}.fog')
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation((Vector(lo) + Vector(hi)) / 2) @
                          Matrix.Diagonal((*(Vector(hi) - Vector(lo)), 1)))
    bm.to_mesh(me)
    bm.free()
    me.materials.append(m)
    ob = bpy.data.objects.new(f'{setname}.fog', me)
    ob.location = Vector(O)
    ob.hide_viewport = True
    ob.display_type = 'BOUNDS'
    ob.visible_shadow = False
    coll.objects.link(ob)
    return ob


# ------------------------------------------------------------------ palette (bright saturated Roblox style)
P = {}
FACADE = ['#e5cfb2', '#a8c8cf', '#bed1a5', '#e4b79c', '#ebe3d3', '#c8b2a2', '#dbc79c', '#a3b8cc']
AWNING = ['#c84b3e', '#3c78a8', '#529448', '#d69636', '#8a5288']
BOOKS = ['#d64541', '#2e77bb', '#e0a82e', '#3da35d', '#9b59b6', '#f39c12', '#1abc9c']


def _mats():
    if P:
        return
    P.update(
        grass=pbr('grass', 'leafy_grass', 6.0, sat=0.95, val=1.05, grime=0.0, floor=True, nstr=0.55),
        walk=pbr('sidewalk', 'square_concrete_pavers', 7.0, tint='#ebe7df', sat=0.5, val=1.22, grime=0.1,
                 floor=True, wet=True, nstr=0.75),
        curb=pbr('curb', 'concrete_wall_008', 4.0, tint='#dad8d2', sat=0.35, val=1.12, grime=0.15, wet=True),
        road=pbr('road', 'asphalt_02', 10.0, sat=0.45, val=1.05, grime=0.0, floor=True, wet=True, nstr=0.75),
        brick=pbr('brick', 'red_brick_03', 3.6, tint='#f0cbb8', sat=0.82, val=1.12, rough_mul=0.95, nstr=0.95,
                  grime=0.15),
        wbrick=pbr('wbrick', 'whitewashed_brick', 4.0, tint='#f5eee2', sat=0.55, val=1.12, grime=0.15),
        stucco=pbr('stucco', 'white_stucco', 6.0, ramp=FACADE, paint_keep=0.22, grime=0.12, nstr=0.6),
        shutter=pbr('shutter', 'rusted_shutter', 3.0, tint='#c8c4be', sat=0.35, val=1.28, grime=0.15, metal=0.3),
        rust=pbr('rustmetal', 'rusty_metal_02', 2.5, sat=0.6, val=1.0, grime=0.15, metal=0.5),
        plank=pbr('plank', 'plywood', 3.0, sat=0.88, val=1.12, grime=0.08),
        wood=pbr('wood', 'wood_table_001', 3.0, sat=0.92, val=1.35, grime=0.05),
        trim=flat('trim', '#f4f0e8', rough=0.55, grime=0.08),
        trimdark=flat('trimdark', '#3a3e44', rough=0.5),
        dark=flat('darkmetal', '#2c3036', rough=0.42, metal=0.55),
        metal=flat('steel', '#ced4da', rough=0.28, metal=0.9, var=0.05),
        black=flat('black', '#1e2024', rough=0.48),
        white=flat('paper', '#f8f6f0', rough=0.72),
        yellow=flat('lineyellow', '#f2c94c', rough=0.65, var=0.12),
        lineW=flat('linewhite', '#f2f0ea', rough=0.65, var=0.12),
        leaf=flat('leaf', '#58b347', rough=0.72, var=0.18),
        leaf2=flat('leaf2', '#469e38', rough=0.72, var=0.18),
        trunk=flat('trunk', '#856347', rough=0.8, var=0.15),
        tire=flat('tire', '#222428', rough=0.8),
        red=flat('red', '#e0483e', rough=0.45),
        blue=flat('blue', '#2e7de0', rough=0.45),
        green=flat('green', '#38a852', rough=0.45),
        awning=flat('awning', '#c84b3e', rough=0.78, ramp=AWNING, var=0.08),
        books=flat('books', '#d64541', rough=0.68, ramp=BOOKS, var=0.06),
        win=skywin('skywin'),
        shopglass=skywin('shopglass', base='#34495e', lit_frac=1.01, drv_expr='0.25+win*0.9'),
        lampglass=flat('lampglass', '#fff4dc', rough=0.28, emit_col='#ffe0a8', drv=('0.8+lamp*30', ['lamp'])),
        neon=flat('neon', '#ff5fbf', rough=0.25, emit_col='#ff4fc8', drv=('2.5+neon*25', ['neon'])),
        bulb=flat('bulb', '#fff6e5', rough=0.25, emit_col='#fff2dc', drv=('(3.5+prac*20)*(1-max(0, cloud-0.5)*1.5)', ['prac', 'cloud'])),
        panel=flat('panel', '#f8faff', rough=0.25, emit_col='#f6f9ff', drv=('(3.0+prac*10)*(1-max(0, cloud-0.5)*1.5)', ['prac', 'cloud'])),
        brushed=flat('brushedsteel', '#d4d8dc', rough=0.35, metal=0.82, var=0.06, grime=0.1),
        enamel=flat('enamel', '#f2f0ea', rough=0.28, grime=0.12, var=0.04),
        plaster=pbr('plaster', 'painted_plaster_wall', 6.0, paint='#eee8dc', paint_keep=0.18, grime=0.08),
    )


# ------------------------------------------------------------------ props (code-built)
def _tree(b, x, y, z=0.0, s=1.0):
    b.cyl('trees', P['trunk'], 0.4 * s, 5.0 * s, (x, y, z + 2.5 * s), seg=10, r2=0.3 * s)
    rnd = random.Random(int(x * 13 + y * 7))
    for i in range(7):
        a = rnd.uniform(0, 6.28)
        r = rnd.uniform(0.6, 1.6) * s
        b.ball('trees', P['leaf' if i % 2 else 'leaf2'], rnd.uniform(1.3, 2.0) * s,
               (x + math.cos(a) * r, y + math.sin(a) * r * 0.7, z + rnd.uniform(5.4, 7.8) * s), sub=2)


def _ac(b, x, y, z, face=-1):
    b.box('wall', P['metal'], (2.0, 1.2, 1.4), (x, y + face * 0.6, z), bev=PROP)
    b.box('wall', P['dark'], (1.6, 0.05, 1.0), (x, y + face * 1.22, z), bev=False)


def _walllamp(b, coll, S, O, x, y, z, face=-1):
    b.box('wall', P['dark'], (0.6, 0.6, 0.25), (x, y + face * 0.4, z + 0.3))
    b.box('lampglass', P['lampglass'], (0.42, 0.42, 0.5), (x, y + face * 0.4, z - 0.05), bev=False)
    _light(coll, S, f'wl{int(x)}', 'SPOT', O, (x, y + face * 0.6, z - 0.4), (x, y + face * 2.2, 0), 'lamp', 900,
           color=(1.0, 0.76, 0.50), spot=95, blend=0.7, size=0.25, cutoff=30)


# ------------------------------------------------------------------ STREET
def _building(b, x0, x1, y_face, depth, h, facade, facing=-1, shop=True, k=0, shutter=False):
    y0, y1 = (y_face, y_face + depth) if facing < 0 else (y_face - depth, y_face)
    g = 'bld'
    b.boxr(g, facade, x0, x1, y0, y1, -0.3, h, bev=ARCH)
    b.boxr(g, P['trim'], x0 - 0.35, x1 + 0.35, y0 - 0.35, y1 + 0.35, h, h + 0.7, bev=ARCH)
    fy = y_face + (-0.06 if facing < 0 else 0.06)
    out = -1 if facing < 0 else 1
    w = x1 - x0
    ncol = max(2, int((w - 1.5) // 3.2))
    sp = (w - 1.0) / ncol
    z = 6.6 if shop else 3.6
    while z + 3.0 < h - 0.8:
        for i in range(ncol):
            cx = x0 + 0.5 + sp * (i + 0.5)
            ww = min(2.2, sp * 0.6)
            b.box('win', P['win'], (ww, 0.2, 2.6), (cx, fy, z + 1.3), bev=False)
            b.box('winframe', P['trim'], (ww + 0.5, 0.3, 0.3), (cx, fy + out * 0.1, z - 0.05), bev=ARCH)
            b.box('winframe', P['trim'], (ww + 0.3, 0.25, 0.22), (cx, fy + out * 0.05, z + 2.7), bev=ARCH)
        z += 4.2
    if shop:
        b.boxr(g, P['trimdark'], x0, x1, *((fy - 0.3, fy) if facing < 0 else (fy, fy + 0.3)), 4.6, 5.6, bev=ARCH)
        b.boxr(g, P['trim'], x0 - 0.1, x1 + 0.1, *((fy - 0.45, fy) if facing < 0 else (fy, fy + 0.45)), 5.6, 5.9, bev=ARCH)
        dx = x0 + w * 0.3
        if shutter:
            b.box('shutter', P['shutter'], (w * 0.75, 0.2, 4.3), ((x0 + x1) / 2, fy + out * 0.05, 2.15), bev=False)
        else:
            b.box(g, P['wood'], (2.0, 0.3, 3.6), (dx, fy, 1.8))
            b.box('shopwin', P['shopglass'], (w * 0.45, 0.2, 3.0), (x0 + w * 0.68, fy, 2.0), bev=False)
            b.box('winframe', P['trimdark'], (w * 0.45 + 0.4, 0.4, 0.35), (x0 + w * 0.68, fy, 0.35), bev=ARCH)
            ay = fy + out * 1.0
            b.box('awning', P['awning'], (w * 0.82, 2.0, 0.3), ((x0 + x1) / 2, ay, 4.3), rnd=(k * 0.37) % 1)
            b.box('awning', P['awning'], (w * 0.82, 0.12, 0.9), ((x0 + x1) / 2, ay + out * 1.0, 3.95), rnd=(k * 0.37) % 1)


def _W(O):
    return lambda x, y, z: Vector(O) + Vector((x, y, z))


def _street(b, coll, O):
    S = 'Street'
    W = _W(O)
    b.boxr('ground', P['grass'], -120, 120, -120, 120, -1.3, -0.3, bev=False)
    b.boxr('walk', P['walk'], -120, 120, -9, 3.6, -0.6, 0.0, bev=False)
    b.boxr('curb', P['curb'], -120, 120, 3.6, 4.2, -0.6, 0.12, bev=ARCH)
    b.boxr('road', P['road'], -120, 120, 4.2, 18.0, -0.8, -0.2, bev=False)
    b.boxr('curb', P['curb'], -120, 120, 18.0, 18.6, -0.6, 0.12, bev=ARCH)
    b.boxr('walk', P['walk'], -120, 120, 18.6, 24.0, -0.6, 0.0, bev=False)
    for x in range(-117, 120, 9):
        b.box('lines', P['yellow'], (4.5, 0.35, 0.04), (x, 11.1, -0.18), bev=False)
    for y in (5.0, 17.2):
        b.box('lines', P['lineW'], (240, 0.3, 0.04), (0, y, -0.18), bev=False)
    for mx in (-22, 16):
        b.cyl('road', P['dark'], 1.0, 0.06, (mx, 8.0, -0.18), seg=24, bev=False)

    rnd = random.Random(11)
    x = -100
    k = 0
    hs = [22, 17, 28, 19, 25, 16, 23, 18, 30, 20, 24]
    far = {}
    while x < 95:
        w = [14, 12, 16, 13][k % 4]
        far[k] = (x, x + w, hs[k % len(hs)])
        fac = [P['brick'], P['stucco'], P['wbrick'], P['stucco']][k % 4]
        _building(b, x, x + w, 24.4, 14, hs[k % len(hs)], fac, -1, True, k, shutter=(k % 5 == 3))
        if k % 2 == 0:
            _ac(b, x + w * 0.7, 24.4, 8.2)
        b.cyl('wall', P['dark'], 0.18, hs[k % len(hs)], (x + w - 0.4, 24.1, hs[k % len(hs)] / 2), seg=8)
        x += w + 0.6
        k += 1

    for lx in (-19.0, -5.0, 9.0, 23.0):
        _walllamp(b, coll, S, O, lx, 24.4, 6.4)

    nx = 12.0
    for (sx, sz, w_, h_) in ((0, 0, 4.0, 0.16), (0, 1.6, 4.0, 0.16), (-2.0, 0.8, 0.16, 1.76), (2.0, 0.8, 0.16, 1.76),
                              (-0.8, 0.8, 1.2, 0.16), (0.9, 0.8, 0.16, 1.0)):
        b.box('neon', P['neon'], (w_, 0.16, h_), (nx + sx, 24.0, 6.6 + sz), bev=False)
    _light(coll, S, 'neon', 'POINT', O, (nx, 22.8, 7.4), None, 'neon', 450, color=(1.0, 0.35, 0.78), size=1.0, cutoff=25)

    sk = flat('tower', '#8c96a0', rough=0.75, ramp=['#8a949c', '#9c9a94', '#7c8894', '#aaa498'], var=0.05)
    for i, (tx, h) in enumerate([(-70, 60), (-48, 78), (-25, 55), (-2, 72), (22, 84), (46, 58), (70, 66)]):
        ty = 70 + (i % 2) * 14
        b.boxr('sky', sk, tx, tx + 15, ty, ty + 14, 0, h, bev=False, rnd=rnd.random())
        zz = 4.0
        while zz < h - 3:
            for j in range(4):
                b.box('skywin', P['win'], (2.2, 0.2, 2.2), (tx + 2.2 + j * 3.5, ty - 0.08, zz), bev=False)
            zz += 4.0

    x = -100
    k = 3
    rev = None
    while x < 95:
        w = [15, 12, 14][k % 3]
        if x <= 0 < x + w:
            rev = (x, x + w)
        fac = [P['stucco'], P['brick'], P['wbrick']][k % 3]
        _building(b, x, x + w, -44.0, 12, hs[(k + 4) % len(hs)], fac, 1, True, k)
        x += w + 0.6
        k += 1
    b.boxr('walk', P['walk'], -120, 120, -44, -36, -0.6, 0.0, bev=False)
    b.boxr('curb', P['curb'], -120, 120, -36.6, -36, -0.6, 0.12, bev=ARCH)

    for (tx, ty, s) in [(13, -2.5, 1.0), (-13.5, -2.8, 0.95), (-31, -3, 1.1), (33, -3, 1.0), (-52, -3, 1.0),
                        (-12, -26, 1.2), (12, -30, 1.3), (-34, -28, 1.2), (36, -22, 1.1)]:
        _tree(b, tx, ty, 0.0 if ty > -9 else -0.3, s)

    banners = {9.5: ('P2', 1), -12.0: ('P2', -1), 30.0: ('P1', 1)}
    for lx in (9.5, -12.0, 30.0, -36.0, 52.0):
        bn, side = banners.get(lx, (None, 1))
        props.lamp_post(coll, f'{S}.lamp{int(lx)}', W(lx, 3.1, 0.0), banner=bn, side=side)
        _light(coll, S, f'lamp{int(lx)}', 'SPOT', O, (lx, 2.3, 12.4), (lx, 0.5, 0), 'lamp', 3800,
               color=(1.0, 0.78, 0.52), spot=110, blend=0.6, size=0.4, cutoff=45)

    mx, my = 8.8, -3.2
    b.box('mailbox', P['dark'], (0.35, 0.35, 2.6), (mx, my, 1.3))
    b.box('mailbox', P['blue'], (1.3, 1.9, 1.1), (mx, my, 3.1))
    b.cyl('mailbox', P['blue'], 0.65, 1.9, (mx, my, 3.65), axis='Y', seg=20)
    b.box('mailbox', P['red'], (0.12, 0.12, 1.0), (mx + 0.72, my + 0.4, 3.9))
    b.box('mailbox', P['red'], (0.12, 0.5, 0.35), (mx + 0.72, my + 0.65, 4.25))

    sx, sy = -6.0, 2.2
    b.box('sign', P['wood'], (0.35, 0.35, 6.4), (sx, sy + 0.3, 3.2))
    b.box('sign', P['plank'], (3.9, 0.3, 2.8), (sx, sy, 4.9))
    b.box('signface', P['white'], (3.4, 0.1, 2.3), (sx, sy - 0.17, 4.9), bev=False)

    props.hydrant(coll, f'{S}.hydrant', W(-9.5, 2.4, 0), rotz=20)
    props.trash_can(coll, f'{S}.trashcan', W(11.6, 2.2, 0), rotz=15)
    props.wheelie_bin(coll, f'{S}.trashbin', W(-22.5, 22.9, 0))
    props.wheelie_bin(coll, f'{S}.trashbin', W(6.0, 23.0, 0))
    props.bench(coll, f'{S}.bench', W(-20.0, 2.4, 0))
    props.bench(coll, f'{S}.bench', W(12.5, -7.9, 0), rotz=180)
    props.car(coll, f'{S}.car', W(-17.0, 8.2, -0.2), length=13.5)
    for i, (bx, by, bz, rz) in enumerate(((-27.0, 22.6, 0, 10), (-25.8, 23.0, 0, -15), (-26.5, 22.8, 1.25, 35))):
        props.cardboard_box(coll, f'{S}.box{i}', W(bx, by, bz), rotz=rz, h=1.25, stamp=(i == 1))
    props.crate(coll, f'{S}.crate0', W(28.0, 22.4, 0), rotz=8, h=2.4)
    props.crate(coll, f'{S}.crate1', W(29.6, 22.8, 0), rotz=-12, h=2.4)
    props.pallet(coll, f'{S}.pallet', W(31.5, 23.0, 0), rotz=90)
    for px in (-30, -20, 22, 38):
        b.boxr('planter', P['curb'], px - 3, px + 3, -8.6, -6.6, 0, 1.0, bev=PROP)
        b.boxr('planter', P['grass'], px - 2.7, px + 2.7, -8.3, -6.9, 0.8, 1.05, bev=False)
        props.shrub(coll, f'{S}.shrub{px}', W(px, -7.6, 0.9), length=5.2)

    x0, x1, _ = far[6]
    props.shop_sign(coll, f'{S}.shopsign', W(x0 + (x1 - x0) * 0.68, 24.04, 4.5), width=7.0, height=1.35)
    x0, x1, h7 = far[7]
    props.billboard(coll, f'{S}.billboard', W((x0 + x1) / 2, 26.0, h7 + 0.7), width=12.0)
    for i, f in enumerate((0.3, 0.7)):
        props.brand_plate(coll, f'{S}.brand.awning{i}', W(x0 + (x1 - x0) * (0.09 + 0.82 * f), 22.27, 3.95),
                          (0, 0, 0), 1.8, plate=False)
    x0, x1, _ = far[8]
    cx = (x0 + x1) / 2
    props.atlas_decal(coll, f'{S}.poster.shutterA', 'P1', W(cx - 2.3, 24.16, 2.35), (0, 0, 0), 2.0)
    props.atlas_decal(coll, f'{S}.poster.shutterB', 'P3', W(cx + 0.2, 24.16, 2.35), (0, 0, 0.0), 2.0)
    x0, x1, _ = far[6]
    props.atlas_decal(coll, f'{S}.poster.wall', 'AD', W(x0 + 2.1, 24.32, 2.7), (0, 0, 0), 3.4)
    if rev:
        props.brand_plate(coll, f'{S}.brand.revsign', W(rev[0] + (rev[1] - rev[0]) * 0.68, -43.62, 5.1),
                          (0, 0, math.pi), 2.1, plate=False, emissive=True)
    props.brand_plate(coll, f'{S}.brand.manhole', W(16.0, 8.0, -0.142), (-math.pi / 2, 0, 0), 1.35, plate=False,
                      alpha_mul=0.75)

    _light(coll, S, 'fill', 'AREA', O, (11, -18, 7), (0, 0, 3.5), 'ext_fill', 1600, colch='fill_col', size=10,
           cutoff=60, volume=0.0)
    _light(coll, S, 'rim', 'AREA', O, (6, 11, 11), (0, 0, 4.2), 'ext_rim', 2800, colch='rim_col', size=4, cutoff=45,
           volume=0.2)
    _light(coll, S, 'key', 'AREA', O, (-9, -10, 9), (0, 0, 4), 'ext_key', 2000, colch='key_col', size=5, cutoff=45,
           volume=0.2)
    _fog(coll, S, O, (-120, -60, -1), (120, 110, 70), 1.0)
    return {'sign': (sx, sy - 0.25, 4.9), 'mailbox': (mx, my, 3.3), 'lamp': (9.5, 3.1, 12.4)}


# ------------------------------------------------------------------ interiors
H_ROOM = 14.0


def _shell(b, wallmat, floormat, base_mat, ceil_mat, lower=None, h=H_ROOM):
    b.boxr('floor', floormat, -15, 15, -32, 9, -0.6, 0.0, bev=False)
    b.boxr('ground', P['grass'], -120, 120, -120, 120, -1.3, -0.65, bev=False)
    b.boxr('walls', wallmat, -15, 15, 8.0, 9.0, 0, h, bev=ARCH)
    b.boxr('walls', wallmat, 14.0, 15.0, -32, 9.0, 0, h, bev=ARCH)
    b.boxr('walls', wallmat, -15.0, -14.0, -32, 9.0, 0, h, bev=ARCH)
    b.boxr('ceiling', ceil_mat, -15.5, 15.5, -32.5, 9.5, h, h + 0.6, bev=False)
    b.boxr('ceiling', P['trim'], -15, 15, -32.6, -31.4, h - 1.6, h, bev=ARCH)
    if lower:
        b.boxr('lower', lower, -14, 14, 7.9, 8.0, 0, 3.6, bev=False)
        b.boxr('lower', lower, 13.9, 14, -32, 8, 0, 3.6, bev=False)
        b.boxr('lower', lower, -14, -13.9, -32, 8, 0, 3.6, bev=False)
        b.boxr('trim', P['trim'], -14, 14, 7.75, 7.95, 3.6, 3.85, bev=ARCH)
        b.boxr('trim', P['trim'], 13.75, 13.95, -32, 8, 3.6, 3.85, bev=ARCH)
        b.boxr('trim', P['trim'], -13.95, -13.75, -32, 8, 3.6, 3.85, bev=ARCH)
    b.boxr('trim', base_mat, -14, 14, 7.8, 8.0, 0, 0.6, bev=ARCH)
    b.boxr('trim', base_mat, 13.8, 14, -32, 8, 0, 0.6, bev=ARCH)
    b.boxr('trim', base_mat, -14, -13.8, -32, 8, 0, 0.6, bev=ARCH)
    b.boxr('trim', P['trim'], -14, 14, 7.6, 8.0, h - 0.5, h, bev=ARCH)
    b.boxr('trim', P['trim'], 13.6, 14, -32, 8, h - 0.5, h, bev=ARCH)
    b.boxr('trim', P['trim'], -14, -13.6, -32, 8, h - 0.5, h, bev=ARCH)


def _window(b, cx, cz, w, h, y, glass, axis='Y'):
    t = 0.35
    if axis == 'Y':
        b.box('winframe', P['trim'], (w + 0.6, t, 0.4), (cx, y, cz - h / 2 - 0.2), bev=ARCH)
        b.box('winframe', P['trim'], (w + 0.6, t, 0.4), (cx, y, cz + h / 2 + 0.2), bev=ARCH)
        b.box('winframe', P['trim'], (0.4, t, h), (cx - w / 2 - 0.1, y, cz), bev=ARCH)
        b.box('winframe', P['trim'], (0.4, t, h), (cx + w / 2 + 0.1, y, cz), bev=ARCH)
        b.box('winframe', P['trim'], (0.2, t, h), (cx, y, cz), bev=ARCH)
        b.box('winframe', P['trim'], (w, t, 0.2), (cx, y, cz), bev=ARCH)
        b.box('glass', glass, (w, 0.1, h), (cx, y + 0.12, cz), bev=False)
    else:
        b.box('winframe', P['trim'], (t, w + 0.6, 0.4), (y, cx, cz - h / 2 - 0.2), bev=ARCH)
        b.box('winframe', P['trim'], (t, w + 0.6, 0.4), (y, cx, cz + h / 2 + 0.2), bev=ARCH)
        b.box('winframe', P['trim'], (t, 0.4, h), (y, cx - w / 2 - 0.1, cz), bev=ARCH)
        b.box('winframe', P['trim'], (t, 0.4, h), (y, cx + w / 2 + 0.1, cz), bev=ARCH)
        b.box('winframe', P['trim'], (t, 0.2, h), (y, cx, cz), bev=ARCH)
        b.box('winframe', P['trim'], (t, w, 0.2), (y, cx, cz), bev=ARCH)
        s = 0.12 if y < 0 else -0.12
        b.box('glass', glass, (0.1, w, h), (y - s, cx, cz), bev=False)


def _exterior_card():
    m, new = _new_mat('wincard')
    if new:
        nt = m.node_tree
        b = _bsdf(m)
        b.inputs['Base Color'].default_value = (0, 0, 0, 1)
        b.inputs['Emission Color'].default_value = _col('#dff0ff')
        v = _drv_value(nt, 'drv_emit', 'max(0.12, 3.2*(1-win)*(1-max(0, cloud-0.5)*1.5))', ['win', 'cloud'])
        nt.links.new(v.outputs[0], b.inputs['Emission Strength'])
    return m


def _door(b, x_wall, y, side=-1):
    xi = x_wall + (0.12 if side < 0 else -0.12)
    b.box('door', P['wood'], (0.15, 3.4, 7.6), (xi, y, 3.8))
    b.box('door', P['trim'], (0.3, 4.2, 0.4), (xi, y, 7.8), bev=ARCH)
    b.box('door', P['trim'], (0.3, 0.4, 7.8), (xi, y - 1.9, 3.9), bev=ARCH)
    b.box('door', P['trim'], (0.3, 0.4, 7.8), (xi, y + 1.9, 3.9), bev=ARCH)
    b.cyl('door', P['metal'], 0.14, 0.3, (xi + (0.2 if side < 0 else -0.2), y + 1.2, 3.6), axis='X', seg=10)


def _room_lights(coll, S, O, wins, ceil_lights, storm_key=((12.5, -9.0, 5.5), (0, 0, 3.6))):
    _light(coll, S, 'stormkey', 'AREA', O, storm_key[0], storm_key[1], 'int_storm', 900, colch='storm_col', size=5,
           size_y=4, cutoff=40, volume=0.3)
    _light(coll, S, 'key', 'AREA', O, (-10, -12, 10.5), (1, 0, 4.2), 'int_key', 1350, colch='key_col', size=5,
           cutoff=45, volume=0.15)
    _light(coll, S, 'fill', 'AREA', O, (9, -19, 6.5), (0, 0, 3.5), 'int_fill', 680, colch='fill_col', size=9,
           cutoff=50, volume=0.0)
    _light(coll, S, 'rim', 'AREA', O, (5, 6.5, 12.5), (-0.5, -0.5, 4.5), 'int_rim', 850, colch='rim_col', size=3.5,
           cutoff=38, volume=0.15)
    for i, (loc, aim, sz, szy) in enumerate(wins):
        _light(coll, S, f'win{i}', 'AREA', O, loc, aim, 'win_light', 820, colch='winl_col', size=sz, size_y=szy,
               cutoff=42, volume=0.2)
    for i, (loc, kind, base) in enumerate(ceil_lights):
        if kind == 'AREA':
            _light(coll, S, f'prac{i}', 'AREA', O, loc, (loc[0], loc[1], 0), 'prac_int', base * 1.25, colch='prac_col',
                   size=3.4, size_y=1.8, cutoff=38, volume=0.3)
        else:
            _light(coll, S, f'prac{i}', 'SPOT', O, loc, (loc[0], loc[1], 0), 'prac_int', base * 1.25, colch='prac_col',
                   spot=120, blend=0.8, size=0.45, cutoff=34, volume=0.45)


def _kitchen(b, coll, O):
    S = 'Kitchen'
    W = _W(O)
    floor = pbr('kitchenfloor', 'floor_tiles_06', 5.0, tint='#f4eee2', sat=0.4, val=1.32, grime=0.08, floor=True,
                nstr=0.55)
    wall = pbr('kitchenwall', 'painted_plaster_wall', 6.0, paint='#b8ceb4', paint_keep=0.2, grime=0.1)
    splash = pbr('backsplash', 'long_white_tiles', 2.5, tint='#f4f2ec', sat=0.35, val=1.18, grime=0.03, nstr=0.75)
    cab = pbr('cabinet', 'plywood', 3.0, paint='#ebe4d4', paint_keep=0.12, grime=0.06)
    counter = flat('counter', '#454950', rough=0.35, var=0.1)
    _shell(b, wall, floor, P['trim'], P['plaster'])

    fx = -9.71
    props.fridge(coll, f'{S}.fridge', W(fx, 5.58, 0))
    sx = -3.3
    props.stove(coll, f'{S}.stove', W(sx, 5.95, 0))
    kx = 9.9
    props.sink_unit(coll, f'{S}.sink', W(kx, 6.18, 0))
    props.cereal_box(coll, f'{S}.cereal', W(kx + 3.1, 6.75, 3.35), rotz=-12)
    x0, x1 = -1.2, 5.8
    b.boxr('cab', cab, x0, x1, 5.8, 7.9, 0.3, 3.0)
    b.boxr('cab', P['trimdark'], x0 + 0.1, x1 - 0.1, 6.0, 7.8, 0, 0.3, bev=False)
    b.boxr('cab', counter, x0 - 0.1, x1 + 0.05, 5.6, 7.95, 3.0, 3.35)
    for i in range(3):
        hx = x0 + (i + 0.5) * (x1 - x0) / 3
        b.box('handles', P['metal'], (0.9, 0.15, 0.15), (hx, 5.72, 2.4), bev=False)
        b.box('cab', P['trimdark'], (0.05, 0.05, 2.6), (x0 + (i + 1) * (x1 - x0) / 3, 5.78, 1.65), bev=False)

    for (nx, nz, c) in ((-2.6, 6.2, 'white'), (-1.7, 6.5, 'white'), (2.2, 5.6, 'white'), (-2.2, 5.2, 'red'),
                        (1.6, 6.6, 'blue')):
        b.box('notes', P[c], (0.7 if c == 'white' else 0.25, 0.04, 0.9 if c == 'white' else 0.25),
              (fx + nx, 3.2, nz), bev=False)
    props.cardboard_box(coll, f'{S}.box0', W(fx - 2.0, 6.4, 8.0), rotz=12, h=1.2, stamp=True)
    props.cardboard_box(coll, f'{S}.box1', W(fx - 0.6, 6.6, 8.0), rotz=-8, h=1.0)

    b.boxr('stove', P['metal'], sx - 2.2, sx + 2.2, 5.9, 7.95, 8.2, 8.8)
    b.cyl('stove', P['metal'], 0.6, 5.2, (sx, 7.2, 11.4), seg=4, r2=0.6)
    b.cyl('pots', P['metal'], 0.62, 0.9, (sx - 1.0, 5.9, 3.4 + 0.45), seg=20)
    b.cyl('pots', P['dark'], 0.66, 0.08, (sx - 1.0, 5.9, 4.34), seg=20)
    props.brass_pan(coll, f'{S}.brass_pan', W(sx + 1.0, 6.4, 3.4), rotz=-20)

    b.boxr('splash', splash, -1.2, 2.4, 7.85, 7.98, 3.35, 6.6, bev=False)
    b.boxr('splash', splash, 2.4, 8.6, 7.85, 7.98, 3.35, 4.2, bev=False)
    b.boxr('splash', splash, 8.6, 13.9, 7.85, 7.98, 3.35, 6.6, bev=False)
    b.boxr('cab', cab, -1.2, 2.3, 6.4, 7.9, 6.6, 9.6)
    b.box('handles', P['metal'], (0.12, 0.15, 0.7), (1.9, 6.32, 7.2), bev=False)

    b.box('micro', P['metal'], (2.2, 1.6, 1.3), (0.1, 6.9, 4.0))
    b.box('micro', P['black'], (1.4, 0.05, 0.95), (-0.15, 6.08, 4.0), bev=False)
    b.box('toaster', P['metal'], (1.3, 0.8, 0.9), (2.4, 6.9, 3.8))
    b.box('toaster', P['black'], (0.9, 0.3, 0.05), (2.4, 6.9, 4.26), bev=False)
    b.cyl('jars', P['white'], 0.35, 0.8, (5.2, 7.0, 3.75), seg=14)
    for dx in (-0.1, 0.05, 0.15):
        b.cyl('jars', P['wood'], 0.05, 1.3, (5.2 + dx, 7.0 + dx, 4.4), seg=6)
    b.box('board', P['wood'], (1.6, 0.12, 1.1), (3.7, 7.75, 3.9), bev=PROP)
    props.cola_bottle(coll, f'{S}.cola0', W(4.1, 6.3, 3.35), rotz=-25, h=0.9)
    props.mug(coll, f'{S}.mug', W(1.5, 5.95, 3.35), rotz=-60)

    card = _exterior_card()
    wx, wz = 5.5, 7.0
    _window(b, wx, wz, 5.6, 5.0, 7.85, card)
    b.boxr('trim', P['trim'], wx - 3.4, wx + 3.4, 7.2, 7.95, 4.2, 4.45)

    _window(b, -8.0, 7.0, 6.0, 5.0, 13.85, card, axis='X')
    _door(b, -14.0, -20.0)
    props.shelves(coll, f'{S}.shelves', W(-13.2, -9.5, 0), rotz=90, h=7.0)
    props.framed_print(coll, f'{S}.print', W(-13.8, -4.5, 8.2), rotz=90, slot='P2', w=2.0)
    for (py, pc, pz) in ((-13.0, '#c89b60', 8.0),):
        b.box('pics', P['wood'], (0.2, 3.6, 3.0), (-13.9, py, pz))
        b.box('pics', flat('pic' + pc, pc, rough=0.75, var=0.2), (0.25, 3.0, 2.4), (-13.9, py, pz), bev=False)
    props.wall_clock(coll, f'{S}.clock', W(11.5, 7.83, 10.0), d=2.6)
    props.calendar(coll, f'{S}.calendar', W(-1.4, 7.95, 10.0), h=2.6)

    tx, ty = 4.5, 1.0
    b.boxr('table', P['wood'], tx - 1.5, tx + 1.5, ty - 1.0, ty + 1.0, 2.35, 2.6)
    for lx in (-1.25, 1.25):
        for ly in (-0.75, 0.75):
            b.box('table', P['wood'], (0.28, 0.28, 2.35), (tx + lx, ty + ly, 1.175))
    b.cyl('tableprops', P['white'], 0.55, 0.2, (tx, ty, 2.7), seg=20, r2=0.4)
    b.ball('tableprops', P['red'], 0.22, (tx - 0.15, ty, 2.95), sub=2)
    b.ball('tableprops', flat('orange', '#f39c12', rough=0.45), 0.22, (tx + 0.2, ty + 0.1, 2.95), sub=2)
    for cx in (3.6, 5.4):
        props.chair(coll, f'{S}.chair', W(cx, 3.6, 0), h=3.4)

    props.pendant_lamp(coll, f'{S}.pendant', W(tx, ty, H_ROOM - 4.6), h=4.6)
    b.cyl('ceilfix', P['bulb'], 1.3, 0.25, (-4.0, -6.0, H_ROOM - 0.12), seg=24, bev=False)

    b.boxr('rug', flat('rug', '#b86858', rough=0.9, var=0.15), 1.5, 7.5, -1.5, 3.5, 0.0, 0.04, bev=False)
    b.cyl('plant', flat('pot', '#c47b4a', rough=0.72), 0.8, 1.6, (-12.8, 1.4, 0.8), seg=14, r2=0.6)
    b.ball('plant', P['leaf'], 1.2, (-12.8, 1.4, 2.4), sub=2)
    b.cyl('bin', P['metal'], 0.6, 1.8, (13.0, 2.4, 0.9), seg=16)
    props.cola_bottle(coll, f'{S}.cola1', W(tx + 0.95, ty - 0.45, 2.6), rotz=30, h=0.9)
    props.plate_set(coll, f'{S}.plates', W(tx - 0.8, ty + 0.55, 2.6))
    props.plate_set(coll, f'{S}.plates', W(tx + 0.8, ty + 0.55, 2.6))
    props.cutlery(coll, f'{S}.cutlery', W(tx - 1.0, ty - 0.45, 2.6), rotz=90)

    _room_lights(coll, S, O,
                 wins=[((wx, 7.3, wz), (wx, 0, 2.5), 5.2, 4.6), ((13.3, -8.0, 7.0), (0, -8, 2.5), 5.6, 4.6)],
                 ceil_lights=[((tx, ty, H_ROOM - 4.9), 'SPOT', 640), ((-4.0, -6.0, H_ROOM - 0.4), 'AREA', 600)])
    _fog(coll, S, O, (-14, -32, 0), (14, 8, H_ROOM), 0.5, col='#e4e0da')
    return {'table': (tx, ty, 2.6), 'stove': (sx, 5.9, 3.4), 'fridge': (fx, 3.25, 4.0), 'window': (wx, 7.7, wz),
            'sink': (kx, 5.0, 3.4), 'cola': (tx + 0.95, ty - 0.45, 3.05)}


# ------------------------------------------------------------------ Universal Semantic Set Synthesizer
def _build_semantic_set(b, coll, O, name):
    """Synthesize a complete, well-lit, prop-rich 3D set for ANY location name."""
    W = _W(O)
    tokens = set(re.findall(r'[a-z]+', str(name).lower()))

    is_outdoor = bool(tokens & {
        'park', 'forest', 'woods', 'garden', 'yard', 'playground', 'beach', 'field',
        'alley', 'road', 'highway', 'bridge', 'plaza', 'square', 'farm', 'camp', 'pool',
    })
    is_rooftop = bool(tokens & {'rooftop', 'roof', 'balcony', 'terrace', 'cliff', 'tower'})
    is_gym = bool(tokens & {'gym', 'arena', 'stadium', 'court', 'dojo', 'ring', 'stage'})
    is_shop = bool(tokens & {'shop', 'store', 'market', 'supermarket', 'mall', 'cafe', 'restaurant', 'diner', 'bakery'})
    is_school_office = bool(tokens & {'school', 'classroom', 'office', 'library', 'lab', 'laboratory', 'hospital', 'clinic', 'bank'})

    # 1. Outdoor / Park / Beach / Yard
    if is_outdoor:
        is_beach = bool(tokens & {'beach', 'island', 'sand', 'coast'})
        ground_mat = flat('sand', '#f2d99c', rough=0.82, var=0.14) if is_beach else P['grass']
        b.boxr('ground', ground_mat, -120, 120, -120, 120, -1.2, 0.0, bev=False)
        if is_beach:
            b.boxr('water', flat('ocean', '#1e88e5', rough=0.12, spec=0.8), -120, 120, 18, 120, -0.8, 0.05, bev=False)
        else:
            b.boxr('walk', P['walk'], -120, 120, -6.5, 4.5, -0.4, 0.02, bev=False)
            for tx, ty, s in [(-12, 8, 1.15), (13, 9, 1.25), (-22, 16, 1.3), (24, 14, 1.1), (-16, -12, 1.1), (18, -14, 1.2)]:
                _tree(b, tx, ty, 0.0, s)
            props.bench(coll, f'{name}.bench0', W(-10.5, 6.2, 0))
            props.bench(coll, f'{name}.bench1', W(10.5, 6.2, 0))
            props.lamp_post(coll, f'{name}.lamp0', W(-14.0, 5.5, 0.0), banner='P1', side=1)
            props.lamp_post(coll, f'{name}.lamp1', W(14.0, 5.5, 0.0), banner='P2', side=-1)
            _light(coll, name, 'lamp0', 'SPOT', O, (-14.0, 4.7, 12.4), (-14.0, 1.0, 0), 'lamp', 3400,
                   color=(1.0, 0.78, 0.52), spot=110, blend=0.6, size=0.4, cutoff=45)
            _light(coll, name, 'lamp1', 'SPOT', O, (14.0, 4.7, 12.4), (14.0, 1.0, 0), 'lamp', 3400,
                   color=(1.0, 0.78, 0.52), spot=110, blend=0.6, size=0.4, cutoff=45)
        props.trash_can(coll, f'{name}.trashcan', W(9.2, 5.2, 0))
        props.brand_plate(coll, f'{name}.brand', W(0.0, 12.0, 3.2), (0, 0, 0), 3.0, plate=True)
        _light(coll, name, 'fill', 'AREA', O, (11, -18, 7), (0, 0, 3.5), 'ext_fill', 1650, colch='fill_col', size=10, cutoff=60, volume=0.0)
        _light(coll, name, 'rim', 'AREA', O, (6, 11, 11), (0, 0, 4.2), 'ext_rim', 2800, colch='rim_col', size=4, cutoff=45, volume=0.2)
        _light(coll, name, 'key', 'AREA', O, (-9, -10, 9), (0, 0, 4), 'ext_key', 2100, colch='key_col', size=5, cutoff=45, volume=0.2)
        _fog(coll, name, O, (-120, -60, -1), (120, 110, 70), 0.7)
        return {'center': (0.0, 0.0, 0.0), 'bench': (-10.5, 6.2, 1.6), 'table': (10.5, 6.2, 1.6)}

    # 2. Rooftop / Sky Balcony
    if is_rooftop:
        roof_mat = pbr('roofconc', 'concrete_wall_008', 6.0, tint='#c8ccd0', sat=0.3, val=1.15, floor=True)
        b.boxr('roof', roof_mat, -18, 18, -22, 12, -1.0, 0.0, bev=False)
        b.boxr('parapet', P['brick'], -18.5, 18.5, 11.2, 12.2, 0.0, 3.2, bev=ARCH)
        b.boxr('parapet', P['brick'], -18.5, -17.5, -22, 12.2, 0.0, 3.2, bev=ARCH)
        b.boxr('parapet', P['brick'], 17.5, 18.5, -22, 12.2, 0.0, 3.2, bev=ARCH)
        b.boxr('trim', P['trim'], -18.7, 18.7, 11.0, 12.4, 3.2, 3.55, bev=ARCH)
        _ac(b, -11.0, 10.5, 1.2, face=-1)
        _ac(b, 11.0, 10.5, 1.2, face=-1)
        sk = flat('tower_roof', '#8c96a0', rough=0.75, ramp=['#8a949c', '#9c9a94', '#7c8894', '#aaa498'], var=0.05)
        for i, (tx, h) in enumerate([(-65, 45), (-40, 62), (-15, 38), (12, 56), (38, 44), (62, 58)]):
            b.boxr('sky', sk, tx, tx + 16, 42 + (i % 2) * 14, 56 + (i % 2) * 14, -40, h, bev=False, rnd=(i * 0.23) % 1)
        props.bench(coll, f'{name}.bench', W(9.5, 8.2, 0), rotz=180)
        props.crate(coll, f'{name}.crate', W(-12.5, 6.5, 0), rotz=14, h=2.2)
        props.brand_plate(coll, f'{name}.brand', W(0.0, 11.1, 1.8), (0, 0, 0), 2.8, plate=True)
        _light(coll, name, 'fill', 'AREA', O, (11, -18, 7), (0, 0, 3.5), 'ext_fill', 1650, colch='fill_col', size=10, cutoff=60, volume=0.0)
        _light(coll, name, 'rim', 'AREA', O, (6, 11, 11), (0, 0, 4.2), 'ext_rim', 2800, colch='rim_col', size=4, cutoff=45, volume=0.2)
        _light(coll, name, 'key', 'AREA', O, (-9, -10, 9), (0, 0, 4), 'ext_key', 2100, colch='key_col', size=5, cutoff=45, volume=0.2)
        return {'center': (0.0, 0.0, 0.0), 'edge': (0.0, 10.5, 0.0), 'bench': (9.5, 8.2, 1.6)}

    # 3. Indoor Worlds (Home, Classroom, Office, Shop, Gym, Hospital, Library)
    if is_gym:
        floor = pbr('gymfloor', 'wood_table_001', 4.5, tint='#f4d5a6', sat=0.85, val=1.28, floor=True)
        wall = pbr('gymwall', 'painted_plaster_wall', 6.0, paint='#dce6f2', paint_keep=0.18, grime=0.05)
    elif is_shop:
        floor = pbr('shopfloor', 'floor_tiles_06', 4.5, tint='#f7f4ee', sat=0.3, val=1.35, floor=True)
        wall = pbr('shopwall', 'painted_plaster_wall', 6.0, paint='#f5e6cc', paint_keep=0.18, grime=0.05)
    elif is_school_office:
        floor = pbr('offfloor', 'square_concrete_pavers', 5.0, tint='#e4e8ec', sat=0.25, val=1.25, floor=True)
        wall = pbr('offwall', 'painted_plaster_wall', 6.0, paint='#e6eef5', paint_keep=0.18, grime=0.05)
    else:
        floor = pbr('homefloor', 'wood_table_001', 4.0, tint='#d9b38c', sat=0.85, val=1.2, floor=True)
        wall = pbr('homewall', 'painted_plaster_wall', 6.0, paint='#f2e8dc', paint_keep=0.18, grime=0.05)

    _shell(b, wall, floor, P['trim'], P['plaster'])
    card = _exterior_card()
    _window(b, 0.0, 7.2, 8.4, 5.2, 7.85, card)
    _window(b, -8.0, 7.2, 6.0, 5.2, 13.85, card, axis='X')
    _door(b, -14.0, -18.0)

    # Back-wall furniture (y >= 5.5, leaving acting zone |x|<7, -4<y<3 wide open)
    b.boxr('back_counter', P['wood'], -11.5, -4.5, 5.6, 7.8, 0.0, 3.0)
    b.boxr('back_counter', P['trim'], -11.6, -4.4, 5.5, 7.9, 3.0, 3.3)
    b.boxr('back_counter2', P['wood'], 4.5, 11.5, 5.6, 7.8, 0.0, 3.0)
    b.boxr('back_counter2', P['trim'], 4.4, 11.6, 5.5, 7.9, 3.0, 3.3)

    if is_shop:
        for sx_pos in (-9.5, -6.5, 6.5, 9.5):
            props.cereal_box(coll, f'{name}.item_{int(sx_pos*10)}', W(sx_pos, 6.5, 3.3), rotz=8)
            props.cola_bottle(coll, f'{name}.drink_{int(sx_pos*10)}', W(sx_pos + 1.1, 6.4, 3.3), h=0.9)
    elif is_gym:
        for gx in (-9.0, 9.0):
            b.cyl('weights', P['dark'], 0.9, 0.25, (gx, 6.4, 3.5), axis='X', seg=18)
            b.cyl('weights', P['metal'], 0.14, 3.2, (gx, 6.4, 3.5), axis='X', seg=12)
    else:
        props.mug(coll, f'{name}.mug', W(-7.5, 6.4, 3.3), rotz=-35)
        props.framed_print(coll, f'{name}.print', W(-13.8, -4.5, 8.2), rotz=90, slot='P2', w=2.2)
        props.wall_clock(coll, f'{name}.clock', W(10.5, 7.83, 10.2), d=2.6)

    props.shelves(coll, f'{name}.shelvesL', W(-13.2, -9.5, 0), rotz=90, h=7.2)
    props.shelves(coll, f'{name}.shelvesR', W(13.2, -9.5, 0), rotz=-90, h=7.2)
    props.chair(coll, f'{name}.chair0', W(-9.5, 3.8, 0), rotz=25, h=3.4)
    props.chair(coll, f'{name}.chair1', W(9.5, 3.8, 0), rotz=-25, h=3.4)

    # Decorative rug & potted plant
    b.boxr('rug', flat('rug_' + name, '#4f7cac' if is_school_office else '#c86d51', rough=0.9, var=0.14),
           -4.5, 4.5, -2.5, 2.5, 0.0, 0.04, bev=False)
    b.cyl('plant', flat('pot_' + name, '#c47b4a', rough=0.72), 0.8, 1.6, (-12.5, 3.5, 0.8), seg=14, r2=0.6)
    b.ball('plant', P['leaf'], 1.25, (-12.5, 3.5, 2.4), sub=2)
    props.brand_plate(coll, f'{name}.brand', W(0.0, 7.82, 11.2), (0, 0, 0), 2.8, plate=True)

    _room_lights(coll, name, O,
                 wins=[((0.0, 7.3, 7.2), (0.0, 0, 2.5), 7.8, 4.8), ((13.3, -8.0, 7.2), (0, -8, 2.5), 5.6, 4.8)],
                 ceil_lights=[((0.0, 0.0, H_ROOM - 0.5), 'AREA', 750), ((-5.0, -8.0, H_ROOM - 0.5), 'AREA', 650)])
    _fog(coll, name, O, (-14, -32, 0), (14, 8, H_ROOM), 0.45, col='#e4e0da')
    return {
        'center': (0.0, 0.0, 0.0),
        'table': (-8.0, 6.6, 3.3),
        'counter': (8.0, 6.6, 3.3),
        'window': (0.0, 7.7, 7.2),
        'door': (-13.5, -18.0, 0.0),
    }


ANCHORS = {}
_BUILDERS = {'Street': _street, 'Kitchen': _kitchen}


def set_names():
    import places, places_built
    return list(_BUILDERS) + list(places_built.BUILT) + list(places.PRESETS)


def _resolve_canonical_set(name):
    import places, places_built
    low = str(name or 'Street').strip().lower()
    for pool in (_BUILDERS, places_built.BUILT, places.PRESETS):
        for k in pool:
            if k.lower() == low:
                return k
    if 'kitchen' in low:
        return 'Kitchen'
    if 'street' in low:
        return 'Street'
    return None


def build_set(name, origin=(0, 0, 0), spec=None):
    import places, places_built
    base = spec.get('base') if spec else None
    resolved_base = _resolve_canonical_set(base) if base else None
    resolved_name = _resolve_canonical_set(name) if not base else None

    _world()
    _mats()
    coll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(coll)
    b = _B(name, coll, origin)
    src = resolved_base or resolved_name or name

    if spec is not None and not base:
        A = places.build(b, coll, origin, name, spec)
    elif src in _BUILDERS:
        A = _BUILDERS[src](b, coll, origin)
    elif src in places_built.BUILT:
        A = places_built.BUILT[src](b, coll, origin)
    elif src in places.PRESETS:
        A = places.build(b, coll, origin, name, places.PRESETS[src])
    else:
        # Universal Defensive Fallback: synthesize a rich, studio-lit 3D environment for ANY location!
        A = _build_semantic_set(b, coll, origin, name)

    if base:
        A = dict(A)
        places._props(coll, name, origin, spec, A)
    b.finish()
    for k, v in A.items():
        _anchor(coll, name, k, origin, v)
    ANCHORS[name] = A
    if 'Sun' not in bpy.data.objects:
        set_mood('sunny')
    else:
        set_mood(*_LAST)
    return coll


# ------------------------------------------------------------------ moods (Bright Warm @craftee_films Studio Default)
MOODS = {
    'sunny': dict(
        sky_hor=(0.64, 0.78, 0.94), sky_zen=(0.24, 0.48, 0.85), cloud_col=(0.98, 0.98, 1.0), cloud=0.35, cam_str=1.25,
        lit_hor=(0.48, 0.46, 0.44), lit_zen=(0.72, 0.80, 0.94), lit_str=1.25,
        sun=5.4, sun_col=(1.0, 0.95, 0.86), elev=52.0, az=-52.0,
        ext_key=0.35, ext_fill=1.25, ext_rim=1.15, int_key=1.15, int_fill=0.95, int_rim=0.90, win_light=0.95, int_storm=0.0,
        storm_col=(0.62, 0.74, 1.0),
        key_col=(1.0, 0.94, 0.85), fill_col=(0.92, 0.96, 1.0), rim_col=(1.0, 0.94, 0.84), winl_col=(0.95, 0.98, 1.0),
        prac_col=(1.0, 0.92, 0.80), prac_int=0.75,
        fog=0.0, wet=0.0, win=0.0, lamp=0.0, neon=0.0, prac=0.45, expo=0.32),
    'storm': dict(
        sky_hor=(0.34, 0.37, 0.42), sky_zen=(0.16, 0.19, 0.24), cloud_col=(0.25, 0.27, 0.30), cloud=1.0, cam_str=1.05,
        lit_hor=(0.18, 0.19, 0.21), lit_zen=(0.36, 0.40, 0.46), lit_str=0.95,
        sun=1.2, sun_col=(0.84, 0.90, 1.0), elev=26.0, az=-60.0,
        ext_key=0.65, ext_fill=0.55, ext_rim=1.15, int_key=0.35, int_fill=0.32, int_rim=0.55, win_light=0.15, int_storm=0.95,
        storm_col=(0.66, 0.78, 1.0),
        key_col=(0.86, 0.92, 1.0), fill_col=(0.78, 0.85, 1.0), rim_col=(0.78, 0.88, 1.0), winl_col=(0.75, 0.84, 1.0),
        prac_col=(0.90, 0.94, 1.0), prac_int=0.55,
        fog=0.008, wet=1.0, win=0.55, lamp=0.45, neon=0.5, prac=0.45, expo=-0.25),
    'night': dict(
        sky_hor=(0.04, 0.06, 0.10), sky_zen=(0.01, 0.015, 0.03), cloud_col=(0.05, 0.06, 0.09), cloud=0.45, cam_str=1.1,
        lit_hor=(0.03, 0.035, 0.045), lit_zen=(0.06, 0.08, 0.14), lit_str=0.8,
        sun=0.18, sun_col=(0.68, 0.80, 1.0), elev=38.0, az=-58.0,
        ext_key=0.55, ext_fill=0.25, ext_rim=1.05, int_key=0.55, int_fill=0.35, int_rim=0.95, win_light=0.15, int_storm=0.0,
        storm_col=(0.62, 0.74, 1.0),
        key_col=(1.0, 0.78, 0.54), fill_col=(0.6, 0.72, 1.0), rim_col=(0.55, 0.82, 1.0), winl_col=(0.5, 0.65, 1.0),
        prac_col=(1.0, 0.82, 0.60), prac_int=1.15,
        fog=0.012, wet=0.7, win=1.0, lamp=1.0, neon=1.0, prac=1.1, expo=0.05),
}
_LAST = ('sunny', 1.0)


def _lerp(a, b, x):
    if isinstance(a, tuple):
        return tuple(p + (q - p) * x for p, q in zip(a, b))
    return a + (b - a) * x


def set_mood(mood, x=1.0):
    global _LAST
    mood_key = str(mood or 'sunny').lower().strip()
    if mood_key not in MOODS:
        if any(k in mood_key for k in ('night', 'dark', 'evening', 'midnight')):
            mood_key = 'night'
        elif any(k in mood_key for k in ('storm', 'rain', 'gloomy', 'overcast', 'cloud')):
            mood_key = 'storm'
        else:
            mood_key = 'sunny'
    _LAST = (mood_key, x)
    A, M = MOODS['sunny'], MOODS[mood_key]
    V = {k: _lerp(A[k], M[k], x) for k in A}
    nt = _world()
    n = nt.nodes
    _sock(n['sky_col'].inputs, 'A_Color').default_value = (*V['sky_hor'], 1)
    _sock(n['sky_col'].inputs, 'B_Color').default_value = (*V['sky_zen'], 1)
    _sock(n['cloud_col'].inputs, 'B_Color').default_value = (*V['cloud_col'], 1)
    _sock(n['lit_col'].inputs, 'A_Color').default_value = (*V['lit_hor'], 1)
    _sock(n['lit_col'].inputs, 'B_Color').default_value = (*V['lit_zen'], 1)
    n['bg_cam'].inputs['Strength'].default_value = V['cam_str']
    n['bg_lit'].inputs['Strength'].default_value = V['lit_str']
    for k in CTL:
        n['ctl_' + k].inputs[0].default_value = V[k]
    sun = bpy.data.objects.get('Sun')
    if sun is None:
        ld = bpy.data.lights.new('Sun', 'SUN')
        sun = bpy.data.objects.new('Sun', ld)
        bpy.context.scene.collection.objects.link(sun)
    ld = sun.data
    ld.energy = V['sun']
    ld.color = V['sun_col']
    ld.angle = math.radians(2.5)
    if hasattr(ld, 'use_shadow_jitter'):
        ld.use_shadow_jitter = False
    sun.rotation_euler = (math.radians(90 - V['elev']), 0, math.radians(V['az']))
    for ob in bpy.data.objects:
        if ob.type == 'LIGHT' and 'ch' in ob:
            ob.data.energy = ob['base'] * V[ob['ch']]
            if 'colch' in ob:
                ob.data.color = V[ob['colch']]


# ------------------------------------------------------------------ render
def _compositor(scene):
    ng = bpy.data.node_groups.get('rbx_comp')
    if ng is None:
        ng = bpy.data.node_groups.new('rbx_comp', 'CompositorNodeTree')
        ng.interface.new_socket('Image', in_out='OUTPUT', socket_type='NodeSocketColor')
        rl = ng.nodes.new('CompositorNodeRLayers')
        gl = ng.nodes.new('CompositorNodeGlare')
        gl.name = 'bloom'
        gl.inputs['Type'].default_value = 'Bloom'
        gl.inputs['Quality'].default_value = 'Medium'
        gl.inputs['Threshold'].default_value = 6.5
        gl.inputs['Smoothness'].default_value = 0.35
        gl.inputs['Strength'].default_value = 0.38
        gl.inputs['Size'].default_value = 0.55
        out = ng.nodes.new('NodeGroupOutput')
        ng.links.new(rl.outputs['Image'], gl.inputs['Image'])
        ng.links.new(gl.outputs['Image'], out.inputs[0])
    scene.compositing_node_group = ng
    try:
        scene.render.use_compositing = True
    except Exception:
        pass


def dof(cam_obj, focus, fstop=2.2):
    d = cam_obj.data.dof
    d.use_dof = True
    if isinstance(focus, (int, float)):
        d.focus_distance = focus
    else:
        d.focus_object = focus
    d.aperture_fstop = fstop
    d.aperture_blades = 7


def setup_render(scene):
    items = [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items]
    scene.render.engine = 'BLENDER_EEVEE' if 'BLENDER_EEVEE' in items else 'BLENDER_EEVEE_NEXT'
    r = scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = 1080, 1920, 100
    r.fps = 30
    r.film_transparent = False
    r.filter_size = 1.7
    r.use_motion_blur = True
    r.motion_blur_shutter = 0.5
    try:
        r.motion_blur_position = 'START'
        r.compositor_device = 'GPU'
    except Exception:
        pass
    ee = scene.eevee
    for k, v in (('taa_render_samples', 20), ('use_shadows', True), ('shadow_ray_count', 1), ('shadow_step_count', 6),
                 ('shadow_resolution_scale', 0.5), ('use_raytracing', True), ('ray_tracing_method', 'SCREEN'),
                 ('use_fast_gi', True), ('fast_gi_method', 'GLOBAL_ILLUMINATION'), ('fast_gi_resolution', '2'),
                 ('fast_gi_step_count', 6), ('fast_gi_ray_count', 2), ('fast_gi_distance', 6.0),
                 ('fast_gi_quality', 0.25), ('volumetric_tile_size', '8'), ('volumetric_samples', 32),
                 ('volumetric_start', 0.5), ('volumetric_end', 220.0), ('volumetric_sample_distribution', 0.8),
                 ('use_volumetric_shadows', True), ('volumetric_shadow_samples', 8), ('volumetric_ray_depth', 4),
                 ('volumetric_light_clamp', 0.0), ('motion_blur_steps', 1), ('bokeh_max_size', 60.0),
                 ('use_bokeh_jittered', False), ('clamp_surface_indirect', 10.0)):
        try:
            setattr(ee, k, v)
        except Exception as e:
            print('[sets] eevee', k, e)
    try:
        rt = ee.ray_tracing_options
        rt.resolution_scale = '2'
        rt.use_denoise = True
        rt.trace_max_roughness = 0.5
        rt.screen_trace_quality = 0.25
    except Exception as e:
        print('[sets] raytracing options', e)
    vs = scene.view_settings
    vs.view_transform = 'AgX'
    try:
        vs.look = 'AgX - Medium High Contrast'
    except Exception:
        vs.look = 'None'
    vs.gamma = 1.0
    scene.display_settings.display_device = 'sRGB'
    _world()
    _drive(scene, 'view_settings.exposure', 'expo', ['expo'])
    _compositor(scene)
    if scene.camera is not None:
        scene.camera.data.dof.use_dof = True
