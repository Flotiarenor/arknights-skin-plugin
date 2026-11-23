# 迁移总结：`arknights-skin-plugin` → `Stronghold-Protocol`

> 写于 2026-11-23，对应 issue https://github.com/sganggs/Stronghold-Protocol/issues/996
> 核对基准：本机两份上游检出（D: 旧快照 / E: 新快照）＋ 本机客户端 `26-11-13` 热更 ＋ 插件仓库 `dev` @ `659c399`。
> **2026-11-24 更新**：召唤物时装提取已由
> [PR #1000](https://github.com/sganggs/Stronghold-Protocol/pull/1000) 实现（基于 `dev`，合并中）；
> 本仓库 README 已改为归档说明，合并后归档。

## 0. 结论

外部仓库退役后，**唯一曾缺的能力是召唤物（token）时装提取**；它已由 PR #1000 补上（合并中），
上游因此成为现有能力的超集：

- 干员时装：上游同表结果 **347 套 / 224 干员**，与本仓库目录表**零差**。
- 召唤物时装：本仓库 **88 套 / 57 token**；上游由 PR #1000 实现（运行时 #876 已在）。
- 名册、热更合并、分卷打包、图库三层、皮肤语音槽：上游都已具备，不需要迁移。

## 1. 上游已有，不用迁

| 能力 | 上游位置 | 状态 |
|---|---|---|
| 干员时装提取（Front/Back 模型、立绘、半身像、头像 → cosmetic 插件） | `tools/local-extract/skins.py`（PR #776 端口：`9449bf70` → `917431ea` → `7155ddee`） | 已有 |
| 皮肤自带语音槽 `voice` / `voiceJp` … | `shared/plugins/visual.js` 的 `OPERATOR_SKIN_RECORD`（PR #734 端口） | 已有 |
| 召唤物时装的运行时、协议、渲染与回退 | PR #876：`tokens[<tokenId>].skins[<主人 skinId>]`，每 token ≤ 64 套，不带 voice | 已有 |
| 召唤物时装提取 | [PR #1000](https://github.com/sganggs/Stronghold-Protocol/pull/1000)：`skins.py` 的 `token_plan` / `_faces` / `tokens` overlay，并入 `--only skins` | 合并中 |
| 插件格式与校验 | `shared/plugins/visual.js`、`schemas/overlay.schema.json`、`tools/plugin.mjs pack/check` | 已有 |
| 热更合并视图 | `tools/local-extract/bundles.py` 的 `client_bundles`（按 active 索引选包，不按 mtime） | 已有，比本仓库的 `tools/merge-bundles.mjs` 更准 |
| 分卷（512 MiB / 5000 文件 / 2000 目录） | `skins.py` 的 `Budget` / `part_folder` | 已有 |
| 图库三层（opillust / opportrait / opavatar） | `--only library` | 已有 |
| 版本名册覆盖 | `data/assets.json` 本身是全版本并集（`tools/assets/versions.mjs` 的 `presentationUnion`） | 已有 |

**名册不需要迁**：本仓库 `7f0caa4` 的“按每个版本的名册加宽”是给**自己 vendored 的旧 `extract.py`** 打的补丁（那份还读 `used_char_ids()` = 基础 `chess.json` + `backups.json`）。上游 #776 端口后改为读 `data/assets.json`，而这份清单由 `tools/fetch-assets.mjs` 从所有版本并集生成：

- 5 个版本 `data/versions/*/chess.json` 的 charId 并集 219 名，**版本独有 98 名全部在册**，且都有 avatar + spine；
- 有时装的出场干员 **196 名，196/196 在册**；
- `data/card-roster.json` 的 250 名**全部在册**。

## 2. 唯一要迁的：召唤物时装（PR #1000 已实现，合并中）

`extract/token_skins.py`（256 行）→ 并入上游 `--only skins`，**不另开 `--only token-skins`**（维护者在 #996 的要求）。PR #1000 按上游接口重写，不拷贝本仓库的 `token_skins.py`（它依赖本仓库 vendored `extract.py` 的 `facings_of` 和不同签名的 `write_spine`）。

| 环节 | 做法（已实现） |
|---|---|
| 映射 | 官方 `skin_table.json` 的 `charSkins[*].tokenSkinMap` → 反向索引 `ownerSkinId → [(tokenId, tokenSkinId)]`（`skins.token_plan`） |
| 读包 | `skinpack/<tokenId>.ab`（tokenId 本身以 `token_` 开头，所以实际文件名就是 `token_*.ab`；经 `client_bundles` 合并视图）；container 里 prefab 名 = `tokenSkinId`，`illust_` 前缀跳过 |
| 模型 | 按 SkeletonDataAsset 取（**不按骨架名匹配**）；Front / Back 用 `prefab_spine_nodes` + `pick_spine_node`，文件名沿用 `_face_namer` 规则，atlas 页名重写 |
| 头像 | `spritepack/ui_char_avatar_*.ab` 里名为 `tokenSkinId` 的 Sprite（180×180）；提不到就省略，客户端回退基础头像 |
| 记录 | `tokens[<tokenId>].skins[<主人 skinId>] = { name, group, avatar, spine: { front, back } }`；`name` / `group` 取**主人那套时装**的 `displaySkin`；**不带 voice** |
| 结构 | `overlay` / `read_parts` / `merge` / `keep_dirs` / `manifest` 的 `tokens` 平行结构；`_alive` / `record_dir` 复用，并纳入 `Budget` 分卷 |
| 权限 | 59 个 token 中 **11 个不在** `data/assets.json` 的 60 条 `tokens` 里 → 插件按 part 追加 `assets.add`（`docs/PLUGINS.md` §9 已允许），其余 48 个是 `assets.override` |
| 64 上限 | `SKINS_MAX = 64`（`shared/plugins/visual.js`，schema `tokenRecord.skins` 同值）。实测单 token 最多 3 套；超出时按官方顺序保留前 64 并**告警**，不静默截断 |
| `--only skins/<charId>` | 连带该主人时装的召唤物 |
| 两个标记单位 | `token_10039_ulpia_block_epoque#48`（乌尔比安「必须开辟的通路」的「[从不混淆的方向](https://prts.wiki/w/%E4%BB%8E%E4%B8%8D%E6%B7%B7%E6%B7%86%E7%9A%84%E6%96%B9%E5%90%91)」）与 `token_10055_phatm2_mndclv_sightseer#4`（酒神「空剧场」的「[迷狂牢笼](https://prts.wiki/w/%E8%BF%B7%E7%8B%82%E7%89%A2%E7%AC%BC)」）按设计没有模型，跳过是预期行为 |

**落地（PR #1000）**：

- `tools/local-extract/skins.py`：`token_plan` / `_faces` / `overlay` / `read_parts` / `manifest` / `keep_dirs` / `export` 的 `tokens` 分支与共用分卷、64 告警
- `tools/local-extract/extract.py`：`skin_jobs` 读 `.chars` + `.tokens`；`--only skins/<charId>` 连带
- `test/local-extract/skins.test.js`：fake UnityPy，覆盖映射 / Front-Back / 头像 / 64 / 权限 / 分卷 / `--limit` / `--only skins/<charId>` / `plugin.mjs pack`
- `docs/SKINS.md`、`docs/PLUGINS.md` §9、`docs/ASSETS.md`、`docs/ARCHITECTURE.md`、`docs/history/0.4.0.md` §37.349、`CHANGELOG.md`

## 3. 不迁移的（退役时丢掉）

| 东西 | 理由 |
|---|---|
| `catalogue/skins.json`（347 条） | 上游提取时直接读 `.cache` 官方表取名，347/347 命中（只有官方表自己的 2 条 `skinGroupName` 带尾随空格「巫异盛宴 」，上游 `_text()` 会 trim）。确需兜底表时只放元数据 + 溯源 sha256 |
| `deploy.mjs`（九步部署） | `client_bundles` + `tools/plugin.mjs pack` 已覆盖 |
| `tools/merge-bundles.mjs` | 上游 `bundles.py` 用 active 索引，比 mtime 合并更可靠 |
| `tools/skin-catalogue.py` / `local-catalogue.py` / `bench-webp.py` | 插件构建侧工具，不属于上游 |

## 4. 数字核对

| 口径 | 本仓库 | 上游同表结果 | 官方全表 |
|---|---|---|---|
| 干员时装 | 347 套 / 224 干员 | **347 套 / 224 干员（零差）** | 533 套 / 376 干员 |
| 召唤物时装 | 88 套 / 57 token | **88 套 / 57 token（PR #1000）** | 90 条映射 / 59 token |

- 与官方全表差的 **186 套 / 152 干员** = 本项目不出场的干员，按设计不进 plain run（要提就 `--only skins/<charId>` 点名）。
- 召唤物差的 **2 套**不是漏，是设计上没有模型的标记单位：
  - `token_10039_ulpia_block_epoque#48`（← `char_4145_ulpia@epoque#48`）是乌尔比安「必须开辟的通路」的「[从不混淆的方向](https://prts.wiki/w/%E4%BB%8E%E4%B8%8D%E6%B7%B7%E6%B7%86%E7%9A%84%E6%96%B9%E5%90%91)」；
  - `token_10055_phatm2_mndclv_sightseer#4`（← `char_1042_phatm2@sightseer#4`）是酒神「空剧场」的「[迷狂牢笼](https://prts.wiki/w/%E8%BF%B7%E7%8B%82%E7%89%A2%E7%AC%BC)」；
  - 两者游戏里靠标记 / 特效表现，提取器按名字跳过是预期行为，不是漏提取，也不算失败。
- 体积参考：本仓库 347 套 + 88 套召唤物皮肤 = 3498 文件 / 485.7 MiB（单包）；上游历史 342 套约 690 MiB（两卷）。召唤物约占 8–12%，现有分卷逻辑会自己处理。

## 5. 复现核对（容易踩的两个点）

**gamedata 快照**：同一台机器上并存两份，谁跑谁的检出，结果就是 338 vs 347。

| 位置 | sha256 | 字节 | charSkins | 日期 |
|---|---|---|---|---|
| `D:\project\html\Stronghold-Protocol\.cache\gamedata\excel\skin_table.json` | `422068f0…` | 3,825,497 | 2401 | 2026-10-13 |
| `E:\Stronghold-Protocol\.cache\gamedata\excel\skin_table.json` | `6bcaa2ad…` | 3,945,749 | 2482 | 2026-11-20 |

E: 那份就是 `catalogue/skins.json` 里 `source.officialSnapshot` 记录的那一份（sha256 与字节数逐位相同）。用 E: 表跑上游 `plan()` → 347 套 / 224 干员，与目录表两个方向集合差均为 0。

用 D: 旧表会恰好少下面 9 套（另有一第 10 套属于非出场干员，故不进 plain run）：

| # | skinId | 名字 / 分组 | 客户端里的包 |
|---|---|---|---|
| 1 | `char_1045_svash2@sale#20` | 雪覆伦城 / 忒斯特收藏·XXII | 基础树（10-23） |
| 2 | `char_4098_vvana@epoque#59` | 还愿礼 / 时代·LIX | 基础树（11-11） |
| 3 | `char_4039_horn@epoque#59` | 锋光初现 / 时代·LIX | 基础树（11-11） |
| 4 | `char_248_mgllan@epoque#60` | 绿影之下 / 时代·LX | 基础树 + 热更覆盖（11-16） |
| 5 | `char_4162_cathy@kitchen#5` | 暖冬教室 / 罗德厨房·V | 基础树（10-23） |
| 6 | `char_1047_halo2@striker#4` | 暗能质子 / 雷神推进者·IV | **只有热更**（11-16） |
| 7 | `char_2025_shu@nlc#1` | 源远流长 / 国家图书馆 | 基础树（11-11） |
| 8 | `char_1040_blaze2@nlc#1` | 夜行烛火 / 国家图书馆 | 基础树（11-11） |
| 9 | `char_1033_swire2@nlc#1` | 盛世之象 / 国家图书馆 | 基础树（11-11） |

第 10 套（表级差异但不是插件缺口）：`char_4178_alanna@race#3`（赤土拉力 / 啸风·III），主人 `char_4178_alanna` 不在 `data/assets.json`，本仓库也没收。

**客户端版本**：`char_1047_halo2@striker#4` 的包只在 `PersistentData/Bundles`，客户端没更新到 `26-11-13` 就会少这一套。同样，官方表里 59 个 token 对应的 `skinpack/token_*.ab` 也要客户端已下到对应版本。

## 6. 上游 PR 口径

- 已实现为 [PR #1000](https://github.com/sganggs/Stronghold-Protocol/pull/1000)（分支 `feat/local-extract-token-skins`，base `dev`）：一个 PR、一个主题：`--only skins` 带召唤物；**不动名册、不提交目录表、不并部署脚本**。
- 测试照 `test/local-extract/skins.test.js` 的假 UnityPy 写法（不需要客户端，16 个用例）；Pillow 相关测试在无 Pillow 分片跳过（#881）；Python 只要求 3.8 语法。
- PR 描述已写清：官方表快照版本与 sha256、客户端热更版本、两个标记单位的跳过、64 上限的告警行为、套数与体积实测数字。

## 7. 退役检查表

- [x] 上游 `--only skins` 带上召唤物时装，`tokens[id].skins` 与 #876 的运行时一致（PR #1000，合并中）
- [x] `--only skins/<charId>` 连带该主人的召唤物
- [x] 超过 64 套时告警（不静默截断）
- [x] 不在安装清单里的 token 走 `assets.add`
- [x] 分卷与 `plugin.mjs pack/check` 通过（含 `check --strict`）
- [x] 文档与 history 更新，`node --test test/docs-consistency.test.js test/docs-paths.test.js` 通过
- [x] `npm run golden` 无变化（291 场景全 match）；定向测试通过；本机 `npm run ci` 未跑完（环境原因，见 PR #1000 描述）
- [x] 本仓库 README 改为归档说明，指向上游文档
- [ ] PR #1000 合并后归档仓库
