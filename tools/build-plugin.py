"""从本机客户端的提取产物构建干员皮肤外观插件（manifest 2）——素材不进仓库。

**唯一的素材来源是本机客户端的提取产物**（`public/assets/local`）：提取里有多少套皮肤就收多少套，一套不落。
插件单包上限是 512 MB（主项目 `PLUGIN_CLASSES.cosmetic.bytes`，`pluginByteLimit('cosmetic')`）；
整套素材 382.5 MiB，所以**默认就是单包**（`--split auto`，目标 500 MiB），超过才按体积拆成多个包，
而不是靠丢掉立绘、跳过某批皮肤来凑数。

为什么是"本地构建"：官方美术（.skel/.atlas/.png）既不能进插件仓库（主项目 docs/PLUGINS.md §1），
也不能对外分发。本仓库只带脚本与说明；有客户端提取产物的机器跑本脚本生成 <repo>/operator-skin-select*/。

素材来源（都在本机，脚本只读它们，只复制/同卷硬链接/转码，从不写入源目录）：

  --extract    提取产物的 local 目录（默认探测 <server>/public/assets/local，
               D:\\project\\html\\sp-skins\\public\\assets\\local，主项目检出\\public\\assets\\local）
                 spine/op/<charId>/<stem>/{front,back}/<stem>.{skel,atlas,png}   战斗模型（273 套量级）
                 spine/op/<charId>/<stem>/illust.{png,jpg,webp}                   立绘
                 library/{opavatar,opportrait,opillust}/<id>/…                    头像 / 半身像 / 立绘

`--have` 是**可选**的跳过清单，只有在你想跳过某个外部资料库已经提供的集合时才用：它**不是默认路径**，
不给就没有 have-集合，提取里的每一套都收。`--downloaded` / `--dump` 那套"看看别的树里有没有"的双线逻辑已经去掉。

键与磁盘路径是两件事（主项目 shared/plugins/visual.js 的皮肤键 vs isPackPath）：

  * JSON 键  = 官方 skinId（char_003_kalts@boc#6）——路径里不允许 @ # +，键允许；
  * 磁盘路径 = stem（char_003_kalts_boc_6）；
  * 拿不到 skinId（没有目录表）时键退化成 stem，并打印警告。

skinId / name / group 的来源（tools/skin-catalogue.py 也是这套），按顺序取第一个拿到的：

  1. 主项目检出的目录表 tools/assets/local-skin-index.json（byStem: stem → skinId）
     与 data/skins-local.json（chars[charId].skins[skinId].name / .group）
  2. 主项目检出的官方表 .cache/gamedata/excel/skin_table.json（displaySkin.skinName / skinGroupName）
  3. 都没有：键 = stem，name / group 留空（只是警告，不是错误）

atlas 里的 `pma` 字段一律删掉（主项目 fix/extract-straight-pages 之后页面是直通 alpha）；
如果某个 atlas 里确实写着 `pma: true`，会打印警告——那说明这批提取来自旧提取器。

**立绘与 WebP**：`--images all`（默认）+ `--illust-format webp`（默认）把立绘一起收进来。源图是 PNG 无损，
WebP 是有损重编码，画质与体积由 `--illust-quality`（默认 85）与 `--illust-method`（Pillow 的编码档位，
默认 5）权衡；`--jobs` 用多进程并行转码（默认 min(4, CPU) 个 worker）。实测数据见 README §4。

**拆分**：`--split auto`（默认）按 skin 键排序后做"最小化最大包"的连续切分，目标每包 ≤ `--split-target`
（默认 500 MiB，给 512 MB 硬上限留余量；当前整套 382.5 MiB 因此是 1 个包）。超过目标时才产出 <out>、
<out>-2、<out>-3 …，每个文件夹有自己的 plugin.json（id 依次 operator-skin-select、operator-skin-select-2 …；
显示名带（i/n））与自己的素材目录。`--split 1` 就是强制单包（id 与显示名都不带后缀）。

  python tools/build-plugin.py [--server <服务器检出>] [--extract <local 目录>] [--main <主项目检出>]
                               [--out <插件文件夹>] [--split <n|auto>] [--split-target <MiB>]
                               [--have <file|ids>] [--gap-only] [--no-dump（已无 dump 依赖，兼容保留）]
                               [--images auto|all|small|none] [--illust-format none|png|webp]
                               [--illust-quality 1..100] [--illust-method 0..6] [--jobs N]
                               [--link auto|hard|copy] [--version x.y.z]
"""
import argparse
import io
import json
import os
import re
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.stdout.reconfigure(encoding='utf-8')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 主项目 shared/plugins/manifest.js：PLUGIN_LIMITS.pluginBytes = 200 MB 是默认上限；
# PLUGIN_CLASSES.cosmetic.bytes = 512 MB（pluginByteLimit('cosmetic')）是外观插件自己的上限。
PLUGIN_BYTES_LIMIT = 512 * 1024 * 1024
# 拆包时每个包的目标上限（给 512 MB 硬上限留余量）；见 --split-target。
SPLIT_TARGET_MIB = 500
# 每个包除了素材还有 assets.json 与 plugin.lock.json：按每套 8 KB 估算（本机实测约 5.5 KB/套），
# 另加一个固定余量，免得拆出来的包刚好越过目标。
PACK_OVERHEAD_PER_SKIN = 8 * 1024
PACK_OVERHEAD_FIXED = 256 * 1024

# 立绘（WebP）的编码参数：整批合计目标 ≤30 MiB（约 300 KB/张）。
WEBP_QUALITY = 85
WEBP_METHOD = 5      # Pillow 的 method：0 最快、6 最慢也最小；5 是体积/时间的平衡点（README §4 实测）
WEBP_JOBS = min(4, os.cpu_count() or 1)
# 立绘在提取目录里的文件名（按顺序取第一个存在的）。
ILLUSTR_NAMES = ('illust.png', 'illust.jpg', 'illust.webp')

