"""Universal 3D Prop Spawner, Hand-Parenting, Side Pedestal & Hinged Articulation Engine.

Resolves any noun from `master_assets/catalog.json` (loading `.glb` meshes when present
or building rich multi-part Roblox procedural meshes as an instant fallback), attaches
handheld items directly to character `hand.R`/`hand.L` bones, spawns unobstructed side
pedestal tables beside actors, animates hinged closet/door openings (`openAt`/`closeAt`),
and adds 4-point star sparkles (`sparkleAt`) on twist/reveal beats.
"""
import json
import math
from pathlib import Path

import bpy
import bmesh
from mathutils import Euler, Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = ROOT / 'master_assets'
CATALOG_PATH = ASSET_DIR / 'catalog.json'
FPS = 30.0

_CATALOG_CACHE = None


def load_catalog():
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE
    if not CATALOG_PATH.exists():
        try:
            import sys
            auto_dir = str(ROOT / 'auto')
            if auto_dir not in sys.path:
                sys.path.insert(0, auto_dir)
            import fetch_master_assets
            _CATALOG_CACHE = fetch_master_assets.build_catalog(online=False)
            return _CATALOG_CACHE
        except Exception:
            _CATALOG_CACHE = {'items': {}, 'tag_index': {}}
            return _CATALOG_CACHE
    _CATALOG_CACHE = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    return _CATALOG_CACHE


def resolve_asset(query):
    """Map any noun or phrase (e.g. 'red pen', 'love note', 'pile of sand') to a catalog entry."""
    cat = load_catalog()
    items = cat.get('items', {})
    tags = cat.get('tag_index', {})
    q = str(query or 'box').strip().lower().replace('-', '_').replace(' ', '_')
    if q in tags:
        return items[tags[q]]
    for token in reversed(q.split('_')):
        if token in tags:
            return items[tags[token]]
    for tag, item_id in tags.items():
        if tag in q or q in tag:
            return items[item_id]
    return items.get('box', {'id': 'box', 'builder': 'box', 'size': 1.0, 'placement': 'floor'})


# ---------------------------------------------------------------- material helpers
def _lin(c):
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def _parse_color(col, default=(0.85, 0.25, 0.22)):
    NAMED = {
        'red': (0.88, 0.22, 0.20), 'blue': (0.20, 0.48, 0.90), 'green': (0.22, 0.72, 0.34),
        'yellow': (0.96, 0.82, 0.20), 'gold': (0.96, 0.76, 0.16), 'white': (0.96, 0.96, 0.95),
        'black': (0.12, 0.12, 0.14), 'gray': (0.55, 0.55, 0.58), 'grey': (0.55, 0.55, 0.58),
        'brown': (0.48, 0.30, 0.16), 'orange': (0.96, 0.50, 0.16), 'purple': (0.58, 0.28, 0.78),
        'pink': (0.96, 0.55, 0.72), 'tan': (0.86, 0.74, 0.52), 'sand': (0.92, 0.82, 0.56),
        'wood': (0.62, 0.42, 0.24), 'silver': (0.78, 0.80, 0.84),
    }
    if not col:
        return default
    if isinstance(col, str):
        s = col.strip().lower()
        if s in NAMED:
            return NAMED[s]
        h = s.lstrip('#')
        if len(h) == 3:
            h = ''.join(c * 2 for c in h)
        if len(h) >= 6:
            return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    if isinstance(col, (list, tuple)) and len(col) >= 3:
        vals = [float(col[0]), float(col[1]), float(col[2])]
        if max(vals) > 1.0:
            vals = [v / 255.0 for v in vals]
        return tuple(max(0.0, min(1.0, v)) for v in vals)
    return default


def _mat(name, rgb, rough=0.42, metal=0.0, emit=0.0):
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get('Principled BSDF')
    lin = tuple(_lin(c) for c in rgb)
    b.inputs['Base Color'].default_value = (*lin, 1.0)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    if emit > 0.0:
        b.inputs['Emission Color'].default_value = (*lin, 1.0)
        b.inputs['Emission Strength'].default_value = emit
    return m


