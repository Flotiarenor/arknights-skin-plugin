# NOTICE — 版权与使用条件

## 美术素材

《明日方舟》官方美术（`.skel` / `.atlas` / `.png`，以及 `assets.json`、`plugin.lock.json` 这类由它们生成的清单）
版权归 **Hypergryph（上海鹰角网络）** 所有；海外发行商为 **Yostar**。

**本仓库不包含任何游戏美术文件**：仓库里只有脚本（含自带的提取器 `extract/`）与说明；插件文件夹里的素材由使用者
在自己的机器上用这些脚本从本机客户端提取后生成，不进 git、也不对外分发。

**素材只有一个来源：本机客户端的提取产物。** 提取里有多少套皮肤就收多少套；一套皮肤都不从别处取——没有远程
素材库、没有社区 dump、也没有"补差"清单。插件单包上限 200 MB，所以全部皮肤会被拆成多个包
（`operator-skin-select`、`operator-skin-select-2` …），每个包各自是一份独立的插件文件夹。

- 本仓库是**非官方、非商业**的同人项目附属产物：不含广告、不接受捐赠、不设付费墙。
- 这些文件来自**本机已安装客户端的提取**，并非从任何第三方仓库转载。
- 它们**不在任何开源许可范围内**；本仓库不就它们授予任何权利，也不对再分发承担责任。
- 仅限学习、研究、个人非商业用途。不得出售、付费分发、广告或用于任何盈利场景。
- 权利人如认为本项目侵犯其权益，请通过 Issue 联系，我们会立即删除相关内容。

## 目录表（`catalogue/skins.json`）

这是本仓库里**唯一随仓库分发的"皮肤数据"**，且**只有元数据**：每套一条
`{skinId, stem, charId, name, group}`，共 273 条 / 174 个干员，**不含任何美术文件、素材路径或 URL**（`name` / `group`
是官方显示名与皮肤系列名，不是美术）。它由 `tools/local-catalogue.py` 生成，来源写在文件自己的 `source` 块里：

| 来源 | 位置 | 是什么 |
| --- | --- | --- |
| 目录索引 | `Stronghold-Protocol` 分支 `feat/skins` 的 `tools/assets/local-skin-index.json`（blob `e94200ae`） | `byStem`：stem → skinId（273 条） |
| 提取元数据 | 本机主项目检出的 `data/skins-local.json`（**未跟踪**，由 `feat/skins` 分支的 `.gitignore` 挡住；本机与 E 盘那份逐字节相同，sha256 `4d39355d…`） | 提取器写下的 `name` / `group` 与 `spine.*.skel` 文件名；其中 99 套的名字是提取器的兜底写法（`name == skinId`），没有被采信 |
| 官方生成表 | `Stronghold-Protocol` 分支 `feat/skins` 的 `data/skins.json`（blob `20fe8937`） | 主项目由官方 gamedata 生成的皮肤列表：那 99 套的真名与分组从它补齐 |
| 官方快照（只核对） | 本机 `.cache/gamedata/excel/skin_table.json` | 273 条的 `displaySkin.skinName` / `skinGroupName` 逐条核对一致 |

生成时逐条核对：index ↔ 提取元数据 ↔ 官方生成表；任何一条不一致生成器就报错退出（不让错的表进仓库）。这些名字与
分组本身来自《明日方舟》官方数据表：**它们不是美术文件**，本仓库把它们当作"哪套皮肤叫什么"的陈述来引用，同样只用于
学习、研究与个人非商业用途；权利人要求即删除。分发本仓库时请把这份表与上面的出处说明一起带走。

上表第 2 行的 `data/skins-local.json` 是**提取产物**（属于主项目 `cs`），本仓库只读它：`deploy.mjs --force-build`
只重跑构建 / pack / check / 安装，**不跑提取**，所以不会重写它；只有 `--force`（或正常部署时发现提取不完整）才会跑提取。
`catalogue/skins.json` 一旦生成就不再依赖任何提取产物，别的机器上照样有全部 273 个真名。

## 工具与数据来源