# 主项目 shared/plugins/visual.js 的 SkinKey / isAssetKey，以及 shared/plugins/manifest.js 的 isPackPath。
SKIN_KEY = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_@#+.-]*$')
ASSET_KEY = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_./-]*$')
PACK_PATH_PART = re.compile(r'^[A-Za-z0-9._ -]+$')
PMA_LINE = re.compile(r'^\s*pma\s*:\s*(true|false)\s*$', re.I)
IMAGE_EXT = ('.png', '.jpg', '.webp')

DEFAULT_MAINS = (
    r'D:\project\html\Stronghold-Protocol',
    r'D:\project\html\sp-skins',
)
# --server 的默认探测顺序（服务器检出）：--extract 与 --main 的默认值都从它推。
DEFAULT_SERVERS = (
    r'D:\project\html\Stronghold-Protocol',
    r'E:\Stronghold-Protocol',
)
# --have 的清单形状：读其中的数组（downloads 清单是 skinId，磁盘目录名是 stem，两种都认）。
HAVE_KEYS = ('installed', 'skins', 'stems', 'ids', 'have')
# --extract 的默认探测顺序：sp-skins 的主提取优先，其次主项目检出。
DEFAULT_EXTRACTS = (
    r'D:\project\html\sp-skins\public\assets\local',
    r'D:\project\html\Stronghold-Protocol\public\assets\local',
)
# 构建报告：deploy.mjs 靠它拿到"这次产出了哪些包"，data/ 不进 git。
REPORT_PATH = os.path.join(REPO, 'data', 'build-report.json')

# 插件清单：id / name / description / authors / license / homepage 沿用仓库现有措辞（脚本会覆盖这份文件）。
BASE_ID = 'operator-skin-select'
DESC_ZH = ('干员皮肤素材：Spine 战斗模型（正/背面）+ 头像 + 半身像 + 立绘——全部来自本机客户端的提取产物。'
           '由使用者提取后本地构建，不随仓库或发布包分发。纯外观插件：服主安装，每个玩家在自己的浏览器里开启；'
           '没开启的人看到的是默认，包括看别人的。不改任何对局。')
DESC_EN = ('Operator skin assets: Spine battle models (front/back) + avatars + portraits + illustrations — '
           'all extracted from the local client. Built locally by the user after extracting them; never shipped '
           'with the repository or a release package. Cosmetic only: the server owner installs it, each player '
           'switches it on in their own browser; without it everything is the default, other players included.')
MANIFEST = {
    "manifest": 2,
    "id": BASE_ID,
    "name": {
        "zh": "干员皮肤选择插件",
        "en": "Operator skin selection",
    },
    "description": {
        "zh": DESC_ZH,
        "en": DESC_EN,
    },
    "version": "0.1.1",
    "app": ">=0.3.0 <0.4.0",
    "api": 1,
    "class": "cosmetic",
    "scope": ["personal"],
    "authors": ["Flotiarenor"],
    "license": "见 NOTICE.md（美术版权归 Hypergryph / Yostar，非商业同人用途）",
    "homepage": "https://github.com/Flotiarenor/arknights-skin-plugin",
    "assets": "assets.json",
    "permissions": ["assets.override"],
}


def say(text=''):
    print(text, flush=True)


def first_dir(candidates):
    for p in candidates:
        if p and os.path.isdir(p):
            return os.path.abspath(p)
    return None


def first_file(candidates):
    for p in candidates:
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    return None


def load_json(path):
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def safe_part(name):
    """一个路径分段是否安全（主项目 isPackPath：字母数字 . _ - 空格，不以 . 开头）。"""
    return bool(PACK_PATH_PART.match(name)) and name == name.strip() and not name.startswith('.')


class Entry:
    """一套皮肤的战斗模型：charId / stem / 每个朝向的目录 / 立绘 / 目录表带来的元数据。"""

    __slots__ = ('char_id', 'stem', 'facings', 'illust', 'skin_id', 'name', 'group', 'source')

    def __init__(self, char_id, stem, facings, illust, skin_id, name, group, source):
        self.char_id = char_id
        self.stem = stem
        self.facings = facings
        self.illust = illust
        self.skin_id = skin_id
        self.name = name
        self.group = group
        self.source = source


# ---- 目录表 -----------------------------------------------------------------------------------------------------------

def read_stem_index(path):
    """tools/assets/local-skin-index.json：byStem { stem: skinId }。"""
    data = load_json(path)
    by = data.get('byStem') if isinstance(data, dict) else None
    return {str(k): str(v) for k, v in (by or {}).items()}


def read_skins_meta(path):
    """data/skins-local.json：{ skinId: (name, group) } 以及 { stem: skinId }（从 spine 的文件名反推）。"""
    data = load_json(path)
    chars = data.get('chars') if isinstance(data, dict) else None
    meta = {}
    by_stem = {}
    for char_id, rec in (chars or {}).items():
        for skin_id, skin in ((rec or {}).get('skins') or {}).items():
            meta[str(skin_id)] = (skin.get('name') or '', skin.get('group') or '')
            for facing in ('front', 'back'):
                skel = (((skin or {}).get('spine') or {}).get(facing) or {}).get('skel')
                if isinstance(skel, str) and skel.endswith('.skel'):
                    stem = skel.rsplit('/', 1)[-1][:-len('.skel')]
                    by_stem.setdefault(stem, str(skin_id))
    return meta, by_stem


def read_skin_table(path):
    """主项目 .cache/gamedata/excel/skin_table.json：{ skinId: (name, group) } 官方显示名。"""
    data = load_json(path)
    skins = data.get('charSkins') if isinstance(data, dict) else None
    out = {}
    for skin_id, rec in (skins or {}).items():
        ds = (rec or {}).get('displaySkin') or {}
        out[str(skin_id)] = (ds.get('skinName') or '', ds.get('skinGroupName') or '')
    return out


# ---- 素材索引 ---------------------------------------------------------------------------------------------------------