# ---------------------------------------------------------------- bmesh primitives
def _bm_box(bm, center, size, mat_idx=0, rot=(0, 0, 0), bevel=0.02):
    tmp = bmesh.new()
    bmesh.ops.create_cube(tmp, size=1.0)
    for v in tmp.verts:
        v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
    if bevel > 0.0:
        bmesh.ops.bevel(tmp, geom=list(tmp.edges) + list(tmp.verts),
                        offset=min(bevel, min(size) * 0.4), segments=2, affect='EDGES')
    M = Matrix.Translation(Vector(center)) @ Euler(rot, 'XYZ').to_matrix().to_4x4()
    tmp.transform(M)
    for f in tmp.faces:
        f.material_index = mat_idx
        f.smooth = True
    me = bpy.data.meshes.new('_tmp_box')
    tmp.to_mesh(me)
    tmp.free()
    bm.from_mesh(me)
    bpy.data.meshes.remove(me)


def _bm_cyl(bm, center, r1, r2, depth, mat_idx=0, seg=18, rot=(0, 0, 0)):
    tmp = bmesh.new()
    bmesh.ops.create_cone(tmp, cap_ends=True, segments=seg, radius1=r1, radius2=r2, depth=depth)
    M = Matrix.Translation(Vector(center)) @ Euler(rot, 'XYZ').to_matrix().to_4x4()
    tmp.transform(M)
    for f in tmp.faces:
        f.material_index = mat_idx
        f.smooth = True
    me = bpy.data.meshes.new('_tmp_cyl')
    tmp.to_mesh(me)
    tmp.free()
    bm.from_mesh(me)
    bpy.data.meshes.remove(me)


def _bm_ico(bm, center, r, scale=(1, 1, 1), mat_idx=0, sub=2):
    tmp = bmesh.new()
    bmesh.ops.create_icosphere(tmp, subdivisions=sub, radius=r)
    M = Matrix.Translation(Vector(center)) @ Matrix.Diagonal((*scale, 1.0))
    tmp.transform(M)
    for f in tmp.faces:
        f.material_index = mat_idx
        f.smooth = True
    me = bpy.data.meshes.new('_tmp_ico')
    tmp.to_mesh(me)
    tmp.free()
    bm.from_mesh(me)
    bpy.data.meshes.remove(me)


def _finalize_bm(name, bm, mats, coll=None):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    ob = bpy.data.objects.new(name, me)
    target = coll or bpy.context.scene.collection
    target.objects.link(ob)
    return ob


