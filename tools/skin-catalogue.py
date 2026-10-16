#!/usr/bin/env python3
"""生成目录表：skinId → `name` / `group`（只含元数据，不含任何美术），写成一个 skin_table.json 形状的文件。

`tools/build-plugin.py --skin-table <文件>` 就读它（主项目 `data/*.json` 的官方表也是这个形状：
`charSkins[skinId].displaySkin.skinName` / `skinGroupName`）。来源按顺序合并，**先拿到的不被后面的覆盖**，
但**每个字段各自取第一个非空值**——先来的来源缺 name 或 group 时，后面的来源可以补上：

  1. `--local-catalogue`  随仓库分发的 `catalogue/skins.json`（`tools/local-catalogue.py` 生成；默认在仓库里，
                          存在就用，`--no-local-catalogue` 关掉）。本机实测 273 套**全部**有名字与分组，
                          所以别的机器没有官方 gamedata 缓存、提取元数据里名字残缺时也能拿到真名；
  2. `--skin-table`       官方 gamedata 表（客户端 / `.cache/gamedata/excel/skin_table.json`）——名字最全，有就用；
  3. `--extra`            额外清单（可重复），认四种形状：
                            * 本脚本自己的输出（`charSkins`）；
                            * `catalogue/skins.json`（`skins: [{skinId, stem, charId, name, group}]`）；
                            * 外部素材目录的 `catalogue.json`（`skins: {"<charId>/<stem>": {skinId,name,group}}`）；
                            * `data/skins-local.json` 那样的 `chars[charId].skins[skinId].name/.group`；
  4. `--skins-meta`       提取器写的 `data/skins-local.json`（本机客户端提取的产物）：名字与分组，另外从
                          `spine.{front,back}.skel` 的文件名反推 stem → skinId；
  5. `--skin-index`       提取器写的 `tools/assets/local-skin-index.json`：只有 stem → skinId，用来把**没有名字**的皮肤
                          也列进目录表（`build-plugin.py` 靠它拿到合法的 skinId，名字留空即可）。

stem 与 charId 也按同样的顺序取：本地表 → 提取元数据的 `.skel` 文件名 → `--skin-index`；charId 最后退回
skinId 里 `@` 之前那一段。没有名字不是错误：`assets.json` 里就不写 `name`，客户端退回显示 skinId。**本脚本不联网**。
"""
import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LOCAL_CATALOGUE = os.path.join(REPO, 'catalogue', 'skins.json')
CHAR_ID = re.compile(r'^[A-Za-z0-9_]+$')


def say(text=''):
    print(text)