def scan_extract(root):
    """提取 spine/op/<charId>/<stem>/{front,back} + <stem>/illust.png（唯一的素材来源）。"""
    out = {}
    op = os.path.join(root, 'spine', 'op')
    if not os.path.isdir(op):
        return out
    for char_id in sorted(os.listdir(op)):
        cdir = os.path.join(op, char_id)
        if not os.path.isdir(cdir):
            continue
        for stem in sorted(os.listdir(cdir)):
            sdir = os.path.join(cdir, stem)
            if not os.path.isdir(sdir):
                continue
            facings = {f: os.path.join(sdir, f) for f in ('front', 'back') if os.path.isdir(os.path.join(sdir, f))}
            if not facings:
                continue
            illust = next((os.path.join(sdir, n) for n in ILLUSTR_NAMES if os.path.isfile(os.path.join(sdir, n))), None)
            out[stem] = Entry(char_id, stem, facings, illust, None, None, None, os.path.join(root, 'spine', 'op'))
    return out


# ---- have-集合（可选：想跳过某个外部资料库已提供的集合时才给） ---------------------------------------------------------

def read_have_spec(value):
    """--have 的值：一个清单文件（JSON 或纯文本）或逗号分隔的 id/stem 列表 → (id 集合, 来源描述)。"""
    ids = set()
    if os.path.isfile(value):
        with open(value, encoding='utf-8') as fh:
            text = fh.read()
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if isinstance(data, dict):
            for key in HAVE_KEYS:
                if isinstance(data.get(key), list):
                    ids.update(str(v).strip() for v in data[key] if str(v).strip())
            if not ids:
                raise SystemExit(f'--have {value}：JSON 里找不到 {"/".join(HAVE_KEYS)} 里的任何一个数组')
        elif isinstance(data, list):
            ids.update(str(v).strip() for v in data if str(v).strip())
        else:
            ids.update(part for part in re.split(r'[\s,]+', text) if part)
        return ids, f'{os.path.abspath(value)}（{len(ids)} 个 id）'
    if os.sep in value or (os.altsep and os.altsep in value) or value.lower().endswith('.json'):
        raise SystemExit(f'--have {value}：不是一个文件（也不是 id 列表）')
    ids = {part.strip() for part in re.split(r'[\s,]+', value) if part.strip()}
    if not ids:
        raise SystemExit(f'--have {value!r}：既不是文件，也没有逗号分隔的 id')
    return ids, f'命令行（{len(ids)} 个 id）'


# ---- 一套皮肤的检查与计划 ---------------------------------------------------------------------------------------------

def model_problem(entry):
    """模型能不能收：.skel/.atlas/至少一张 .png，且目录名与文件名一致。返回原因或 None。"""
    if not safe_part(entry.stem) or not safe_part(entry.char_id):
        return f'名称不是安全路径（{entry.char_id!r} / {entry.stem!r}）'
    if not ASSET_KEY.match(entry.char_id):
        return f'charId {entry.char_id!r} 不是合法的条目键'
    for facing, src in sorted(entry.facings.items()):
        for ext in ('.skel', '.atlas'):
            if not os.path.isfile(os.path.join(src, entry.stem + ext)):
                return f'{facing} 缺少 {entry.stem + ext}'
        if not pages_of(src, entry.stem):
            return f'{facing} 没有图集页（.png）'
    return None


def pages_of(src, stem):
    """一个朝向目录里的图集页（atlas 的 textures）。"""
    try:
        names = sorted(os.listdir(src))
    except OSError:
        return []
    return [n for n in names if os.path.splitext(n)[1].lower() in IMAGE_EXT]


def library_image(root, skin_id, stem, tier, filename):
    """library/<tier>/<id>/<filename>：id 依次试 skinId 去 @、skinId、stem。

    这些目录名可能带 `#` `+`（皮肤键允许），它们是**读**的来源目录，不是插件里的路径，
    所以这里只拒绝路径分隔符与 `..`，不套 isPackPath。
    """
    for candidate in (str(skin_id).replace('@', '_'), str(skin_id), stem):
        if not candidate or '/' in candidate or '\\' in candidate or candidate in ('.', '..'):
            continue
        path = os.path.join(root, 'library', tier, candidate, filename)
        if os.path.isfile(path):
            return path
    return None


def illust_source(root, skin_id, stem, from_entry):
    """立绘源：模型目录里的 illust.* 优先，其次 library/opillust/<id>/illust.*。"""
    if from_entry:
        return from_entry
    if not root:
        return None
    for filename in ILLUSTR_NAMES:
        found = library_image(root, skin_id, stem, 'opillust', filename)
        if found:
            return found
    return None


def has_alpha(im):
    """这张图是不是带透明通道（WebP 要按 RGBA 编，否则透明处会变黑）。"""
    return im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info)


def webp_bytes(raw, quality, method):
    """把一张图的字节编码成 WebP 的字节（Pillow；带 alpha 走 RGBA，其余 RGB）。"""
    from PIL import Image  # 只有真的要转 WebP 才依赖 Pillow
    with Image.open(io.BytesIO(raw)) as src:
        im = src.convert('RGBA' if has_alpha(src) else 'RGB')
    buf = io.BytesIO()
    im.save(buf, format='WEBP', quality=quality, method=method)
    return buf.getvalue()


def illust_job(job):
    """子进程的活：读一张立绘 → 编码成 WebP → 写到暂存路径（多进程并行转码用）。"""
    src, dst, quality, method = job
    with open(src, 'rb') as fh:
        raw = fh.read()
    data = webp_bytes(raw, quality, method)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    part = dst + '.part'
    with open(part, 'wb') as fh:
        fh.write(data)
    os.replace(part, dst)
    return len(data)


# ---- 写文件 -----------------------------------------------------------------------------------------------------------