# ---------------------------------------------------------------- procedural prop builders
def _build_procedural(name, builder, col_rgb, coll=None):
    bm = bmesh.new()
    m_main = _mat(f'prop_{builder}_main', col_rgb, rough=0.40)
    m_white = _mat('prop_white', (0.96, 0.96, 0.95), rough=0.45)
    m_dark = _mat('prop_dark', (0.14, 0.14, 0.16), rough=0.35)
    m_gold = _mat('prop_gold', (0.96, 0.78, 0.18), rough=0.25, metal=0.85)
    m_wood = _mat('prop_wood', (0.64, 0.44, 0.24), rough=0.52)
    mats = [m_main, m_white, m_dark, m_gold, m_wood]

    if builder in ('pen', 'pencil'):
        # Orient along Y so when held in hand.R it points forward naturally
        _bm_cyl(bm, (0, 0.0, 0), 0.036, 0.036, 0.56, mat_idx=0, rot=(math.pi / 2, 0, 0))
        _bm_cyl(bm, (0, -0.33, 0), 0.036, 0.004, 0.11, mat_idx=4 if builder == 'pencil' else 3, rot=(math.pi / 2, 0, 0))
        _bm_cyl(bm, (0, 0.30, 0), 0.038, 0.038, 0.06, mat_idx=3 if builder == 'pencil' else 2, rot=(math.pi / 2, 0, 0))
    elif builder == 'note':
        _bm_box(bm, (0, -0.05, 0), (0.56, 0.72, 0.025), mat_idx=1, bevel=0.005)
        for z_off in (-0.20, -0.08, 0.04, 0.16):
            _bm_box(bm, (0, z_off, 0.016), (0.40, 0.035, 0.008), mat_idx=2, bevel=0.0)
        _bm_box(bm, (-0.12, 0.25, 0.016), (0.16, 0.04, 0.008), mat_idx=0, bevel=0.0)
    elif builder == 'book':
        _bm_box(bm, (0, 0, 0), (0.62, 0.82, 0.14), mat_idx=0, bevel=0.02)
        _bm_box(bm, (0.02, 0, 0), (0.56, 0.76, 0.11), mat_idx=1, bevel=0.01)
    elif builder == 'ruler':
        _bm_box(bm, (0, 0, 0), (0.16, 0.95, 0.025), mat_idx=3, bevel=0.005)
    elif builder == 'eraser':
        _bm_box(bm, (0, 0, 0), (0.22, 0.36, 0.10), mat_idx=1, bevel=0.02)
        _bm_box(bm, (0, -0.06, 0), (0.23, 0.20, 0.11), mat_idx=0, bevel=0.01)
    elif builder == 'backpack':
        _bm_box(bm, (0, 0, 0.65), (1.05, 0.56, 1.30), mat_idx=0, bevel=0.14)
        _bm_box(bm, (0, -0.32, 0.45), (0.76, 0.16, 0.62), mat_idx=1, bevel=0.06)
    elif builder in ('phone', 'tablet'):
        sc = 1.65 if builder == 'tablet' else 1.0
        _bm_box(bm, (0, 0, 0), (0.34 * sc, 0.64 * sc, 0.045), mat_idx=2, bevel=0.015)
        _bm_box(bm, (0, 0, 0.025), (0.30 * sc, 0.58 * sc, 0.008), mat_idx=0, bevel=0.005)
    elif builder == 'laptop':
        _bm_box(bm, (0, 0, 0.04), (1.25, 0.88, 0.06), mat_idx=2, bevel=0.015)
        _bm_box(bm, (0, 0.40, 0.46), (1.25, 0.05, 0.84), mat_idx=2, rot=(-0.22, 0, 0), bevel=0.015)
        _bm_box(bm, (0, 0.37, 0.46), (1.14, 0.02, 0.74), mat_idx=0, rot=(-0.22, 0, 0), bevel=0.005)
    elif builder == 'controller':
        _bm_box(bm, (0, 0, 0), (0.62, 0.36, 0.14), mat_idx=2, bevel=0.05)
        _bm_cyl(bm, (-0.16, 0.04, 0.08), 0.06, 0.06, 0.04, mat_idx=0)
        _bm_cyl(bm, (0.16, 0.04, 0.08), 0.06, 0.06, 0.04, mat_idx=1)
    elif builder == 'money':
        _bm_box(bm, (0, 0, 0), (0.56, 0.28, 0.12), mat_idx=0, bevel=0.01)
        _bm_box(bm, (0, 0, 0), (0.12, 0.29, 0.13), mat_idx=1, bevel=0.005)
    elif builder == 'gold_bar':
        _bm_box(bm, (0, 0, 0.12), (0.68, 0.34, 0.24), mat_idx=3, bevel=0.04)
    elif builder == 'key':
        _bm_cyl(bm, (0, 0.18, 0), 0.12, 0.12, 0.03, mat_idx=3)
        _bm_box(bm, (0, -0.10, 0), (0.05, 0.38, 0.03), mat_idx=3, bevel=0.005)
        _bm_box(bm, (0.06, -0.22, 0), (0.10, 0.08, 0.03), mat_idx=3, bevel=0.005)
    elif builder == 'trophy':
        _bm_box(bm, (0, 0, 0.12), (0.44, 0.44, 0.24), mat_idx=2, bevel=0.03)
        _bm_cyl(bm, (0, 0, 0.38), 0.08, 0.12, 0.28, mat_idx=3)
        _bm_cyl(bm, (0, 0, 0.72), 0.16, 0.34, 0.44, mat_idx=3)
    elif builder == 'gift':
        _bm_box(bm, (0, 0, 0.45), (0.90, 0.90, 0.90), mat_idx=0, bevel=0.04)
        _bm_box(bm, (0, 0, 0.45), (0.93, 0.16, 0.93), mat_idx=3, bevel=0.01)
        _bm_box(bm, (0, 0, 0.45), (0.16, 0.93, 0.93), mat_idx=3, bevel=0.01)
    elif builder == 'box':
        _bm_box(bm, (0, 0, 0.55), (1.20, 1.10, 1.10), mat_idx=4, bevel=0.04)
        _bm_box(bm, (0, 0, 1.11), (1.22, 0.14, 0.02), mat_idx=1, bevel=0.0)
    elif builder == 'pizza':
        _bm_box(bm, (0, 0, 0.09), (1.20, 1.20, 0.18), mat_idx=1, bevel=0.02)
        _bm_cyl(bm, (0, 0, 0.20), 0.52, 0.52, 0.05, mat_idx=3, seg=24)
        for px, py in ((-0.2, 0.15), (0.22, 0.18), (0.0, -0.22), (-0.18, -0.15), (0.2, -0.12)):
            _bm_cyl(bm, (px, py, 0.23), 0.08, 0.08, 0.02, mat_idx=0, seg=12)
    elif builder == 'burger':
        _bm_cyl(bm, (0, 0, 0.07), 0.28, 0.26, 0.12, mat_idx=4)
        _bm_cyl(bm, (0, 0, 0.16), 0.29, 0.29, 0.07, mat_idx=2)
        _bm_cyl(bm, (0, 0, 0.22), 0.30, 0.30, 0.04, mat_idx=3)
        _bm_ico(bm, (0, 0, 0.27), 0.28, scale=(1.0, 1.0, 0.55), mat_idx=4)
    elif builder == 'cake':
        _bm_cyl(bm, (0, 0, 0.22), 0.52, 0.52, 0.44, mat_idx=1, seg=24)
        _bm_cyl(bm, (0, 0, 0.46), 0.54, 0.54, 0.08, mat_idx=0, seg=24)
        _bm_cyl(bm, (0, 0, 0.62), 0.03, 0.03, 0.24, mat_idx=3, seg=10)
    elif builder in ('apple', 'ball'):
        r = 0.40 if builder == 'ball' else 0.20
        _bm_ico(bm, (0, 0, r), r, mat_idx=0, sub=2)
    elif builder == 'donut':
        _bm_cyl(bm, (0, 0, 0.07), 0.24, 0.24, 0.14, mat_idx=4, seg=20)
        _bm_cyl(bm, (0, 0, 0.12), 0.25, 0.25, 0.06, mat_idx=0, seg=20)
    elif builder == 'ice_cream':
        _bm_cyl(bm, (0, 0, 0.18), 0.02, 0.14, 0.36, mat_idx=4, seg=16)
        _bm_ico(bm, (0, 0, 0.42), 0.17, mat_idx=0, sub=2)
    elif builder == 'drink':
        _bm_cyl(bm, (0, 0, 0.28), 0.15, 0.18, 0.56, mat_idx=0, seg=18)
        _bm_cyl(bm, (0, 0, 0.58), 0.19, 0.19, 0.04, mat_idx=1, seg=18)
        _bm_cyl(bm, (0.04, 0, 0.70), 0.02, 0.02, 0.24, mat_idx=1, seg=8)
    elif builder == 'plate':
        _bm_cyl(bm, (0, 0, 0.04), 0.44, 0.36, 0.08, mat_idx=1, seg=24)
    elif builder == 'dumbbell':
        _bm_cyl(bm, (0, 0, 0), 0.045, 0.045, 0.78, mat_idx=2, rot=(0, math.pi / 2, 0))
        _bm_cyl(bm, (-0.34, 0, 0), 0.19, 0.19, 0.14, mat_idx=0, rot=(0, math.pi / 2, 0))
        _bm_cyl(bm, (0.34, 0, 0), 0.19, 0.19, 0.14, mat_idx=0, rot=(0, math.pi / 2, 0))
    elif builder == 'umbrella':
        _bm_cyl(bm, (0, 0, 0.90), 0.035, 0.035, 1.80, mat_idx=2)
        _bm_cyl(bm, (0, 0, 1.65), 1.35, 0.15, 0.45, mat_idx=0, seg=16)
    elif builder == 'broom':
        _bm_cyl(bm, (0, 0, 1.15), 0.04, 0.04, 2.0, mat_idx=4)
        _bm_box(bm, (0, 0, 0.16), (0.65, 0.16, 0.32), mat_idx=3, bevel=0.03)
    elif builder == 'flashlight':
        _bm_cyl(bm, (0, 0, 0), 0.06, 0.06, 0.48, mat_idx=2, rot=(math.pi / 2, 0, 0))
        _bm_cyl(bm, (0, -0.28, 0), 0.11, 0.07, 0.14, mat_idx=0, rot=(math.pi / 2, 0, 0))
    elif builder == 'hammer':
        _bm_cyl(bm, (0, 0, 0.32), 0.04, 0.04, 0.68, mat_idx=4)
        _bm_box(bm, (0, 0, 0.66), (0.14, 0.38, 0.14), mat_idx=2, bevel=0.02)
    elif builder == 'flower':
        _bm_cyl(bm, (0, 0, 0.30), 0.025, 0.025, 0.60, mat_idx=0)
        _bm_ico(bm, (0, 0, 0.64), 0.14, scale=(1.1, 1.1, 0.7), mat_idx=3, sub=2)
    elif builder == 'sand_pile':
        _bm_ico(bm, (0, 0, 0.16), 0.95, scale=(1.2, 1.0, 0.34), mat_idx=0, sub=2)
        _bm_ico(bm, (0.35, -0.2, 0.12), 0.55, scale=(1.1, 0.9, 0.28), mat_idx=0, sub=2)
    elif builder == 'pedestal_table':
        _bm_cyl(bm, (0, 0, 0.08), 0.72, 0.58, 0.16, mat_idx=1, seg=24)
        _bm_cyl(bm, (0, 0, 1.18), 0.14, 0.14, 2.15, mat_idx=1, seg=18)
        _bm_cyl(bm, (0, 0, 2.32), 1.15, 1.15, 0.14, mat_idx=4, seg=28)
    elif builder == 'bed':
        _bm_box(bm, (0, 0, 0.55), (3.4, 5.4, 0.70), mat_idx=4, bevel=0.06)
        _bm_box(bm, (0, 0.1, 1.02), (3.1, 5.0, 0.38), mat_idx=1, bevel=0.08)
        _bm_box(bm, (0, -0.4, 1.08), (3.15, 3.8, 0.40), mat_idx=0, bevel=0.08)
        _bm_box(bm, (0, 2.55, 1.65), (3.4, 0.24, 2.2), mat_idx=4, bevel=0.06)
        _bm_box(bm, (0, 1.95, 1.32), (2.2, 0.85, 0.26), mat_idx=1, bevel=0.08)
    elif builder == 'desk':
        _bm_box(bm, (0, 0, 2.35), (3.6, 1.8, 0.18), mat_idx=4, bevel=0.04)
        for lx in (-1.55, 1.55):
            for ly in (-0.72, 0.72):
                _bm_box(bm, (lx, ly, 1.15), (0.22, 0.22, 2.30), mat_idx=2, bevel=0.02)
    elif builder == 'chair':
        _bm_box(bm, (0, 0, 1.45), (1.45, 1.45, 0.18), mat_idx=4, bevel=0.04)
        _bm_box(bm, (0, 0.65, 2.45), (1.45, 0.18, 1.85), mat_idx=4, bevel=0.04)
        for lx in (-0.58, 0.58):
            for ly in (-0.58, 0.58):
                _bm_box(bm, (lx, ly, 0.72), (0.16, 0.16, 1.44), mat_idx=2, bevel=0.02)
    elif builder == 'sofa':
        _bm_box(bm, (0, 0, 0.85), (4.8, 2.0, 1.1), mat_idx=0, bevel=0.14)
        _bm_box(bm, (0, 0.75, 1.85), (4.8, 0.5, 1.4), mat_idx=0, bevel=0.14)
        for sx in (-2.2, 2.2):
            _bm_box(bm, (sx, -0.1, 1.35), (0.45, 1.9, 0.85), mat_idx=0, bevel=0.12)
    elif builder == 'tv':
        _bm_box(bm, (0, 0, 0.12), (1.6, 0.75, 0.14), mat_idx=2, bevel=0.02)
        _bm_box(bm, (0, 0, 0.55), (0.28, 0.22, 0.75), mat_idx=2, bevel=0.02)
        _bm_box(bm, (0, 0, 1.85), (3.4, 0.18, 2.0), mat_idx=2, bevel=0.04)
        _bm_box(bm, (0, -0.10, 1.85), (3.15, 0.02, 1.78), mat_idx=0, bevel=0.01)
    elif builder == 'mirror':
        _bm_box(bm, (0, 0, 2.3), (2.2, 0.18, 4.4), mat_idx=4, bevel=0.05)
        _bm_box(bm, (0, -0.10, 2.3), (1.85, 0.02, 4.0), mat_idx=1, bevel=0.01)
    else:
        _bm_box(bm, (0, 0, 0.5), (1.0, 1.0, 1.0), mat_idx=0, bevel=0.06)

    return _finalize_bm(name, bm, mats, coll=coll)