def load_json(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def read_official(path):
    """官方 skin_table.json：{ skinId: (name, group) }。"""
    data = load_json(path)
    out = {}
    for skin_id, rec in (data.get('charSkins') or {}).items():
        ds = (rec or {}).get('displaySkin') or {}
        name = (ds.get('skinName') or '').strip()
        group = (ds.get('skinGroupName') or '').strip()
        if name or group:
            out[str(skin_id)] = (name, group)
    return out


def read_local_catalogue(path):
    """随仓库分发的 catalogue/skins.json（`tools/local-catalogue.py` 的输出）。

    返回 ({skinId: (name, group)}, {skinId: stem}, {skinId: charId})。
    """
    data = load_json(path)
    rows = data.get('skins') if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise SystemExit(f'--local-catalogue {path}: 里没有 skins 数组')
    meta = {}
    stems = {}
    chars = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        skin_id = row.get('skinId')
        if not skin_id:
            continue
        skin_id = str(skin_id)
        meta[skin_id] = ((row.get('name') or '').strip(), (row.get('group') or '').strip())
        if row.get('stem'):
            stems[skin_id] = str(row['stem'])
        if row.get('charId'):
            chars[skin_id] = str(row['charId'])
    return meta, stems, chars


def read_extra(path):
    """额外清单：认 charSkins / skins（数组或映射）/ chars 三种形状 → { skinId: (name, group) }。"""
    data = load_json(path)
    if not isinstance(data, dict):
        return {}
    if data.get('charSkins'):
        return read_official(path)
    out = {}
    skins = data.get('skins')
    if isinstance(skins, list):
        for rec in skins:
            if not isinstance(rec, dict):
                continue
            skin_id = rec.get('skinId') or rec.get('id')
            if skin_id:
                out[str(skin_id)] = ((rec.get('name') or '').strip(), (rec.get('group') or '').strip())
    elif isinstance(skins, dict):
        for rec in skins.values():
            if not isinstance(rec, dict):
                continue
            skin_id = rec.get('skinId')
            if skin_id:
                out[str(skin_id)] = ((rec.get('name') or '').strip(), (rec.get('group') or '').strip())
    chars = data.get('chars')
    if isinstance(chars, dict):
        for rec in chars.values():
            rows = rec if isinstance(rec, list) else ((rec or {}).get('skins') or {})
            pairs = ((row.get('id'), row) for row in rows) if isinstance(rows, list) else rows.items()
            for skin_id, skin in pairs:
                if not skin_id:
                    continue
                skin = skin or {}
                out.setdefault(str(skin_id), ((skin.get('name') or '').strip(), (skin.get('group') or '').strip()))
    return out


def read_skins_meta(path):
    """data/skins-local.json → ({skinId: (name, group)}, {skinId: stem})（stem 从 spine.*.skel 反推）。"""
    data = load_json(path)
    meta = {}
    stems = {}
    for rec in (data.get('chars') or {}).values():
        for skin_id, skin in ((rec or {}).get('skins') or {}).items():
            skin = skin or {}
            meta[str(skin_id)] = ((skin.get('name') or '').strip(), (skin.get('group') or '').strip())
            for facing in ('front', 'back'):
                skel = ((skin.get('spine') or {}).get(facing) or {}).get('skel')
                if isinstance(skel, str) and skel.endswith('.skel'):
                    stems.setdefault(str(skin_id), skel.rsplit('/', 1)[-1][:-len('.skel')])
    return meta, stems


def read_stem_index(path):
    """tools/assets/local-skin-index.json → { stem: skinId }。"""
    data = load_json(path)
    return {str(k): str(v) for k, v in ((data.get('byStem') if isinstance(data, dict) else None) or {}).items()}


def main(argv):
    ap = argparse.ArgumentParser(description='生成目录表（skinId → name/group），只含元数据')
    ap.add_argument('--out', required=True, help='输出文件（例如 <插件仓库>/data/skin-table.json）')
    ap.add_argument('--local-catalogue', default=DEFAULT_LOCAL_CATALOGUE,
                    help=f'随仓库分发的目录表（默认 {DEFAULT_LOCAL_CATALOGUE}；存在就**优先**用它，缺字段才往后面的来源找）')
    ap.add_argument('--no-local-catalogue', action='store_true', help='不用仓库自带的目录表（只看后面的来源）')
    ap.add_argument('--skin-table', help='官方 .cache/gamedata/excel/skin_table.json')
    ap.add_argument('--skins-meta', help='提取器写的 data/skins-local.json')
    ap.add_argument('--skin-index', help='提取器写的 tools/assets/local-skin-index.json')
    ap.add_argument('--extra', action='append', default=[], metavar='FILE',
                    help='额外清单（可重复）：本脚本的输出 / dump 的 catalogue.json / data/skins-local.json 形状')
    args = ap.parse_args(argv)

    table = {}      # skinId -> [name, group]（按来源顺序逐字段填）
    stems = {}      # skinId -> stem
    chars = {}      # skinId -> charId
    sources = []
    missing = []

    def merge(got, desc, got_stems=None, got_chars=None):
        """按来源顺序填：name / group / stem / charId 各自只补空位。"""
        names = groups = 0
        for skin_id, (name, group) in got.items():
            row = table.setdefault(skin_id, ['', ''])
            if not row[0] and name and name != skin_id:
                row[0] = name
                names += 1
            if not row[1] and group:
                row[1] = group
                groups += 1
        for skin_id, stem in (got_stems or {}).items():
            stems.setdefault(skin_id, stem)
        for skin_id, char_id in (got_chars or {}).items():
            chars.setdefault(skin_id, char_id)
        sources.append(f'{desc}（{len(got)} 个 skinId，补了 {names} 个名字、{groups} 个分组）')

    if not args.no_local_catalogue:
        if os.path.isfile(args.local_catalogue):
            got, got_stems, got_chars = read_local_catalogue(args.local_catalogue)
            merge(got, f'仓库目录表 {os.path.abspath(args.local_catalogue)}', got_stems, got_chars)
        elif args.local_catalogue != DEFAULT_LOCAL_CATALOGUE:
            raise SystemExit(f'--local-catalogue {args.local_catalogue}: 不是一个文件')
        else:
            missing.append(f'仓库里没有 {args.local_catalogue}（用 tools/local-catalogue.py 生成；'
                           f'没有它也能跑，只是名字要看官方表或提取元数据）')

    if args.skin_table:
        if not os.path.isfile(args.skin_table):
            raise SystemExit(f'--skin-table {args.skin_table}: 不是一个文件')
        merge(read_official(args.skin_table), f'官方表 {os.path.abspath(args.skin_table)}')
    for path in args.extra:
        if not os.path.isfile(path):
            raise SystemExit(f'--extra {path}: 不是一个文件')
        merge(read_extra(path), f'额外清单 {os.path.abspath(path)}')
    if args.skins_meta:
        if not os.path.isfile(args.skins_meta):
            raise SystemExit(f'--skins-meta {args.skins_meta}: 不是一个文件')
        got, got_stems = read_skins_meta(args.skins_meta)
        merge(got, f'提取元数据 {os.path.abspath(args.skins_meta)}', got_stems)

    by_stem = read_stem_index(args.skin_index) if args.skin_index and os.path.isfile(args.skin_index) else {}
    if by_stem:
        sources.append(f'目录索引 {os.path.abspath(args.skin_index)}（{len(by_stem)} 个 stem → skinId，用来补齐没有名字的皮肤）')
    if args.skin_index and not by_stem and not os.path.isfile(args.skin_index):
        missing.append(f'{args.skin_index} 不在（没有它就只能列出来源里出现过的皮肤）')
    if not sources:
        raise SystemExit('没有可读的来源：至少给 --local-catalogue / --skin-table / --extra / --skins-meta / --skin-index 之一')

    # 名字与 skinId 相同等于没名字（提取器的兜底写法），丢掉免得客户端把 skinId 当显示名。
    char_skins = {}
    for skin_id in sorted(set(table) | set(stems) | set(by_stem.values()) | set(chars)):
        name, group = table.get(skin_id, ('', ''))
        if name == skin_id:
            name = ''
        entry = {'displaySkin': {'skinName': name, 'skinGroupName': group}}
        stem = stems.get(skin_id) or next((s for s, sid in by_stem.items() if sid == skin_id), None)
        if stem:
            entry['stem'] = stem
        char_id = chars.get(skin_id) or skin_id.split('@', 1)[0]
        if CHAR_ID.match(char_id):
            entry['charId'] = char_id
        char_skins[skin_id] = entry

    doc = {
        'version': 1,
        'note': 'Skin catalogue for the skin-models plugin build (tools/build-plugin.py --skin-table). Metadata only '
                '(skinId → name/group); no game art. Generated by tools/skin-catalogue.py.',
        'sources': sources,
        'count': len(char_skins),
        'named': sum(1 for e in char_skins.values() if e['displaySkin']['skinName']),
        'charSkins': char_skins,
    }
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
        fh.write('\n')

    say(f'目录表 {out}')
    for line in sources:
        say(f'  来源：{line}')
    for line in missing:
        say(f'  提醒：{line}')
    say(f'  {doc["count"]} 个 skinId，其中 {doc["named"]} 个有名字、{doc["count"] - doc["named"]} 个只有键'
        f'（客户端退回显示 skinId）')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