def strip_pma(text):
    """删掉 atlas 里的 pma 行；返回 (新文本, 是否写着 pma: true, 是否有改动)。"""
    kept = []
    saw_true = False
    changed = False
    for line in text.splitlines(True):
        if PMA_LINE.match(line.rstrip('\r\n')):
            changed = True
            if 'true' in line.lower():
                saw_true = True
            continue
        kept.append(line)
    return ''.join(kept), saw_true, changed


class Writer:
    """把源文件放进插件目录：优先同卷硬链接，失败则复制。硬链接前先摘掉旧目标（不会写到源文件上）。"""

    def __init__(self, mode):
        self.mode = mode
        self.links = 0
        self.copies = 0
        self.adopted = 0
        self.bytes = 0
        self.files = 0

    def put(self, src, dst, transform=None):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.lexists(dst):
            os.remove(dst)
        if transform is None and self.mode != 'copy':
            try:
                os.link(src, dst)
                self.links += 1
                self._count(dst)
                return 'link'
            except OSError:
                if self.mode == 'hard':
                    raise
        if transform is None:
            shutil.copyfile(src, dst)
        else:
            with open(src, 'rb') as fh:
                raw = fh.read()
            with open(dst, 'wb') as fh:
                fh.write(transform(raw))
        self.copies += 1
        self._count(dst)
        return 'copy'

    def adopt(self, src, dst):
        """把已经算好的文件（并行的 WebP 产物在暂存目录里）搬进来：同卷改名，瞬间完成。"""
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.lexists(dst):
            os.remove(dst)
        os.replace(src, dst)
        self.adopted += 1
        self._count(dst)

    def _count(self, path):
        self.files += 1
        self.bytes += os.path.getsize(path)


def clear(out, names):
    """只删插件目录里由本脚本生成的那几项；每一步都核对绝对路径确实在 <out> 下。"""
    root = os.path.abspath(out)
    for name in names:
        target = os.path.abspath(os.path.join(root, name))
        if os.path.dirname(target) != root:
            raise SystemExit(f'拒绝删除 {target}：不在 {root} 下')
        if os.path.isdir(target):
            shutil.rmtree(target)
        elif os.path.lexists(target):
            os.remove(target)


# ---- 拆分（确定性、按体积均衡） ---------------------------------------------------------------------------------------

def min_max_partition(sizes, k):
    """把 sizes 切成 k 段**连续**分组使最大段和最小（DP，精确解）。返回 (最大段和, [(起, 止), …])。

    连续切分保留"按 skin 键排序"的顺序：同样的输入永远得到同样的包，便于核对与续跑。
    """
    n = len(sizes)
    if n == 0:
        return 0, []
    if k <= 1:
        return sum(sizes), [(0, n)]
    prefix = [0] * (n + 1)
    for i, size in enumerate(sizes):
        prefix[i + 1] = prefix[i] + size
    inf = float('inf')
    dp = [[inf] * (n + 1) for _ in range(k + 1)]
    back = [[0] * (n + 1) for _ in range(k + 1)]
    dp[0][0] = 0
    for j in range(1, k + 1):
        for i in range(j, n + 1):
            best, best_p = inf, j - 1
            row = dp[j - 1]
            for p in range(j - 1, i):
                if row[p] == inf:
                    continue
                value = row[p] if row[p] > prefix[i] - prefix[p] else prefix[i] - prefix[p]
                if value < best:
                    best, best_p = value, p
            dp[j][i], back[j][i] = best, best_p
    if dp[k][n] == inf:
        return inf, []
    bounds = []
    i = n
    for j in range(k, 0, -1):
        p = back[j][i]
        bounds.append((p, i))
        i = p
    bounds.reverse()
    return dp[k][n], bounds