# ---------------------------------------------------------------- hinged furniture (closet / chest / door)
def _build_hinged(name, builder, col_rgb, spec, coll=None):
    target = coll or bpy.context.scene.collection
    root = bpy.data.objects.new(name, None)
    target.objects.link(root)

    m_body = _mat(f'hinged_{builder}_body', col_rgb, rough=0.45)
    m_trim = _mat(f'hinged_{builder}_trim', tuple(max(0.0, c * 0.78) for c in col_rgb), rough=0.45)
    m_gold = _mat('prop_gold', (0.96, 0.78, 0.18), rough=0.25, metal=0.85)
    m_dark = _mat('prop_dark', (0.14, 0.14, 0.16), rough=0.35)
    mats = [m_body, m_trim, m_gold, m_dark]

    if builder == 'chest':
        w, d, h = 2.2, 1.35, 1.15
        bm = bmesh.new()
        _bm_box(bm, (0, 0, h * 0.4), (w, d, h * 0.8), mat_idx=0, bevel=0.05)
        _bm_box(bm, (0, 0, h * 0.4), (w + 0.04, d + 0.04, 0.10), mat_idx=2, bevel=0.01)
        body = _finalize_bm(f'{name}_body', bm, mats, coll=target)
        body.parent = root

        lid_pivot = bpy.data.objects.new(f'{name}_lid_hinge', None)
        lid_pivot.location = (0, d * 0.48, h * 0.8)
        lid_pivot.parent = root
        target.objects.link(lid_pivot)

        lbm = bmesh.new()
        _bm_box(lbm, (0, -d * 0.48, h * 0.16), (w, d, h * 0.32), mat_idx=1, bevel=0.05)
        _bm_box(lbm, (0, -d * 0.98, 0.02), (0.26, 0.06, 0.24), mat_idx=2, bevel=0.01)
        lid = _finalize_bm(f'{name}_lid', lbm, mats, coll=target)
        lid.parent = lid_pivot
        hinges = [(lid_pivot, 'X', math.radians(-85))]
    else:
        # Wardrobe / closet / double-door with hinged left & right doors
        w = 3.6 if builder == 'closet' else 3.2
        d = 1.6 if builder == 'closet' else 0.35
        h = 6.2 if builder == 'closet' else 6.6

        bm = bmesh.new()
        if builder == 'closet':
            # Open interior cavity + back + sides + top + bottom + inner shelf
            _bm_box(bm, (0, d * 0.42, h * 0.5), (w, 0.16, h), mat_idx=0, bevel=0.03)
            _bm_box(bm, (-w * 0.47, 0, h * 0.5), (0.18, d, h), mat_idx=0, bevel=0.03)
            _bm_box(bm, (w * 0.47, 0, h * 0.5), (0.18, d, h), mat_idx=0, bevel=0.03)
            _bm_box(bm, (0, 0, h - 0.10), (w + 0.12, d + 0.12, 0.22), mat_idx=1, bevel=0.04)
            _bm_box(bm, (0, 0, 0.12), (w + 0.10, d + 0.10, 0.24), mat_idx=1, bevel=0.04)
            _bm_box(bm, (0, 0.05, h * 0.68), (w - 0.32, d - 0.22, 0.12), mat_idx=1, bevel=0.02)
        else:
            # Doorframe
            _bm_box(bm, (-w * 0.5, 0, h * 0.5), (0.24, d + 0.16, h), mat_idx=1, bevel=0.03)
            _bm_box(bm, (w * 0.5, 0, h * 0.5), (0.24, d + 0.16, h), mat_idx=1, bevel=0.03)
            _bm_box(bm, (0, 0, h + 0.10), (w + 0.24, d + 0.16, 0.24), mat_idx=1, bevel=0.03)
        body = _finalize_bm(f'{name}_frame', bm, mats, coll=target)
        body.parent = root

        hinges = []
        leaf_w = (w - 0.36) * 0.5
        y_front = -d * 0.46 if builder == 'closet' else 0.0
        for side, sname in ((-1, 'L'), (1, 'R')):
            hx = side * (w * 0.5 - 0.18)
            piv = bpy.data.objects.new(f'{name}_hinge_{sname}', None)
            piv.location = (hx, y_front, 0.24)
            piv.parent = root
            target.objects.link(piv)

            dbm = bmesh.new()
            _bm_box(dbm, (-side * leaf_w * 0.5, 0, (h - 0.48) * 0.5), (leaf_w - 0.03, 0.12, h - 0.48), mat_idx=0, bevel=0.03)
            _bm_cyl(dbm, (-side * (leaf_w - 0.22), -0.09, h * 0.46), 0.06, 0.06, 0.10, mat_idx=2, rot=(math.pi / 2, 0, 0))
            leaf = _finalize_bm(f'{name}_door_{sname}', dbm, mats, coll=target)
            leaf.parent = piv
            hinges.append((piv, 'Z', side * math.radians(-105)))

    open_at = spec.get('openAt')
    close_at = spec.get('closeAt')
    if open_at is not None:
        f0 = int(round(float(open_at) * FPS))
        f1 = f0 + 10
        for piv, axis, angle in hinges:
            piv.rotation_euler = (0, 0, 0)
            piv.keyframe_insert('rotation_euler', frame=max(1, f0 - 1))
            if axis == 'X':
                piv.rotation_euler = (angle, 0, 0)
            else:
                piv.rotation_euler = (0, 0, angle)
            piv.keyframe_insert('rotation_euler', frame=f1)
            if close_at is not None:
                fc0 = int(round(float(close_at) * FPS))
                piv.keyframe_insert('rotation_euler', frame=max(f1 + 1, fc0 - 1))
                piv.rotation_euler = (0, 0, 0)
                piv.keyframe_insert('rotation_euler', frame=fc0 + 10)

    return root


