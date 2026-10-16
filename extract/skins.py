#!/usr/bin/env python3
"""皮肤 / 干员图库提取的入口：只暴露本插件需要的那两条 job（`spine/op` 与 `library`）。

`extract.py` 是主项目 `tools/local-extract/extract.py`（分支 `feat/skins`）的**原样拷贝**，一个字都没改
（见 NOTICE.md §"提取器"）：它带 20 多条 job（地图 / UI / 表情 / 场景 / 敌人 / token …），这里只用其中两条。
本文件是本仓库自己的代码，负责：

  1. 把上游模块的 `ROOT` 与几个 `ROOT` 派生路径**重定基**到 `--data-root`（默认 `--server`）。上游是照
     `<主项目>/tools/local-extract/extract.py` 的位置算 `ROOT = parents[2]` 的，拷贝到 `<插件仓库>/extract/` 之后
     那个推导会落到仓库外面，所以必须在调用前改掉；
  2. 只接受皮肤 / 图库相关的参数，翻译成上游的 `--only spine/op` / `--only library`。

上游会往 data-root 写这些**元数据**（都不含美术，是本插件构建时的输入）：
`data/skins-local.json`、`data/library-index.json`、`tools/assets/local-skin-index.json`、
`tools/assets/local-skins-meta.json`、`tools/skin-library/library-index.json`；
美术写到 `--out`（默认 `<data-root>/public/assets/local`）。

用法（Python 需要 UnityPy / lz4 / Pillow，见 requirements.txt；deploy.mjs 会自动建 venv）：

  python extract/skins.py --server <服务器检出> --game <AB 根>/Windows [--only both|skins|library]
                          [--out <local 目录>] [--manifest <local-assets.json>] [--skin <stem> …]
                          [--library-tier avatar|portrait|illust] [--print-jobs] [--dry-run]

注意 `--skin`（上游也有）用来只提一套。**第一次跑要先 `--only library`，再 `--only skins`**：上游按磁盘上的
`tools/skin-library/library-index.json` 枚举"客户端有哪些皮肤"，而那次运行要到结尾才写这个索引，所以在索引还不
存在时跑皮肤那条 job 会一套都选不出来（`--only both` 也一样）。索引存在之后 `--only both` 才是安全的。
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
UPSTREAM = HERE / 'extract.py'

# 上游在 import 时按自己的位置算这几个路径；重定基就是把这几个名字指到 data-root 下（见模块开头）。
REBASED = {
    'SKIN_INDEX': ('tools', 'assets', 'local-skin-index.json'),
    'SKIN_MANIFEST': ('data', 'skins-local.json'),
    'SKIN_META': ('tools', 'assets', 'local-skins-meta.json'),
    'SKIN_LIBRARY_DIR': ('tools', 'skin-library'),
    'LIBRARY_INDEX': ('tools', 'skin-library', 'library-index.json'),
    'LIBRARY_DATA_FILE': ('data', 'library-index.json'),
}


def load_upstream():
    """按路径加载拷贝来的 extract.py（不装包、不改 sys.path 的顺序）。"""
    spec = importlib.util.spec_from_file_location('sp_local_extract', UPSTREAM)
    if spec is None or spec.loader is None:
        raise SystemExit(f'读不到 {UPSTREAM}')
    module = importlib.util.module_from_spec(spec)
    sys.modules['sp_local_extract'] = module
    spec.loader.exec_module(module)  # 顶层会 sys.path.insert(HERE) 并 import scenes
    return module


def rebase(module, root):
    """把 ROOT 与 ROOT 派生路径指到 root（上游的目录表 / 清单都写在这里）。

    上游假定这些目录由主项目检出带出来（tools/assets/、data/、tools/skin-library/ 都存在）；重定基之后不一定
    存在，所以这里替它建好，免得第一次跑就 FileNotFoundError。
    """
    module.ROOT = root
    for name, parts in REBASED.items():
        path = root.joinpath(*parts)
        setattr(module, name, path)
        parent = path if name == 'SKIN_LIBRARY_DIR' else path.parent
        parent.mkdir(parents=True, exist_ok=True)


def main(argv):
    ap = argparse.ArgumentParser(description='皮肤战斗模型 + 干员图库的提取入口（上游 extract.py 的两条 job）')
    ap.add_argument('--game', help='客户端 AssetBundle 根目录（…/StreamingAssets/AB/Windows）')
    ap.add_argument('--server', help='服务器 / 主项目检出：目录表与清单写在这里，也是 --out 的默认基准')
    ap.add_argument('--data-root', help='显式指定元数据的落地检出（默认 --server）')
    ap.add_argument('--out', help='美术输出目录（默认 <data-root>/public/assets/local）')
    ap.add_argument('--manifest', help='提取清单（默认 <data-root>/data/local-assets.json）')
    ap.add_argument('--only', choices=('both', 'skins', 'library'), default='both',
                    help='both 提取皮肤战斗模型与图库（默认），skins 只提 spine/op，library 只提图库三层')
    ap.add_argument('--skin', action='append', default=[], metavar='STEM',
                    help='只提这些模型 stem（可重复）；不给就是客户端里的全套')
    ap.add_argument('--library-tier', action='append', default=[], choices=('avatar', 'portrait', 'illust'),
                    help='只提图库的这些层（可重复，默认三层都提）')
    ap.add_argument('--print-jobs', action='store_true', help='打印上游的完整 job 表（调试用）并退出')
    ap.add_argument('--dry-run', action='store_true', help='只打印将要执行的路径与参数，不提取')
    args = ap.parse_args(argv)

    data_root = args.data_root or args.server
    if not data_root:
        raise SystemExit('要给 --server 或 --data-root（目录表与清单写在那里）')
    data_root = Path(data_root).expanduser().resolve()
    if not data_root.is_dir():
        raise SystemExit(f'--server/--data-root {data_root} 不是一个目录')
    out = Path(args.out).expanduser().resolve() if args.out else data_root / 'public/assets/local'
    manifest = Path(args.manifest).expanduser().resolve() if args.manifest else data_root / 'data/local-assets.json'

    module = load_upstream()
    rebase(module, data_root)

    upstream_argv = []
    if args.game:
        upstream_argv += ['--game', args.game]
    upstream_argv += ['--out', str(out), '--manifest', str(manifest)]
    for sub in {'both': ('spine/op', 'library'), 'skins': ('spine/op',), 'library': ('library',)}[args.only]:
        upstream_argv += ['--only', sub]
    for stem in args.skin:
        upstream_argv += ['--skin', stem]
    for tier in args.library_tier:
        upstream_argv += ['--library-tier', tier]
    if args.print_jobs:
        upstream_argv += ['--print-jobs']

    # 上游用 data/chess.json 与 data/backups.json 算"本项目实际出场的干员"，没有它们会一套都选不出来
    # （只有 --skin 显式点名时例外），所以这里先说清楚，而不是让它静默提取 0 套。
    plan_sources = [data_root / 'data/chess.json', data_root / 'data/backups.json']
    missing = [str(p) for p in plan_sources if not p.is_file()]
    if missing and not args.skin and not args.print_jobs:
        print(f'warn: {"、".join(missing)} 不存在 —— 上游无法枚举干员，皮肤会提取 0 套；'
              f'用 --skin <stem> 点名，或把 --data-root 指到完整的主项目检出', file=sys.stderr)
    if not args.print_jobs:
        library_index = data_root / 'tools/skin-library/library-index.json'
        if args.only in ('both', 'skins') and not library_index.is_file():
            print(f'warn: {library_index} 还不存在：上游按磁盘上的图库索引枚举客户端有哪些皮肤，'
                  f'而索引要到这次运行结尾才写，所以本次皮肤会提取 0 套。'
                  f'请先跑 --only library，再跑 --only skins', file=sys.stderr)
    if args.dry_run:
        print(f'data-root: {data_root}')
        print(f'python {UPSTREAM} ' + ' '.join(upstream_argv))
        return 0

    print(f'data-root: {data_root}')
    print(f'out: {out}')
    argv_backup = sys.argv
    sys.argv = [str(UPSTREAM)] + upstream_argv
    try:
        return module.main()
    finally:
        sys.argv = argv_backup


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