- [Stronghold-Protocol](https://github.com/sganggs/Stronghold-Protocol)：插件格式、`tools/plugin.mjs`
  打包与校验工具、以及本插件的素材来源流程（`docs/PLUGINS.md` §1：插件不得携带官方游戏文件）。
- [fexli/ArknightsResource](https://github.com/fexli/ArknightsResource)：公开的皮肤素材整理仓库。本插件的素材
  **不取自它**，也不再读它的任何清单：`--dump` / `--downloaded` 那条线已经去掉（`--no-dump` 只剩兼容用的空开关），
  素材一律来自本机客户端的提取。名字补不全时只会退化成显示 skinId（`skin-catalogue.py --extra` 仍可吃任意
  只含元数据的名字清单，可选、不给也行）。
- Spine 运行时：pixi-spine（MIT）内嵌 Spine Runtime，受
  [Spine Runtimes License](http://esotericsoftware.com/spine-runtimes-license) 约束。

## 提取器（`extract/`）

`extract/` 里的三个 Python 文件是主项目 [Stronghold-Protocol](https://github.com/sganggs/Stronghold-Protocol)
的**原样拷贝**（逐字节一致，原文件头注释保留），来源分支/路径如下：

| 本仓库文件 | 来源仓库文件（分支 `feat/skins`，提交 `166ae6c2`） | 许可 |
| --- | --- | --- |
| `extract/extract.py` | `tools/local-extract/extract.py` | **GPL-3.0-or-later**（主项目自身许可） |
| `extract/scenes.py` | `tools/local-extract/scenes.py` | **GPL-3.0-or-later** |
| `extract/aklz4.py` | `tools/local-extract/aklz4.py` | **BSD-3-Clause**，Copyright (c) 2022 Harry Huang（[Ark-Unpacker](https://github.com/isHarryh/Ark-Unpacker) 的 LZ4AK 解码，随 [MooncellWiki/UnityPy](https://github.com/MooncellWiki/UnityPy) 分发）；全文见 `extract/LICENSE-Ark-Unpacker.txt` |
| `extract/requirements.txt` | `tools/local-extract/requirements.txt` | 依赖声明（UnityPy / lz4 / Pillow，各自许可） |
| `extract/LICENSE-Ark-Unpacker.txt` | `tools/local-extract/LICENSE-Ark-Unpacker.txt` | BSD-3-Clause 全文 |

`extract/extract.py` 是 GPL-3.0-or-later 的作品：**再分发本仓库时 `extract/` 与它一起受 GPL-3.0-or-later 约束**，
GPL-3.0 的**全文随仓库附在根目录的 [`LICENSE`](LICENSE)**（674 行 / 35,149 字节；与主项目检出里的 `LICENSE`
**逐字节相同**——本仓库统一用 LF，主项目检出那份是 CRLF，只有换行符不同）——那份文本只覆盖 `extract/` 这一部分，
本仓库自己的其余内容见下面"本仓库自身"一节。
（本仓库自己的脚本 `tools/build-plugin.py`、`tools/skin-catalogue.py`、`deploy.mjs`、`extract/skins.py` 与文档不受影响，
仍按本文件末尾的"本仓库自身"处理。）`extract/skins.py` 是本仓库新写的入口（只把上游的两条 job 暴露出来），
GPL 作品与它同目录分发，按 GPL 的口径这里也一并按 GPL-3.0-or-later 对待最省事。

`extract/aklz4.py` 是上游的**原样拷贝、没有改动一行**，所以文件头注释仍写着上游的路径。它的 BSD 许可那段注释
指的两个路径在本仓库里是另一处，对照如下（**只在本 NOTICE 里说明，不改上游文件本体**）：

| 注释里写的（上游 `tools/local-extract/` 的位置） | 本仓库里的位置 |
| --- | --- |
| `tools/local-extract/LICENSE-Ark-Unpacker.txt` | [`extract/LICENSE-Ark-Unpacker.txt`](extract/LICENSE-Ark-Unpacker.txt)（BSD-3-Clause 全文） |
| `THIRD-PARTY-NOTICES.md` | 本文件（`NOTICE.md`）的"工具与数据来源"一节 |

拷贝没有改动上游一行代码：`extract/skins.py` 在调用前把上游模块的 `ROOT` 与几个 `ROOT` 派生路径重定基到
`--data-root`（默认 `--server`），因为上游是按 `<主项目>/tools/local-extract/extract.py` 的位置推导这些路径的。

## 本仓库自身

`tools/build-plugin.py`、`tools/skin-catalogue.py`、`tools/local-catalogue.py`、`tools/bench-webp.py`、`deploy.mjs`、
`extract/skins.py`、`README.md`、`NOTICE.md` 是本仓库自己的内容，可自由使用与修改。
`catalogue/skins.json` 是元数据清单（见上文"目录表"一节），同样可以随本仓库自由分发。
根目录的 [`LICENSE`](LICENSE) 是 GPL-3.0 全文，**只为 `extract/` 而放**（见上文"提取器"一节），不是本仓库自己内容
的许可——上面列出的这些文件不在它覆盖范围内。