# ---------------------------------------------------------------- 4-point star sparkle FX
def spawn_sparkle(name, loc, start_t, duration=1.2, scale=0.65, coll=None):
    """Animated 4-point star sparkles seen in @craftee_films reveal & magic beats."""
    target = coll or bpy.context.scene.collection
    m_star = _mat('fx_sparkle_gold', (1.0, 0.92, 0.35), rough=0.1, emit=6.5)
    root = bpy.data.objects.new(name, None)
    root.location = Vector(loc)
    target.objects.link(root)

    offsets = [(-0.45, -0.25, 0.35, 1.0), (0.48, -0.20, 0.55, 0.8), (0.0, -0.35, 0.85, 0.65)]
    f_start = max(1, int(round(float(start_t) * FPS)))
    f_peak = f_start + 8
    f_end = max(f_peak + 6, int(round((float(start_t) + float(duration)) * FPS)))

    for idx, (dx, dy, dz, mult) in enumerate(offsets):
        bm = bmesh.new()
        _bm_box(bm, (0, 0, 0), (0.08, 0.04, 0.55), mat_idx=0, bevel=0.01)
        _bm_box(bm, (0, 0, 0), (0.55, 0.04, 0.08), mat_idx=0, bevel=0.01)
        star = _finalize_bm(f'{name}_star_{idx}', bm, [m_star], coll=target)
        star.parent = root
        star.location = (dx, dy, dz)

        s_max = scale * mult
        star.scale = (0.001, 0.001, 0.001)
        star.keyframe_insert('scale', frame=max(1, f_start - 1))
        star.scale = (s_max, s_max, s_max)
        star.keyframe_insert('scale', frame=f_peak)
        star.scale = (0.001, 0.001, 0.001)
        star.keyframe_insert('scale', frame=f_end)

        star.rotation_euler = (0, 0, 0)
        star.keyframe_insert('rotation_euler', frame=f_start)
        star.rotation_euler = (0, math.radians(140), 0)
        star.keyframe_insert('rotation_euler', frame=f_end)

    return root


