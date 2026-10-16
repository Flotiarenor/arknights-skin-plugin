# arknights-skin-plugin — 干员皮肤外观插件（本地构建工具箱）

给《卫戍协议：盟约》同人复刻 [Stronghold-Protocol](https://github.com/sganggs/Stronghold-Protocol) 用的
**外观插件**：把干员皮肤素材（Spine 战斗模型的正/背面、头像、半身像、立绘）做成若干个
`operator-skin-select*` 插件文件夹，装进服务器的 `plugins/`。

**本仓库只带脚本、目录表与说明，一套素材都不带**：所有 `.skel` / `.atlas` / `.png` 都只能在
**使用者自己的机器上**从**使用者的客户端**提取后现场构建。原因有两条：这些是《明日方舟》的官方美术，主项目
[docs/PLUGINS.md](https://github.com/sganggs/Stronghold-Protocol/blob/feat/plugin-keys/docs/PLUGINS.md) §1 明确要求
**插件不得携带官方游戏文件**；本仓库同样不把它们提交进 git、不做成 zip / Release / 网盘分发。所以你拿到的是
「怎么在自己机器上做出来」的全部步骤与工具，而不是成品素材。

> 非官方、非商业同人用途。美术版权归 Hypergryph（上海鹰角网络）/ Yostar，详见 [NOTICE.md](NOTICE.md)。
> 权利人要求即删除。

---

## 目录

1. [这是什么、仓库里有什么](#1-这是什么仓库里有什么)
2. [前置条件](#2-前置条件)
3. [一键部署：`node deploy.mjs`](#3-一键部署node-deploymjs)
4. [参数表](#4-参数表)
5. [包拆分：为什么是多个包](#5-包拆分为什么是多个包)
6. [目录表 `catalogue/skins.json`](#6-目录表-catalogueskinsjson)
7. [手动跑每一步](#7-手动跑每一步)
8. [体积、立绘与 WebP 取舍](#8-体积立绘与-webp-取舍)
9. [常见问题](#9-常见问题)
10. [不要做](#10-不要做)
11. [许可与出处](#11-许可与出处)
12. [附录：交付时实际核对过的命令与结果](#12-附录交付时实际核对过的命令与结果)

---

## 1. 这是什么、仓库里有什么

一条命令把「本机客户端 → 提取 → 目录表 → 构建 → 拆包 → pack → check → 装进 `plugins/`」整条链跑完：

```bash
node deploy.mjs --server <服务器检出> --game "<客户端 AB\Windows>" --yes
```

| | |
| --- | --- |
| 仓库里有的 | `deploy.mjs`（一键部署九步）、`extract/`（自带的客户端提取器：`extract.py` / `scenes.py` / `aklz4.py` / `skins.py`）、`tools/build-plugin.py`（构建 + 拆包）、`tools/skin-catalogue.py`（生成目录表）、`tools/local-catalogue.py`（生成随仓库分发的那份目录表）、`tools/bench-webp.py`（WebP 基准）、**`catalogue/skins.json`**（273 套皮肤的纯元数据目录表，见 §6）、`operator-skin-select/plugin.json`（清单模板，构建会覆盖它）、`LICENSE`（GPL-3.0 全文，**只为 `extract/` 而放**，见 §11）、本说明、`NOTICE.md` |
| 仓库里没有的 | 所有 `.skel` / `.atlas` / `.png`，以及生成物 `assets.json`、`plugin.lock.json`、`data/`、拆出来的 `operator-skin-select*/` 素材目录、`.build-illust-staging/`、`.deploy/`、`dist/`（见 `.gitignore`；`git status --ignored` 可核对） |
| 素材唯一的来源 | `<服务器检出>/public/assets/local` —— 本机客户端的提取产物。提取里有多少套就收多少套，**没有远程素材库、没有社区 dump、没有"补差"清单** |
| 插件类别 | `class: cosmetic` · `scope: ["personal"]` · `permissions: ["assets.override"]`（`operator-skin-select/plugin.json`） |
| 单包上限 | **200 MiB（209,715,200 字节）**，另加 5000 个文件、单个 JSON 8 MB（主项目 `shared/plugins/manifest.js` 的 `PLUGIN_LIMITS`） |

服务器只需要最终的插件文件夹：**提取器跟着本仓库走，不并进主项目**。

> `operator-skin-select/plugin.json` 是**第 1 个包的清单**（构建脚本每次都会覆盖它）。它在仓库里只是为了
> 让人看清楚清单长什么样；这个文件夹里的 `assets.json` / `spine/` / `skin/` 都不在 git 里，**不要**把仓库里
> 这个文件夹直接拷进 `plugins/`——那会是一个缺素材的插件（`check` 会报 `PLUGIN_FILE_MISSING`）。

---

## 2. 前置条件

| 需要 | 说明 |
| --- | --- |
| **Node.js** | 跑 `deploy.mjs` 与主项目的 `tools/plugin.mjs`。`deploy.mjs` 是纯 ESM、无第三方依赖。本机核对用 node v24.21.0 |
| **Python 3** | 跑 `extract/` 与 `tools/*.py`。`deploy.mjs` 第 2 步会在 `<服务器检出>/.venv-extract` 里自动建 venv 并 `pip install -r extract/requirements.txt`（`UnityPy>=1.25`、`lz4>=4`、`Pillow>=10`）。**除这一次 pip 之外整条链不联网** |
| **本机安装的游戏客户端** | 需要客户端里的 AssetBundle 根目录，Windows 上的形态就是：<br>`…\Arknights_Data\StreamingAssets\AB\Windows`<br>（例如 `C:\Program Files\Hypergryph Launcher\games\Arknights\Arknights_Data\StreamingAssets\AB\Windows`）<br>这个目录下应当有 `skinpack\`（本机实测 426 个 `*.ab`），`deploy.mjs` 第 1 步会数它。不给 `--game` 时按「上次记录 → 常见路径探测」找：Hypergryph 启动器的两处 Program Files、bilibili 端的 `E:\arknight endfield\…`、macOS 的 CrossOver 瓶与容器路径 |
| **主项目是带「外观插件皮肤载体」的版本** | 也就是 **`feat/plugin-keys` 那条线（或并入它之后的 master）**：皮肤键 `chars[<charId>].skins[<skinId>]`、`name` / `group` 字段、`plugin.lock.json` 的模型剪辑数据、`node tools/plugin.mjs pack/check/list`，都在那条线上。`plugin.json` 写的是 `app: ">=0.3.0 <0.4.0"`、`api: 1`，与 `feat/plugin-keys`（`APP_VERSION = '0.3.0'`、`PLUGIN_API = { current: 1, min: 1 }`）一致。<br>**核对方法**：`git -C <服务器检出> log --oneline -1 feat/plugin-keys`、`ls <服务器检出>/tools/plugin.mjs`、`ls <服务器检出>/shared/plugins/visual.js`。实测 `origin/master`（0.2.6）上根本没有 `shared/plugins/`，也没有 `tools/plugin.mjs`，装不了这个插件 |
| **磁盘** | 客户端本身，加上提取产物 `<服务器检出>/public/assets/local`（本机这份是 **1652.7 MiB / 7873 个文件**——它可能不止皮肤：敌人 / token 的 Spine、图库原图等都在里面），再加上拆出来的包（**384.9 MiB**）；`--link auto` 在同卷时用硬链接，能省掉一份素材的占用 |

---

## 3. 一键部署：`node deploy.mjs`

### 3.1 命令

```bash
node deploy.mjs --server "E:\Stronghold-Protocol" \
                --game "C:\Program Files\Hypergryph Launcher\games\Arknights\Arknights_Data\StreamingAssets\AB\Windows" \
                --yes
```

* `--server` 必填：服务器检出（提取产物、`tools/plugin.mjs`、`plugins/` 都在它下面）。
* `--game` 可省：省略时用 `.deploy/state.json` 里上次记下的路径，再不行就探测常见安装位置。
* `--yes`：不问就执行。**标准输入不是终端时没有 `--yes` 会直接退出（码 2）**；先看命令用 `--dry-run`。
* 想换立绘参数 / 拆包口径，加 `--illust-*`、`--split*`（见 §4.1）。
* 失败会把**原始命令**和**退出码**原样打出来，并以同样的退出码退出（不吞错误）。

### 3.2 九步：每一步做什么、留下什么

| # | 步骤 | 做什么 | 产物 | 第二次跑 |
| --- | --- | --- | --- | --- |
| 1 | 找到客户端 | `--game` > `.deploy/state.json` 的上次记录 > 常见路径探测；数 `<game>/skinpack/*.ab` | 无（只在 `.deploy/state.json` 里记下路径） | 总是执行 |
| 2 | 确保 Python 环境 | 探 `<server>/.venv-extract`（Windows 下 `Scripts\python.exe`）能不能 `import UnityPy, lz4, PIL`；不能就 `python -m venv` + `pip install -r extract/requirements.txt` | `<server>/.venv-extract/`（主项目 `.gitignore` 的 `.venv*/` 已挡住） | venv 在且三个依赖都能 import → 跳过 |
| 3 | 跑皮肤提取 | `extract/skins.py --data-root <server> --game <game> --out <server>/public/assets/local --manifest <server>/data/local-assets.json`；`tools/skin-library/library-index.json` 不存在时先跑 `--only library`，再跑 `--only skins` | 美术：`public/assets/local/spine/op/<charId>/<stem>/{front,back}/<stem>.{skel,atlas,png}`、`spine/op/<charId>/<stem>/illust.*`、`library/{opavatar,opportrait,opillust}/<id>/image.png`；元数据：`data/local-assets.json`、`data/skins-local.json`、`data/library-index.json`、`tools/assets/local-skin-index.json`、`tools/assets/local-skins-meta.json`、`tools/skin-library/library-index.json` | 提取"够用"**且客户端与上次相同** → 跳过（判定条件见 §3.3）。`--force` 重跑；**`--force-build` 一律不跑**（不完整就直接退出 2） |
| 4 | 生成目录表 | `tools/skin-catalogue.py --out <repo>/data/skin-table.json [--local-catalogue <repo>/catalogue/skins.json] [--skins-meta <server>/data/skins-local.json] [--skin-index <server>/tools/assets/local-skin-index.json] [--skin-table <server>/.cache/gamedata/excel/skin_table.json]`——方括号里这几个参数**只在文件存在时才传**，缺的打印警告后略过（§9.6） | `<repo>/data/skin-table.json`（本机 273 个 skinId / 273 个有名字；只用仓库目录表时同样 273/273） | 输出比所有来源新、且来源签名（路径 + 秒级 mtime）没变 → 跳过 |
| 5 | 构建插件 | `tools/build-plugin.py --server <server> --out <repo>/operator-skin-select --split auto --split-target 190 --images all --illust-format webp --illust-quality 85 --illust-method 5`（`--illust none` 时改成 `--images small`） | `<repo>/operator-skin-select/`、`-2`、`-3` …（各自 `plugin.json` + `assets.json`），以及 `<repo>/data/build-report.json` | 报告比 `build-plugin.py` 与目录表新、签名一致、且报告里的包都还在 → 跳过 |
| 6 | pack（每个包各算） | `node <server>/tools/plugin.mjs pack <包目录>` | 每个包的 `plugin.lock.json`（模型剪辑数据 + 每个文件的 SHA-256） | 该包 `plugin.lock.json` 比 `assets.json`/`plugin.json` 新且签名一致 → 跳过 |
| 7 | check（每个包各算） | `plugin.mjs check <包>` 与 `check <包> --strict`，解析 `N problem(s), M warning(s)` | 无（只打印） | **总是执行**（校验不该跳）；非 0 退出码就整体失败 |
| 8 | 装进 `plugins/`（每个包各算） | 每个包复制到 `<server>/plugins/<id>/`；把上一轮多出来、这一轮不再需要的 `operator-skin-select*` 包删掉 | `<server>/plugins/<id>/` | 该包与构建产物的 `plugin.lock.json`、`plugin.json` 逐字节相同 + 文件数相同 + 签名一致 → 跳过 |
| 9 | 汇总 | 步骤表、每个包一行（套数/干员/文件/体积/check）、下一步怎么做 | 无（只打印） | 总是执行 |

第 6、8 步**按每个包各自算**（状态键 `pack:<id>` / `install:<id>`），所以只改了一个包时其余包照旧跳过。

### 3.3 幂等与续跑

判断依据只有这些，没有隐藏状态：

* **venv**：能不能 import（第 2 步）；
* **提取**：`spine/op` 里有模型目录、`library/{opavatar,opportrait,opillust}` 三层都非空、
  `data/local-assets.json` 里以 `spine/op/` 开头的组数 > 100、`tools/skin-library/library-index.json` 存在（第 3 步）；
* **客户端换没换**：`.deploy/state.json` 里上次记的路径与这一次比（第 3 步，见下）；
* **每一步的输入签名**：存在 `<repo>/.deploy/state.json`（第 4~6、8 步）；
* **mtime**：`plugin.lock.json` 是否比 `assets.json` 新（第 6 步）、`plugins/<id>` 与构建产物是否逐字节同源（第 8 步）。

第 3 步的"提取够用就跳过"多一个条件：**这一次的客户端和上一次记下的相同**。`deploy.mjs` 第 1 步先把
`state.steps.extract.game` / `state.game` 里的旧路径取出来（`previousGame()`），再写新的；第 3 步拿旧值去比
（`gameChanged()`），不同就打印

```
客户端与上次不同（上次 <旧 AB 根>，这次 <新 AB 根>），重新提取
```

并真的重跑提取，插件里因此不会是旧客户端的美术。`--force-build` 下第 3 步一律不跑，但换了客户端时会多打印一行
`（客户端与上次不同：… ；--force-build 不重跑提取，插件里仍是上次那批美术）`，不让人以为已经换过了。

第二次跑同一套参数时，实测输出是"**3 步执行 / 6 步跳过**"：第 1、7、9 步执行，第 2、3、4、5、6、8 步
打印 `跳过（已存在）`。换了 `--game` 之后同一份输入变成"**4 步执行 / 5 步跳过**"（第 3 步不再跳过）。

### 3.4 `--force` 与 `--force-build`

两者都关掉"跳过"判断，但范围完全不同：

| | 第 2 步 venv | 第 3 步 提取 | 第 4 步 目录表 | 第 5 步 构建 | 第 6 步 pack | 第 7 步 check | 第 8 步 安装 | 会重写 `data/skins-local.json` 吗 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 不给 | 按需 | 按需 | 按需 | 按需 | 按需 | **总是** | 按需 | 只在提取真的跑了时 |
| `--force-build` | 只在 venv 不能 import 时才动（见下） | **一律不跑**，提取不完整直接退出 2 | 按需 | 强制 | 强制 | **总是** | 强制 | **绝不** |
| `--force` | 强制重建 | **强制重跑** | 强制 | 强制 | 强制 | **总是** | 强制 | **会**（这就是它危险的地方） |

**为什么要在意 `data/skins-local.json`**：那是提取器写在主项目 `data/` 下的元数据，而主项目把
`data/*.json` 里除 `assets` / `local-assets` / `local-fx` / `emotes` 之外**每一个文件都算进内容标识 `cs`**
（`server/plugins/identity.js` 的 `gameplayDataFiles` + `PRESENTATION_DATA`）。`data/skins-local.json` 与
`data/library-index.json` 都不在排除名单里（本机实测：`cs` 的 data 输入共 18 个，两个都在其中），所以
**提取一跑，`content.vanilla` 就会变**（§9.4）。`--force-build` 的设计目的正是"只想重新出一遍包"：
不提取、绝不碰这两个文件。

> `--force-build` 的"第 3 步一律不跑"是**硬保证**：提取产物不完整就直接退出（码 2），不会顺手去补。
>
> 第 2 步**不是**一律不跑，只在 venv **能 import** 时跳过：`.venv-extract` 缺失、或三个依赖有一个装不上，
> 第 2 步照样 `python -m venv` + `pip install -r extract/requirements.txt`（`deploy.mjs:371-402`；只有 `--force`
> 才连这个跳过也一并忽略、强制重建）。代价可以忽略：它只写 `<server>/.venv-extract/`（主项目 `.gitignore` 的
> `.venv*/` 已挡住），不碰任何提取产物，所以 `data/skins-local.json` 仍然**绝不会**被它重写。

换过 `catalogue/skins.json`、改了立绘参数、想重新出一遍包时：

```bash
node deploy.mjs --server "E:\Stronghold-Protocol" --force-build --yes
```

---

## 4. 参数表

### 4.1 `deploy.mjs`

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--server <目录>` | 必填 | 服务器检出（提取产物、`tools/plugin.mjs`、`plugins/` 都在它下面） |
| `--game <目录>` | 上次记录 > 常见路径探测 | 客户端 `…\StreamingAssets\AB\Windows` |
| `--illust none\|webp\|png` | `webp` | 立绘：不收（只要头像 + 半身像）/ 转 WebP / 原样 PNG（会很大） |
| `--illust-quality 1..100` | `85` | WebP 的 quality |
| `--illust-method 0..6` | `5` | WebP 的 Pillow method（0 最快、6 最慢也最小），见 §8 |
| `--jobs N` | `min(4, CPU)` | 立绘转码的并行进程数（本机 32 逻辑核 → 默认 4） |
| `--split <n\|auto>` | `auto` | 拆成几个包；`auto` 按 `--split-target` 定，见 §5 |
| `--split-target <MiB>` | `190` | 每包的目标上限（允许 1..200；硬上限 200 MiB，留余量） |
| `--have <文件\|ids>` | 无 | **可选**的跳过清单（§7.2）。不给就是收提取里的全部 |
| `--catalogue <文件>` | 无 | 额外的**名字**来源（可重复），只影响显示名，不影响素材 |
| `--python <解释器>` | PATH 上的 `python` / `python3` / `py` | 建 venv 用的解释器 |
| `--venv <目录>` | `<server>/.venv-extract` | venv 位置 |
| `--force` | 关 | 忽略"跳过"判断，重跑第 2~6 步——**包括第 3 步的皮肤提取**，因此会重写 `<server>/data/skins-local.json`（改 `cs`），**谨慎** |
| `--force-build` | 关 | 只重跑构建（5）/ pack（6）/ check（7）/ 安装（8），**第 3 步一律不跑**，绝不触碰 `<server>/data/skins-local.json`；提取不完整时直接退出（2），不会顺手去补提取。第 2 步只在 venv 能 import 时跳过（缺 venv 或依赖不全仍会建 venv + `pip install`，只写 `<server>/.venv-extract/`），见 §3.4 |
| `--yes` / `-y` | 关 | 不问就执行（非终端下没有 `--yes` 会直接退出 2） |
| `--dry-run` | 关 | 只打印将执行的命令，**不写任何东西** |
| `-h` / `--help` | — | 用法与 `--force` / `--force-build` 的说明 |

### 4.2 `tools/build-plugin.py`

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--server <目录>` | 探测 `D:\project\html\Stronghold-Protocol`、`E:\Stronghold-Protocol` | 服务器检出：`--extract` 与目录表的默认值都从它推 |
| `--extract <目录>` | `<server>/public/assets/local`，其次 sp-skins、主项目检出 | 提取产物目录（`spine/op/<charId>/<stem>/`、`library/…`）——**唯一素材来源** |
| `--main <目录>` | `--server` 兼作主项目检出，再退到默认候选 | 目录表与官方表从它读 |
| `--out <目录>` | `<repo>/operator-skin-select` | 插件文件夹；拆包时还会产出 `<out>-2`、`<out>-3` …（**id 以文件夹名为准**） |
| `--split <n\|auto>` | `auto` | 拆几个包；`1` = 不拆（id 与显示名都不带后缀） |
| `--split-target <MiB>` | `190` | 每包目标上限（1..200） |
| `--images auto\|all\|small\|none` | `all` | `all` 全收（模型 + 头像 + 半身像 + 立绘；`auto` 是它的旧名）、`small` 只要头像 + 半身像、`none` 只要模型 |
| `--illust-format none\|png\|webp` | `webp` | 立绘（只在 `--images all` 下生效）：转 WebP / 原样复制 / 不收 |
| `--illust-quality 1..100` | `85` | WebP 的 quality（`--illust-format` 不是 webp 时给值会警告"只对 webp 有效"） |
| `--illust-method 0..6` | `5` | WebP 的 Pillow method |
| `--jobs N` | `min(4, CPU)` | 立绘转码的并行进程数（`concurrent.futures.ProcessPoolExecutor`，1 = 不并行） |
| `--link auto\|hard\|copy` | `auto` | 素材落地：优先同卷硬链接，失败则复制（**从不写源目录**） |
| `--skin-index <文件>` | `<main>/tools/assets/local-skin-index.json` | 提取器写的 `byStem: stem → skinId` |
| `--skins-meta <文件>` | `<main>/data/skins-local.json` | 提取器写的名字/分组 |
| `--skin-table <文件>` | `<main>/.cache/gamedata/excel/skin_table.json` | 官方显示名表（`charSkins[skinId].displaySkin`） |
| `--have <文件\|ids>` | 不给 | **可选**的跳过清单，见 §7.2 |
| `--gap-only` | 关 | 等价于"给了 `--have`"；不给 `--have` 会报错（默认就是收全部） |
| `--no-dump` | 关 | 兼容保留的**空开关**（dump 那条线已删除） |
| `--version x.y.z` | `0.1.1` | 写进每个包 `plugin.json` 的版本 |

### 4.3 `extract/skins.py`

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--game <目录>` | 无 | 客户端 AssetBundle 根目录（`…/StreamingAssets/AB/Windows`） |
| `--server <目录>` | 无 | 服务器/主项目检出：目录表与清单写在这里，也是 `--out` 的默认基准 |
| `--data-root <目录>` | `--server` | 显式指定元数据的落地检出（上游按自己文件位置推 `ROOT`，这里重定基） |
| `--out <目录>` | `<data-root>/public/assets/local` | 美术输出目录 |
| `--manifest <文件>` | `<data-root>/data/local-assets.json` | 提取清单 |
| `--only both\|skins\|library` | `both` | `skins` 只提 `spine/op`，`library` 只提图库三层。**第一次必须先 `library` 再 `skins`**（上游按磁盘上的图库索引枚举"客户端有哪些皮肤"，索引要到那次运行结尾才写） |
| `--skin <stem>` | 不给 = 全套 | 只提这些模型 stem（可重复） |
| `--library-tier avatar\|portrait\|illust` | 三层都提 | 只提图库的这些层（可重复） |
| `--print-jobs` | — | 打印上游完整 job 表（调试用）并退出 |
| `--dry-run` | 关 | 只打印路径与参数 |

### 4.4 目录表与基准工具

| 工具 | 主要参数 |
| --- | --- |
| `tools/skin-catalogue.py` | `--out`（必填）、`--local-catalogue`（默认仓库里的 `catalogue/skins.json`，存在就优先）、`--no-local-catalogue`、`--skin-table`、`--skins-meta`、`--skin-index`、`--extra`（可重复） |
| `tools/local-catalogue.py` | `--out`（默认 `<repo>/catalogue/skins.json`）、`--repo`、`--ref`（默认 `feat/skins`）、`--skin-index`、`--skins-meta`、`--official-names`、`--official-table` |
| `tools/bench-webp.py` | `--extract`（必填）、`--stems`、`--limit`、`--methods`（默认 `6,5,4`）、`--qualities`（默认 `85`）、`--jobs`（默认 `1,4,8,16`）、`--method-for-jobs`、`--repeat`、`--emit-json` |

---

## 5. 包拆分：为什么是多个包

### 5.1 账目

一个插件文件夹的上限是 **200 MiB = 209,715,200 字节**（`PLUGIN_LIMITS.pluginBytes`），另有 5000 个文件的
上限。本机这份提取（273 套皮肤，`--images all --illust-format webp --illust-quality 85 --illust-method 5`）
拆成三个包后的实际账目：

| 类别 | 文件数 | 体积 |
| --- | --- | --- |
| Spine 骨架 `.skel` | 540 | **198.61 MiB** |
| Spine 图集页 `.png` | 540 | 72.30 MiB |
| Spine 图集 `.atlas` | 540 | 5.00 MiB |
| 头像 `avatar.png` | 273 | 16.71 MiB |
| 半身像 `portrait.png` | 273 | 33.09 MiB |
| 立绘 `illust.webp` | 273 | 56.54 MiB |
| `assets.json` ×3 | 3 | 0.24 MiB |
| `plugin.lock.json` ×3 | 3 | 1.40 MiB |
| **合计** | **2448** | **383.91 MiB** |

比 200 MiB 多出近一倍，**光 `.skel` 就 198.6 MiB**，所以需要拆分。三个包（`--split auto --split-target 190`
的结果，不是常量）：

| 包 | 插件 id | 显示名 | 套数 | 包内干员 | 文件 | 体积 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `operator-skin-select` | 干员皮肤选择插件（1/3） | 97 | 60 | 870 | 127.3 MiB |
| 2 | `operator-skin-select-2` | 干员皮肤选择插件（2/3） | 102 | 61 | 915 | 128.3 MiB |
| 3 | `operator-skin-select-3` | 干员皮肤选择插件（3/3） | 74 | 55 | 663 | 128.3 MiB |
| 合计 | | | **273** | 176（去重 174） | **2448** | **383.9 MiB** |

包内干员数相加是 176 而不是 174：`char_2023_ling`（1+2 套）与 `char_4064_mlynar`（1+1 套）的皮肤被拆进了
不同的包。**同一个干员的皮肤可能落在不同的包里**，所以只开一个包时，那个干员会只剩另一个包里的几套。

三个包各自 `node <服务器检出>/tools/plugin.mjs check <包> --strict` 都是
`1 folder(s): 0 problem(s), 0 warning(s)`。

### 5.2 怎么拆（确定性）

1. 把选中的皮肤按 **skinId 排序**（同键用 stem）；
2. 每套算出它会占的**真实**体积：模型文件的实际大小 + 头像/半身像的实际大小 + 立绘**精确**转码后的字节数
   （立绘先并行转码到暂存目录，所以拆包用的是真实数字）+ 每套 8 KiB 的清单开销；
3. 在排序后的序列上做**连续切分**，用动态规划精确求"让最大那个包最小"的切点（本次核对：DP 与穷举在
   200 组随机输入上结果完全一致，切分连续、包数正确）；`--split auto` 从 `ceil(总体积 / 目标)` 起往上试，
   第一个让最大包 ≤ `--split-target` 的包数就是答案；
4. 第 1 个包沿用 `--out` 的文件夹名（默认 `operator-skin-select`），第 i 个是 `<out>-i`；**插件 id 就是文件夹名**
   （上游以文件夹名为准），显示名带（i/n）；
5. 上一轮拆出来、这一轮不再需要的 `<out>-N` 文件夹会被删掉（只删 `plugin.json` 里 id 与文件夹名对得上、
   且名字形如 `<out>-数字` 的目录）。

同样的输入永远得到同样的包。真正超过 200 MiB 时构建会打印警告，`check` 会报 `PLUGIN_FILE_SIZE`（§9.1）。

### 5.3 玩家必须**每个包都开**

* **服主**只负责把包放进 `plugins/`（`deploy.mjs` 第 8 步自动做，或手动拷贝）。服主是唯一能决定这些插件
  存不存在的人；装它不用重启服务器。
* **每个玩家在自己的浏览器里开启**：设置 → 外观插件 → 打开。谁开谁看得到，**各开各的**。
* 三个包是三份独立插件，**必须逐个开启**：只开第 1 个，第 2、3 个包里的皮肤（包括同一干员被拆走的那几套）
  就都不显示。
* **房主无关**：这些插件的 `scope` 只有 `personal`，房间面板上没有它们的开关，房主开不了、也不用开。
* **没开启的人看到默认外观**，包括看别人的棋子。

核对：`node <服务器检出>/tools/plugin.mjs list` 应列出这几个包；`GET /plugins/index.json` 里只有插件 id 与
相对信息（**不含任何磁盘路径**）；`GET /healthz` 的 `content.plugins` 等于包数。

---

## 6. 目录表 `catalogue/skins.json`

这是**唯一随仓库分发的"皮肤数据"**，而且**只有元数据**：273 条
`{ skinId, stem, charId, name, group }` + `source` + `counts`。

```json
{ "skinId": "char_003_kalts@boc#6", "stem": "char_003_kalts_boc_6",
  "charId": "char_003_kalts", "name": "残余", "group": "斗争血脉/VI" }
```

| | |
| --- | --- |
| 字段 | `skinId`（官方皮肤 id，进 `assets.json` 当 JSON 键）/ `stem`（进插件文件路径，`@ # +` 不能出现在路径里）/ `charId` / `name`（官方显示名）/ `group`（皮肤系列名） |
| 规模 | 273 条 / 174 个干员；`name`、`group` 各 273/273（`counts`: `named 273`、`grouped 273`、`nameFromExtraction 174`、`nameFromGeneratedList 99`） |
| **不含** | 任何 URL、任何绝对路径、任何 `.png` / `.skel` / `.atlas`（本次核对：三个模式在整个文件里 0 命中；全文件也没有一个反斜杠） |
| 谁生成 | `tools/local-catalogue.py`（维护者偶尔跑一次），来源记录在文件自己的 `source` 里 |
| 来源 | 主项目分支 `feat/skins` 的 `tools/assets/local-skin-index.json`（blob `e94200ae`，`byStem: stem → skinId`）＋ 本机 `data/skins-local.json`（未跟踪的提取产物，sha256 `4d39355d…`：`name` / `group` 与 `.skel` 文件名）＋ 该分支的 `data/skins.json`（blob `20fe8937`，由官方 gamedata 生成：提取器解不出显示名的那 99 套的真名从这里补） |
| 核对方式 | 生成时逐条核对 index ↔ 提取元数据 ↔ 官方生成表，任何一条不一致就报错退出（不让错的表进仓库）；另外用官方 gamedata 快照 `.cache/gamedata/excel/skin_table.json`（sha256 `422068f0…`）把 273 条的 `displaySkin.skinName` / `skinGroupName` 逐条比对过（`source.officialSnapshotChecked: 273`） |
| 为什么随仓库分发 | 它是构建的**第一优先名字来源**（`tools/skin-catalogue.py --local-catalogue`）：有了它，**没有官方 gamedata 缓存、提取元数据里名字残缺的机器也能拿到全部 273 个真名**（提取器解不出显示名的那 99 套在本机是写成 `name = skinId` 的兜底值）。它不含美术，因此可以安全地进 git |

维护者更新这份表（读主项目检出，不写主项目）：

```bash
# 检出里只有远程跟踪分支时用 origin/feat/skins（脚本不会自动加 origin/ 前缀）
python tools/local-catalogue.py --out catalogue/skins.json \
    --repo "E:\Stronghold-Protocol" --ref origin/feat/skins
```

> 命令里写 `origin/feat/skins` 是有意的，**保留这个写法**：脚本用 `git <ref>:<路径>` 直接读文件，不做 `origin/`
> 兜底——检出里只有远程跟踪分支 `origin/feat/skins` 时，写 `--ref feat/skins` 会以
> `读不到 data/skins.json：给了 --repo 就在分支 feat/skins 上找它…` 退出（码 1）。
> 若你那台机器的检出里**确有同名本地分支** `feat/skins`，那么 `--ref feat/skins` 亦可（仓库里这份表的 `source`
> 记的就是 `git feat/skins:…`）；两种写法读到的 blob 相同。

构建时读它的是第 5 步的 `--skin-table <repo>/data/skin-table.json`（第 4 步产出，形状是官方
`skin_table.json`：`charSkins[skinId].displaySkin.skinName` / `skinGroupName`），第 4 步的第一优先来源就是
这份 `catalogue/skins.json`。

---

## 7. 手动跑每一步

`deploy.mjs` 就是把下面这些命令按顺序跑一遍加判断，看懂这一步再手动跑，出问题时好定位。

### 7.1 提取

```bash
# 第一次：先图库（写 tools/skin-library/library-index.json），再皮肤
python extract/skins.py --server "<服务器检出>" --game "<AB 根>" --only library
python extract/skins.py --server "<服务器检出>" --game "<AB 根>" --only skins

# 只验一套 / 看上游完整 job 表
python extract/skins.py --server "<服务器检出>" --game "<AB 根>" --only skins --skin char_1012_skadi2_boc_4
python extract/skins.py --data-root "<服务器检出>" --print-jobs
```

`extract/extract.py`、`extract/scenes.py` 是主项目 `tools/local-extract/`（分支 `feat/skins`，提交
`166ae6c2`）的**原样拷贝**（逐字节一致，GPL-3.0-or-later；`aklz4.py` 是 BSD-3-Clause）。`extract/skins.py`
是本仓库新写的入口，只暴露 `spine/op` 与 `library` 两条 job，并在调用前把上游的 `ROOT` 与几个派生路径
重定基到 `--data-root`。

### 7.2 `--have`：可选的跳过清单

默认什么都不跳：**提取里的每一套都收**。只有想跳过"某个外部资料库已经提供的那批"时才给 `--have`：

```bash
python tools/build-plugin.py --server "<服务器检出>" --have "<清单文件>"
python tools/build-plugin.py --server "<服务器检出>" --have char_003_kalts@boc#6,char_1012_skadi2_boc_4
python tools/build-plugin.py --server "<服务器检出>" --gap-only --have "<清单文件>"   # 显式说"只收缺口"
```

`--have` 可以是一个文件（JSON：读 `installed` / `skins` / `stems` / `ids` / `have` 数组，或裸数组；也可以是
每行/逗号一个 id 的纯文本）或逗号分隔的列表；**skinId 与 stem 两种写法都认**。`--gap-only` 要求同时给
`--have`。**不再自动探测** `<server>/data/skins-installed.json`，也不扫描任何下载树：`--dump`、
`--downloaded` 已经删除，`--no-dump` 只剩兼容用的空开关。

键与磁盘路径是两件事：

| | 用什么 | 例子 |
| --- | --- | --- |
| `assets.json` 的键 | 官方 **skinId**（允许 `@ # +`） | `chars.char_003_kalts.skins.char_003_kalts@boc#6` |
| 插件里的文件路径 | **stem** | `spine/char_003_kalts_boc_6/front/char_003_kalts_boc_6.skel` |

### 7.3 目录表、构建、pack、check、安装

```bash
python tools/skin-catalogue.py --out data/skin-table.json \
    --local-catalogue catalogue/skins.json \
    --skins-meta "<服务器检出>/data/skins-local.json" \
    --skin-index "<服务器检出>/tools/assets/local-skin-index.json" \
    --skin-table "<服务器检出>/.cache/gamedata/excel/skin_table.json"   # 没有这个官方缓存就别给这一行

python tools/build-plugin.py --server "<服务器检出>" --skin-table data/skin-table.json \
    --split auto --images all --illust-format webp --illust-method 5 --jobs 4

for d in operator-skin-select operator-skin-select-2 operator-skin-select-3; do
  node "<服务器检出>/tools/plugin.mjs" pack  "$d"            # 写 plugin.lock.json（本地）
  node "<服务器检出>/tools/plugin.mjs" check "$d" --strict   # 必须 0 problem / 0 warning
  rm -rf "<服务器检出>/plugins/$d" && cp -r "$d" "<服务器检出>/plugins/$d"   # 装
done
```

> `skin-catalogue.py` 把 `--skins-meta` / `--skin-index` / `--skin-table` / `--extra` 当**显式路径**：给了但文件
> 不存在会直接退出（码 1），不会退回"只用仓库目录表"。**给与不给是两回事**：把它们去掉、只写
> `--local-catalogue catalogue/skins.json`，273 个名字与分组照样全有（本机实测 `count 273 / named 273 /
> grouped 273`），因为仓库自带的这份表本来就是第一优先来源。
> `deploy.mjs` 第 4 步按这个规则来：四个来源参数都先 `existsSync` 再传，缺的打印
> `警告：… 不在，本步只用剩下的来源（N 个）` 然后略过，**不会**再因为少了一个提取产物就整步失败（§9.6）。

`pack` 在这里只有一个用途：生成 `plugin.lock.json`（模型的剪辑数据 + 每个文件的 SHA-256）。
**不要打 zip、不要上传 Release**——这些包只在本机构建、本机安装；改了素材就要重新 `pack`。

`avatar` / `portrait` 按 `skinId`（`@` 换 `_`）、`skinId`、`stem` 三种目录名依次到 `library/opavatar`、
`library/opportrait` 里找；`illust` 优先用 `spine/op/<charId>/<stem>/illust.{png,jpg,webp}`，其次
`library/opillust/<id>/illust.{png,jpg,webp}`；找不到就不写那个字段。atlas 里的 `pma` 行一律删掉（主项目
`fix/extract-straight-pages` 之后图集页是直通 alpha）；如果某个 atlas 里确实写着 `pma: true`，构建会打印警告
——那说明这批提取来自旧提取器，渲染会偏暗。

---

## 8. 体积、立绘与 WebP 取舍

插件上限是 **200 MiB**；拆包之后每包都在上限内。

| 想要什么 | 命令 | 体积（273 套，本机） |
| --- | --- | --- |
| 全部皮肤 + WebP 立绘（默认） | `--images all --illust-format webp` | 383.9 MiB，拆成 3 个包（127.3 / 128.3 / 128.3 MiB） |
| 不要立绘 | `--images small`（`deploy.mjs --illust none`） | 约 327 MiB（模型 275.9 + 头像 16.7 + 半身像 33.1），2 个包 |
| 只要模型 | `--images none` | 约 277 MiB（模型 275.9 + 清单），2 个包 |

立绘源图是无损 PNG（本批 273 张共 333.4 MiB），WebP 是**有损重编码**：`quality` 越低体积越小、细节越糊
（脸、发丝、渐变背景最先看出来）；`method` 是 Pillow 的编码档位（0 最快、6 最慢也最小）。本批 **273 张**立绘、
`quality 85`、单进程的实测（`tools/bench-webp.py --stems` 指定这 273 张，`--repeat 2` 取最快那次）：

| method | 耗时 | s/张 | 体积 | KB/张 | 相对 method 6 |
| --- | --- | --- | --- | --- | --- |
| 6 | 1205.1 s | 4.41 | 55.56 MiB | 208 | 基准 |
| 5 | 73.7 s | 0.27 | 56.54 MiB | 212 | 体积 +1.8%，时间 ×0.061（快 16.3 倍） |
| 4 | 57.5 s | 0.21 | 57.96 MiB | 217 | 体积 +4.3%，时间 ×0.048（快 21.0 倍） |

并行（同一批、`quality 85`、`method 5`；单进程基准 73.7 s，第二次单跑复测 71.2 s——两者相差 3.5%，
下面是按当次基线算的加速比）：

| worker | 耗时 | s/张 | 加速比 |
| --- | --- | --- | --- |
| 1 | 71.5 s | 0.26 | 1.03× |
| 4 | 19.3 s | 0.07 | 3.82× |
| 8 | 13.3 s | 0.05 | 5.37× |
| 16 | 7.8 s | 0.03 | 9.16× |

**默认值**：`--illust-quality 85`、`--illust-method 5`、`--jobs min(4, CPU)`。理由：method 6 只比 5 小 **1.8%**
（273 张省 1.0 MiB），单进程却要 **20.1 分钟**（method 5 只要 1.2 分钟，快 16.3 倍）；method 4 比 5 再快 1.3 倍，
体积涨 2.5%。并行的收益主要在 1→4 个 worker（3.8×），再往上要 8/16 个才继续涨，对整批的绝对时间
（19.3 s → 7.8 s）不值。想让包更小就用 `--illust-method 6`（准备好等），想更快就用 `--illust-method 4 --jobs 8`。自己复测（只测量、不写插件）：

```bash
python tools/bench-webp.py --extract "<服务器检出>/public/assets/local" --methods 6,5,4 --jobs 1,4,8,16
```

> 不给 `--stems` / `--limit` 时这个脚本会测提取里**全部**有立绘的皮肤（本机 879 张：`spine/op` 的 273 张
> 加上 `library/opillust` 里另外 606 张），数字与上表不同。要复现上表就指定那 273 个 `spine/op` 的 stem。

---

## 9. 常见问题

### 9.1 `check` 报 `PLUGIN_FILE_SIZE`

三种触发条件（`shared/plugins/manifest.js`）：

| 触发 | 上限 | 怎么办 |
| --- | --- | --- |
| 整个文件夹超过 200 MiB | 209,715,200 字节 | 拆得更碎：`--split-target` 调小（如 `170`）或 `--split 4` 重出包；或降低 `--illust-quality` / 用 `--illust-method 6` |
| 文件数超过 5000 | 5000 | 同上（本机每包 663~915 个，离上限很远） |
| 单个 JSON 超过 8 MB | 8 MB | 本机的 `assets.json` 每包 69~93 KiB；真超了就是单包套数太多，拆包 |

`check` 的报错里带具体数字（`X MB in all, more than 200 MB`），照它调参数重建即可。

### 9.2 皮肤栏里某个干员只有「默认 · 0 套外观」

**大概率不是 bug**：这位干员在你的提取里确实没有时装。核对方法：

```bash
python -c "import json;d=json.load(open('catalogue/skins.json',encoding='utf-8'));print([r for r in d['skins'] if r['charId']=='char_102_texas'])"
```

`catalogue/skins.json` 里没有这个 `charId`，就是客户端里没有（本仓库的目录表 273 套只覆盖 174 个干员）。
另一种情况见 §9.3：这位干员的皮肤都在你**没开**的那个包里。

### 9.3 只开了一个包，别的包里的皮肤不显示

三个包是三份独立插件，各自有自己的 `plugin.json` / `assets.json` / 素材目录，**必须逐个开启**：

1. 服主确认三个都装上了：`node <服务器检出>/tools/plugin.mjs list` 应列出
   `operator-skin-select`、`operator-skin-select-2`、`operator-skin-select-3`；
2. 每个玩家在自己的浏览器里 设置 → 外观插件，把**三个**都打开（显示名带（1/3）（2/3）（3/3））；
3. 同一干员的皮肤可能被拆到了不同的包（§5.1），只开其中一个时，那个干员看起来会"少几套"。

房间面板上没有这些开关（`scope` 只有 `personal`），房主无关。

### 9.4 `/healthz` 的 `content.vanilla` 变了

`cs`（内容标识）把主项目 `data/` 下除 `assets` / `local-assets` / `local-fx` / `emotes` 之外的**每个
`*.json`** 都算进去（`server/plugins/identity.js` 的 `gameplayDataFiles`）。提取器会写
`data/skins-local.json` 与 `data/library-index.json`，**这两个文件都在 `cs` 的输入里**（本机实测：`cs` 的 data
输入共 18 个，`skins-local`、`library-index` 都在其中），所以：

* 跑过一次提取（第 3 步，或 `--force`）之后，`content.vanilla` 与上一次不同；
* 别的机器/别的存档里对不上同一个 `cs`；这不是插件造成的（`cosmetic` 插件不进 `cs`），是**提取产物本身**造成的。

要回滚：这两个文件是**未跟踪**的提取产物（`git status` 里是 `??`），改动前先备份，需要还原就把备份拷回去
（或从另一台同版本的机器拷贝）。**只想重新出一遍包时用 `--force-build`**：它不跑提取，绝不碰这两个文件。
如果服务器不想要本地提取产物参与内容标识，那就别把它们留在 `data/` 里（提取器会写，需要自己清理）。

### 9.5 装上了但一点变化都没有

1. 插件是**个人开关**：设置 → 外观插件里必须打开（§5.3）；没开的人看到默认外观，包括看别人的棋子。
2. 服务器看到了吗：`node <服务器检出>/tools/plugin.mjs list`，以及 `GET /plugins/index.json`；
   服务器**不用重启**，刷新页面即可。
3. 素材是否真的在：`check` 必须 `0 problem / 0 warning`；`PLUGIN_FILE_MISSING` 说明这个包缺素材文件
   （多半是把仓库里那个空壳 `operator-skin-select/` 拷进去了，见 §10）。
4. 旧提取器提取的 `.atlas` 带 `pma: true` 时渲染会偏暗，构建日志里会有警告（§7.3）。

### 9.6 第 4 步：少了 `data/skins-local.json` 之类的提取元数据

这个报错曾经会让第 4 步整步失败，**现在已经不会**：`deploy.mjs` 第 4 步只把**存在**的来源传给
`skin-catalogue.py`，缺的打印一行警告后略过。所以机器上只有素材（例如只从别人的完整包里拷了
`public/assets/local` 与 `data/local-assets.json`）时，输出长这样：

```
[4/9] 生成目录表 …       警告：E:\Stronghold-Protocol\data\skins-local.json、E:\Stronghold-Protocol\tools\assets\local-skin-index.json 不在，本步只用剩下的来源（1 个）
      $ python tools/skin-catalogue.py --out data/skin-table.json --local-catalogue catalogue/skins.json
```

只用仓库自带的 `catalogue/skins.json` 时，实测结果与完整来源**一样**：`273 个 skinId，其中 273 个有名字`、
分组同样 273/273（§6）。手工复现（`--out` 换成临时文件）：

```bash
python tools/skin-catalogue.py --out data/skin-table.json --local-catalogue catalogue/skins.json
```

**为什么这样改而不是改脚本**：`tools/skin-catalogue.py` 是通用工具，"给了显式路径却不存在"报错退出是它应该
有的行为（免得悄悄少了一个来源）；"我这台机器上哪些来源有"是 `deploy.mjs` 自己知道的事，所以在 deploy 侧判断。
两者只有一边改：脚本的显式路径语义**保持不变**。

> 真的什么都没有时（提取元数据没有、仓库目录表也被删了）才会走另一条路：脚本 `没有可读的来源…` 退出（码 1），
> 这属于仓库被弄坏了，不是机器缺提取产物。

---

## 10. 不要做

* **不要把素材提交进任何仓库**：`.skel` / `.atlas` / `.png` / `assets.json` / `plugin.lock.json` /
  `operator-skin-select*/` 的素材目录都留在本机（`.gitignore` 已经挡住，`git status --ignored` 可核对）。
* **不要对外分发 zip / Release / 网盘 / 镜像**：这些文件是《明日方舟》的官方美术，主项目
  `docs/PLUGINS.md` §1 要求插件不得携带官方游戏文件。需要插件的人，请他在**自己的机器**上按 §3 跑一遍。
* **不要写 `data/assets.json`**：那是主项目自己的美术清单（跟踪文件）。插件通过 `assets.json` 这个
  **overlay** 覆盖安装里已有的条目，本仓库的构建脚本从不碰主项目的 `data/assets.json`。
* **不要给插件加 `entry`**：`cosmetic` 类不允许 `entry`（`entry` 只属于 script / ui / trusted），加了会被判
  problem。清单只要 `class: cosmetic` + `scope: ["personal"]` + `permissions: ["assets.override"]` +
  `assets: "assets.json"`。
* **不要手写 `plugin.lock.json`**：模型的剪辑数据（`anims` / `events` / `hits` / `bounds`）只能由
  `node tools/plugin.mjs pack <包>` 从骨架里解析出来；手写的 lock 会被判 `PLUGIN_LOCK` /
  `PLUGIN_LOCK_STALE`。改了素材就重新 `pack`。
* 不要手改 `catalogue/skins.json`：它由 `tools/local-catalogue.py` 生成并逐条核对，手改会让下一次生成
  对不上（`source` / `counts` 就是核对记录）。
* 不要把仓库里的空壳 `operator-skin-select/`（只有一份 `plugin.json`）直接拷进 `plugins/`——它不是可用的
  插件（`assets.json` 与素材都不在 git 里）。
* 不要给别的插件起 `operator-skin-select-<数字>` 这样的 id：构建与 `deploy.mjs` 第 8 步会把 `plugins/` 下
  名字匹配 `^operator-skin-select(-\d+)?$`、且 `plugin.json` 的 id 与文件夹名一致、本轮又没产出的目录删掉。

---

## 11. 许可与出处

* **美术**（`.skel` / `.atlas` / `.png`）：版权归 Hypergryph（上海鹰角网络）/ Yostar，**不在任何开源许可范围内**，
  本仓库不就它们授予任何权利。仅限学习、研究、个人非商业用途；不得出售、付费分发、挂广告或任何盈利场景。
  权利人要求即删除。
* **`extract/`**：`extract.py`、`scenes.py` 是主项目 GPL-3.0-or-later 的代码（原样拷贝）；`aklz4.py` 是
  BSD-3-Clause（Copyright © 2022 Harry Huang，Ark-Unpacker 的 LZ4AK 解码），全文见
  `extract/LICENSE-Ark-Unpacker.txt`。**再分发本仓库时 `extract/` 与它一起受 GPL-3.0-or-later 约束**：
  GPL-3.0 的**全文随仓库附在根目录的 [`LICENSE`](LICENSE)**（674 行 / 35,149 字节，正文与主项目检出里的
  `LICENSE` 逐字相同，只有换行符不同——本仓库统一 LF，主项目检出那份是 CRLF）。那份文本**只为 `extract/` 而放**，
  不覆盖本仓库自己的脚本与 `catalogue/skins.json`。
  `extract/aklz4.py` 是上游原样拷贝，文件头注释里指向上游的 `tools/local-extract/LICENSE-Ark-Unpacker.txt` 与
  `THIRD-PARTY-NOTICES.md` 在本仓库分别对应 `extract/LICENSE-Ark-Unpacker.txt` 与 `NOTICE.md`（**没有改动上游
  文件本体**，对照写在 [NOTICE.md](NOTICE.md) 的"提取器"一节）。
* **本仓库自己的内容**：`tools/build-plugin.py`、`tools/skin-catalogue.py`、`tools/local-catalogue.py`、
  `tools/bench-webp.py`、`deploy.mjs`、`extract/skins.py`、`README.md`、`NOTICE.md`，以及元数据清单
  `catalogue/skins.json`（只含 skinId / stem / charId / 名字 / 分组，不含美术），可自由使用与修改。
* 详细出处、blob / sha256 与使用条件见 [NOTICE.md](NOTICE.md)；插件格式与上限见主项目
  [docs/PLUGINS.md](https://github.com/sganggs/Stronghold-Protocol/blob/feat/plugin-keys/docs/PLUGINS.md)（§1 原则、§5 文件与上限、
  §9 外观插件）。

---

## 12. 附录：交付时实际核对过的命令与结果

下面这些是写这份 README 时**在本机真跑过**的，供你复现（Windows，node v24.21.0，Python 3.12，32 逻辑核）：

| 命令 | 结果 |
| --- | --- |
| `node --check deploy.mjs` | 退出 0 |
| `python -m py_compile tools/*.py extract/skins.py` | 退出 0 |
| `node deploy.mjs --help` / `python tools/build-plugin.py --help` / `python extract/skins.py --help` / `python tools/skin-catalogue.py --help` / `python tools/local-catalogue.py --help` / `python tools/bench-webp.py --help` | 全部退出 0；§4 的参数与默认值逐条对得上本文 |
| `node deploy.mjs --server "E:\Stronghold-Protocol" --dry-run --yes` | 第二次跑：**3 步执行 / 6 步跳过**（第 1、7、9 步执行）；三个包分别 97/102/74 套、127.3/128.3/128.3 MiB（第 9 步的汇总表按 `operator-skin-select*` 目录里的文件算，共 2448 个） |
| 同上，再加 `--game "<另一个 AB 根>"` | **4 步执行 / 5 步跳过**：第 3 步打印 `客户端与上次不同（上次 …，这次 …），重新提取` 并列出将跑的两趟 `extract/skins.py`（这就是 §3.3 那个"换了客户端就重新提取"的判断，本机实测有效） |
| 同上，再加 `--force-build`（客户端不同） | 第 3 步**仍然不跑**（硬保证），但多打印一行 `（客户端与上次不同：… ；--force-build 不重跑提取，插件里仍是上次那批美术）` |
| `node "E:\Stronghold-Protocol\tools\plugin.mjs" check operator-skin-select operator-skin-select-2 operator-skin-select-3 --strict` | `3 folder(s): 0 problem(s), 0 warning(s)`，退出 0；`check` 自己报的文件数是 868 / 913 / 661（它数的是清单里引用的文件，与上面第 9 步的数法不同） |
| `node "E:\Stronghold-Protocol\tools\plugin.mjs" list` | 三个包都在 `cosmetic (loaded)` 下，`unofficial`，体积与文件数如上 |
| `python tools/local-catalogue.py --out <临时文件> --repo "E:\Stronghold-Protocol" --ref origin/feat/skins` | 退出 0；再生成的 273 条记录与 `counts` 与仓库里这份**完全一致**（只有 `branch` 字符串与可选快照块不同：E 盘检出没有 `.cache/gamedata/excel/skin_table.json`） |
| `python tools/local-catalogue.py … --ref feat/skins` | **退出 1**（该检出只有远程跟踪分支 `origin/feat/skins`；脚本不做 `origin/` 兜底）→ 本文 §6 因此写 `origin/feat/skins`，并说明检出里有同名本地分支时 `--ref feat/skins` 亦可 |
| `python tools/skin-catalogue.py --out <临时> --local-catalogue catalogue/skins.json --skins-meta <不存在的文件>` | **退出 1**、`--skins-meta …: 不是一个文件`（脚本对显式路径的语义没变） |
| `python tools/skin-catalogue.py --out <临时> --local-catalogue catalogue/skins.json` | 退出 0；`273 个 skinId，其中 273 个有名字`（`count 273 / named 273 / grouped 273`）——第 4 步在缺提取元数据时就是这么退回来的（§9.6） |
| `node deploy.mjs --server "E:\Stronghold-Protocol" --dry-run --yes --force-build`，临时把 `data/skins-local.json` 与 `tools/assets/local-skin-index.json` 挪走 | 第 4 步打印 `警告：… 不在，本步只用剩下的来源（1 个）`，只把 `--local-catalogue` 传给脚本，**不再失败**；两个文件随后放回原处（都是主项目未跟踪的提取产物，`git status` 无变化） |
| `python tools/bench-webp.py --extract "E:\Stronghold-Protocol\public\assets\local" --stems <273 个 stem> --methods 6,5,4 --jobs 1,4 --repeat 2` | 退出 0；§8 的两张表就是这次 273 张（源图 333.4 MiB）的实测 |
| 拆包 DP 与穷举对拍（200 组随机输入） | 0 处不一致；`--split auto` 可重复、包数最小、切分连续 |
| `catalogue/skins.json` 全文件扫描 | 273 条 / 174 干员 / `name`、`group` 各 273；URL、绝对路径、`.png`/`.skel`/`.atlas` 各 0 命中；所有 skinId ≤ 64 字符 |
| `operator-skin-select/assets.json` 抽查 | JSON 键是 skinId（带 `@`、`#`），文件路径是 stem；文件里没有盘符、没有 `//`、没有 URL |
| `extract/` 与上游对拍 | `extract.py` / `scenes.py` / `aklz4.py` / `requirements.txt` / `LICENSE-Ark-Unpacker.txt` 的 git blob 与 `origin/feat/skins`（`166ae6c2`）**逐一相同** |
| `LICENSE` 与主项目 `LICENSE` 对拍 | 文本逐字节相同（674 行 / 35,149 字节；主项目检出那份是 CRLF，本仓库统一 LF，只有换行符不同）——GPL-3.0 全文因此确实随仓库附带（§11） |
| `cs` 输入核对 | `gameplayDataFiles("<服务器检出>/data")` 共 18 个输入，含 `skins-local`、`library-index`（§9.4） |
