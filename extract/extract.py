#!/usr/bin/env python3
"""Extract autochess art from a locally installed Arknights client (optional, host-side).

The official CN client ships Unity AssetBundles compressed with a custom LZ4 variant ("LZ4AK");
aklz4.py registers a decoder for it. This script pulls the art the web sources lack:
  - map_autochess / map_autochesssand textures (the real board tile atlas)
  - every Sprite of the three autochess UI bundles (HUD frames, badges, banners, icons)
  - the 6 in-match emoticon themes of 盟约 (activity_table autoChessData.enabledEmoticonThemeIdList; only the
    *_battle sprites, keyed by display_meta_table picId: emoticon/<dir>/<picId>.png, see data/emotes.json)
  - the autochess guidebook pages and battle projectile sprites
  (the emotes and the guidebook pages are on the public mirror too: tools/fetch-assets.mjs downloads them, and the
  client uses these local copies first — GitHub issue #42)
  - the enemy battle Spine models no community dump carries (ENEMY_SPINES: 灼热源石虫 / 炽焰源石虫), from the enemy art
    bundles (refs/arts/enm_art_*.ab) → spine/enemy/<enemyId>/<stem>.skel|.atlas + page PNGs with the [alpha] texture
    merged in (straight RGBA, no `pma` field: the atlas gets `size:` like the fetched ones, so the web renderer treats
    an extracted page exactly like a downloaded one); the client draws them instead of the web alias once this manifest
    lists them (data/assets.json enemies[id].spineLocal, docs/ASSETS.md "Enemy aliases")
  - the token (summon) battle Spine models no community dump carries (TOKEN_SPINES: most 自选 summons, 凯瑟琳's
    爬行号·防护单元, 凛御银灰's 风雪之眼), from the battle token prefabs (pkgrps/btl_pfb_tokens_*.ab: the skeleton
    the prefab's Front / only Spine renderer draws) → spine/token/<tokenId>/<stem>.skel|.atlas + merged page PNGs, the
    same format; drawn instead of the avatar diamond once this manifest lists them (data/assets.json
    tokens[id].spineLocal)
  - for the official 3D board (DESIGN §15): the map theme's Material parameters (map/<theme>/materials.json; shader
    names resolved through the shaders/*.ab bundles), the background / device meshes as Wavefront OBJ
    (mesh/<bundle>/<mesh>.obj; UnityPy's exporter, X mirrored into a right-handed frame) and their GameObject
    placement (mesh/<bundle>/prefab.json)
  - the standard gate / objective effects of every battle map (arts/effects/[pack]map.ab → map/fx: the [opt]start_box /
    [opt]end_box / [opt]start_fly meshes, their merged additive textures, materials and prefab), the blower's texture
    (arts/maps/common/res.ab → map/common: TX_wind_device of the s_wind_device mesh) and the shared water / noise
    textures (arts/maps/effect.ab → map/water) used for deep-sea / mire / smog tiles
  - derived PBR maps for three.js (DERIVED): Unity stores the theme's normal map as two channels (BC5: RG = XY, B = 0;
    DXT5nm in an older bundle: AG = XY, R = 1) and metallic/gloss with the smoothness in A; the board renderer needs
    an RGB normal map (Z rebuilt) and a roughness map in G (1 − smoothness; metalness B = 0), written next to the
    source as <name>_rgb.png / _rough.png
  - WebP copies of the board textures every player downloads with the 3D board (WEBP) and of the 19 guidebook pages
    (GUIDE_WEBP_*), written next to their PNGs; the manifest lists the copy
  - the official battlefield scenes (scenes.py SCENES: one prebuilt scene per 卫戍协议 battlefield) → scene/<stageId>/
    scene.json + scene.bin + lightmap pages and scene/tex/ (the materials' albedo textures). The scene bundles ship
    only while the season runs: they are read from the client when it has them, else from --scenes <dir> (default
    .cache/official-scenes/*, filled by tools/local-extract/fetch_scenes.py)

Usage:
  python3 -m venv .venv && .venv/bin/pip install -r tools/local-extract/requirements.txt
  .venv/bin/python tools/local-extract/extract.py [--game <AB root>] [--out public/assets/local] [--only <subdir prefix>]
  python3 tools/local-extract/extract.py --print-jobs     (the job table as JSON; needs no dependencies)
  python3 tools/local-extract/extract.py --webp           (only the WebP copies of the board textures and the guide
                                                          pages, from the PNGs already extracted — e.g. the local art
                                                          copied from a release bundle; needs Pillow)
  .venv/bin/python tools/local-extract/extract.py --only scene [--scenes <dir of in-season bundles>]

Writes <out>/**.png|.webp|.skel|.atlas and data/local-assets.json (manifest of what was extracted). With --only, just
the jobs whose output subdir starts with one of the prefixes run, and their groups replace those of the existing
manifest (every other group is kept as is).
Everything is (c) Hypergryph; for private, non-commercial fan use only.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import quote
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenes  # noqa: E402  (the battlefield scene table and exporter; imports UnityPy only when it runs)

ROOT = Path(__file__).resolve().parents[2]
HOME = Path.home()
CANDIDATES = [
    HOME / 'Library/Application Support/CrossOver/Bottles/Arknights/drive_c/Program Files/Hypergryph Launcher/games/Arknights/Arknights_Data/StreamingAssets/AB/Windows',
    HOME / 'Library/Containers/com.hypergryph.arknights/Data/Documents/Bundles',
    # native Windows installs of the official launcher (default and x86 locations)
    Path('C:/Program Files/Hypergryph Launcher/games/Arknights/Arknights_Data/StreamingAssets/AB/Windows'),
    Path('C:/Program Files (x86)/Hypergryph Launcher/games/Arknights/Arknights_Data/StreamingAssets/AB/Windows'),
]

# In-match emote themes (display_meta_table emoticonData, scene AUTOCHESS_BATTLE), in the order of
# activity_table autoChessData.enabledEmoticonThemeIdList: (themeId, output dir under emoticon/). The dirs are the
# ones of shared/constants.js EMOTE_THEMES / data/emotes.json. Only the *_battle sprites are exported: the bundles also
# hold room / pick pics of other modes (and the autochess room pics are not in the local client at all).
EMOTE_THEMES = [
    ('emoticon_autochess_basic', 'basic'),
    ('emoticon_originium_slug', 'slug'),
    ('emoticon_autochess_basic_2', 'basic_2'),
    ('emoticon_foolsday_doctor', 'fooldoctor'),
    ('emoticon_foolsday_amiya', 'foolamiya'),
    ('emoticon_foolsday_wisdel', 'foolwisdel'),
]
BATTLE_EMOTE = r'^pic_.+_battle$'

# Meshes of the official board scene (DESIGN §15): (bundle, output name under mesh/).
MESH_BUNDLES = [
    ('arts/maps/map_autochess/bkg_mesh.ab', 'map_autochess_bkg'),
    ('arts/maps/common/meshes/s_background_common.ab', 's_background_common'),
    ('arts/maps/common/meshes/s_common_box_01.ab', 's_common_box_01'),
    ('arts/maps/common/meshes/s_wind_device.ab', 's_wind_device'),
]

# (bundle path relative to the AB root, output subdir, which object types to export[, name regex to keep])
JOBS = [
    ('arts/maps/map_autochess/res.ab', 'map/autochess', {'Texture2D', 'Material'}),
    ('arts/maps/map_autochesssand/res.ab', 'map/autochesssand', {'Texture2D', 'Material'}),
    ('ui/autochess/[uc]autochesscommon.ab', 'ui/common', {'Sprite'}),
    ('ui/autochess/[uc]autochessbattle.ab', 'ui/battle', {'Sprite', 'TextAsset'}),
    ('ui/autochess/[uc]autochessouter.ab', 'ui/outer', {'Sprite'}),
    *[(f'ui/emoticon/theme/[uc]{theme}.ab', f'emoticon/{sub}', {'Sprite'}, BATTLE_EMOTE) for theme, sub in EMOTE_THEMES],
    ('arts/guidebookpages/[pack]autochess.ab', 'guide', {'Sprite', 'Texture2D'}),
    ('battle/prefabs/[uc]projectiles.ab', 'projectiles', {'Sprite', 'Texture2D'}),
    # official module (uniequip) type icons, keyed by lower-case type name (e.g. 'mar-x')
    ('spritepack/ui_equip_type_hub_h2_0.ab', 'module', {'Sprite'}),
    *[(rel, f'mesh/{sub}', {'Mesh', 'GameObject', 'Material', 'Texture2D'}) for rel, sub in MESH_BUNDLES],
    ('arts/effects/[pack]map.ab', 'map/fx', {'Mesh', 'GameObject', 'Material', 'Texture2D'}),
    ('arts/maps/common/res.ab', 'map/common', {'Material', 'Texture2D'}, r'^(TX|MT)_wind_device$'),
    ('arts/maps/effect.ab', 'map/water', {'Texture2D'}, r'water_normal|Caustics|WaterNoise|noise_clouds|Water_Foam|SmoothWaves'),
]

# Enemy battle Spine models that no community dump carries (isHarryh/Ark-Models lists them with an empty assetList, so
# tools/fetch-assets.mjs aliases them to another enemy's skeleton — the web model): every enemy of data/enemies.json whose
# official battle prefab draws a skeleton of its own that is missing upstream (audited against the client's prefabs, user
# feedback after 0.1.0 report D3: 灼热源石虫 / 炽焰源石虫 — the ELEMENT faction's slugs — were drawn as the plain 源石虫).
# Read from the enemy art bundles: Assets/Torappu/Arts/Enemies/Spines/<…>/<id>_SkeletonData.asset → its skeleton
# TextAsset, the atlas TextAsset of its atlas asset and every page texture of the atlas materials (_MainTex, with its
# _AlphaTex merged in as A). Output: spine/enemy/<id>/ (manifest group spine/enemy/<id>); the client draws the model
# when the group lists every file of data/assets.json enemies[id].spineLocal (whose metadata
# tools/assets/local-enemy-spines.json keeps: `node tools/fetch-assets.mjs --local-spines` after a game update).
ENEMY_SPINES = ['enemy_1305_mhslim', 'enemy_1305_mhslim_2']
ENEMY_ART = 'refs/arts/enm_art_*.ab'
ENEMY_SPINE_SUB = 'spine/enemy'

# Token (summon) battle Spine models that no community dump carries: fexli/ArknightsResource has most of the 自选
# summons (data/backups.json `tokens`) only as skin variants or not at all, so tools/fetch-assets.mjs reports "missing
# skel" for them and the client drew the avatar diamond. Every token of data/tokens.json and data/backups.json whose
# battle prefab draws a Spine model and that has no web model (audited 2026-10-06 against both local installs). Read from
# the battle token packs (dyn/battle/prefabs/[uc]tokens/<id>.prefab): the SkeletonDataAsset of the prefab's Spine
# renderer — of a directional token (FaceSwitcher with Front / Back / Down renderers, each its own skeleton under the
# same name) the Front one, the model the fetched tokens use too (plan.mjs: Spine/ or Front/) — with its skeleton,
# atlas and page textures as in ENEMY_SPINES. The Windows build carries every one (pkgrps/btl_pfb_tokens_0/4/5.ab; the
# iOS build lacks btl_pfb_tokens_0, and its pages are ASTC rather than BC7). Output: spine/token/<id>/ (manifest group
# spine/token/<id>); the client draws the model when the group lists every file of data/assets.json
# tokens[id].spineLocal (metadata in tools/assets/local-token-spines.json, `node tools/fetch-assets.mjs --local-spines`).
# Not here: the tokens whose prefab draws nothing (an EmptyAnimator in place of the Spine renderer, displayType HIDDEN
# or an effect only, and no avatar in either install's asset index) — 乌尔比安's 从不混淆的方向, 圣聆初雪's frozen
# protection point, 酒神's 迷狂牢笼, 贝洛内's 牵绊, 予愿安洁莉娜's “一会儿见！” (token_10039 / 10058 / 10055 / 10065 / 10071).
TOKEN_SPINES = [
    'token_10002_kalts_mon3tr', 'token_10003_cgbird_bird', 'token_10005_mgllan_drone1', 'token_10005_mgllan_drone2',
    'token_10005_mgllan_drone3', 'token_10007_phatom_twin', 'token_10008_cqbw_box', 'token_10009_weedy_cannon',
    'token_10020_ling_soul1', 'token_10020_ling_soul2', 'token_10020_ling_soul3', 'token_10024_ebnhlz_rcube',
    'token_10025_doroth_recttp', 'token_10026_bgsnow_subbow', 'token_10027_ironmn_pile1', 'token_10027_ironmn_pile2',
    'token_10027_ironmn_pile3', 'token_10029_slent2_protrb', 'token_10031_swire2_gdtrap', 'token_10032_jesca2_jckshd', 'token_10034_ray_sndbst',
    'token_10035_wisdel_wward', 'token_10041_cathy_catsld', 'token_10043_necras_skeltn', 'token_10050_monstr_prosts',
    'token_10051_radian_tower1', 'token_10052_radian_tower2', 'token_10053_radian_tower3', 'token_10054_phatm2_encdool',
    'token_10057_svash2_eagle1', 'token_10057_svash2_eagle2', 'token_10057_svash2_eagle3', 'token_10059_nasti_nstdef',
    'token_10060_nasti_nstchr', 'token_10061_nasti_nstbld', 'token_10064_wang_stone1', 'token_10066_closur_ourbase',
    'token_10068_kalts2_mtship', 'token_10069_mcnist_mcgraf', 'token_10070_aphris_pc',
]
TOKEN_PACKS = 'pkgrps/btl_pfb_tokens_*.ab'
TOKEN_SPINE_SUB = 'spine/token'

# Derived three.js maps: (output subdir, source texture, kind, output name). 'normal_rg' rebuilds Z of a two-channel
# (BC5 or DXT5nm) normal map into an RGB tangent-space map; 'rough_from_gloss' turns Unity's metallic/gloss map
# (smoothness in A) into a roughness (G) / metalness (B) map. Written after the job that exported the source texture.
DERIVED = [
    ('map/autochess', 'TX_autochessi_N', 'normal_rg', 'TX_autochessi_N_rgb'),
    ('map/autochess', 'TX_autochessi_M', 'rough_from_gloss', 'TX_autochessi_M_rough'),
]

# The board textures every player downloads when a match shows the 3D board (public/js/render/board3d/load.js
# PACK_IMAGES; D / common_D / BG also feed the 2D board art, render/boardArt.js): (output subdir, name, mode). A WebP
# copy is written next to the PNG and the manifest lists the copy instead (≈ 6.7 MB → 2.0 MB per cold start); the PNG
# stays for tools/crop-board-atlas.mjs and setup's check. 'lossy' = colour maps at quality 95 with the alpha lossless
# and the RGB under transparent texels kept (`exact`: the board material is opaque and samples it); 'lossless' =
# normal and data maps, whose channels hold independent values that lossy WebP's chroma subsampling would mix (a
# normal map ends up tens of degrees off). A Pillow without WebP support keeps the PNG.
WEBP = [
    ('map/autochess', 'TX_autochessi_D', 'lossy'),
    ('map/autochess', 'TX_autochessi_BG', 'lossy'),
    ('map/autochess', 'TX_autochessi_common_D', 'lossy'),
    ('map/autochess', 'TX_autochessi_N_rgb', 'lossless'),
    ('map/autochess', 'TX_autochessi_M_rough', 'lossless'),
    ('map/autochess', 'TX_autochessi_E', 'lossless'),
    ('map/autochess', 'TX_autochessi_common_E', 'lossless'),
    ('map/common', 'TX_wind_device', 'lossy'),
    ('map/fx', '[opt]merged_textures', 'lossless'),
    ('map/water', '[ucp]TX_water_normal', 'lossless'),
    ('map/water', 'TX_Caustics256', 'lossy'),
    ('map/water', 'T_noise_clouds_01', 'lossless'),
]
WEBP_OPTIONS = {
    'lossy': {'quality': 95, 'method': 6, 'alpha_quality': 100, 'exact': True},
    'lossless': {'lossless': True, 'quality': 100, 'method': 6, 'exact': True},
}

# The 19 玩法说明 pages (output subdir guide: 1024², opaque) get a WebP copy too — every page PNG of the group, each a
# 1.2–1.5 MB download whenever a player opens the guide (public/js/ui/guide.js shows the local page first and preloads
# the next one). Lossy quality 90, the maintainer's choice of 2026-10-12 after a side-by-side comparison at 2× (DESIGN
# §31.1, docs/history/0.2.6.md): 25.6 MB of PNG → 4.2 MB on the CN client's pages (lossless would be 17.4 MB);
# `extract.py --webp` rewrites the copies when GUIDE_WEBP_MODE changes. Method 4: method 6 spends about 8 s
# a page for 0.4 % less.
GUIDE_WEBP_SUB = 'guide'
GUIDE_WEBP_MODE = 'lossy'
GUIDE_WEBP_OPTIONS = {
    'lossless': {'lossless': True, 'quality': 100, 'method': 4, 'exact': True},
    'lossy': {'quality': 90, 'method': 4, 'alpha_quality': 100},
}

# Shader bundles loaded beside every job that exports Materials, only so that the materials' shader references
# (external CABs) resolve to a name in materials.json (e.g. Torappu/Scene/StandardDirectional); nothing is exported
# from them.
SHADER_DEPS = 'shaders/*.ab'
# the root shader bundle ([uc]shaders.ab) holds the Torappu particle shaders of the map effects (map/fx)
SHADER_DEPS_ROOT = '[uc]shaders.ab'

SAFE = re.compile(r'[^A-Za-z0-9_.\-\[\]]+')


def safe_name(name):
    name = SAFE.sub('_', name).strip('._') or 'unnamed'
    return name[:120]


def job_parts(job):
    """(rel, sub, kinds, keep) of a JOBS entry; keep is a compiled name filter or None."""
    rel, sub, kinds = job[:3]
    keep = re.compile(job[3]) if len(job) > 3 and job[3] else None
    return rel, sub, kinds, keep


def wants_sub(only, sub):
    """Whether output subdir `sub` runs under --only: no prefixes, or one prefix is `sub`, a parent of it or below it."""
    if not only:
        return True
    return any(sub == p.rstrip('/') or sub.startswith(p.rstrip('/') + '/') or p.rstrip('/').startswith(sub + '/')
               for p in only)


def select_jobs(only):
    """The jobs whose output subdir starts with one of the `only` prefixes (all jobs when `only` is empty)."""
    if not only:
        return list(JOBS)
    return [j for j in JOBS if any(j[1] == p.rstrip('/') or j[1].startswith(p.rstrip('/') + '/') for p in only)]


def enemy_spine_id(container, wanted):
    """The enemy id of an enemy SkeletonData container path (Assets/Torappu/Arts/Enemies/Spines/<dir>[/<n>]/<id>_
    SkeletonData.asset) when it is one of `wanted`, else None."""
    m = re.search(r'/Enemies/Spines/(?:[^/]+/)+([^/]+)_SkeletonData\.asset$', container or '', re.I)
    return m.group(1) if m and m.group(1) in wanted else None


def token_prefab_id(container, wanted):
    """The token id of a battle token prefab container path (dyn/battle/prefabs/[uc]tokens/<id>.prefab) when it is one
    of `wanted`, else None (a skin's prefab lives under battle/prefabs/skins/character/…)."""
    m = re.search(r'(?:^|/)battle/prefabs/(?:\[uc\])?tokens/([^/]+)\.prefab$', container or '', re.I)
    return m.group(1) if m and m.group(1) in wanted else None


def spine_ids(only, sub, ids):
    """The ids of a Spine model list (ENEMY_SPINES / TOKEN_SPINES, written to `<sub>/<id>`) that run under --only: all of
    them with no prefix, `sub` or a parent of it; else those whose output dir is a prefix or below one."""
    if not wants_sub(only, sub):
        return []
    if not only or any(sub == p.rstrip('/') or sub.startswith(p.rstrip('/') + '/') for p in only):
        return list(ids)
    return [i for i in ids if any(f'{sub}/{i}' == p.rstrip('/') or f'{sub}/{i}'.startswith(p.rstrip('/') + '/')
                                  for p in only)]


def skin_ids(only, stems):
    """The operator-skin stems that run: None = none selected, [] = the whole installed set, else only those named.

    `--skin <stem>` selects explicitly whatever `--only` says; without it the whole installed set runs when `--only`
    covers `spine/op` (or is empty), and nothing runs otherwise."""
    if stems:
        return list(stems)
    if not wants_sub(only, SKIN_SPINE_SUB):
        return None
    if not only or any(SKIN_SPINE_SUB == p.rstrip('/') or SKIN_SPINE_SUB.startswith(p.rstrip('/') + '/')
                       or p.rstrip('/').startswith(SKIN_SPINE_SUB + '/') for p in only):
        return []
    return None


def prefab_spine_nodes(root, objects):
    """The Spine renderers of a prefab, depth first: [(GameObject name, active, skeletonDataAsset PPtr)] for every
    MonoBehaviour holding a `skeletonDataAsset` (Spine's SkeletonAnimation). `root` is the root GameObject's type tree,
    `objects` the bundle's {path id: object}; references into other bundles are skipped."""
    out = []

    def local(pptr):
        return objects.get(pptr.get('m_PathID')) if pptr and not pptr.get('m_FileID') else None

    def walk(go, active, depth):
        tr, refs = None, []
        for c in go.get('m_Component') or []:
            o = local(c.get('component'))
            if o is None:
                continue
            try:
                if o.type.name == 'Transform':
                    tr = o.read_typetree()
                elif o.type.name == 'MonoBehaviour':
                    sda = o.read_typetree().get('skeletonDataAsset')
                    if sda and sda.get('m_PathID'):
                        refs.append(sda)
            except Exception:  # a script without a readable type tree is no Spine renderer we could use
                continue
        active = active and bool(go.get('m_IsActive', 1))
        out.extend((go.get('m_Name') or '', active, ref) for ref in refs)
        if tr is None or depth >= 12:
            return
        for ch in tr.get('m_Children') or []:
            t = local(ch)
            g = local(t.read_typetree().get('m_GameObject')) if t is not None else None
            if g is not None:
                walk(g.read_typetree(), active, depth + 1)

    walk(root, True, 0)
    return out


def pick_spine_node(nodes):
    """The renderer the remake draws among prefab_spine_nodes: of a directional token (a FaceSwitcher with Front / Back /
    Down renderers) the Front one, else one named Spine, else the first — active renderers first; None when empty."""
    live = [n for n in nodes if n[1]] or list(nodes)
    for want in ('Front', 'Spine'):
        hit = next((n for n in live if n[0] == want), None)
        if hit:
            return hit
    return live[0] if live else None


def _num(v, nd=6):
    """JSON-safe rounded float (NaN / inf → 0)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0
    return round(f, nd) + 0.0 if f == f and abs(f) != float('inf') else 0  # + 0.0: no '-0.0'


def vec(v, keys='xyz'):
    """[x, y, z(, w)] of a UnityPy vector / quaternion (missing components → 0)."""
    return [_num(getattr(v, k, 0)) for k in keys]


def _pptr_name(pptr):
    """Name of the object a PPtr points to, or None (null pointer or an unloaded external bundle)."""
    try:
        if not getattr(pptr, 'm_PathID', 0):
            return None
        return getattr(pptr.read(), 'm_Name', None) or None
    except Exception:  # external dependency not loaded, unsupported type, …
        return None


def material_info(mat):
    """JSON summary of a Material: shader, keywords, textures (by name, with tiling), floats and colours."""
    shader = None
    try:
        sh = mat.m_Shader.read()
        shader = getattr(getattr(sh, 'm_ParsedForm', None), 'm_Name', None) or getattr(sh, 'm_Name', None)
    except Exception:
        shader = None
    props = getattr(mat, 'm_SavedProperties', None)
    textures, floats, colors = {}, {}, {}
    for k, env in (getattr(props, 'm_TexEnvs', None) or []):
        name = _pptr_name(env.m_Texture)
        if name:
            textures[k] = {'texture': name, 'scale': vec(env.m_Scale, 'xy'), 'offset': vec(env.m_Offset, 'xy')}
    for k, v in (getattr(props, 'm_Floats', None) or []):
        floats[k] = _num(v)
    for k, c in (getattr(props, 'm_Colors', None) or []):
        colors[k] = vec(c, 'rgba')
    kw = getattr(mat, 'm_ValidKeywords', None) or getattr(mat, 'm_ShaderKeywords', None) or []
    if isinstance(kw, str):
        kw = kw.split()
    return {'shader': shader, 'keywords': sorted(kw), 'textures': dict(sorted(textures.items())),
            'floats': dict(sorted(floats.items())), 'colors': dict(sorted(colors.items()))}


def prefab_node(go, mesh_keys=None):
    """JSON summary of a GameObject: local transform (Unity space), parent, mesh and material names. `mesh_keys`
    ({mesh path id: manifest key}) names the exported OBJ when two meshes of a bundle share a name."""
    node = {'name': getattr(go, 'm_Name', '') or '', 'parent': None, 'pos': [0, 0, 0], 'rot': [0, 0, 0, 1],
            'scale': [1, 1, 1], 'mesh': None, 'materials': []}
    for c in getattr(go, 'm_Component', None) or []:
        pptr = getattr(c, 'component', c)
        try:
            comp = pptr.read()
        except Exception:
            continue
        kind = type(comp).__name__
        if kind in ('Transform', 'RectTransform'):
            node['pos'] = vec(comp.m_LocalPosition)
            node['rot'] = vec(comp.m_LocalRotation, 'xyzw')
            node['scale'] = vec(comp.m_LocalScale)
            try:
                father = comp.m_Father.read() if getattr(comp.m_Father, 'm_PathID', 0) else None
                node['parent'] = father.m_GameObject.read().m_Name if father else None
            except Exception:
                node['parent'] = None
        elif kind == 'MeshFilter':
            node['mesh'] = _pptr_name(comp.m_Mesh)
            pid = getattr(comp.m_Mesh, 'm_PathID', 0)
            if mesh_keys and pid in mesh_keys and not getattr(comp.m_Mesh, 'm_FileID', 0):
                node['mesh'] = mesh_keys[pid]
        elif kind in ('MeshRenderer', 'SkinnedMeshRenderer'):
            node['materials'] = [_pptr_name(m) for m in getattr(comp, 'm_Materials', None) or []]
    return node


def dep_bundles(ab_root, kinds):
    """Bundles to load next to a job so its references resolve: the shader bundles when it exports Materials."""
    if 'Material' not in kinds:
        return []
    root = Path(ab_root)
    extra = [root / SHADER_DEPS_ROOT] if (root / SHADER_DEPS_ROOT).is_file() else []
    return sorted(p for p in root.glob(SHADER_DEPS) if p.is_file()) + extra


_NORMAL_Z = None


def _normal_z_table():
    """Z byte of a unit normal for every (x byte, y byte) pair: 128 + 127·sqrt(max(0, 1 − x² − y²))."""
    global _NORMAL_Z
    if _NORMAL_Z is None:
        t = bytearray(65536)
        for xb in range(256):
            x = xb / 127.5 - 1.0
            for yb in range(256):
                y = yb / 127.5 - 1.0
                z = max(0.0, 1.0 - x * x - y * y) ** 0.5
                t[(xb << 8) | yb] = min(255, int(round(127.5 + 127.5 * z)))
        _NORMAL_Z = bytes(t)
    return _NORMAL_Z


def derive_normal_rg(img):
    """RGB tangent-space normal map from Unity's two-channel one: Z rebuilt per pixel. X and Y are read the way Unity's
    shaders unpack them (UnityCG.cginc UnpackNormalmapRGorAG: x = R · A, y = G), which covers both layouts a client
    build holds: BC5 (R = X, G = Y, B unused, no alpha → A = 1) and DXT5nm (R = 1, G = Y, A = X — the map_autochess
    bundle before the client update of 2026-10)."""
    from PIL import Image, ImageChops
    r, g, _, a = img.convert('RGBA').split()
    x = ImageChops.multiply(r, a)  # exact when either factor is 255
    table = _normal_z_table()
    z = bytes(table[(xb << 8) | yb] for xb, yb in zip(x.tobytes(), g.tobytes()))
    return Image.merge('RGB', (x, g, Image.frombytes('L', img.size, z)))


def derive_rough_from_gloss(img):
    """three.js roughness / metalness map (G = 1 − smoothness from Unity's A, B = metalness 0, R = 1) from a
    Unity metallic/gloss map."""
    from PIL import Image
    rgba = img.convert('RGBA')
    rough = rgba.getchannel('A').point(lambda v: 255 - v)
    return Image.merge('RGB', (Image.new('L', rgba.size, 255), rough, Image.new('L', rgba.size, 0)))


DERIVERS = {'normal_rg': derive_normal_rg, 'rough_from_gloss': derive_rough_from_gloss}


def run_derived(out_root, sub, manifest, log):
    """Write the DERIVED maps of output subdir `sub` (from its exported PNGs) and record them in the manifest."""
    from PIL import Image
    n = 0
    for dsub, src, kind, name in DERIVED:
        if dsub != sub:
            continue
        path = Path(out_root) / sub / f'{src}.png'
        if not path.exists():
            log(f'  derived {name}: source {src} missing')
            continue
        try:
            img = DERIVERS[kind](Image.open(path))
            img.save(Path(out_root) / sub / f'{name}.png')
        except Exception as e:  # a broken source only drops the derived map (the renderer falls back)
            log(f'  warn derived {name}: {e}')
            continue
        manifest.setdefault(sub, {})[name] = {'path': asset_url(*sub.split('/'), f'{name}.png'), 'w': img.width, 'h': img.height,
                                              'kind': 'Derived', 'from': src, 'derive': kind}
        n += 1
    return n


def webp_targets(sub, manifest):
    """(name, mode, Pillow options) of every WebP copy output subdir `sub` gets: its WEBP rows and, for the guide, each
    page of the group (an image entry: its path ends in .png, or in .webp after an earlier run)."""
    out = [(name, mode, WEBP_OPTIONS[mode]) for wsub, name, mode in WEBP if wsub == sub]
    if sub == GUIDE_WEBP_SUB:
        out += [(name, GUIDE_WEBP_MODE, GUIDE_WEBP_OPTIONS[GUIDE_WEBP_MODE])
                for name, entry in sorted(manifest.get(sub, {}).items())
                if isinstance(entry, dict) and str(entry.get('path', '')).endswith(('.png', '.webp'))]
    return out


def run_webp(out_root, sub, manifest, log):
    """Write the WebP copies of output subdir `sub` from its PNGs and point their manifest entries at them."""
    n = 0
    for name, mode, options in webp_targets(sub, manifest):
        entry = manifest.get(sub, {}).get(name)
        png = Path(out_root) / sub / f'{name}.png'
        if not entry or not png.exists():
            continue
        dst = png.with_name(f'{name}.webp')
        try:
            from PIL import Image
            with Image.open(png) as img:
                img.save(dst, 'WEBP', **options)
        except Exception as e:  # no WebP support in this Pillow, or a broken PNG: the entry keeps the PNG
            log(f'  warn webp {name}: {e}')
            continue
        entry.update(path=asset_url(*sub.split('/'), dst.name), webp=mode)
        n += 1
    return n


def webp_only(out_root, manifest_path, log):
    """--webp: the WEBP copies of an existing extraction (e.g. the local art copied from a release bundle)."""
    try:
        doc = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        print(f'No readable manifest at {manifest_path} ({e}). Extract the local art first.', file=sys.stderr)
        return 2
    groups = doc.get('groups') if isinstance(doc, dict) else None
    if not isinstance(groups, dict):
        print(f'{manifest_path} has no groups. Extract the local art first.', file=sys.stderr)
        return 2
    n = sum(run_webp(out_root, sub, groups, log) for sub in dict.fromkeys([*(s for s, _, _ in WEBP), GUIDE_WEBP_SUB]))
    Path(manifest_path).write_text(json.dumps(doc, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    log(f'done: {n} WebP copies, manifest {manifest_path}')
    return 0 if n else 1


def merge_manifest(old_groups, new_groups, ran_subs):
    """Groups of the previous manifest minus the subdirs that were re-extracted, plus the new ones (sorted keys)."""
    out = {g: v for g, v in (old_groups or {}).items() if g not in ran_subs}
    out.update(new_groups)
    return {g: dict(sorted(out[g].items())) for g in sorted(out)}


def export_bundle(ab_root, job, out_root, manifest, log):
    import aklz4  # noqa: F401  (registers the LZ4AK decoder)
    import UnityPy
    rel, sub, kinds, keep = job_parts(job)
    src = ab_root / rel
    if not src.exists():
        log(f'skip (missing) {rel}')
        return 0
    try:
        env = UnityPy.load(str(src))
    except Exception as e:  # corrupt or unsupported bundle: report and continue
        log(f'FAIL load {rel}: {e}')
        return 0
    objects = list(env.objects)  # the job's own objects, listed before any dependency joins the environment
    for dep in dep_bundles(ab_root, kinds):
        try:
            env.load_file(str(dep))
        except Exception as e:  # a missing shader only leaves that material's shader name null
            log(f'  warn dependency {dep.name}: {e}')
    out_dir = out_root / sub
    out_dir.mkdir(parents=True, exist_ok=True)
    seen, n = set(), 0
    materials, prefab, gos, mesh_keys = {}, [], [], {}
    for obj in objects:
        t = obj.type.name
        if t not in kinds:
            continue
        try:
            data = obj.read()
            raw_name = getattr(data, 'm_Name', '') or ''
            if keep is not None and not keep.search(raw_name):
                continue
            name = safe_name(raw_name or f'obj_{obj.path_id}')
            if t in ('Sprite', 'Texture2D'):
                img = data.image
                if img is None or img.width < 2 or img.height < 2:
                    continue
                fname = name + '.png'
                if fname in seen:  # same name twice: a Sprite (true aspect) beats its padded Texture2D
                    if t == 'Texture2D' or manifest.get(sub, {}).get(name, {}).get('kind') == 'Sprite':
                        continue
                img.save(out_dir / fname)
                seen.add(fname)
                manifest.setdefault(sub, {})[name] = {
                    'path': asset_url(*sub.split('/'), fname), 'w': img.width, 'h': img.height, 'kind': t}
                n += 1
            elif t == 'TextAsset':
                raw = data.m_Script
                blob = raw.encode('utf-8', 'surrogateescape') if isinstance(raw, str) else bytes(raw)
                if name.endswith('.atlas') or name.endswith('.skel'):
                    fname = name
                elif blob[:1] in (b'\n', b'') or b'size:' in blob[:200]:
                    fname = name + '.atlas'
                else:
                    fname = name + '.skel'
                (out_dir / fname).write_bytes(blob)
                manifest.setdefault(sub, {})[fname] = {'path': asset_url(*sub.split('/'), fname), 'kind': t}
                n += 1
            elif t == 'Mesh':
                text = data.export()
                if not text or 'v ' not in text:
                    continue
                fname = name + '.obj'
                if fname in seen:
                    name, fname = f'{name}_{obj.path_id}', f'{name}_{obj.path_id}.obj'
                (out_dir / fname).write_text(text, encoding='utf-8')
                seen.add(fname)
                verts = sum(1 for line in text.splitlines() if line.startswith('v '))
                manifest.setdefault(sub, {})[name] = {'path': asset_url(*sub.split('/'), fname), 'kind': 'Mesh', 'verts': verts}
                mesh_keys[obj.path_id] = name
                n += 1
            elif t == 'Material':
                materials[raw_name or name] = material_info(data)
            elif t == 'GameObject':
                gos.append(data)  # summarised after every mesh got its manifest key
        except Exception as e:
            log(f'  warn {rel} #{obj.path_id}: {e}')
    for go in gos:
        try:
            prefab.append(prefab_node(go, mesh_keys))
        except Exception as e:
            log(f'  warn {rel} GameObject: {e}')
    for key, fname, payload in (('materials', 'materials.json', materials), ('prefab', 'prefab.json', prefab)):
        if not payload:
            continue
        if isinstance(payload, list):
            payload = sorted(payload, key=lambda nd: (nd['parent'] or '', nd['name']))
        else:
            payload = dict(sorted(payload.items()))
        (out_dir / fname).write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        manifest.setdefault(sub, {})[key] = {'path': asset_url(*sub.split('/'), fname), 'kind': key.capitalize(), 'count': len(payload)}
        n += 1
    n += run_derived(out_root, sub, manifest, log)
    log(f'{rel}: {n} files -> {sub}')
    k = run_webp(out_root, sub, manifest, log)
    if k:
        log(f'  {k} WebP copies -> {sub}')
    return n


def _text_bytes(text_asset):
    raw = text_asset.m_Script
    return raw.encode('utf-8', 'surrogateescape') if isinstance(raw, str) else bytes(raw)


def merge_alpha(rgb, alpha):
    """Straight RGBA page of a Spine atlas texture: the main texture's RGB unchanged, A from its [alpha] texture (the
    split pages: _UseAlphaTex 1), else the main texture's own alpha (the newer RGBA pages: _UseAlphaTex 0).

    Straight, like the pages tools/fetch-assets.mjs serves: PIXI premultiplies once on upload (ALPHA_MODES.UNPACK),
    while `pma: true` in the atlas makes pixi-spine treat the page as premultiplied already. A page whose data really is
    premultiplied has to be converted here (RGB × A) or kept with that field, never passed on as straight."""
    from PIL import Image
    r, g, b = rgb.convert('RGB').split()
    if alpha is not None:
        a = alpha.convert('L').resize(rgb.size)
    elif rgb.mode in ('RGBA', 'LA', 'PA') or 'transparency' in rgb.info:
        a = rgb.convert('RGBA').getchannel('A')
    else:
        a = Image.new('L', rgb.size, 255)
    return Image.merge('RGBA', (r, g, b, a))


def _is_page_line(lines, i):
    """Whether line i of a Spine atlas starts a page: a page name is an unindented line without ':' that comes first
    or after a blank line (a region name follows its page's or the previous region's fields)."""
    line = lines[i]
    return bool(line.strip()) and ':' not in line and not line[:1].isspace() and (i == 0 or not lines[i - 1].strip())


def atlas_pages(text):
    """The page names (image files) of a Spine atlas text, in order."""
    lines = text.replace('\r\n', '\n').replace('\r', '\n').lstrip('\ufeff').split('\n')
    return [lines[i].strip() for i in range(len(lines)) if _is_page_line(lines, i)]


def normalize_atlas(text, sizes):
    """Spine atlas text with every page header carrying its real `size: w,h` (`sizes`: page name → (w, h)) and no `pma`
    field: merge_alpha writes straight pages, and the literal `pma: true` is what makes pixi-spine skip premultiplying a
    page on upload, so the field has to match the data. Page fields are the unindented `key: value` lines right after a
    page name (a line after a blank line, or the first line); everything else is kept."""
    lines = text.replace('\r\n', '\n').replace('\r', '\n').lstrip('\ufeff').split('\n')
    out, i, n = [], 0, len(lines)
    while i < n:
        line = lines[i]
        if not _is_page_line(lines, i):
            out.append(line)
            i += 1
            continue
        name = line.strip()
        fields, j = [], i + 1
        while j < n and lines[j].strip() and not lines[j][:1].isspace() and ':' in lines[j]:
            fields.append(lines[j])
            j += 1
        fields = [f for f in fields if f.split(':', 1)[0].strip() != 'pma']
        keys = [f.split(':', 1)[0].strip() for f in fields]
        size = sizes.get(name)
        if size:
            sz = f'size: {size[0]},{size[1]}'
            if 'size' in keys:
                fields[keys.index('size')] = sz
            else:
                fields.insert(0, sz)
        out.append(line)
        out.extend(fields)
        i = j
    return '\n'.join(out)


def page_filename(name):
    """A page file name that is safe in a URL. The client names a skin page `<charId>_<series>#<n>.png`, and the page
    name is the one string this project cannot percent-encode: pixi-spine reads it out of the .atlas text and resolves it
    against the atlas URL itself (the `textures` of the manifest are never consulted), so a bare `#` reaches the loader,
    which strips everything from `#` on before it picks a parser — the URL left (`..._epoque`) has no `.png`, no image
    parser matches it, `load()` resolves null and no request is even made; pixi-spine then reads `.baseTexture` of that
    null and the whole model fails. `?` (a query) and `%` (an escape) break a page URL the same way, so they map too.
    The `#` becomes `_`, which is the stem the .skel/.atlas of the same model already use."""
    return re.sub(r'[#?%]', '_', name)


def url_safe_atlas(atlas, pages):
    """The atlas text and its `page name → image` map with every page name made URL-safe (page_filename). The two must
    change together: the client resolves a page by the name the atlas gives it, so a renamed file with an unrenamed page
    line (or the reverse) 404s. Returns (text, pages)."""
    lines = atlas.replace('\r\n', '\n').replace('\r', '\n').lstrip('\ufeff').split('\n')
    out = [page_filename(line.strip()) if _is_page_line(lines, i) else line for i, line in enumerate(lines)]
    return '\n'.join(out), {page_filename(p): img for p, img in pages.items()}


def write_spine(objects, sda, sub, name, out_root, manifest, log):
    """Write one Spine model of a SkeletonDataAsset type tree — its skeleton TextAsset, its atlas TextAsset(s) (sized,
    `pma` dropped: normalize_atlas) and the page textures of the atlas materials (_MainTex with its _AlphaTex merged in,
    straight: merge_alpha) — to <out_root>/<sub>/ as <stem>.skel, <stem>.atlas (one stem: pixi-spine finds the atlas by the
    skeleton's name) and <page>.png, and list them in the manifest group `sub`. Returns the file count; 0 when a part
    is missing or the textures do not match the atlas pages (nothing is written then). `name` labels the log lines and
    names a skeleton without a name."""
    get = lambda pptr: objects.get(pptr['m_PathID']) if pptr and not pptr.get('m_FileID') else None  # noqa: E731
    skel = get(sda.get('skeletonJSON'))
    if skel is None:
        log(f'  warn {name}: skeleton TextAsset not in this bundle')
        return 0
    ta = skel.read()
    stem = safe_name(getattr(ta, 'm_Name', '') or name).removesuffix('.skel')
    texts, pages = [], {}
    for aref in sda.get('atlasAssets') or []:
        aa = get(aref)
        if aa is None:
            continue
        at = aa.read_typetree()
        af = get(at.get('atlasFile'))
        if af is not None:
            texts.append(_text_bytes(af.read()).decode('utf-8', 'replace'))
        for mref in at.get('materials') or []:
            mo = get(mref)
            if mo is None:
                continue
            props = mo.read_typetree()['m_SavedProperties']
            texs = dict(props['m_TexEnvs'])
            main, alpha = get(texs.get('_MainTex', {}).get('m_Texture')), get(texs.get('_AlphaTex', {}).get('m_Texture'))
            if main is None:
                continue
            mt = main.read()
            pages[safe_name(mt.m_Name) + '.png'] = merge_alpha(mt.image, alpha.read().image if alpha is not None else None)
    if not texts or not pages:
        log(f'  warn {name}: atlas or page textures missing')
        return 0
    atlas = texts[0] if len(texts) == 1 else '\n\n'.join(t.strip('\n') for t in texts) + '\n'
    atlas, pages = url_safe_atlas(atlas, pages)  # a `#` in a page name would never survive a URL (page_filename)
    names = atlas_pages(atlas)
    if set(names) != set(pages):
        if len(names) != 1 or len(pages) != 1:
            log(f'  warn {name}: atlas pages {names} do not match the textures {sorted(pages)}')
            return 0
        pages = {names[0]: next(iter(pages.values()))}  # one page under another name: saved as the atlas names it
    files = {f'{stem}.skel': _text_bytes(ta),
             f'{stem}.atlas': normalize_atlas(atlas, {p: img.size for p, img in pages.items()}).encode('utf-8')}
    out_dir = Path(out_root) / sub
    out_dir.mkdir(parents=True, exist_ok=True)
    segs = sub.split('/')
    for fname, blob in files.items():
        (out_dir / fname).write_bytes(blob)
        manifest.setdefault(sub, {})[fname] = {'path': asset_url(*segs, fname), 'kind': 'TextAsset'}
    for fname, img in pages.items():
        img.save(out_dir / fname)
        manifest.setdefault(sub, {})[fname] = {'path': asset_url(*segs, fname), 'w': img.width, 'h': img.height,
                                               'kind': 'Texture2D'}
    return len(files) + len(pages)


def scene_ids(only):
    """The stage ids of scenes.SCENES that run under --only (all with no prefix, `scene` or a parent of it)."""
    return spine_ids(only, scenes.SCENE_SUB, [sid for sid, _deps in scenes.SCENES])


def scene_roots(ab_root, extra):
    """AB roots searched for the scene bundles, in order: the client, --scenes dirs, then every version kept under
    .cache/official-scenes (newest name first)."""
    kept = ROOT / '.cache' / 'official-scenes'
    cached = sorted((p for p in kept.iterdir() if p.is_dir()), reverse=True) if kept.is_dir() else []
    return [Path(ab_root), *[Path(p) for p in extra], *cached]


def export_scenes(ab_root, out_root, manifest, log, ids, roots):
    """scenes.SCENES (the ids in `ids`) → scene/<stageId>/ (scenes.export_scene); a stage without a scene bundle in
    any root is skipped."""
    root = Path(ab_root)
    shader_deps = dep_bundles(root, {'Material'})
    n = 0
    for sid, deps in scenes.SCENES:
        if sid not in ids:
            continue
        src = scenes.find_scene(sid, roots)
        if src is None:
            log(f'skip (no scene bundle: off-season client, see --scenes) {scenes.scene_bundle(sid)}')
            continue
        try:
            n += scenes.export_scene(sid, deps, src, root, out_root, manifest, log, material_info, shader_deps)
        except Exception as e:  # one broken scene must not stop the others
            log(f'FAIL scene {sid}: {e}')
    return n


def export_enemy_spines(ab_root, out_root, manifest, log, ids=None):
    """ENEMY_SPINES (or `ids`) from the enemy art bundles (each bundle loaded on its own; stops once every model was
    found)."""
    import aklz4  # noqa: F401  (registers the LZ4AK decoder)
    import UnityPy
    wanted, n = set(ENEMY_SPINES if ids is None else ids), 0
    for f in sorted(Path(ab_root).glob(ENEMY_ART)):
        if not wanted:
            break
        try:
            env = UnityPy.load(str(f))
        except Exception as e:  # corrupt or unsupported bundle: report and continue
            log(f'FAIL load {f.name}: {e}')
            continue
        objects = {o.path_id: o for o in env.objects}
        for name, ref in env.container.items():
            eid = enemy_spine_id(name, wanted)
            if not eid:
                continue
            try:
                k = write_spine(objects, ref.read_typetree(), f'{ENEMY_SPINE_SUB}/{eid}', eid, out_root, manifest, log)
            except Exception as e:
                log(f'  warn {eid}: {e}')
                continue
            if k:
                wanted.discard(eid)
                n += k
                log(f'{f.relative_to(ab_root).as_posix()}: {eid} -> {ENEMY_SPINE_SUB}/{eid} ({k} files)')
    for eid in sorted(wanted):
        log(f'skip (not found) enemy Spine {eid}')
    return n


def export_token_spines(ab_root, out_root, manifest, log, ids=None):
    """TOKEN_SPINES (or `ids`) from the battle token packs: each token's prefab → the SkeletonDataAsset its Front / only
    Spine renderer draws (pick_spine_node) → write_spine. Each pack is loaded on its own; stops once every model was
    found."""
    import aklz4  # noqa: F401  (registers the LZ4AK decoder)
    import UnityPy
    wanted, n = set(TOKEN_SPINES if ids is None else ids), 0
    for f in sorted(Path(ab_root).glob(TOKEN_PACKS)):
        if not wanted:
            break
        try:
            env = UnityPy.load(str(f))
        except Exception as e:  # corrupt or unsupported bundle: report and continue
            log(f'FAIL load {f.name}: {e}')
            continue
        objects = {o.path_id: o for o in env.objects}
        for name, ref in env.container.items():
            tid = token_prefab_id(name, wanted)
            if not tid:
                continue
            sub = f'{TOKEN_SPINE_SUB}/{tid}'
            try:
                node = pick_spine_node(prefab_spine_nodes(ref.read_typetree(), objects))
                sda = objects.get(node[2]['m_PathID']) if node and not node[2].get('m_FileID') else None
                if sda is None:
                    log(f'  warn {tid}: its prefab has no Spine renderer in this bundle')
                    continue
                k = write_spine(objects, sda.read_typetree(), sub, tid, out_root, manifest, log)
            except Exception as e:
                log(f'  warn {tid}: {e}')
                continue
            if k:
                wanted.discard(tid)
                n += k
                log(f'{f.relative_to(ab_root).as_posix()}: {tid} ({node[0]}) -> {sub} ({k} files)')
    for tid in sorted(wanted):
        log(f'skip (not found) token Spine {tid}')
    return n


# ---------------------------------------------------------------------------------------------------
# Operator skins (docs/SKINS.md): the local client is the authoritative source, so a skin's battle
# model can be taken from the installed game instead of the fexli mirror.
#
# The client keeps one bundle per operator under skinpack/<charId>.ab holding EVERY skin of that
# operator, and three models per skin — told apart by the skeleton's own name and its page texture:
#   char_<charId>_<series>#<n>       battle chibi, the model the remake draws (512×512 or smaller)
#   build_char_<charId>_<series>#<n> the base/dormitory chibi (own name prefix, larger page)
#   char_<charId>_<series>#<n>b      the dynamic illustration (name suffix `b`, up to 2048×2048)
# A skin has two battle chibis of the same stem (Front and Back — the facing variants) sharing one page
# texture, which is written once and listed in both.
# ---------------------------------------------------------------------------------------------------
SKIN_PACK = 'skinpack/{}' + '.ab'
SKIN_SPINE_SUB = 'spine/op'


def skin_stem_of(skel_name):
    """The skin stem of a battle-chibi skeleton name, or None for the build / illustration variants."""
    if not skel_name.endswith('.skel'):
        return None
    stem = skel_name[:-len('.skel')]
    if stem.startswith('build_') or stem.endswith('b'):
        return None
    return stem


def standing_page(tt, objects):
    """The largest atlas page a SkeletonDataAsset draws from, or 0 when it cannot be read.

    This is what tells a battle chibi from the two kinds of skeleton that share its file name in the same bundle:
    a STANDING chibi is drawn from a 300-600 px page, while a `build_` display model and the dynamic-illustration
    skeleton use 592-1124 px pages. The distinction is load-bearing — see facings_of.
    """
    best = 0
    for ref in (tt.get('atlasAssets') or []):
        ao = _pptr_obj(objects, ref)
        if ao is None:
            continue
        try:
            att = ao.read_typetree()
        except Exception:
            continue
        for mref in (att.get('materials') or []):
            mo = _pptr_obj(objects, mref)
            if mo is None:
                continue
            try:
                mtt = mo.read_typetree()
            except Exception:
                continue
            props = mtt.get('m_SavedProperties') or {}
            for pair in (props.get('m_TexEnvs') or []):
                # UnityPy hands m_TexEnvs over as (name, value) tuples, not dicts
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    continue
                if pair[0] != '_MainTex':
                    continue
                val = pair[1] or {}
                to = _pptr_obj(objects, val.get('m_Texture') or {})
                if to is None:
                    continue
                try:
                    best = max(best, int(getattr(to.read(), 'm_Width', 0) or 0))
                except Exception:
                    pass
    return best


def facings_of(refs, log=None, skin_id=None, objects=None):
    """Which SkeletonDataAsset of a skin is its Front and which its Back, as `[('front', tt|None), ('back', tt|None)]`.

    Three kinds of skeleton share one file name inside a skinpack bundle — the standing chibi drawn in battle, a
    `build_...` display model, and occasionally a dynamic-illustration skeleton — so the choice cannot be made by name
    or by bundle order. Two rules, in order:

    1. A standing chibi draws from a 300-600 px page; `build_` and illustration skeletons use 592-1124 px pages.
       Taking the largest skeleton instead (the first version of this function) picked the ILLUSTRATION for
       char_1012_skadi2@boc#4, char_291_aglina@boc#1 and three others, which is why those five skins showed a
       picture where a chibi belongs and had no Back at all.
    2. Of the standing ones, the LARGER skeleton is the Front: the Back carries only the clips a standing, walking
       chibi needs, and in the web mirror the Back is the smaller of the pair for 167 of 169 skins.

    `refs` are `(typetree, skeleton TextAsset)` pairs, in bundle order. `objects` is the bundle's path_id → object
    map, needed to read the atlas pages; without it every candidate counts as standing and only rule 2 applies.
    """
    usable = [(tt, ta) for tt, ta in refs if tt is not None and ta is not None]
    if not usable:
        return [('front', None), ('back', None)]

    def size_of(ta):
        raw = getattr(ta, 'm_Script', None)
        if isinstance(raw, (bytes, bytearray)):
            return len(raw)
        if isinstance(raw, str):
            return len(raw.encode('utf-8', 'surrogateescape'))
        return 0

    standing = usable
    if objects is not None:
        kept = []
        for tt, ta in usable:
            w = standing_page(tt, objects)
            # an unreadable page keeps the candidate: dropping it would lose a skin rather than mis-order one
            if w == 0 or w <= 600:
                kept.append((tt, ta))
            elif log is not None:
                log(f'  note {skin_id}: skipped a {w} px display/illustration skeleton')
        if kept:
            standing = kept

    if len(standing) == 1:
        # the client ships a single standing chibi for this skin: it is the Front, and the renderer draws it for
        # both facings (there is no Back art to extract — 升华 / 红女爵 / 质素访客 / 夏卉 FA017 / 追悼)
        return [('front', standing[0][0]), ('back', None)]
    ordered = sorted(standing, key=lambda p: size_of(p[1]), reverse=True)
    if log is not None and size_of(ordered[0][1]) == size_of(ordered[1][1]):
        log(f'  warn {skin_id}: the two facings are the same size; the bundle order decides them')
    return [('front', ordered[0][0]), ('back', ordered[1][0])]


def export_skin_spines(ab_root, out_root, manifest, log, stems=None):
    """The battle chibi (Front + Back) of every skin listed in data/skins-installed.json, from the local client's
    skinpack/<charId>.ab. `stems` limits it to those stems (the `skins` job under --only). Output:
    spine/op/<charId>/<stem>/{front,back}/<stem>.skel|.atlas, the shared page at the skin root; the manifest groups are
    spine/op/<charId>/<stem>, the group data/assets.json chars[charId].skins[skinId].spineLocal names."""
    import aklz4  # noqa: F401  (registers the LZ4AK decoder)
    import UnityPy
    from UnityPy.helpers.MeshHelper import MeshHandler  # noqa: F401  (UnityPy needs it loaded for some types)

    plan = skin_plan()
    if not plan:
        log('skip skins: no data/skins-installed.json or docs/research/08-skins.json')
        return 0
    write_skin_index(plan, log)
    # the committed index is the authority on stem → skinId (the same mapping this plan was built from)
    index = load_skin_index() or {}
    if stems is not None:
        # `--skin <stem>`: exactly those, whenever the client has them (either the catalogue stem or the client's own)
        plan = {c: [s for s in v if s['stem'] in stems or s['client'] in stems] for c, v in plan.items()}
        plan = {c: v for c, v in plan.items() if v}
    n = 0
    for char_id in sorted(plan):
        bundle = Path(ab_root) / SKIN_PACK.format(char_id)
        if not bundle.exists():
            log(f'  skip {char_id}: {bundle.name} not in this client')
            continue
        try:
            env = UnityPy.load(str(bundle))
        except Exception as e:
            log(f'FAIL load {bundle.name}: {e}')
            continue
        objects = {o.path_id: o for o in env.objects}
        # the SkeletonDataAssets of this bundle, keyed by battle-chibi stem (Front and Back share a stem)
        found = {}
        for o in env.objects:
            if o.type.name != 'MonoBehaviour':
                continue
            try:
                tt = o.read_typetree()
            except Exception:
                continue
            if 'skeletonJSON' not in tt:
                continue
            skel_obj = _pptr_obj(objects, tt.get('skeletonJSON'))
            if skel_obj is None:
                continue
            try:
                skel_data = skel_obj.read()
                skel_name = str(getattr(skel_data, 'm_Name', '') or '')
            except Exception:
                continue
            stem = skin_stem_of(skel_name)
            if stem:
                # the TextAsset rides along: its length is what tells the two facings apart (facings_of)
                found.setdefault(stem, []).append((tt, skel_data))
        for entry in plan[char_id]:
            stem, skin_id = entry['stem'], entry['skinId']
            if index.get(stem) is not None:
                skin_id = index[stem]
            refs = found.get(entry['client']) or found.get(stem)
            if not refs:
                log(f'  warn {skin_id}: no battle chibi of stem {entry["client"]} in {bundle.name}')
                continue
            sub = f'{SKIN_SPINE_SUB}/{char_id}/{stem}'
            written = 0
            for tag, tt in facings_of(refs, log, skin_id, objects):
                if tt is None:
                    continue
                k = write_spine(objects, tt, f'{sub}/{tag}', skin_id, out_root, manifest, log)
                if not k:
                    continue
                written += k
                # one shared page texture: list only the first copy, the second points at it (the client resolves a
                # relative asset URL, render/spine.js). The PNG is written by whichever variant ran first.
                group = manifest.get(f'{sub}/{tag}') or {}
                if tag == 'back':
                    # both facings share the front's page file, so point the back entries at it
                    for fname in list(group):
                        if fname.endswith('.png'):
                            group[fname]['path'] = asset_url(*sub.split('/'), 'front', fname)
            if written:
                n += written
                log(f'{bundle.relative_to(ab_root).as_posix()}: {skin_id} -> {sub} ({written} files)')
    draw = write_skin_illustrations(ab_root, out_root, plan, manifest, log, stems)
    if draw:
        n += draw
    # avatars: the client's own bundles first, the mirror only for what this client lacks (normally nothing)
    avatars = extract_skin_avatars(ab_root, plan, log)
    avatars.update(fetch_missing_avatars(plan, log))
    # The 180×360 button art is NOT extracted here: the library's `portrait` tier owns it
    # (spritepack/char_portrait_<N>.ab → public/assets/local/library/opportrait/), covering every operator the client
    # ships rather than only the planned skins. `write_skin_manifest` reads its URL back off that index.
    # The metadata must be current BEFORE the manifest is written: a model it does not know is written without clips,
    # and the renderer holds those back (see the note below). run_skins_meta regenerates it from the files just written.
    run_skins_meta(log)
    write_skin_manifest(out_root, plan, manifest, log, stems, avatars, skin_portraits_from_library(plan, log))
    return n


def _pptr_obj(objects, pptr):
    """The object a PPtr points at within the same bundle (None for a cross-file or empty reference)."""
    if not pptr or pptr.get('m_FileID'):
        return None
    return objects.get(pptr.get('m_PathID'))


# Committed stem → skinId index (tools/assets/local-skin-index.json). The join between the client's model stems and the
# skin ids is mechanical, so the generator below derives it from 08-skins.json and the extractor writes it here. It sits
# beside tools/assets/local-enemy-spines.json and local-token-spines.json — the other committed metadata of local-client
# models — because the tooling that consumes it (tools/, not the shipped game) is the same audience. Deliberately NOT
# under docs/research/: that directory is the shipped research tables, and a `09-…json` name there would be read as one.
SKIN_INDEX = ROOT / 'tools/assets/local-skin-index.json'

# The client-side manifest of the extracted skin models (the local counterpart of chars[charId].skins in
# data/assets.json). data/skins-installed.json is the web downloader's list and cannot describe these: a skin the
# mirror has lost is never in it, which is the whole reason this source exists. The server reads it at /data/, so it
# lives under data/ and, like data/local-assets.json, holds machine-local names and is never committed.
SKIN_MANIFEST = ROOT / 'data/skins-local.json'

# Model metadata (anims / durations / bounds) of those same models, written by tools/local-skins-meta.mjs. The client's
# validSpine requires `anims`, so the manifest cannot carry a model without it; the parse needs the pixi-spine runtime,
# which lives in node_modules, so that part is Node's. It sits beside tools/assets/local-enemy-spines.json.
SKIN_META = ROOT / 'tools/assets/local-skins-meta.json'

# The 180×180 head icons: spritepack/ui_char_avatar_<N>.ab, 19 bundles, 121 icons each (the last holds 24). The
# bundling manifest arts/charavatars/avatar_hub.ab names the packing tag `UI_CHAR_AVATAR` — that is the bundle stem —
# declares the standard size 180×180 and lists each id twice (as the sprite name and as `Arts/CharAvatars/[Skins|Elite]/<id>`).
# Every planned skin is in there, so the avatar needs no network either.
AVATAR_PACKS = 'spritepack/ui_char_avatar_*.ab'
AVATAR_DIR = 'char/avatar/skin'

# The 180×360 skin button art (the "big icon" a skin is chosen by) is the LIBRARY's `portrait` tier — see LIBRARY_PORTRAIT
# below, which owns the bundle glob and the packing manifest. It is one family at one fixed size and covers every
# operator the client ships, including the default appearance (`<charId>_1` E0/E1, `_2` E2). The alternative,
# spritepack/arts_shop_skin_portrait_*.ab at 292×552, is a fixed size too but holds only 164 of this mode's 174 skins:
# the shop gallery never received ten event and collab skins (`@kfc#1`, `@wwf#1`, `@daily#1`, `@race#1`, `@shining#1` …).
# A census of the whole client — all 13,163 bundles, 104,711 Texture2D — found exactly 443 textures at 292×552, so
# mixing the two would mean a gallery of two shapes with a hole in it. One family, one size.

# ---- the operator image library (docs/SKINS.md) ------------------------------------------------------------------
# Every operator's art in the client, extracted ONCE for the whole client rather than only for the skins the mode
# happens to catalogue. That matters because the catalogue is a hand-maintained research table of 174 skins while the
# client holds 529, and the 自选编队 pool draws on operators outside the mode's 121-operator roster (煌, 陈 …), whose
# skins the catalogue never listed — the extractor could not see art it had no id for. Scanning the client answers
# "which skins exist" without any table.
#
# Three tiers, matching the three families the client packs by packing tag (arts/*/*_hub.ab `_rootPackingTag`):
#
#   LIBRARY = (
#     (stem, dir, hub, bundle glob, id keys, size),
#   )
#
# `id keys` are the manifest fields that name a packed asset. char_portrait covers BOTH the default appearance
# (`<charId>_1` E0/E1, `_2` E2) and every skin at one fixed 180×360 — the same bust crop the 292×552 shop gallery uses
# but complete (174/174 of the mode's skins against the gallery's 164) and uniform, which is what makes it the button
# art (public/css/screens/loadout.css).
LIBRARY_AVATAR = ('avatar', 'opavatar', 'arts/charavatars/avatar_hub.ab', 'spritepack/ui_char_avatar_*.ab',
                  ('avatarId',), '180x180')
LIBRARY_PORTRAIT = ('portrait', 'opportrait', 'arts/charportraits/portraits_hub.ab', 'spritepack/char_portrait_*.ab',
                    ('portraitId', 'spAvatarId'), '180x360')
# The illustration is NOT packed by a hub: it lives in skinpack/<charId>.ab next to the skin's Spine model, as
# `<clientStem>b` (static, 1024–1416 px) and `<clientStem>` (the dynamic page, 2200–2508 px, deliberately skipped).
#
# `spIllustId` is read with `illustId` because it is the same skin's SECOND illustration (the official table gives one
# to 4 skins: 克洛丝 星月漂流记, 凯尔希 时遗, 阿米娅 于万千宇宙之中, 新约能天使 寻翼之歌) — the picker shows both. Its
# page is listed under `<skinId>_sp` (`SP_ILLUSTR_SUFFIX`): the library index is a listing of the client's art, but that
# entry is NOT a skin — client_skin_plan skips it and the catalogue folds it into the skin it belongs to (docs/SKINS.md).
LIBRARY_ILLUST = ('illust', 'opillust', 'skinpack/<charId>.ab', None, ('illustId', 'spIllustId'), 'variable')
LIBRARIES = (LIBRARY_AVATAR, LIBRARY_PORTRAIT, LIBRARY_ILLUST)
# The suffix that marks a second illustration rather than a skin of its own (the same constant in
# tools/skin-library/build-catalogue.mjs and public/js/ui/skins.js).
SP_ILLUSTR_SUFFIX = '_sp'
LIBRARY_ROOT = 'library'
# The library's own folder: everything this extractor writes for the operator image library lands under
# tools/skin-library/ (the index below, plus the generators added alongside it).
SKIN_LIBRARY_DIR = ROOT / 'tools/skin-library'
LIBRARY_INDEX = SKIN_LIBRARY_DIR / 'library-index.json'
# The copy the CLIENT reads: the static server only mounts /data/, so the index is written there too and
# data/library-index.json is git-ignored like the other machine-local manifests (data/local-assets.json,
# data/skins-local.json). tools/skin-library/library-index.json is the committed one, so a server without a client can
# still build the catalogue from it (tools/skin-library/build-catalogue.mjs).
LIBRARY_DATA_FILE = ROOT / 'data/library-index.json'







def skin_portraits_from_library(plan, log):
    """{skinId: 180×360 portrait URL} for the planned skins, read off the library index the `library` job wrote.

    The library's `portrait` tier (spritepack/char_portrait_<N>.ab) is the only portrait source: one family, one fixed
    180×360 size, and it covers every operator the client ships — the 292×552 shop gallery holds only 164 of the 174
    and does not exist for the rest, so mixing the two would give a gallery of two shapes with a hole in it. Returns {}
    when the library has not been extracted yet, and the manifest simply carries no portrait for those skins."""
    try:
        tiers = json.loads(LIBRARY_INDEX.read_text(encoding='utf-8')).get('tiers') or {}
    except (OSError, ValueError):
        log('  note: library index absent, so no portrait URLs (run extract.py --only library first)')
        return {}
    wanted = {e['client']: e['skinId'] for entries in plan.values() for e in entries}
    out = {}
    for asset_id, entry in (tiers.get('portrait') or {}).items():
        skin_id = entry.get('skinId')
        if skin_id and entry.get('path') and asset_id in wanted:
            out[skin_id] = entry['path']
    return out


def run_skins_meta(log):
    """Regenerate tools/assets/local-skins-meta.json from the models just written (the Node pass).

    `write_skin_manifest` needs it: the client's `validSpine()` requires the clips, so without metadata a skin is
    rejected by the renderer. Running it here is what keeps it current — before, nothing did: the script existed but
    no pipeline called it, so the file stayed at whatever an earlier manual run produced and every skin extracted
    afterwards was silently dropped from the manifest."""
    node = shutil.which('node')
    script = ROOT / 'tools/local-skins-meta.mjs'
    if not node or not script.exists():
        log('  warn node or tools/local-skins-meta.mjs unavailable; the manifest keeps its previous metadata')
        return False
    try:
        r = subprocess.run([node, str(script)], cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.SubprocessError) as e:
        log(f'  warn skins meta failed ({e})')
        return False
    if r.returncode != 0:
        log(f'  warn skins meta exited {r.returncode}: {(r.stderr or "").strip()[:200]}')
        return False
    log(f'  {(r.stdout or "").strip().splitlines()[0] if r.stdout else "skins meta ok"}')
    return True


def load_skin_meta():
    """{`<charId>/<stem>[/back]`: metadata} from tools/assets/local-skins-meta.json, or {}."""
    try:
        return json.loads(SKIN_META.read_text(encoding='utf-8')).get('models') or {}
    except (OSError, ValueError):
        return {}


def write_skin_manifest(out_root, plan, manifest, log, stems=None, avatars=None, portraits=None):
    """Write data/skins-local.json: { chars: { charId: { skins: { skinId: { name, group, spine } } } } } for the skins
    this run actually extracted (every file of the group present in `manifest`). Shape mirrors the web manifest's
    chars[charId].skins, so public/js/assets.js can fall back to it field by field."""
    local_root = Path(out_root)
    research = {}
    try:
        research = json.loads((ROOT / 'docs/research/08-skins.json').read_text(encoding='utf-8')).get('skins') or {}
    except (OSError, ValueError):
        pass
    meta = {}  # skinId -> {name, group}
    for entries in research.values():
        for s in entries:
            if s.get('skinId'):
                meta[s['skinId']] = {'name': s.get('name') or s['skinId'], 'group': s.get('group') or ''}
    # model metadata from the Node pass (tools/local-skins-meta.mjs), keyed `<charId>/<stem>[/back]`
    models = load_skin_meta()

    chars = {}
    avatars = avatars or {}
    portraits = portraits or {}
    for char_id in sorted(plan):
        for entry in plan[char_id]:
            skin_id, stem = entry['skinId'], entry['stem']
            if stems is not None and stem not in stems and entry['client'] not in stems:
                continue
            groups = {tag: f'{SKIN_SPINE_SUB}/{char_id}/{stem}/{tag}' for tag in ('front', 'back')}
            present = {tag: g for tag, g in groups.items() if manifest.get(g)}
            if not present:
                continue
            spine = {}
            for tag, g in present.items():
                files = manifest[g]
                skel = next((n for n in files if n.endswith('.skel')), None)
                atlas = next((n for n in files if n.endswith('.atlas')), None)
                pages = sorted(n for n in files if n.endswith('.png'))
                if not skel or not atlas or not pages:
                    continue
                # the group + file names LAST: tools/local-skins-meta.mjs keys its entries by absolute paths (it reads
                # them straight off disk), and only the names belong in a manifest whose group is the directory.
                # A model whose metadata is missing still gets an entry: `validSpine()` needs the clips, so the
                # renderer holds it back until run_skins_meta fills them in — but dropping the entry outright would
                # hide the skin from the picker, which is what a stale metadata file used to do.
                spine[tag] = {**(models.get(f'{char_id}/{stem}' + ('/back' if tag == 'back' else '')) or {}),
                              'group': g, 'skel': skel, 'atlas': atlas, 'textures': pages}
            if not spine:
                continue
            # `spine` carries the same front / back shape as chars[charId].spine in data/assets.json (the web
            # manifest), so the client can fall back to it field by field (public/js/assets.js spineEntry)
            spine = {'front': spine['front'], **({'back': spine['back']} if 'back' in spine else {})}
            m = meta.get(skin_id) or {}
            entry_out = {'name': m.get('name') or skin_id, 'group': m.get('group') or '', 'spine': spine}
            if avatars.get(skin_id):
                entry_out['avatar'] = avatars[skin_id]
            # the 292×552 button art (a fixed size, unlike the illustration) — present for most skins
            if portraits.get(skin_id):
                entry_out['portrait'] = portraits[skin_id]
            # the static illustration (write_skin_illustrations), for the picker's tile art and preview
            if manifest.get(f'{SKIN_SPINE_SUB}/{char_id}/{stem}', {}).get('illust.png'):
                entry_out['illust'] = asset_url(*f'{SKIN_SPINE_SUB}/{char_id}/{stem}'.split('/'), 'illust.png')
            chars.setdefault(char_id, {}).setdefault('skins', {})[skin_id] = entry_out
    doc = {'version': 1, 'source': 'local-client',
           'note': 'Operator skin models extracted from the local game client (tools/local-extract/extract.py `skins`); '
                   'the local counterpart of chars[charId].skins in data/assets.json. Never committed (game art).',
           'count': sum(len(v.get('skins') or {}) for v in chars.values()), 'chars': chars}
    SKIN_MANIFEST.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    log(f'wrote {SKIN_MANIFEST.relative_to(ROOT).as_posix()} ({doc["count"]} skins, {len(chars)} operators)')



def client_stem(skin_id):
    """The model stem the CLIENT uses for a skin: the skinId with `@` → `_` and `#` kept
    (`char_498_inside@kitchen#2` → `char_498_inside_kitchen#2`). docs/research/08-skins.json normalizes `#` to `_` too
    for URL-safe file names (`stem`), so a lookup from the bundle has to try this form first."""
    return skin_id.replace('@', '_')


def write_skin_index(plan, log):
    """Write tools/assets/local-skin-index.json: {version, counts, byStem: {stem: skinId}} for every skin of a playable
    chess. Deterministic — regenerating it from the same catalogue produces the same file."""
    by_stem = {}
    for entries in plan.values():
        for s in entries:
            by_stem[s['stem']] = s['skinId']
    doc = {'version': 1, 'counts': {'skins': len(by_stem), 'operators': len(plan)},
           'note': 'Local-client operator skins (tools/local-extract/extract.py `skins`): the stem → skinId mapping the '
                   'extractor writes to public/assets/local/spine/op/<charId>/<stem>/ and the build step reads to fill '
                   'chars[charId].skins[skinId].spineLocal (docs/SKINS.md). Derived from docs/research/08-skins.json — '
                   'the skins of the playable chess of data/chess.json.',
           'byStem': dict(sorted(by_stem.items()))}
    SKIN_INDEX.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    log(f'wrote {SKIN_INDEX.relative_to(ROOT).as_posix()} ({len(by_stem)} stems)')


def load_skin_index():
    """{stem: skinId} from the committed index, or None when it has not been generated yet."""
    try:
        return json.loads(SKIN_INDEX.read_text(encoding='utf-8')).get('byStem') or None
    except (OSError, ValueError):
        return None


def used_char_ids():
    """Every operator the project actually fields: the roster of `data/chess.json` plus the 自选编队 pool of
    `data/backups.json` (`diy.ownedPool` and `diy.prototypes`).

    The roster alone is not enough. The 自选编队 pool draws on operators outside it (煌, 陈, 凯尔希 …), and a catalogue
    built for the roster cannot see their skins — which is exactly why those operators offered only 默认 while the
    client had their art. tools/skin-library/used-operators.mjs computes the same set for the Node side."""
    ids = set()
    try:
        chess = json.loads((ROOT / 'data/chess.json').read_text(encoding='utf-8'))
        for v in chess.values():
            if isinstance(v, dict) and v.get('charId'):
                ids.add(v['charId'])
    except (OSError, ValueError) as e:
        print(f'warn: chess.json unreadable ({e})', file=sys.stderr)
    try:
        diy = (json.loads((ROOT / 'data/backups.json').read_text(encoding='utf-8')).get('diy') or {})
        ids.update(diy.get('ownedPool') or [])
        for group in (diy.get('prototypes') or {}).values():
            ids.update(group or [])
    except (OSError, ValueError) as e:
        print(f'warn: backups.json unreadable ({e})', file=sys.stderr)
    return ids


def client_skin_plan(used):
    """{charId: [{skinId, stem, client}]} for every skin the CLIENT holds for an operator in `used`.

    Read from the library index (tools/skin-library/library-index.json) rather than a catalogue: the client enumerates
    its own art, so a skin no research table lists is extracted all the same. The index carries `charId` and `skinId`
    on every entry, so no stem has to be parsed back into an id here.

    `stem` is the URL-safe form (`#` → `_`) the manifest groups use; `client` is the name the bundle itself uses.

    A `<skinId>_sp` entry is skipped: the official skin table gives a few skins TWO illustrations (`illustId` and the
    「sp」 差分立绘 `spIllustId` — 凯尔希 时遗, 新约能天使 寻翼之歌 here), and the `illust` tier lists the second page
    under that derived id. It is not a skin and has no model, so planning it only produced a model group holding
    nothing but an illust.png (docs/SKINS.md; tools/skin-library/build-catalogue.mjs folds it into `spIllust`)."""
    try:
        tiers = json.loads(LIBRARY_INDEX.read_text(encoding='utf-8')).get('tiers') or {}
    except (OSError, ValueError):
        return {}
    plan = {}
    for entry in (tiers.get('illust') or {}).values():
        skin_id, char_id = entry.get('skinId'), entry.get('charId')
        if not skin_id or not char_id or char_id not in used:
            continue
        if skin_id.endswith(SP_ILLUSTR_SUFFIX):
            continue
        plan.setdefault(char_id, []).append(
            {'skinId': skin_id, 'stem': skin_id.replace('@', '_').replace('#', '_'),
             'client': client_stem(skin_id)})
    for entries in plan.values():
        entries.sort(key=lambda e: e['skinId'])
    return plan


def skin_plan():
    """{charId: [{skinId, stem, client}]} for every skin to extract, from the client's own enumeration.

    Supersedes the research table as the source: docs/research/08-skins.json lists 174 skins on 115 of the operators
    the project fields, while the client holds 275 — the difference is the 自选编队 operators' skins, which had no model
    at all, so choosing one fell back to the operator's default chibi. The table is still consulted for one thing: the
    URL-safe `stem` it coined (`char_1012_skadi2@boc#4` → `char_1012_skadi2_boc_4`), because the committed
    tools/skin-library/skin-index.json and the directories extracted before this change use that form. A stem the table
    does not know gets the same rule applied directly."""
    used = used_char_ids()
    plan = client_skin_plan(used)
    if not plan:
        # no library yet (an older install): fall back to the research table, as before
        try:
            research = json.loads((ROOT / 'docs/research/08-skins.json').read_text(encoding='utf-8')).get('skins') or {}
        except (OSError, ValueError):
            return {}
        for char_id, entries in research.items():
            if char_id not in used:
                continue
            keep = [{'skinId': s['skinId'], 'stem': s['stem'], 'client': client_stem(s['skinId'])}
                    for s in entries if s.get('skinId') and s.get('stem')]
            if keep:
                plan[char_id] = keep
        return plan
    try:
        research = json.loads((ROOT / 'docs/research/08-skins.json').read_text(encoding='utf-8')).get('skins') or {}
        known = {s['skinId']: s['stem'] for entries in research.values() for s in entries if s.get('skinId')}
    except (OSError, ValueError):
        known = {}
    for entries in plan.values():
        for e in entries:
            if e['skinId'] in known:
                e['stem'] = known[e['skinId']]
    return plan


def fetch_missing_avatars(plan, log):
    """Last-resort network fallback for a skin avatar the CLIENT did not supply: download it from the URL
    docs/research/08-skins.json carries (the source tools/install-skins.mjs uses).

    Kept only for a client older than the avatar bundles, or one missing them. The normal path is
    extract_skin_avatars(): the 180×180 icons live in the client's spritepack/ui_char_avatar_<N>.ab, so nothing has to
    be fetched — this function's result is normally empty."""
    import urllib.request
    research = {}
    try:
        research = json.loads((ROOT / 'docs/research/08-skins.json').read_text(encoding='utf-8')).get('skins') or {}
    except (OSError, ValueError):
        return {}
    by_id = {}
    for entries in research.values():
        for s in entries:
            if s.get('skinId'):
                by_id[s['skinId']] = s
    out, avatars = {}, Path(ROOT) / 'public/assets' / AVATAR_DIR
    for _char_id, entries in sorted(plan.items()):
        for entry in entries:
            skin_id, stem = entry['skinId'], entry['stem']
            dest = avatars / f'{stem}.png'
            if dest.exists() and dest.stat().st_size:
                continue
            url = ((by_id.get(skin_id) or {}).get('avatar') or {}).get('url')
            if not url:
                continue
            try:
                avatars.mkdir(parents=True, exist_ok=True)
                with urllib.request.urlopen(url, timeout=30) as res:  # noqa: S310 (the research table's own URL)
                    blob = res.read()
                if not blob:
                    continue
                dest.write_bytes(blob)
                out[skin_id] = f'/assets/{AVATAR_DIR}/{stem}.png'
                log(f'  avatar {skin_id} -> {dest.name} ({len(blob)} B, from the mirror: not in this client)')
            except Exception as e:
                log(f'  warn {skin_id}: avatar fetch failed ({e}); the picker falls back to the operator avatar')
    return out


def extract_skin_avatars(ab_root, plan, log):
    """The 180×180 head icon of every planned skin, from the client's spritepack/ui_char_avatar_<N>.ab, written to
    public/assets/char/avatar/skin/<stem>.png (where tools/install-skins.mjs puts the mirror's copy, so the client's
    existing lookups work unchanged). Returns {skinId: URL}.

    Pure local: no download. Each avatar is both a Sprite and a Texture2D named <stem> — `char_1012_skadi2@boc#4`
    becomes `char_1012_skadi2_boc#4` (@→_, # kept). Bundles are opened one at a time and skipped once every stem they
    can supply is already written, so the six bundles this mode needs are the six that get read."""
    import aklz4  # noqa: F401
    import UnityPy
    wanted = {}
    for char_id, entries in plan.items():
        for e in entries:
            wanted.setdefault(e['client'], (e['skinId'], e['stem']))
    if not wanted:
        return {}
    dest_dir = Path(ROOT) / 'public/assets' / AVATAR_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for f in sorted(Path(ab_root).glob(AVATAR_PACKS)):
        if not wanted:
            break
        try:
            env = UnityPy.load(str(f))
        except Exception as e:
            log(f'FAIL load {f.name}: {e}')
            continue
        hit = 0
        for o in env.objects:
            if o.type.name not in ('Texture2D', 'Sprite'):
                continue
            try:
                d = o.read()
            except Exception:
                continue
            name = str(getattr(d, 'm_Name', '') or '')
            item = wanted.get(name)
            if not item:
                continue
            skin_id, stem = item
            try:
                img = d.image
            except Exception as e:
                log(f'  warn {skin_id}: avatar unreadable ({e})')
                continue
            img.save(dest_dir / f'{stem}.png')
            out[skin_id] = f'/assets/{AVATAR_DIR}/{stem}.png'
            wanted.pop(name, None)
            hit += 1
        if hit:
            log(f'{f.relative_to(ab_root).as_posix()}: {hit} skin avatar(s)')
    for name, (skin_id, _stem) in sorted(wanted.items()):
        log(f'  warn {skin_id}: no avatar for {name} in this client')
    return out


def write_skin_illustrations(ab_root, out_root, plan, manifest, log, stems=None):
    """The STATIC illustration of every planned skin as spine/op/<charId>/<stem>/illust.png, listed in the same
    manifest group as the skin's Front model. Two shapes exist in the client:

      * `<stem>b` — 1024×1024, what most skins carry (172 of the mode's 174);
      * bare `<stem>` — 1320–1416×1416, the full-page illustration, for the few skins that have no `b` variant
        (char_4051_akkord@summer#23, char_4163_rosesa@game#7 here).

    `b` is preferred where both exist. The DYNAMIC illustration page (`<stem>` at 2200–2508 px on a skin that also has
    `b`) stays out: it needs a canvas player the remake has no use for and is 4–7 MB per skin against ~1 MB for this
    one. This is what the 皮肤 picker shows — the tile art and the enlarged preview — and the local client is its only
    source, no mirror carries it."""
    import aklz4  # noqa: F401
    import UnityPy
    n = 0
    for char_id in sorted(plan):
        # keyed by BOTH stem forms: the catalogue's `char_1012_skadi2_boc_4` and the client's `char_1012_skadi2_boc#4`
        # (the two differ only in `#` vs `_`, and the texture name uses the client's)
        wanted = {}
        for e in plan[char_id]:
            if stems is None or e['stem'] in stems or e['client'] in stems:
                wanted[e['stem']] = e
                wanted[e['client']] = e
        if not wanted:
            continue
        bundle = Path(ab_root) / SKIN_PACK.format(char_id)
        if not bundle.exists():
            continue
        try:
            env = UnityPy.load(str(bundle))
        except Exception as e:
            log(f'FAIL load {bundle.name}: {e}')
            continue
        # pass 1 collects the candidates, pass 2 picks one per skin: `b` beats the bare name, and among equal names the
        # LARGEST wins (a skin without `b` carries several textures under the bare name — an illustration page plus
        # 316–340 px thumbnails — and the page is the one worth showing)
        best = {}
        for o in env.objects:
            if o.type.name != 'Texture2D':
                continue
            try:
                d = o.read()
            except Exception:
                continue
            name = str(getattr(d, 'm_Name', '') or '')
            if name.endswith('b'):
                key, rank = name[:-1], 0
            else:
                key, rank = name, 1
            entry = wanted.get(key)
            if not entry:
                continue
            area = (getattr(d, 'm_Width', 0) or 0) * (getattr(d, 'm_Height', 0) or 0)
            cur = best.get(key)
            if cur is None or (rank, -area) < (cur[0], -cur[3]):
                best[key] = (rank, entry, d, area)
        for _key, (_rank, entry, d, _area) in sorted(best.items()):
            try:
                img = d.image
            except Exception as e:
                log(f'  warn {entry["skinId"]}: illustration unreadable ({e})')
                continue
            # the catalogue stem, the same one export_skin_spines uses for the directory and the manifest group
            # (the client's name differs only in `#` vs `_`)
            stem = entry['stem']
            sub = f'{SKIN_SPINE_SUB}/{char_id}/{stem}'
            out_dir = Path(out_root) / sub
            out_dir.mkdir(parents=True, exist_ok=True)
            img.save(out_dir / 'illust.png')
            # The illustration gets its OWN group, never `<sub>/front`: that group belongs to the Spine model, and
            # everything in it is read as the model's atlas pages (`assets.js spinePages` → `localSpineEntry`, which
            # requires every one of them to be a real file). Registering illust.png there made the skin's page list
            # name a file that does not sit in the model's directory — the entry then failed its own check and the
            # renderer fell back to the operator's default chibi (the diamond the owner reported).
            manifest.setdefault(sub, {})['illust.png'] = {
                'path': asset_url(*sub.split('/'), 'illust.png'), 'w': img.width, 'h': img.height,
                'kind': 'Texture2D'}
            n += 1
            log(f'{bundle.relative_to(ab_root).as_posix()}: {entry["skinId"]} illustration -> {sub} ({img.width}x{img.height})')
    return n


def read_hub_keys(hub_path, log):
    """The asset ids a packing manifest declares (`_keys` of the AutoPackConfig MonoBehaviour), or an empty set.

    The keys list every packed id twice — once as the sprite name and once as its source path
    (`Arts/CharAvatars/Skins/<id>`) — so the caller gets both forms and can match either. They are stored
    LOWERCASED: the catalogue and the Texture2D names use the camelCase skin token (`…_ambienceSynesthesia#6`) while
    `_keys` holds `…_ambiencesynesthesia#6`, so a verbatim comparison silently drops every id with a capital."""
    import aklz4  # noqa: F401
    import UnityPy
    keys = set()
    try:
        env = UnityPy.load(str(hub_path))
    except Exception as e:
        log(f'  warn {hub_path.name} unreadable ({e})')
        return keys
    for o in env.objects:
        if o.type.name != 'MonoBehaviour':
            continue
        try:
            tt = o.read_typetree()
        except Exception:
            continue
        for k in tt.get('_keys') or []:
            s = str(k)
            keys.add(s)
            keys.add(s.lower())
            keys.add(s.rsplit('/', 1)[-1])
            keys.add(s.rsplit('/', 1)[-1].lower())
    return keys


def operator_of_client_id(name):
    """The operator a client asset id belongs to: `char_017_huang_witch#5` → `char_017_huang`, and `char_017_huang_2`
    → `char_017_huang`. None for a summon (`token_<n>_<name>_…`) or anything else that is not an operator id."""
    m = re.match(r'^(char_\d+_[a-z0-9]+)', str(name))
    return m.group(1) if m else None


def skin_id_of_stem(stem, char_id):
    """`char_017_huang_witch#5` → `char_017_huang@witch#5`: the catalogue id a client model stem corresponds to.

    The client names a skin `<charId>_<token>` (its `@` → `_`, `#` kept), so the first `_` after the charId is the one
    the `@` replaced. Returns None for a stem that is not a skin of `char_id` — a summon's skin is named
    `token_<n>_<name>_<series>#<n>` and belongs to no operator, and the default appearance is `<charId>` alone."""
    if not stem.startswith(f'{char_id}_'):
        return None
    token = stem[len(char_id) + 1:]
    return f'{char_id}@{token}' if token else None


def asset_url(*parts):
    """A `/assets/...` URL for path parts that may contain the client's `#` — percent-encoded as `%23`.

    The client names a skin `char_017_huang_witch#5`, and in a URL a bare `#` starts the fragment, so the browser
    requests everything before it and the image 404s. Every URL the manifest carries goes through here.

    The escape has to live here rather than be left to the client, because the consumers differ: the board art
    (render/boardArt.js) and the avatar / portrait / skin URLs of assets.js put this string in front of the browser
    unchanged, so a `#` that survives into the manifest is truncated. render/board3d/load.js is the one consumer that
    escapes, and it must not escape an already-escaped path (see `manifestUrl` there) — `encodeURI('%23')` is
    `'%2523'`, which 404s.

    Only the SEGMENTS are quoted (`safe=''`), the separators stay literal: quoting the whole path would turn `/` into
    `%2F`, which a static file server treats as one very long file name."""
    return '/'.join(['/assets/local'] + [quote(str(p), safe='') for p in parts])


def export_library(ab_root, out_root, manifest, log, which=None, stems=None):
    """Every operator image of the client, in three tiers, written under public/assets/local/library/<tier>/ and
    listed in data/local-assets.json groups `library/<tier>/<id>`.

    Pure local and catalogue-independent: it walks the client's own packing manifests and skin bundles, so a skin the
    research table never listed is extracted all the same. Returns {tier: {id: URL}}.

    `which` limits the tiers (e.g. {'portrait'}); `stems` limits the illustration tier to those client stems."""
    import aklz4  # noqa: F401
    import UnityPy
    out_root = Path(out_root)
    result = {}
    for tier, sub, hub_rel, glob, _idkeys, size in LIBRARIES:
        if which and tier not in which:
            continue
        got = {}
        if tier == 'illust':
            # one bundle per operator, named by the skin stems inside it
            for bundle in sorted(Path(ab_root).glob('skinpack/*.ab')):
                char_id = bundle.stem
                try:
                    env = UnityPy.load(str(bundle))
                except Exception as e:
                    log(f'FAIL load {bundle.name}: {e}')
                    continue
                # `<stem>b` (static) beats the bare `<stem>` (the dynamic page, 4–7 MB, needs a canvas player)
                best = {}
                for o in env.objects:
                    if o.type.name != 'Texture2D':
                        continue
                    try:
                        d = o.read()
                    except Exception:
                        continue
                    name = str(getattr(d, 'm_Name', '') or '')
                    if not name or name.startswith('build_') or name.endswith('[alpha]'):
                        continue
                    stem = name[:-1] if name.endswith('b') else name
                    # a skin's texture is named `<charId>_<series>#<n>`; the operator's own name alone is the
                    # default appearance, which char_portrait already carries at a fixed size
                    if not stem.startswith(f'{char_id}_'):
                        continue
                    if stems is not None and stem not in stems and name not in stems:
                        continue
                    area = (getattr(d, 'm_Width', 0) or 0) * (getattr(d, 'm_Height', 0) or 0)
                    rank = (0 if name.endswith('b') else 1, -area)
                    cur = best.get(stem)
                    if cur is None or rank < cur[0]:
                        best[stem] = (rank, d, name)
                for stem, (_rank, d, _name) in sorted(best.items()):
                    try:
                        img = d.image
                    except Exception as e:
                        log(f'  warn {stem}: illustration unreadable ({e})')
                        continue
                    rel = f'{LIBRARY_ROOT}/{sub}/{stem}'
                    (out_root / rel).mkdir(parents=True, exist_ok=True)
                    img.save(out_root / rel / 'illust.png')
                    entry = {'path': asset_url(LIBRARY_ROOT, sub, stem, 'illust.png'), 'w': img.width, 'h': img.height,
                             'kind': 'Texture2D', 'charId': char_id,
                             'skinId': skin_id_of_stem(stem, char_id)}
                    manifest.setdefault(rel, {})['illust.png'] = {k: v for k, v in entry.items() if k != 'skinId'}
                    got[stem] = entry
                if best:
                    log(f'{bundle.relative_to(ab_root).as_posix()}: {len(best)} illustration(s)')
        else:
            hub = Path(ab_root) / hub_rel
            keys = read_hub_keys(hub, log) if hub.exists() else set()
            if hub.exists():
                log(f'{hub_rel}: {len(keys)} key form(s)')
            for bundle in sorted(Path(ab_root).glob(glob)):
                try:
                    env = UnityPy.load(str(bundle))
                except Exception as e:
                    log(f'FAIL load {bundle.name}: {e}')
                    continue
                hit = 0
                for o in env.objects:
                    if o.type.name != 'Texture2D':
                        continue
                    try:
                        d = o.read()
                    except Exception:
                        continue
                    name = str(getattr(d, 'm_Name', '') or '')
                    if not name or (keys and name not in keys and name.lower() not in keys):
                        continue
                    try:
                        img = d.image
                    except Exception as e:
                        log(f'  warn {name}: unreadable ({e})')
                        continue
                    rel = f'{LIBRARY_ROOT}/{sub}/{name}'
                    (out_root / rel).mkdir(parents=True, exist_ok=True)
                    img.save(out_root / rel / 'image.png')
                    owner = operator_of_client_id(name)
                    # `<charId>_1` and `_2` are the operator's own default appearance, not a skin
                    skin = None if name in (f'{owner}_1', f'{owner}_2') else skin_id_of_stem(name, owner)
                    entry = {'path': asset_url(LIBRARY_ROOT, sub, name, 'image.png'), 'w': img.width, 'h': img.height,
                             'kind': 'Texture2D', 'id': name, 'charId': owner, 'skinId': skin}
                    manifest.setdefault(rel, {})['image.png'] = {k: v for k, v in entry.items() if k != 'skinId'}
                    got[name] = entry
                    hit += 1
                if hit:
                    log(f'{bundle.relative_to(ab_root).as_posix()}: {hit} {tier}(s)')
        result[tier] = got
        log(f'{tier}: {len(got)} image(s) ({size})')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--game', help='AssetBundle root (…/StreamingAssets/AB/Windows or …/Documents/Bundles)')
    ap.add_argument('--out', default=str(ROOT / 'public/assets/local'))
    ap.add_argument('--manifest', default=str(ROOT / 'data/local-assets.json'))
    ap.add_argument('--only', action='append', default=[], metavar='SUBDIR',
                    help='only run the jobs whose output subdir starts with this prefix (repeatable), e.g. emoticon')
    ap.add_argument('--scenes', action='append', default=[], metavar='DIR',
                    help='an AB root holding the battlefield scene bundles of an in-season version (repeatable; '
                         'searched after --game and before .cache/official-scenes/*)')
    ap.add_argument('--print-jobs', action='store_true', help='print the job table as JSON and exit')
    ap.add_argument('--webp', action='store_true',
                    help='only write the WebP copies of the board textures and the guide pages from the PNGs already '
                         'under --out and list them in the manifest (needs Pillow, not the client)')
    ap.add_argument('--skin', action='append', default=[], metavar='STEM',
                    help='only the operator skins with this model stem (repeatable), e.g. char_1012_skadi2_boc_4; '
                         'the whole installed set otherwise')
    ap.add_argument('--library-tier', action='append', default=[], metavar='TIER',
                    help='with --only library, extract only these tiers (repeatable; avatar / portrait / illust)')
    args = ap.parse_args()

    if args.print_jobs:
        jobs = [{'bundle': rel, 'sub': sub, 'kinds': sorted(kinds), 'keep': keep.pattern if keep else None}
                for rel, sub, kinds, keep in map(job_parts, JOBS)]
        derived = [{'sub': sub, 'from': src, 'derive': kind, 'name': name} for sub, src, kind, name in DERIVED]
        webp = [{'sub': sub, 'name': name, 'mode': mode} for sub, name, mode in WEBP]
        print(json.dumps({'emoteThemes': [{'themeId': t, 'dir': d} for t, d in EMOTE_THEMES], 'jobs': jobs,
                          'derived': derived, 'webp': webp,
                          'guideWebp': {'sub': GUIDE_WEBP_SUB, 'mode': GUIDE_WEBP_MODE,
                                        'options': GUIDE_WEBP_OPTIONS[GUIDE_WEBP_MODE]},
                          'enemySpines': {'bundles': ENEMY_ART, 'sub': ENEMY_SPINE_SUB, 'ids': ENEMY_SPINES},
                          'tokenSpines': {'bundles': TOKEN_PACKS, 'sub': TOKEN_SPINE_SUB, 'ids': TOKEN_SPINES},
                          'scenes': {'sub': scenes.SCENE_SUB, 'tex': scenes.TEX_SUB,
                                     'stages': [{'id': sid, 'bundle': scenes.scene_bundle(sid), 'deps': deps}
                                                for sid, deps in scenes.SCENES]}},
                         ensure_ascii=False))
        return 0
    if args.webp:
        return webp_only(Path(args.out), Path(args.manifest), print)

    ab_root = Path(args.game) if args.game else next((p for p in CANDIDATES if p.exists()), None)
    if not ab_root or not ab_root.exists():
        print('No Arknights install found. Pass --game <AssetBundle root>.', file=sys.stderr)
        return 2
    jobs = select_jobs(args.only)
    enemy_ids = spine_ids(args.only, ENEMY_SPINE_SUB, ENEMY_SPINES)
    token_ids = spine_ids(args.only, TOKEN_SPINE_SUB, TOKEN_SPINES)
    stage_ids = scene_ids(args.only)
    skin_stems = skin_ids(args.only, args.skin)
    library_tiers = set()
    # The library is part of a FULL extraction, not an opt-in: `setup --local` runs this script with no --only, and the
    # catalogue the client reads (data/skins.json) names library images, so skipping it would leave a clone that ran
    # the official setup with a catalogue whose every image 404s. `--only library` extracts just this, and
    # `--library-tier` narrows it further.
    if not args.only or 'library' in args.only:
        known = {t for t, _s, _h, _g, _k, _z in LIBRARIES}
        unknown = set(args.library_tier) - known
        if unknown:
            print(f'--library-tier: unknown tier(s) {sorted(unknown)}; known: {sorted(known)}', file=sys.stderr)
            return 2
        library_tiers = set(args.library_tier) or known

    if not jobs and not enemy_ids and not token_ids and not stage_ids and skin_stems is None and not library_tiers:
        print(f'--only {args.only}: no job matches', file=sys.stderr)
        return 2
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    manifest, total = {}, 0
    print(f'AB root: {ab_root}')
    for job in jobs:
        total += export_bundle(ab_root, job, out_root, manifest, print)
    if enemy_ids:
        total += export_enemy_spines(ab_root, out_root, manifest, print, enemy_ids)
    if token_ids:
        total += export_token_spines(ab_root, out_root, manifest, print, token_ids)
    if stage_ids:
        total += export_scenes(ab_root, out_root, manifest, print, stage_ids, scene_roots(ab_root, args.scenes))
    # The library FIRST when both run: export_skin_spines reads its portrait tier for the manifest's button art
    # (skin_portraits_from_library), so the reverse order would write data/skins-local.json without any portrait URL
    # and only fix it on a second run.
    lib = {}
    if library_tiers:
        lib = export_library(ab_root, out_root, manifest, print, library_tiers)
    if skin_stems is not None:
        total += export_skin_spines(ab_root, out_root, manifest, print, set(skin_stems) or None)
    # The index (and the count) belong to the library tiers, and only a run that extracted them may write it: a
    # `--only spine/op` run used to reach this block and die on the unbound `lib` — after the skins were written, so
    # data/local-assets.json (the merged manifest below) was never updated and the new page names never reached the
    # client. Nothing is written without the library, and the files keep the index of the last run that had it.
    if lib:
        total += sum(len(v) for v in lib.values())
        index = {'version': 1, 'source': 'local-client',
                 'note': 'Operator images extracted from the local client by tools/local-extract/extract.py '
                         '(`--only library`): every operator, not only the skins the research catalogue lists. Written '
                         'to public/assets/local/library/<tier>/<id>/ and listed in data/local-assets.json.',
                 'counts': {t: len(v) for t, v in lib.items()},
                 'tiers': {t: dict(sorted(v.items())) for t, v in lib.items()}}
        text = json.dumps(index, ensure_ascii=False, indent=1) + '\n'
        LIBRARY_INDEX.parent.mkdir(parents=True, exist_ok=True)
        LIBRARY_INDEX.write_text(text, encoding='utf-8', newline='\n')
        LIBRARY_DATA_FILE.write_text(text, encoding='utf-8', newline='\n')
        print(f'wrote {LIBRARY_INDEX.relative_to(ROOT).as_posix()} and {LIBRARY_DATA_FILE.relative_to(ROOT).as_posix()} '
              f'({", ".join(f"{t} {len(v)}" for t, v in lib.items())})')
    old = {}
    if args.only and Path(args.manifest).exists():
        try:
            old = json.loads(Path(args.manifest).read_text(encoding='utf-8')).get('groups') or {}
        except (OSError, ValueError) as e:
            print(f'warn: previous manifest unreadable ({e}); writing only the re-extracted groups', file=sys.stderr)
    groups = merge_manifest(old, manifest, set(manifest))  # a missing bundle keeps its previous group
    count = sum(len(v) for v in groups.values())
    doc = {'version': 1, 'source': 'local-client', 'count': count, 'groups': groups}
    Path(args.manifest).write_text(json.dumps(doc, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'done: {total} files extracted, manifest {args.manifest} ({count} entries)')
    return 0 if total else 1


if __name__ == '__main__':
    sys.exit(main())
