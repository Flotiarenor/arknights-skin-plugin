# arknights-skin-plugin — 已归档（只读）

> **归档说明（2026-11-28）**
> 本仓库的能力已全部并入上游 [Stronghold-Protocol](https://github.com/sganggs/Stronghold-Protocol)：
> 干员时装与图库提取（§37.331）、时装语音（§37.330）、召唤物（token）时装运行时（#876）、
> 召唤物时装提取（[PR #1000](https://github.com/sganggs/Stronghold-Protocol/pull/1000)，2026-11-26 合入，§37.351；
> 插件说明与只含召唤物的分卷由 [PR #1017](https://github.com/sganggs/Stronghold-Protocol/pull/1017) 补齐，2026-11-28，§37.373）。
> 本仓库自 2026-11-28 起归档为只读，代码与目录表保留作历史参考，不再更新。
> **新工作请直接用上游的 `tools/local-extract/extract.py --only skins`。**

这个仓库曾是《卫戍协议：盟约》同人复刻
[Stronghold-Protocol](https://github.com/sganggs/Stronghold-Protocol) 的本地构建工具箱：把本机客户端里的
干员时装与召唤物时装素材（Spine 正 / 背面、头像、半身像、立绘）做成 cosmetic 插件
（`operator-skin-select*`），装进服务器的 `plugins/`。

**本仓库只带脚本、目录表与说明，一套素材都不带**：所有 `.skel` / `.atlas` / `.png` 都只能在用户自己的
机器上、从用户自己的客户端提取后现场构建；仓库不提交、也不分发官方美术。

> 非官方、非商业同人用途。美术版权归 Hypergryph（上海鹰角网络）/ Yostar，详见 [NOTICE.md](NOTICE.md)。
> 权利人要求即删除。

---

## 迁移状态

| 能力 | 上游位置 | 状态 |
| --- | --- | --- |
| 干员时装 + 图库提取 | `tools/local-extract/extract.py --only skins` / `--only library`（PR #776 移植，§37.331） | 已合入 |
| 时装语音槽 | §37.330（PR #734 移植） | 已合入 |
| 召唤物（token）时装运行时 | PR #876：`tokens[<tokenId>].skins[<主人 skinId>]` | 已合入 |
| 召唤物时装提取 | [PR #1000](https://github.com/sganggs/Stronghold-Protocol/pull/1000)（并入 `--only skins`，§37.351） | 已合入（2026-11-26；说明与分卷见 PR #1017） |
| 名册 | 上游 `data/assets.json` 本来就是全版本并集 | 不需要迁移 |
| 目录表 `catalogue/skins.json` | — | 不迁移：上游提取时直接读 `.cache` 的官方表 |
| `deploy.mjs` / `merge-bundles.mjs` / 构建工具 | — | 不迁移：上游有 `client_bundles` 与 `plugin.mjs pack` |

两个按设计**没有模型**的召唤物标记单位不导出，跳过是预期行为，不是漏提取：
`token_10039_ulpia_block_epoque#48`（乌尔比安「必须开辟的通路」的
「[从不混淆的方向](https://prts.wiki/w/%E4%BB%8E%E4%B8%8D%E6%B7%B7%E6%B7%86%E7%9A%84%E6%96%B9%E5%90%91)」）
与 `token_10055_phatm2_mndclv_sightseer#4`（酒神「空剧场」的
「[迷狂牢笼](https://prts.wiki/w/%E8%BF%B7%E7%8B%82%E7%89%A2%E7%AC%BC)」）。

## 现在该用什么

在上游检出的根目录（需要官方 `skin_table.json`，默认 `.cache/gamedata/excel/skin_table.json`）：

```bash
# 在 Stronghold-Protocol 检出根目录
python tools/local-extract/extract.py --only skins --game "<客户端 AB 根>"
# 默认读 .cache/gamedata/excel/skin_table.json；产物在 out/local-extract/skins/local-skins*/
# （--out 可改输出根；skins / library 不写 data/local-assets.json）
```

上游文档：`docs/SKINS.md`、`docs/PLUGINS.md` §9、`docs/ASSETS.md`、
`docs/history/0.4.0.md`（§37.331 干员时装、§37.351 召唤物时装、§37.373 说明与分卷）。

召唤物时装提取已在上游（PR #1000 合入；PR #1017 补齐说明文字与只含召唤物的分卷）。本仓库的
`extract/token_skins.py` 只作参考实现留档，不必再跑。

## 仓库里还留着什么

- `MIGRATION-TO-UPSTREAM.md` — 完整迁移核对：能力对照、数字口径、两个标记单位、未迁移项、退役检查表。
- `extract/token_skins.py` — 召唤物时装提取的参考实现（PR #1000 已按上游接口重写并合入，此处留档）。
- `catalogue/skins.json` — 347 套 / 224 个干员的纯元数据目录（不迁移，留作历史）。
- `deploy.mjs`、`tools/`、`operator-skin-select/` 模板 — 旧的一键部署与构建工具（不迁移）。
- `extract/` 里其余文件是上游提取器的旧拷贝（GPL-3.0-or-later，见 [LICENSE](LICENSE)；
  `aklz4.py` 为 BSD-3-Clause）。

## 归档记录

- [x] 干员时装与图库、时装语音、召唤物运行时并入上游（§37.331 / §37.330 / #876）
- [x] 召唤物时装提取并入上游（[PR #1000](https://github.com/sganggs/Stronghold-Protocol/pull/1000)，2026-11-26，§37.351）
- [x] 合并后复查（[PR #1017](https://github.com/sganggs/Stronghold-Protocol/pull/1017)，2026-11-28，§37.373）：插件说明点名召唤物、只含召唤物的分卷也打包通过
- [x] 归档本仓库（GitHub → Settings → Archive，2026-11-28）；本 README 保留为归档说明
- 归档后本仓库只读；新问题请到上游仓库提。

---

> 历史版本（含完整的 `deploy.mjs` 九步、参数表、拆包与 WebP 说明）见本文件此前的提交。