def choose_split(sizes, want, target):
    """决定拆几个包 → (包数, 最大包估算, [(起, 止), …])。

    want 给了就是它（1 = 不拆）；auto = 从 ceil(总体积/目标) 起往上试，第一个让最大包 ≤ 目标的包数就是答案。
    """
    n = len(sizes)
    total = sum(sizes)
    if want is not None:
        k = max(1, min(want, n))
        worst, bounds = min_max_partition(sizes, k)
        return k, worst, bounds
    if n == 0:
        return 1, 0, []
    start = max(1, -(-total // max(1, target)))
    best = None
    for k in range(start, min(n, start + 8) + 1):
        worst, bounds = min_max_partition(sizes, k)
        best = (k, worst, bounds)
        if worst <= target:
            break
    return best


def package_id(base, index):
    """第 index 个包（1 起）的插件 id：第一个沿用文件夹名，其余加 -N 后缀（上游以**文件夹名**为准）。"""
    return base if index == 1 else f'{base}-{index}'


def package_manifest(base, index, total, count, version):
    manifest = dict(MANIFEST)
    manifest['version'] = version
    manifest['id'] = package_id(base, index)
    if total > 1:
        manifest['name'] = {
            'zh': f'{MANIFEST["name"]["zh"]}（{index}/{total}）',
            'en': f'{MANIFEST["name"]["en"]} ({index}/{total})',
        }
        manifest['description'] = {
            'zh': f'{DESC_ZH}（插件单包上限 {PLUGIN_BYTES_LIMIT // 1048576} MB，全部皮肤拆成 {total} 个包，这是第 {index} 个，装 {count} 套。）',
            'en': f'{DESC_EN} (One plugin folder may hold {PLUGIN_BYTES_LIMIT // 1048576} MB, so all skins are split into {total} '
                  f'packages; this is package {index} of {total}, {count} skins.)',
        }
    return manifest


def prune_stale_packages(base_out, keep):
    """删掉上一轮拆出来、这一轮不再需要的 <base>-N 文件夹（只删 id 对得上的插件目录）。"""
    removed = []
    parent = os.path.dirname(os.path.abspath(base_out)) or '.'
    stem = os.path.basename(os.path.abspath(base_out))
    try:
        names = sorted(os.listdir(parent))
    except OSError:
        return removed
    for name in names:
        if name == stem or not name.startswith(stem + '-'):
            continue
        suffix = name[len(stem) + 1:]
        if not suffix.isdigit():
            continue
        target = os.path.join(parent, name)
        if target in keep or not os.path.isdir(target):
            continue
        manifest = os.path.join(target, 'plugin.json')
        if not os.path.isfile(manifest):
            continue
        try:
            plugin = load_json(manifest)
        except ValueError:
            continue
        if plugin.get('id') != name:
            continue
        shutil.rmtree(target)
        removed.append(target)
    return removed


def dir_stats(root):
    total = 0
    files = 0
    for base, _, names in os.walk(root):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                continue
            files += 1
    return files, total


# ---- 构建 -------------------------------------------------------------------------------------------------------------

def build(args):
    warnings = []
    skips = []
    started = time.perf_counter()

    quality = WEBP_QUALITY if args.illust_quality is None else args.illust_quality
    if not 1 <= quality <= 100:
        raise SystemExit(f'--illust-quality {quality} 不在 1..100')
    method = WEBP_METHOD if args.illust_method is None else args.illust_method
    if not 0 <= method <= 6:
        raise SystemExit(f'--illust-method {method} 不在 0..6')
    jobs = max(1, min(args.jobs if args.jobs else WEBP_JOBS, os.cpu_count() or 1))
    if args.illust_quality is not None and args.illust_format != 'webp':
        warnings.append(f'--illust-quality 只对 --illust-format webp 有效（当前 {args.illust_format}）')
    if args.illust_method is not None and args.illust_format != 'webp':
        warnings.append(f'--illust-method 只对 --illust-format webp 有效（当前 {args.illust_format}）')
    target = int((args.split_target or SPLIT_TARGET_MIB) * 1024 * 1024)
    if target <= 0 or target > PLUGIN_BYTES_LIMIT:
        raise SystemExit(f'--split-target {args.split_target} 要在 1..{PLUGIN_BYTES_LIMIT // 1048576} MiB 之间')

    server = first_dir([args.server] if args.server else list(DEFAULT_SERVERS))
    if args.server and not server:
        raise SystemExit(f'--server {args.server} 不是一个目录')
    # 目录表与官方表从"主项目检出"读；部署时服务器检出就是主项目检出，所以 --server 也当 --main 用。
    main = first_dir([args.main] if args.main else ([server] if server else []) + list(DEFAULT_MAINS))
    if args.main and not main:
        raise SystemExit(f'--main {args.main} 不是一个目录')
    extract_candidates = ([args.extract] if args.extract else
                          ([os.path.join(server, 'public', 'assets', 'local')] if server else []) + list(DEFAULT_EXTRACTS))
    extract = first_dir(extract_candidates)
    if not extract:
        hint = ('--extract 指向客户端提取产物的 public/assets/local（spine/op/<charId>/<stem>/），'
                '或 --server 指向服务器检出（默认取它的 public/assets/local）。')
        raise SystemExit(f'找不到提取产物。\n  {hint}\n  找过：{"；".join(extract_candidates)}')

    entries = scan_extract(extract)
    if not entries:
        raise SystemExit(f'{extract} 里没有 spine/op/<charId>/<stem>/ 这样的皮肤目录')
    used = [f'提取 {extract}']
    if not main:
        warnings.append(f'找不到主项目检出（默认候选：{"；".join(DEFAULT_MAINS)}），目录表与官方表都读不到')

    # 目录表
    index_path = first_file([args.skin_index] if args.skin_index else
                            [os.path.join(main, 'tools', 'assets', 'local-skin-index.json')] if main else [])
    meta_path = first_file([args.skins_meta] if args.skins_meta else
                           [os.path.join(main, 'data', 'skins-local.json')] if main else [])
    table_path = first_file([args.skin_table] if args.skin_table else
                            [os.path.join(main, '.cache', 'gamedata', 'excel', 'skin_table.json')] if main else [])

    by_stem = read_stem_index(index_path) if index_path else {}
    skins_meta, meta_by_stem = read_skins_meta(meta_path) if meta_path else ({}, {})
    skin_table = read_skin_table(table_path) if table_path else {}
    if not index_path:
        warnings.append('找不到目录表 tools/assets/local-skin-index.json'
                        '（主项目 feat/skins 分支上有；本机也可由 tools/local-extract 生成）——'
                        'skinId 退化：有 data/skins-local.json 时从模型文件名反推，否则键=stem')
    if not meta_path and not table_path:
        warnings.append('找不到 data/skins-local.json 与官方 skin_table.json —— name/group 留空')

    # have-集合：**只在显式给了 --have 时才有**（想跳过某个外部资料库已提供的集合时才用）。
    have = have_source = None
    if args.have:
        have, have_source = read_have_spec(args.have)
    elif args.gap_only:
        raise SystemExit('--gap-only 需要同时给 --have <文件|ids>；不给 --have 时默认就是收提取里的全部')

    # 收套：默认收提取里的全部；给了 --have 就跳过命中的那些。
    chosen = []
    skipped_have = []
    for stem in sorted(entries):
        entry = entries[stem]
        skin_id = by_stem.get(stem) or entry.skin_id or meta_by_stem.get(stem) or stem
        skin_id = str(skin_id)
        if have is not None and (stem in have or skin_id in have):
            skipped_have.append(stem)
            continue
        why = model_problem(entry)
        if why:
            skips.append((stem, why))
            continue
        if not (SKIN_KEY.match(skin_id) and len(skin_id) <= 64):
            skips.append((stem, f'skinId {skin_id!r} 不是合法的皮肤键'))
            continue
        name = entry.name if entry.name and entry.name != skin_id else ''
        group = entry.group or ''
        for source in (skins_meta.get(skin_id), skin_table.get(skin_id)):
            if not source:
                continue
            if not name and source[0] and source[0] != skin_id:
                name = source[0]
            if not group and source[1]:
                group = source[1]
        name = (name or '').strip()[:64]
        group = (group or '').strip()[:64]
        chosen.append({'entry': entry, 'skin_id': skin_id, 'name': name, 'group': group,
                       'key_from': 'index' if stem in by_stem else
                                   ('meta' if stem in meta_by_stem else 'stem')})

    if not chosen:
        raise SystemExit('没有可收录的皮肤（检查 --extract / --have）')

    # 图片：默认全收（模型 + 头像 + 半身像 + 立绘）；单包上限由 --split 负责。
    mode = args.images
    if mode == 'auto':
        mode = 'all'   # auto 的旧含义是"按旧上限砍掉立绘"，现在上限由拆包承担
    order = {'all': ('avatar', 'portrait', 'illust'), 'small': ('avatar', 'portrait'), 'none': ()}
    keep = list(order[mode])
    if 'illust' in keep and args.illust_format == 'none':
        keep = [k for k in keep if k != 'illust']
        warnings.append('--illust-format none：本次不含立绘（模型 + 头像 + 半身像）')
    wants_illust = 'illust' in keep

    for item in chosen:
        entry = item['entry']
        root = extract
        avatar = library_image(root, item['skin_id'], entry.stem, 'opavatar', 'image.png')
        portrait = library_image(root, item['skin_id'], entry.stem, 'opportrait', 'image.png')
        illust = illust_source(root, item['skin_id'], entry.stem, entry.illust)
        item['avatar'], item['portrait'], item['illust'] = avatar, portrait, illust
        item['illust_dst'] = None
        if illust and wants_illust:
            ext = os.path.splitext(illust)[1].lower()
            ext = ext if ext in IMAGE_EXT else '.png'
            item['illust_dst'] = 'illust.webp' if (args.illust_format == 'webp' and ext != '.webp') else f'illust{ext}'

    # 立绘转码：先并行写进暂存目录（拿到精确体积，拆分才能算准），再按包搬进去。
    staging = None
    illust_bytes = 0
    converted = kept_webp = 0
    if wants_illust:
        todo = [(item, item['illust']) for item in chosen if item['illust']]
        illust_bytes = sum(os.path.getsize(src) for _, src in todo)
        webp_todo = [item for item, src in todo if item['illust_dst'] == 'illust.webp' and not src.lower().endswith('.webp')]
        if webp_todo:
            staging = os.path.join(os.path.dirname(os.path.abspath(args.out)), '.build-illust-staging')
            if os.path.isdir(staging):
                shutil.rmtree(staging)
            plan = []
            for item in webp_todo:
                item['staged'] = os.path.join(staging, item['entry'].stem + '.webp')
                plan.append((item['illust'], item['staged'], quality, method))
            say(f'  立绘转码：{len(plan)} 张 → WebP（quality {quality}，method {method}，'
                f'{jobs} 个 worker，源图 {illust_bytes / 1048576:.1f} MiB）')
            done_started = time.perf_counter()
            if jobs == 1:
                for i, size in enumerate((illust_job(job) for job in plan), 1):
                    if i % 25 == 0 or i == len(plan):
                        say(f'    {i}/{len(plan)}')
            else:
                with ProcessPoolExecutor(max_workers=jobs) as pool:
                    for i, size in enumerate(pool.map(illust_job, plan, chunksize=1), 1):
                        if i % 25 == 0 or i == len(plan):
                            say(f'    {i}/{len(plan)}')
            converted = len(plan)
            say(f'    转码用时 {time.perf_counter() - done_started:.1f}s')

    # 每套的落地体积（立绘用暂存文件的精确值）→ 拆包
    for item in chosen:
        entry = item['entry']
        size = 0
        for src in entry.facings.values():
            try:
                names = os.listdir(src)
            except OSError:
                names = []
            size += sum(os.path.getsize(os.path.join(src, n)) for n in names)
        for kind in ('avatar', 'portrait'):
            if kind in keep and item[kind]:
                size += os.path.getsize(item[kind])
        if item['illust_dst'] and item['illust']:
            size += os.path.getsize(item.get('staged') or item['illust'])
        item['size'] = size + PACK_OVERHEAD_PER_SKIN

    # 排序键：skinId（JSON 键）优先，同键时用 stem —— 纯确定性，拆包结果可复现。
    chosen.sort(key=lambda i: (i['skin_id'], i['entry'].stem))
    want = None
    if args.split not in (None, 'auto'):
        try:
            want = int(args.split)
        except ValueError:
            raise SystemExit(f'--split {args.split!r} 既不是整数也不是 auto')
        if want < 1:
            raise SystemExit(f'--split {want} 至少是 1')
    # 每个包除了素材还有 plugin.json + assets.json + plugin.lock.json：留出固定余量再切。
    count, worst, bounds = choose_split([i['size'] for i in chosen], want, max(1, target - PACK_OVERHEAD_FIXED))
    groups = [chosen[a:b] for a, b in bounds] if bounds else [chosen]
    if count > 1 and worst > target:
        warnings.append(f'拆成 {count} 个包后最大的包仍约 {worst / 1048576:.1f} MiB，超过目标 '
                        f'{target / 1048576:.0f} MiB —— 提高 --split 的包数或降低 --illust-quality')

    # 写：每个包一个文件夹、自己的 plugin.json 与 assets.json
    base_out = os.path.abspath(args.out)
    base_id = os.path.basename(base_out)
    if not re.match(r'^[a-z0-9][a-z0-9-]{1,31}$', base_id):
        raise SystemExit(f'--out 的文件夹名 {base_id!r} 不是合法的插件 id（2–32 个小写字母/数字/-）：'
                         f'上游以文件夹名为准，改个名字或换 --out')
    silent_pma = []
    packages = []
    illust_out_bytes = 0
    for index, group in enumerate(groups, 1):
        out = base_out if index == 1 else f'{base_out}-{index}'
        clear(out, ('spine', 'skin', 'assets.json', 'plugin.lock.json'))
        os.makedirs(out, exist_ok=True)
        writer = Writer(args.link)
        chars = {}
        for item in group:
            entry = item['entry']
            for facing, src in sorted(entry.facings.items()):
                dst_dir = os.path.join(out, 'spine', entry.stem, facing)
                for name in pages_of(src, entry.stem) + [entry.stem + '.skel', entry.stem + '.atlas']:
                    source = os.path.join(src, name)
                    dest = os.path.join(dst_dir, name)

                    def transform(raw, stem=entry.stem):
                        text = raw.decode('utf-8')
                        new, saw_true, changed = strip_pma(text)
                        if saw_true and stem not in silent_pma:
                            silent_pma.append(stem)
                        return raw if not changed else new.encode('utf-8')

                    if name.endswith('.atlas'):
                        writer.put(source, dest, transform)
                    else:
                        writer.put(source, dest)
            rec = {}
            if item['name']:
                rec['name'] = item['name']
            if item['group']:
                rec['group'] = item['group']
            for kind in ('avatar', 'portrait'):
                if kind in keep and item[kind]:
                    writer.put(item[kind], os.path.join(out, 'skin', entry.stem, f'{kind}.png'))
                    rec[kind] = f'skin/{entry.stem}/{kind}.png'
            if item['illust_dst'] and item['illust']:
                dest = os.path.join(out, 'skin', entry.stem, item['illust_dst'])
                if item.get('staged'):
                    writer.adopt(item['staged'], dest)
                elif item['illust_dst'] == 'illust.webp':
                    writer.put(item['illust'], dest, lambda raw, q=quality, m=method: webp_bytes(raw, q, m))
                else:
                    writer.put(item['illust'], dest)
                    kept_webp += 1
                rec['illust'] = f'skin/{entry.stem}/{item["illust_dst"]}'
                illust_out_bytes += os.path.getsize(dest)
            spine = {}
            for facing, src in sorted(entry.facings.items()):
                spine[facing] = {
                    'skel': f'spine/{entry.stem}/{facing}/{entry.stem}.skel',
                    'atlas': f'spine/{entry.stem}/{facing}/{entry.stem}.atlas',
                    'textures': [f'spine/{entry.stem}/{facing}/{p}' for p in pages_of(src, entry.stem)],
                }
            rec['spine'] = spine
            chars.setdefault(entry.char_id, {}).setdefault('skins', {})[item['skin_id']] = rec

        manifest = package_manifest(base_id, index, len(groups), len(group), args.version)
        with open(os.path.join(out, 'plugin.json'), 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
            fh.write('\n')
        with open(os.path.join(out, 'assets.json'), 'w', encoding='utf-8', newline='\n') as fh:
            json.dump({'chars': chars}, fh, ensure_ascii=False, indent=1)
            fh.write('\n')

        files, total = dir_stats(out)
        packages.append({'id': manifest['id'], 'dir': out, 'index': index, 'packages': len(groups),
                         'name': manifest['name']['zh'], 'skins': len(group), 'chars': len(chars),
                         'files': files, 'bytes': total, 'estimated': sum(i['size'] for i in group),
                         'stems': [i['entry'].stem for i in group]})

    if staging and os.path.isdir(staging):
        shutil.rmtree(staging, ignore_errors=True)
    removed = prune_stale_packages(base_out, {p['dir'] for p in packages})

    grand_files = sum(p['files'] for p in packages)
    grand_bytes = sum(p['bytes'] for p in packages)
    only_front = [i['entry'].stem for i in chosen if 'back' not in i['entry'].facings]
    from collections import Counter
    keys = Counter(i['key_from'] for i in chosen)
    skins_all = len(chosen)

    say()
    say(f'插件：{base_out}' + (f' 等 {len(packages)} 个包' if len(packages) > 1 else ''))
    say(f'  素材来源：{"；".join(used)}')
    say(f'  收录 {skins_all} 套 / {len({i["entry"].char_id for i in chosen})} 个干员 / {grand_files} 个文件 / '
        f'{grand_bytes / 1048576:.1f} MiB')
    say(f'  键：skinId（目录表 {keys["index"]}，文件名反推 {keys["meta"]}，退化 stem {keys["stem"]}）；路径：stem')
    say(f'  图片：{mode}（头像 {sum(1 for i in chosen if i["avatar"])}，半身像 {sum(1 for i in chosen if i["portrait"])}，'
        f'立绘 {sum(1 for i in chosen if i["illust_dst"])}）')
    if wants_illust:
        written = sum(1 for i in chosen if i['illust_dst'])
        say(f'  立绘：{written} 张 / {illust_out_bytes / 1048576:.1f} MiB（源图 {illust_bytes / 1048576:.1f} MiB；'
            f'平均 {illust_out_bytes / written / 1024 if written else 0:.0f} KB/张；'
            f'WebP 重编码 {converted} 张，原样保留 {kept_webp} 张，quality {quality}，method {method}）')
    say(f'  拆分：--split {args.split} → {count} 个包（目标每包 ≤ {target / 1048576:.0f} MiB，'
        f'最大包估算 {worst / 1048576:.1f} MiB，实际最大 {max(p["bytes"] for p in packages) / 1048576:.1f} MiB）')
    say()
    say(f'  {"包":<34}{"套":>5}{"干员":>6}{"文件":>7}{"体积":>12}  check')
    for package in packages:
        flag = '' if package['bytes'] <= PLUGIN_BYTES_LIMIT else f'  ← 超过 {PLUGIN_BYTES_LIMIT // 1048576} MB'
        say(f'  {package["id"]:<34}{package["skins"]:>5}{package["chars"]:>6}{package["files"]:>7}'
            f'{package["bytes"] / 1048576:>10.1f} MiB{flag}')
        if package['bytes'] > PLUGIN_BYTES_LIMIT:
            warnings.append(f'{package["id"]} 体积 {package["bytes"] / 1048576:.1f} MiB 超过插件上限 {PLUGIN_BYTES_LIMIT // 1048576} MB，'
                            f'check 会报 PLUGIN_FILE_SIZE')
    if removed:
        say(f'  已删除上一轮多出来的包：{"，".join(os.path.basename(r) for r in removed)}')
    named = sum(1 for i in chosen if i['name'])
    say(f'  name {named}/{skins_all}，group {sum(1 for i in chosen if i["group"])}/{skins_all}；'
        f'只有正面没有背面：{len(only_front)} 套')
    if skipped_have:
        say(f'  跳过 {len(skipped_have)} 套（--have 命中：外部资料库已有）')
    if skips:
        say(f'  跳过 {len(skips)} 套（模型不全或键不合法）：')
        for stem, why in skips:
            say(f'    {stem}：{why}')
    for stem in silent_pma:
        say(f'  警告：{stem} 的 atlas 里写着 pma: true —— 这批提取来自旧提取器，页面是预乘 alpha，渲染会偏暗')
    for text in warnings:
        say(f'  警告：{text}')
    if not index_path:
        say('  提示：目录表在主项目 feat/skins 分支上是 tools/assets/local-skin-index.json；'
            '本机也可由主项目 tools/local-extract 生成 data/skins-local.json。')
    say()
    say('  下一步：')
    for package in packages:
        say(f'    node <主项目>/tools/plugin.mjs pack  {package["dir"]}   # 写 plugin.lock.json（本地）')
        say(f'    node <主项目>/tools/plugin.mjs check {package["dir"]}   # 应为 0 problem / 0 warning')
    say(f'  构建用时 {time.perf_counter() - started:.1f}s')

    report = {
        'version': args.version,
        'at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'extract': extract,
        'skins': skins_all,
        'files': grand_files,
        'bytes': grand_bytes,
        'split': args.split,
        'target_bytes': target,
        'illust': {'format': args.illust_format, 'quality': quality, 'method': method, 'jobs': jobs,
                   'count': sum(1 for i in chosen if i['illust_dst'])},
        'packages': [{k: v for k, v in p.items() if k not in ('stems', 'walked', 'estimated')} for p in packages],
    }
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
        fh.write('\n')
    say(f'  构建报告：{REPORT_PATH}（deploy.mjs 靠它拿到这次的包）')
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description='从本机客户端提取产物构建 operator-skin-select*（素材不进仓库）')
    ap.add_argument('--server', help='服务器检出（默认探测 %s）：--extract 与目录表的默认值从这里推'
                                     % '；'.join(DEFAULT_SERVERS))
    ap.add_argument('--extract', help='提取产物的 local 目录（默认 <server>/public/assets/local，其次 sp-skins、主项目检出）')
    ap.add_argument('--have', metavar='FILE|IDS',
                    help='**可选**的跳过清单：一个 JSON 文件（读它的 installed / skins / stems / ids / have 数组，'
                         '或裸数组）或逗号分隔的 skinId/stem。只有在你想跳过某个外部资料库已经提供的集合时才用；'
                         '不给就是收提取里的全部')
    ap.add_argument('--gap-only', action='store_true',
                    help='只收 --have 里没有的（等价于"给了 --have"；不给 --have 会报错。旧的默认行为，现在需要显式给）')
    ap.add_argument('--no-dump', action='store_true',
                    help='兼容保留：素材来源现在只有本机提取，dump 那条线已经去掉，这个开关是空操作')
    ap.add_argument('--out', default=os.path.join(REPO, BASE_ID),
                    help='插件文件夹（默认 <repo>/operator-skin-select）；拆包时还会产出 <out>-2、<out>-3 …')
    ap.add_argument('--split', default='auto', metavar='n|auto',
                    help='拆成几个包（auto = 默认：按 --split-target 自动定；1 = 不拆，id 与显示名都不带后缀）')
    ap.add_argument('--split-target', type=float, default=SPLIT_TARGET_MIB, metavar='MiB',
                    help=f'每包的目标上限（默认 {SPLIT_TARGET_MIB} MiB；外观插件硬上限 {PLUGIN_BYTES_LIMIT // 1048576} MB，留余量）')
    ap.add_argument('--version', default=MANIFEST['version'], help='插件版本（默认 %(default)s）')
    ap.add_argument('--images', choices=('auto', 'all', 'small', 'none'), default='all',
                    help='图片：all 全收（模型 + 头像 + 半身像 + 立绘，默认；auto 是它的旧名），'
                         'small 只要头像+半身像，none 只要模型')
    ap.add_argument('--illust-format', choices=('none', 'png', 'webp'), default='webp',
                    help='立绘（只在 --images all 下生效）：webp 转 WebP（默认，有损），png 原样复制（会很大），none 不收')
    ap.add_argument('--illust-quality', type=int, default=None, metavar='1..100',
                    help=f'WebP 的 quality（默认 {WEBP_QUALITY}；越低越小越糊）')
    ap.add_argument('--illust-method', type=int, default=None, metavar='0..6',
                    help=f'WebP 的 Pillow method：0 最快、6 最慢也最小（默认 {WEBP_METHOD}；实测见 README §4）')
    ap.add_argument('--jobs', type=int, default=None, metavar='N',
                    help=f'立绘转码的并行进程数（默认 min(4, CPU) = {WEBP_JOBS}；1 = 不并行）')
    ap.add_argument('--link', choices=('auto', 'hard', 'copy'), default='auto', help='素材落地方式（默认同卷硬链接，失败则复制）')
    ap.add_argument('--main', help='主项目检出（目录表与官方表从这里读）')
    ap.add_argument('--skin-index', help='tools/assets/local-skin-index.json 的位置')
    ap.add_argument('--skins-meta', help='data/skins-local.json 的位置')
    ap.add_argument('--skin-table', help='.cache/gamedata/excel/skin_table.json 的位置')
    args = ap.parse_args(argv)
    if args.no_dump:
        pass  # 素材来源只有本机提取：这个开关已无实际作用，保留只为兼容旧命令行
    if args.gap_only and not args.have:
        raise SystemExit('--gap-only 需要同时给 --have <文件|ids>')
    return build(args)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