# ---------------------------------------------------------------- main spawn API
def _parent_to_hand(ob, arm, bone_name='hand.R'):
    bone = arm.data.bones.get(bone_name) or arm.data.bones.get('hand.R')
    if bone is None:
        return
    ob.parent = arm
    ob.parent_type = 'BONE'
    ob.parent_bone = bone.name
    # Bone tail in local space sits right at the center of the character's palm
    ob.matrix_parent_inverse = (bone.matrix_local @ Matrix.Translation((0, bone.length, 0))).inverted()
    ob.location = Vector((0.0, -0.05, -0.05))
    ob.rotation_euler = (0.0, 0.0, 0.0)


def spawn_prop(name, spec, chars=None, coll=None):
    """Spawn any prop from a shot/story spec dict and attach to hand, side pedestal, or floor.

    Supported spec keys:
      type / asset / noun : string name ('pen', 'note', 'pizza', 'closet', 'sand', ...)
      color               : hex or named color
      scale               : float multiplier (default 1.0)
      hold                : character name (parents to char's hand.R) or {'char': 'Name', 'hand': 'hand.L'}
      pedestal            : bool or character name (spawns a side pedestal table beside char and places prop on top)
      loc                 : [x, y, z] world coordinates (used when not held or on pedestal)
      yaw                 : rotation around Z in degrees
      openAt / closeAt    : float timestamps in seconds for hinged doors/closets/chests
      sparkleAt           : float timestamp in seconds to emit 4-point star sparkles
      showAt / hideAt     : float timestamps in seconds for animated visibility
    """
    target = coll or bpy.context.scene.collection
    noun = spec.get('type') or spec.get('asset') or spec.get('noun') or name
    entry = resolve_asset(noun)
    builder = entry.get('builder', 'box')
    col_rgb = _parse_color(spec.get('color'))
    user_scale = float(spec.get('scale', 1.0))

    ob = None
    if entry.get('placement') == 'hinged' or builder in ('closet', 'chest', 'door'):
        ob = _build_hinged(name, builder, col_rgb, spec, coll=target)
    else:
        glb_rel = entry.get('glb')
        if glb_rel and (ASSET_DIR / glb_rel).exists():
            before = set(bpy.data.objects)
            bpy.ops.import_scene.gltf(filepath=str(ASSET_DIR / glb_rel))
            imported = [o for o in bpy.data.objects if o not in before]
            if imported:
                ob = bpy.data.objects.new(name, None)
                target.objects.link(ob)
                for io in imported:
                    if io.parent is None:
                        io.parent = ob
                    if io.name not in target.objects:
                        target.objects.link(io)
        if ob is None:
            ob = _build_procedural(name, builder, col_rgb, coll=target)

    ob.scale = (user_scale, user_scale, user_scale)

    # 1. Hand attachment
    hold = spec.get('hold')
    if hold and chars:
        cname = hold.get('char') if isinstance(hold, dict) else str(hold)
        bname = hold.get('hand', 'hand.R') if isinstance(hold, dict) else 'hand.R'
        arm = chars.get(cname)
        if arm is not None:
            _parent_to_hand(ob, arm, bname)
            if spec.get('sparkleAt') is not None:
                spawn_sparkle(f'{name}_sparkle', arm.location + Vector((0, -0.8, 2.8)), spec['sparkleAt'], coll=target)
            _apply_visibility(ob, spec)
            return ob

    # 2. Side pedestal table attachment (keeps actors 100% unblocked in camera view)
    ped = spec.get('pedestal')
    if ped:
        px, py, pz = 1.45, 0.15, 0.0
        if isinstance(ped, str) and chars and ped in chars:
            cloc = chars[ped].location
            side = -1.45 if cloc.x >= 0 else 1.45
            px, py, pz = cloc.x + side, cloc.y + 0.10, cloc.z
        elif 'loc' in spec:
            px, py, pz = spec['loc']
        table = _build_procedural(f'{name}_pedestal', 'pedestal_table', (0.64, 0.44, 0.24), coll=target)
        table.location = (px, py, pz)
        ob.location = (px, py, pz + 2.39)
    else:
        loc = spec.get('loc', (0.0, 2.5, 0.0))
        ob.location = Vector(loc)

    if 'yaw' in spec:
        ob.rotation_euler = (0.0, 0.0, math.radians(float(spec['yaw'])))

    if spec.get('sparkleAt') is not None:
        spawn_sparkle(f'{name}_sparkle', ob.location + Vector((0, 0, 0.45)), spec['sparkleAt'], coll=target)

    _apply_visibility(ob, spec)
    return ob


def _apply_visibility(ob, spec):
    show_at = spec.get('showAt')
    hide_at = spec.get('hideAt')
    targets = [ob] + list(ob.children_recursive)
    if show_at is not None:
        f_show = max(1, int(round(float(show_at) * FPS)))
        for t in targets:
            t.hide_render = True
            t.hide_viewport = True
            t.keyframe_insert('hide_render', frame=1)
            t.keyframe_insert('hide_viewport', frame=1)
            t.hide_render = False
            t.hide_viewport = False
            t.keyframe_insert('hide_render', frame=f_show)
            t.keyframe_insert('hide_viewport', frame=f_show)
    if hide_at is not None:
        f_hide = max(1, int(round(float(hide_at) * FPS)))
        for t in targets:
            t.hide_render = False
            t.hide_viewport = False
            t.keyframe_insert('hide_render', frame=max(1, f_hide - 1))
            t.keyframe_insert('hide_viewport', frame=max(1, f_hide - 1))
            t.hide_render = True
            t.hide_viewport = True
            t.keyframe_insert('hide_render', frame=f_hide)
            t.keyframe_insert('hide_viewport', frame=f_hide)
