#!/usr/bin/env python3
"""召唤物（token）皮肤提取 —— 本仓库自己的入口。

只加载上游 `extract/extract.py` 的拷贝来复用 Spine 读写（`prefab_spine_nodes` / `facings_of` / `write_spine`），
不修改它。按 `skinpack/token_<tokenId>.ab` 里每个皮肤 prefab 的 SkeletonDataAsset 取模型（不按骨架名匹配），写出：

  <out>/spine/token-skin/<tokenId>/<stem>/{front,back}/<骨架文件名>.{skel,atlas,png}
  <out>/spine/token-skin/<tokenId>/<stem>/avatar.png        （ui_char_avatar_*.ab 的 180×180 头像）

元数据（默认 `<data-root>/data/token-skins-local.json`）：

  { "tokens": { "<tokenId>": { "skins": { "<主人皮肤 id>": { "stem", "name", "group" } } } } }

主人的皮肤 id 来自官方 `skin_table.json` 的 `tokenSkinMap`；`tools/build-plugin.py` 据此写
`tokens[<tokenId>].skins[<主人皮肤 id>]`。

用法：

  python extract/token_skins.py --data-root <服务器检出> --game <AB 根>
      [--out <服务器检出>/public/assets/local] [--manifest <服务器检出>/data/token-skins-local.json]
      [--dry-run] [--token <tokenId> …]

需要 `<data-root>/.cache/gamedata/excel/skin_table.json`（官方表，映射主人皮肤用）。
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
UPSTREAM = HERE / 'extract.py'


def load_upstream():
    """加载上游提取模块（与 skins.py 用同一种方式：按路径加载，不装包）。"""
    sys.path.insert(0, str(HERE))
    spec = importlib.util.spec_from_file_location('sp_local_extract', UPSTREAM)
    if spec is None or spec.loader is None:
        raise SystemExit(f'读不到 {UPSTREAM}')
    module = importlib.util.module_from_spec(spec)
    sys.modules['sp_local_extract'] = module
    spec.loader.exec_module(module)
    return module


def read_official(path):
    """官方 tokenSkinMap → {tokenSkinId: (tokenId, ownerSkinId, name, group)}。"""
    data = json.loads(path.read_text(encoding='utf-8'))
    chars = data.get('charSkins') if isinstance(data, dict) else None
    if not isinstance(chars, dict):
        raise SystemExit(f'{path}: 不是官方的 skin_table.json（缺 charSkins）')
    out = {}
    for owner_skin, rec in chars.items():
        token_map = (rec or {}).get('tokenSkinMap') or []
        if not token_map:
            continue
        ds = (rec or {}).get('displaySkin') or {}
        for entry in token_map:
            if not isinstance(entry, dict):
                continue
            token_id, token_skin = entry.get('tokenId'), entry.get('tokenSkinId')
            if not token_id or not token_skin:
                continue
            out[token_skin.casefold()] = {
                'tokenSkinId': token_skin,
                'tokenId': token_id,
                'ownerSkinId': owner_skin,
                'name': ds.get('skinName') or '',
                'group': ds.get('skinGroupName') or '',
            }
    return out


def stem_of(token_skin_id):
    """皮肤键 → 目录/文件 stem：`@` `#` 换成 `_`（和主项目 skin stem 的规则一致）。"""
    return token_skin_id.replace('@', '_').replace('#', '_')


def load_avatar_textures(ab_root):
    """客户端 ui_char_avatar_*.ab 里的 token 头像：{名字: (对象, 文件)}；只读名字，命中的才解码。"""
    sys.path.insert(0, str(HERE))
    import aklz4  # noqa: F401  (registers the LZ4AK decoder for UnityPy)
    import UnityPy
    out = {}
    for bundle in sorted((ab_root / 'spritepack').glob('ui_char_avatar_*.ab')):
        try:
            env = UnityPy.load(str(bundle))
        except Exception:
            continue
        for obj in env.objects:
            if obj.type.name not in ('Texture2D', 'Sprite'):
                continue
            try:
                tt = obj.read_typetree()
            except Exception:
                continue
            name = str(tt.get('m_Name') or '')
            if name.startswith('token_') and name not in out:
                out[name] = (obj, bundle)
    return out


def save_avatar(obj, dest):
    """把头像 Texture2D（或 Sprite 的 texture）写成 PNG；失败返回 False。"""
    try:
        data = obj.read()
        image = getattr(data, 'image', None)
        if image is None and obj.type.name == 'Sprite':
            texture = getattr(data, 'm_RD', None)
            image = getattr(texture, 'texture', None)
            image = image.image if hasattr(image, 'image') else None
        if image is None:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        image.save(dest)
        return True
    except Exception:
        return False


def run(args):
    data_root = Path(args.data_root).resolve()
    ab_root = Path(args.game).resolve()
    out = Path(args.out).resolve() if args.out else data_root / 'public/assets/local'
    manifest_path = Path(args.manifest).resolve() if args.manifest else data_root / 'data/token-skins-local.json'
    table_path = data_root / '.cache/gamedata/excel/skin_table.json'
    if not table_path.is_file():
        raise SystemExit(f'缺官方表 {table_path}：token 皮肤要靠 tokenSkinMap 找主人皮肤（先在服务器检出跑一次 setup / 更新 .cache）')
    if not (ab_root / 'skinpack').is_dir():
        raise SystemExit(f'{ab_root}: 不是客户端的 AB 根（没有 skinpack/）')

    extract = load_upstream()
    official = read_official(table_path)
    wanted_tokens = set(args.token or [])
    avatars = {} if args.dry_run or args.no_avatars else load_avatar_textures(ab_root)

    groups = {}
    metadata = {}
    skipped = []
    failures = []
    used_avatar = 0
    log = (print if args.dry_run else print)
    for bundle in sorted((ab_root / 'skinpack').glob('token_*.ab')):
        token_from_file = bundle.stem
        if wanted_tokens and token_from_file not in wanted_tokens:
            continue
        try:
            env = load_env(bundle)
        except Exception as exc:
            log(f'FAIL load {bundle.name}: {exc}')
            failures.append(f'{bundle.name}: {exc}')
            continue
        objects = {o.path_id: o for o in env.objects}
        for name, ref in env.container.items():
            if not name.endswith('.prefab'):
                continue
            prefab_stem = Path(name).stem
            if prefab_stem.casefold().startswith('illust_'):
                continue  # token 的立绘 prefab（只有 2 个 token 皮肤有自己的 illustId）
            info = official.get(prefab_stem.casefold())
            if not info:
                skipped.append((bundle.name, prefab_stem, 'not in tokenSkinMap'))
                continue
            nodes = extract.prefab_spine_nodes(ref.read_typetree(), objects)
            refs = []
            for _gname, _active, pptr in nodes:
                sda = objects.get(pptr.get('m_PathID')) if pptr and not pptr.get('m_FileID') else None
                if sda is None:
                    continue
                try:
                    sda_tt = sda.read_typetree()
                    skel_ref = sda_tt.get('skeletonJSON')
                    skel = objects.get(skel_ref.get('m_PathID')) if skel_ref and not skel_ref.get('m_FileID') else None
                    if skel is None:
                        continue
                    refs.append((sda_tt, skel.read()))
                except Exception:
                    continue
            if not refs:
                skipped.append((bundle.name, prefab_stem, 'no Spine model'))
                continue
            token_id = info['tokenId']
            owner_skin = info['ownerSkinId']
            stem = stem_of(info['tokenSkinId'])
            sub = f'spine/token-skin/{token_id}/{stem}'
            if args.dry_run:
                log(f'  would extract {info["tokenSkinId"]} -> {sub} (skin {owner_skin})')
                metadata.setdefault(token_id, {}).setdefault('skins', {})[owner_skin] = {
                    'stem': stem, 'name': info['name'], 'group': info['group']}
                continue
            written = 0
            for tag, sda_tt in extract.facings_of(refs, log, info['tokenSkinId'], objects):
                if sda_tt is None:
                    continue
                written += extract.write_spine(objects, sda_tt, f'{sub}/{tag}', info['tokenSkinId'], out, groups, log)
            if not written:
                skipped.append((bundle.name, prefab_stem, 'nothing written'))
                failures.append(f'{info["tokenSkinId"]}: nothing written')
                continue
            avatar_obj = avatars.get(info['tokenSkinId'])
            if avatar_obj is not None and save_avatar(avatar_obj[0], out / sub / 'avatar.png'):
                used_avatar += 1
            metadata.setdefault(token_id, {}).setdefault('skins', {})[owner_skin] = {
                'stem': stem, 'name': info['name'], 'group': info['group']}
            log(f'{bundle.name}: {info["tokenSkinId"]} -> {sub} ({written} files, {owner_skin})')

    if args.dry_run:
        log(f'dry-run: {sum(len(v.get("skins", {})) for v in metadata.values())} skins / '
            f'{len(metadata)} tokens; skipped {len(skipped)} prefabs')
        return 0
    manifest = {
        'version': 1,
        'source': 'local-client',
        'note': 'Summon (token) skins extracted from the local game client (extract/token_skins.py). '
                'Never committed: game art. Keyed by tokenId, then by the owner operator skin id (official tokenSkinMap).',
        'tokens': metadata,
        'counts': {
            'tokens': len(metadata),
            'skins': sum(len(v.get('skins', {})) for v in metadata.values()),
            'avatars': used_avatar,
            'skipped': len(skipped),
            'errors': len(failures),
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    log(f'\n{manifest["counts"]["skins"]} skins / {manifest["counts"]["tokens"]} tokens '
        f'({used_avatar} avatars) -> {manifest_path}')
    for bundle, prefab, why in skipped:
        log(f'  skip {prefab} ({bundle}): {why}')
    for failure in failures:
        log(f'  FAIL {failure}')
    return 1 if failures else 0


def load_env(bundle):
    import aklz4  # noqa: F401  (registers the LZ4AK decoder)
    import UnityPy
    return UnityPy.load(str(bundle))


def main(argv):
    ap = argparse.ArgumentParser(description='召唤物（token）皮肤提取：客户端 skinpack/token_*.ab → spine/token-skin/')
    ap.add_argument('--data-root', required=True, help='服务器检出：官方表（.cache）、默认 --out 与元数据都从这里推')
    ap.add_argument('--game', required=True, help='客户端 AB 根（…/StreamingAssets/AB/Windows）')
    ap.add_argument('--out', help='提取产物的 local 目录（默认 <data-root>/public/assets/local）')
    ap.add_argument('--manifest', help='元数据输出（默认 <data-root>/data/token-skins-local.json）')
    ap.add_argument('--token', action='append', default=[], help='只提这些 tokenId（可重复；默认全部）')
    ap.add_argument('--no-avatars', action='store_true', help='不提 180×180 头像（只出模型）')
    ap.add_argument('--dry-run', action='store_true', help='只打印计划，不写文件')
    return run(ap.parse_args(argv))


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
