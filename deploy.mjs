#!/usr/bin/env node
// deploy.mjs — 一条命令把"本机客户端 → 插件（可能多个包）"整条链跑完（纯 ESM，无第三方依赖，除 pip 装依赖外不联网）。
//
//   node deploy.mjs --server E:\Stronghold-Protocol \
//                   --game "E:\arknight endfield\...\StreamingAssets\AB\Windows" \
//                   [--illust none|webp|png] [--illust-quality 85] [--illust-method 5] [--jobs 4] \
//                   [--split auto|n] [--split-target 500] [--have <文件|ids>] [--catalogue <文件>]... \
//                   [--python <解释器>] [--venv <目录>] [--force | --force-build] [--yes] [--dry-run]
//
// 九步（每一步先判断是否已完成，已完成就打印"跳过（已存在）"）：
//   1 找到客户端        2 确保 Python 环境      3 跑皮肤提取（extract/skins.py + extract/token_skins.py）
//   4 生成目录表        5 构建插件（可能拆成多个包）  6 pack（每个包）
//   7 check + --strict（每个包）  8 装进 <server>/plugins/（每个包）  9 汇总
//
// 素材只有一个来源：**本机客户端的提取产物**（`<server>/public/assets/local`）。提取里有多少套皮肤就收多少套，
// 一套不落；外观插件单包上限 512 MB（主项目 PLUGIN_CLASSES.cosmetic.bytes），整套素材默认就是一个包
// （`--split auto`、目标 500 MiB），超过目标才由 build-plugin.py 的 `--split` 拆成多个包（`plugins/<id>`、
// `plugins/<id>-2` …）。这个脚本不下载任何皮肤，也**不看任何 dump / 外部素材树**。
//
// 幂等与续跑：判断依据分别是 venv 能不能 import、提取产物的数量与清单、每一步的输入签名（存在 <repo>/.deploy/state.json）、
// plugin.lock.json 是否比 assets.json 新、plugins/<id> 与构建产物是否逐字节同源（比对 plugin.lock.json）。
// 因为一次构建产出多个包，pack / check / 安装这三步**按每个包各自算**（状态键是 `pack:<id>` / `install:<id>`）。
//
// `--force`       忽略这些判断，从头重跑第 2~6 步 —— **包括第 3 步的皮肤提取**，提取会重写
//                 `<server>/data/skins-local.json`（那个文件属于 `cs`，是主项目的产物）：上一次就是这么把 115 个
//                 干员的显示名覆盖掉的。除非你确实要重新提取，否则不要用它。
// `--force-build` 只重跑"构建（第 5 步）/ pack（第 6 步）/ check（第 7 步，本来就总跑）/ 安装（第 8 步）"，
//                 **第 3 步一律不跑**：不提取、不碰 `<server>/data/skins-local.json`；提取产物不完整就直接退出
//                 （码 2），不会顺手去补提取。这是"换了目录表/换了立绘参数，想重新出一遍包"时该用的开关。
//                 第 2 步**不是**一律不跑：venv 在且三个依赖都能 import 才跳过；venv 缺失或依赖不全时照样
//                 `python -m venv` + `pip install`（`--force` 才连这个跳过也一并忽略、强制重建）。那一步只写
//                 `<server>/.venv-extract/`（主项目 `.gitignore` 已挡住），不动任何提取产物。
// 任何一步失败都打印**原始命令**并原样退出码退出，不吞错误。

import { spawnSync } from 'node:child_process';
import {
  cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync,
} from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import { fileURLToPath } from 'node:url';

const REPO = path.dirname(fileURLToPath(import.meta.url));
const IS_WIN = process.platform === 'win32';
const STATE_DIR = path.join(REPO, '.deploy');
const STATE_FILE = path.join(STATE_DIR, 'state.json');
const EXTRACT_PY = path.join(REPO, 'extract', 'extract.py');
const SKINS_PY = path.join(REPO, 'extract', 'skins.py');
const TOKEN_SKINS_PY = path.join(REPO, 'extract', 'token_skins.py');
const REQUIREMENTS = path.join(REPO, 'extract', 'requirements.txt');
const CATALOGUE_PY = path.join(REPO, 'tools', 'skin-catalogue.py');
const BUILD_PY = path.join(REPO, 'tools', 'build-plugin.py');
const OUT_DIR = path.join(REPO, 'operator-skin-select');
// 随仓库分发的目录表（tools/local-catalogue.py 生成，纯元数据）：第 4 步的第一优先名字来源。
const CATALOGUE_LOCAL = path.join(REPO, 'catalogue', 'skins.json');
const CATALOGUE_OUT = path.join(REPO, 'data', 'skin-table.json');
const REPORT_FILE = path.join(REPO, 'data', 'build-report.json');
const MERGE_TOOL = path.join(REPO, 'tools', 'merge-bundles.mjs');

// 客户端 AB 根目录的常见位置（--game > 上次记录 > 这里）。
const GAME_CANDIDATES = [
  'E:\\arknight endfield\\Arknights bilibili\\games\\Arknights\\Arknights_Data\\StreamingAssets\\AB\\Windows',
  'C:\\Program Files\\Hypergryph Launcher\\games\\Arknights\\Arknights_Data\\StreamingAssets\\AB\\Windows',
  'C:\\Program Files (x86)\\Hypergryph Launcher\\games\\Arknights\\Arknights_Data\\StreamingAssets\\AB\\Windows',
  path.join(process.env.HOME || '', 'Library/Application Support/CrossOver/Bottles/Arknights/drive_c/Program Files/Hypergryph Launcher/games/Arknights/Arknights_Data/StreamingAssets/AB/Windows'),
  path.join(process.env.HOME || '', 'Library/Containers/com.hypergryph.arknights/Data/Documents/Bundles'),
];
// 拆出来的包（以及上一轮留下的包）：id 形如 operator-skin-select、operator-skin-select-2。
const PACKAGE_ID = /^operator-skin-select(-\d+)?$/;

const STEP_NAMES = [
  '找到客户端', '确保 Python 环境', '跑皮肤提取', '生成目录表', '构建插件', 'pack', 'check', '装进 plugins/', '汇总',
];
const TOTAL = STEP_NAMES.length;

// ---- 小工具 -------------------------------------------------------------------------------------------------------

const results = [];   // { n, name, status, seconds, bytes, note }
let current = null;

function log(text = '') { process.stdout.write(text + '\n'); }

function step(n, name) {
  current = { n, name, started: Date.now(), status: '完成', bytes: null, note: '' };
  results.push(current);
  process.stdout.write(`[${n}/${TOTAL}] ${name} … `);
}

function done(text, { status = '完成', bytes = null, note = '' } = {}) {
  const seconds = (Date.now() - current.started) / 1000;
  current.seconds = seconds;
  current.status = status;
  current.bytes = bytes;
  if (note) current.note = note;
  process.stdout.write(`${text ? text + '  ' : ''}用时 ${seconds.toFixed(1)}s\n`);
}

function human(bytes) {
  if (bytes === null || bytes === undefined) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / 1048576).toFixed(1)} MiB`;
}

function readJson(file) {
  try { return JSON.parse(readFileSync(file, 'utf8')); } catch { return null; }
}

function mtime(file) {
  try { return statSync(file).mtimeMs; } catch { return 0; }
}

function dirBytes(dir) {
  let total = 0;
  const walk = (d) => {
    let entries;
    try { entries = readdirSync(d, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p);
      else { try { total += statSync(p).size; } catch { /* vanished */ } }
    }
  };
  walk(dir);
  return total;
}

function countFiles(dir) {
  let n = 0;
  const walk = (d) => {
    let entries;
    try { entries = readdirSync(d, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      if (e.isDirectory()) walk(path.join(d, e.name));
      else n += 1;
    }
  };
  walk(dir);
  return n;
}

function countDirs(dir) {
  try { return readdirSync(dir, { withFileTypes: true }).filter((e) => e.isDirectory()).length; } catch { return 0; }
}

/** data/token-skins-local.json 里的召唤物皮肤总数（没有这个文件就 0）。 */
function countTokenSkins(file) {
  const doc = readJson(file);
  const tokens = doc?.tokens || {};
  return Object.values(tokens).reduce((n, t) => n + Object.keys(t?.skins || {}).length, 0);
}

/** 客户端 `skinpack/` 下的干员包数量（`skinpack` 是目录，里面是 `char_003_kalts.ab` 这样的文件）。 */
function countAb(dir) {
  try { return readdirSync(dir, { withFileTypes: true }).filter((e) => e.isFile() && e.name.endsWith('.ab')).length; } catch { return 0; }
}

function countStems(opDir) {
  let n = 0;
  let chars;
  try { chars = readdirSync(opDir, { withFileTypes: true }); } catch { return 0; }
  for (const c of chars) {
    if (!c.isDirectory()) continue;
    let subs;
    try { subs = readdirSync(path.join(opDir, c.name), { withFileTypes: true }); } catch { continue; }
    for (const s of subs) {
      if (s.isDirectory() && !['front', 'back'].includes(s.name.toLowerCase())) n += 1;
    }
  }
  return n;
}

function loadState() {
  const state = readJson(STATE_FILE) || { version: 1, steps: {} };
  if (!state.steps) state.steps = {};
  return state;
}

function saveState(state) {
  mkdirSync(STATE_DIR, { recursive: true });
  writeFileSync(STATE_FILE, JSON.stringify(state, null, 1) + '\n', 'utf8');
}

/** 跑一条命令：把原始命令与退出码原样报出来，失败就退出（不吞错误）。 */
function run(cmd, args, { cwd = REPO, allowFail = false, dry = false, label = '' } = {}) {
  const shown = [cmd, ...args].map((a) => (/\s/.test(a) ? `"${a}"` : a)).join(' ');
  if (dry) { log(`      $ ${shown}`); return { status: 0, stdout: '', dry: true }; }
  log(`      $ ${shown}`);
  const r = spawnSync(cmd, args, { cwd, stdio: ['ignore', 'inherit', 'inherit'], shell: false, encoding: 'utf8' });
  if (r.error) {
    log(`      失败：${r.error.message}`);
    log(`      原始命令：${shown}`);
    process.exit(1);
  }
  if (r.status !== 0 && !allowFail) {
    log(`      失败：退出码 ${r.status}${label ? `（${label}）` : ''}`);
    log(`      原始命令：${shown}`);
    process.exit(r.status || 1);
  }
  return { status: r.status, shown };
}

/** 跑一条命令并拿 stdout（解析 check 的输出，或探测解释器）。 */
function capture(cmd, args, { cwd = REPO } = {}) {
  const r = spawnSync(cmd, args, { cwd, encoding: 'utf8' });
  if (r.error) return { status: 127, stdout: '', stderr: r.error.message };
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' };
}

function checkOutput(cmd, args, { cwd = REPO } = {}) {
  const r = spawnSync(cmd, args, { cwd, encoding: 'utf8' });
  const text = `${r.stdout || ''}${r.stderr || ''}`.trim();
  if (text) for (const line of text.split(/\r?\n/)) log(`      ${line}`);
  return { status: r.status, text };
}

/** `1 folder(s): 0 problem(s), 0 warning(s)` → { problems, warnings } */
function parseCheck(text) {
  const m = /(\d+)\s*problem\(s\),\s*(\d+)\s*warning\(s\)/.exec(text);
  return m ? { problems: Number(m[1]), warnings: Number(m[2]) } : null;
}

function findExecutable(names) {
  for (const name of names) {
    const r = capture(name, ['-V']);
    if (r.status === 0) return name;
  }
  return null;
}

function signature(...parts) { return JSON.stringify(parts); }

function confirmOrExit(args) {
  const plan = [
    `客户端      ${args.game || '（自动探测）'}`,
    `服务器      ${args.server}`,
    `venv        ${args.venvDir}`,
    `提取        ${path.join(args.server, 'public', 'assets', 'local')}（唯一素材来源）`,
    `目录表      ${CATALOGUE_OUT}（名字来源第一优先：`
      + `${existsSync(CATALOGUE_LOCAL) ? CATALOGUE_LOCAL : '（仓库里没有 catalogue/skins.json）'}）`,
    `插件        ${OUT_DIR}（拆包：--split ${args.split}，每包目标 ≤${args.splitTarget} MiB，`
      + `立绘：${args.illust}${args.illust === 'webp' ? ` q${args.illustQuality} m${args.illustMethod} ${args.jobs ?? 'auto'} 进程` : ''}）`,
    `来源集合    ${args.have ? `跳过 --have ${args.have} 里的（其余全收）` : '提取里的全部皮肤（不给 --have）'}`,
    `装到        ${path.join(args.server, 'plugins', '<id>')}（每个包一个文件夹）`,
    `重跑        ${args.force ? '--force：第 2~6 步全部重跑，包括皮肤提取（会重写 data/skins-local.json）'
      : args.forceBuild ? '--force-build：只重跑构建 / pack / check / 安装，不跑提取、不建 venv'
        : '（没给 --force / --force-build：已完成的步骤跳过）'}`,
    `上次状态    ${existsSync(STATE_FILE) ? STATE_FILE : '（无）'}`,
  ];
  log('');
  log('将要执行：');
  for (const line of plan) log(`  ${line}`);
  if (args.yes) return;
  if (!process.stdin.isTTY) {
    log('');
    log('没有 --yes 且标准输入不是终端：不执行。要跑就加 --yes（或 --dry-run 先看命令）。');
    process.exit(2);
  }
}

async function ask() {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  const answer = await new Promise((resolve) => rl.question('继续？[y/N] ', resolve));
  rl.close();
  if (!/^y(es)?$/i.test(answer.trim())) { log('已取消。'); process.exit(0); }
}

// ---- 参数 ---------------------------------------------------------------------------------------------------------

function parseArgs(argv) {
  const args = {
    server: null, game: null, illust: 'webp', illustQuality: 85, illustMethod: 5, jobs: null,
    split: 'auto', splitTarget: 500, have: null, catalogue: [],
    python: null, venvDir: null, yes: false, dryRun: false, force: false, forceBuild: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    const next = () => {
      i += 1;
      if (i >= argv.length) { log(`参数 ${a} 缺一个值`); process.exit(2); }
      return argv[i];
    };
    switch (a) {
      case '--server': args.server = next(); break;
      case '--game': args.game = next(); break;
      case '--illust': args.illust = next(); break;
      case '--illust-quality': args.illustQuality = Number(next()); break;
      case '--illust-method': args.illustMethod = Number(next()); break;
      case '--jobs': args.jobs = Number(next()); break;
      case '--split': args.split = next(); break;
      case '--split-target': args.splitTarget = Number(next()); break;
      case '--python': args.python = next(); break;
      case '--venv': args.venvDir = next(); break;
      case '--have': args.have = next(); break;
      case '--catalogue': args.catalogue.push(next()); break;
      case '--yes': case '-y': args.yes = true; break;
      case '--dry-run': args.dryRun = true; break;
      case '--force': args.force = true; break;
      case '--force-build': args.forceBuild = true; break;
      case '-h': case '--help': usage(); process.exit(0); break;
      default: log(`未知参数 ${a}`); usage(); process.exit(2);
    }
  }
  if (!args.server) { log('缺 --server <服务器检出>'); usage(); process.exit(2); }
  args.server = path.resolve(args.server);
  if (!existsSync(args.server)) { log(`--server ${args.server} 不是一个目录`); process.exit(2); }
  if (!['none', 'webp', 'png'].includes(args.illust)) { log(`--illust 只能是 none|webp|png（给的 ${args.illust}）`); process.exit(2); }
  if (!(args.illustQuality >= 1 && args.illustQuality <= 100)) { log(`--illust-quality 要在 1..100（给的 ${args.illustQuality}）`); process.exit(2); }
  if (!(args.illustMethod >= 0 && args.illustMethod <= 6)) { log(`--illust-method 要在 0..6（给的 ${args.illustMethod}）`); process.exit(2); }
  if (args.jobs !== null && !(args.jobs >= 1)) { log(`--jobs 至少是 1（给的 ${args.jobs}）`); process.exit(2); }
  if (args.split !== 'auto' && !/^\d+$/.test(args.split)) { log(`--split 只能是整数或 auto（给的 ${args.split}）`); process.exit(2); }
  if (!(args.splitTarget > 0 && args.splitTarget <= 512)) { log(`--split-target 要在 1..512 MiB（给的 ${args.splitTarget}）`); process.exit(2); }
  args.venvDir = path.resolve(args.venvDir || path.join(args.server, '.venv-extract'));
  return args;
}

function usage() {
  log('用法: node deploy.mjs --server <服务器检出> [--game <AB 根>]');
  log('                      [--illust none|webp|png] [--illust-quality 1..100] [--illust-method 0..6] [--jobs N]');
  log('                      [--split <n|auto>] [--split-target <MiB>] [--have <文件|ids>] [--catalogue <文件>]...');
  log('                      [--python <解释器>] [--venv <目录>] [--force | --force-build] [--yes] [--dry-run]');
  log('');
  log('  --force        忽略"跳过"判断，重跑第 2~6 步——**包括第 3 步的皮肤提取**。提取会重写');
  log('                 <server>/data/skins-local.json（属于 cs），会覆盖别人的显示名。谨慎。');
  log('  --force-build  只重跑构建（5）/ pack（6）/ check（7）/ 安装（8）；**第 3 步（提取）一律不跑**，');
  log('                 因此绝不触碰 <server>/data/skins-local.json。提取产物不完整会直接退出（2）而不是去补提取。');
  log('                 第 2 步不是一律不跑：venv 可用（三个依赖都能 import）才跳过，否则仍会建 venv 并 pip install');
  log('                 （只写 <server>/.venv-extract/，不动提取产物；--force 才连这个跳过也一并忽略）。');
}

// ---- 九步 ---------------------------------------------------------------------------------------------------------

/** 上一次部署记下的客户端路径（还没被本轮覆盖的那个）。 */
function previousGame(state) {
  return state.steps?.extract?.game || state.game || null;
}

/**
 * 客户端是否换了。第 3 步据此决定要不要重新提取：判断必须拿**上一次**记下的路径来比，
 * 所以第 1 步在覆盖 `state.game` 之前先把旧值取出来交给它（`prior`）。
 */
function gameChanged(previous, game) {
  if (!previous || !game) return false;
  return path.resolve(previous) !== path.resolve(game);
}

function step1(args, state) {
  step(1, STEP_NAMES[0]);
  const previous = previousGame(state);
  let game = null;
  let source = '';
  if (args.game) {
    if (!existsSync(args.game)) {
      log('没找到');
      log(`--game ${args.game} 不是一个目录`);
      process.exit(2);
    }
    game = path.resolve(args.game);
    source = '--game';
  } else if (state.game && existsSync(state.game)) {
    game = state.game;
    source = '上次记录';
  } else {
    for (const c of GAME_CANDIDATES) {
      if (c && existsSync(c)) { game = c; source = '常见路径探测'; break; }
    }
  }
  if (!game) {
    log('没找到');
    log('找不到客户端。请给 --game <…/StreamingAssets/AB/Windows>。找过：');
    for (const t of GAME_CANDIDATES) log(`      ${t}`);
    process.exit(1);
  }
  game = path.resolve(game);
  const bundles = countAb(path.join(game, 'skinpack'));
  // 先记下本轮客户端，再交给第 3 步比较：旧值必须在这里取走，否则"客户端换了"永远比不出来。
  state.game = game;
  done(`${game}（来源：${source}，skinpack ${bundles} 个干员包）`);
  return { game, previous, changed: gameChanged(previous, game) };
}

function step2(args, state) {
  step(2, STEP_NAMES[1]);
  const venvPython = IS_WIN ? path.join(args.venvDir, 'Scripts', 'python.exe') : path.join(args.venvDir, 'bin', 'python');
  const probe = (exe) => capture(exe, ['-c', 'import UnityPy, lz4, PIL; print("UnityPy", UnityPy.__version__)']);
  if (existsSync(venvPython) && !args.force) {
    const r = probe(venvPython);
    if (r.status === 0) {
      done(`跳过（已存在）：${venvPython}，${r.stdout.trim()}`, { status: '跳过' });
      state.steps.python = { python: venvPython };
      return venvPython;
    }
    log(`（venv 存在但依赖不全：${r.stderr.trim().split('\n').pop()}）`);
  }
  let base = args.python;
  if (base) {
    if (capture(base, ['-V']).status !== 0) { log(`--python ${base} 跑不起来`); process.exit(1); }
  } else {
    base = findExecutable(['python', 'python3', 'py']);
    if (!base) { log('PATH 里没有 python/python3/py；用 --python <解释器> 指定'); process.exit(1); }
  }
  const created = !existsSync(venvPython) || args.force;
  if (created) run(base, ['-m', 'venv', args.venvDir], { dry: args.dryRun });
  if (!args.dryRun) run(venvPython, ['-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', REQUIREMENTS]);
  else log(`      $ ${venvPython} -m pip install -r "${REQUIREMENTS}"`);
  if (!args.dryRun) {
    const r = probe(venvPython);
    if (r.status !== 0) {
      log(`venv 建好了但依赖仍然不全：${r.stderr.trim()}`);
      log(`原始命令：${venvPython} -m pip install -r "${REQUIREMENTS}"`);
      process.exit(1);
    }
    done(`${created ? `新建 ${args.venvDir}` : `补装依赖 ${args.venvDir}`}（${r.stdout.trim()}）`);
  } else {
    done(`（dry-run：将${created ? '新建 venv 并' : ''} pip install）`);
  }
  state.steps.python = { python: venvPython, base };
  return venvPython;
}

/** 客户端的热更目录：`<Arknights_Data>/PersistentData/Bundles`，与 StreamingAssets 同级（AB/Windows 往上三层）。 */
function hotUpdateDir(game) {
  return path.join(path.dirname(path.dirname(path.dirname(game))), 'PersistentData', 'Bundles');
}

/**
 * 提取器只接受一个 AB 根，而客户端运行时是"热更目录优先、再读基础树"：只在热更里的皮肤（联动款）
 * 只有合成一份视图才提得到（tools/merge-bundles.mjs，硬链接，不复制素材）。没有热更目录就原样返回。
 * `build: false` 只算路径、不落盘（dry-run 用）。
 */
function extractionRoot(game, { build = true } = {}) {
  const hot = hotUpdateDir(game);
  if (game.endsWith('__merged') || !existsSync(hot) || !readdirSync(hot).length) return game;
  const merged = `${game}__merged`;
  if (!build) return merged;
  log(`      热更目录 ${hot}：先合成提取视图 ${merged}`);
  run(process.execPath, [MERGE_TOOL, '--ab', game, '--out', merged]);
  return merged;
}

function step3(args, state, client, python) {
  step(3, STEP_NAMES[2]);
  const { game, previous, changed: gameChangedFlag } = client;
  const out = path.join(args.server, 'public', 'assets', 'local');
  const manifest = path.join(args.server, 'data', 'local-assets.json');
  const libraryIndex = path.join(args.server, 'tools', 'skin-library', 'library-index.json');
  const tokenMeta = path.join(args.server, 'data', 'token-skins-local.json');
  const tokenTable = path.join(args.server, '.cache', 'gamedata', 'excel', 'skin_table.json');
  const opDir = path.join(out, 'spine', 'op');
  const stems = countStems(opDir);
  const manifestJson = readJson(manifest);
  const groups = manifestJson?.groups || {};
  const tiers = ['opavatar', 'opportrait', 'opillust'].map((t) => countDirs(path.join(out, 'library', t)));
  const groupsOk = Object.keys(groups).some((k) => k.startsWith('spine/op/')) && Object.keys(groups).length > 100;
  const tokenSkins = countTokenSkins(tokenMeta);
  const adequate = stems > 0 && tiers.every((n) => n > 0) && groupsOk && existsSync(libraryIndex);
  const sameGame = !gameChangedFlag;
  if (args.forceBuild) {
    // --force-build 的硬保证：第 3 步一律不跑。提取会重写 <server>/data/skins-local.json（那个文件属于 cs），
    // 所以这里宁可直接退出，也不在"顺手"的名义下把别人的产物覆盖掉。
    if (!adequate) {
      log('提取产物不完整，而 --force-build 不跑提取');
      log(`  spine/op ${stems} 套、library 头像/半身像/立绘 ${tiers.join('/')}、召唤物皮肤 ${tokenSkins} 套、` +
        `清单 ${Object.keys(groups).length} 组、图库索引 ${existsSync(libraryIndex) ? '在' : '不在'}，` +
        `客户端 ${sameGame ? '与上次相同' : '与上次不同'}`);
      log('  先跑一次不带 --force-build 的部署把提取补齐（那一步会重写 data/skins-local.json，属于 cs，需要服主同意）。');
      process.exit(2);
    }
    if (!sameGame) {
      log(`（客户端与上次不同：上次 ${previous}，这次 ${game}；--force-build 不重跑提取，插件里仍是上次那批美术）`);
    }
    if (tokenSkins === 0) {
      log('（还没有召唤物皮肤元数据；--force-build 不补提取，本次构建将不含召唤物皮肤）');
    }
    done(`跳过（--force-build 不重跑提取）：spine/op ${stems} 套、library 头像/半身像/立绘 ${tiers.join('/')}、` +
      `召唤物皮肤 ${tokenSkins} 套、清单 ${Object.keys(groups).length} 组`, { status: '跳过' });
    state.steps.extract = { ...(state.steps.extract || {}), forceBuildSkippedAt: new Date().toISOString(), stems, tokenSkins, out };
    return { out, manifest, libraryIndex, stems, tokenSkins, ran: false };
  }
  if (adequate && sameGame && !args.force) {
    if (tokenSkins === 0) {
      // 干员提取已经齐了，但还没有召唤物皮肤：只补跑 token 提取，不重写干员的那批产物。
      const extractGame = extractionRoot(game);
      log('      干员提取已完整，缺召唤物皮肤：只补跑 extract/token_skins.py');
      if (args.dryRun) {
        log(`      $ ${python} "${TOKEN_SKINS_PY}" --data-root ${args.server} --game ${extractGame} --out ${out} --manifest ${tokenMeta}`);
      } else if (!existsSync(tokenTable)) {
        log(`      warn 缺官方表 ${tokenTable}：跳过召唤物皮肤（只出干员皮肤）`);
      } else {
        run(python, [TOKEN_SKINS_PY, '--data-root', args.server, '--game', extractGame, '--out', out, '--manifest', tokenMeta]);
      }
      const tokenAfter = args.dryRun ? 0 : countTokenSkins(tokenMeta);
      done(`spine/op ${stems} 套（已有）、召唤物皮肤 ${tokenAfter} 套（只补跑）`, { status: '完成' });
      state.steps.extract = { at: new Date().toISOString(), game, stems, tokenSkins: tokenAfter, out };
      return { out, manifest, libraryIndex, stems, tokenSkins: tokenAfter, ran: true };
    }
    done(`跳过（已存在）：spine/op ${stems} 套、library 头像/半身像/立绘 ${tiers.join('/')}、召唤物皮肤 ${tokenSkins} 套、` +
      `清单 ${Object.keys(groups).length} 组`, { status: '跳过' });
    state.steps.extract = { at: new Date().toISOString(), game, stems, tokenSkins, out };
    return { out, manifest, libraryIndex, stems, tokenSkins, ran: false };
  }
  if (!sameGame) {
    log(`      客户端与上次不同（上次 ${previous}，这次 ${game}），重新提取`);
  }
  if (args.dryRun) {
    const dryGame = extractionRoot(game, { build: false });
    const flags = ['--data-root', args.server, '--game', dryGame, '--out', out, '--manifest', manifest];
    const tokenFlags = ['--data-root', args.server, '--game', dryGame, '--out', out, '--manifest', tokenMeta];
    if (dryGame !== game) log(`      热更目录会先合成提取视图：${dryGame}`);
    log(`      $ ${python} "${SKINS_PY}" ${flags.join(' ')} --only library`);
    log(`      $ ${python} "${SKINS_PY}" ${flags.join(' ')} --only skins`);
    log(`      $ ${python} "${TOKEN_SKINS_PY}" ${tokenFlags.join(' ')}`);
    done(`（dry-run：将先跑 library、再跑 skins，最后跑 召唤物皮肤${adequate ? '' : '；上次的提取不完整'}）`);
    return { out, manifest, libraryIndex, stems, tokenSkins, ran: false };
  }
  const extractGame = extractionRoot(game);
  // 上游按磁盘上的图库索引枚举客户端有哪些皮肤，而索引要到那次运行结尾才写：第一次必须分两趟。
  if (!existsSync(libraryIndex)) {
    run(python, [SKINS_PY, '--data-root', args.server, '--game', extractGame, '--out', out, '--manifest', manifest, '--only', 'library']);
  } else {
    log('      （图库索引已存在：只跑 skins 一趟）');
  }
  run(python, [SKINS_PY, '--data-root', args.server, '--game', extractGame, '--out', out, '--manifest', manifest, '--only', 'skins']);
  if (!existsSync(tokenTable)) {
    log(`      warn 缺官方表 ${tokenTable}：跳过召唤物皮肤（只出干员皮肤）`);
  } else {
    run(python, [TOKEN_SKINS_PY, '--data-root', args.server, '--game', extractGame, '--out', out, '--manifest', tokenMeta]);
  }
  const after = countStems(opDir);
  if (!after) { log('提取跑完了但 spine/op 里一套模型都没有 —— 上游没有可枚举的皮肤计划'); process.exit(1); }
  const tiersAfter = ['opavatar', 'opportrait', 'opillust'].map((t) => countDirs(path.join(out, 'library', t)));
  const tokenAfter = countTokenSkins(tokenMeta);
  done(`spine/op ${after} 套、library 头像/半身像/立绘 ${tiersAfter.join('/')}、召唤物皮肤 ${tokenAfter} 套`, { bytes: dirBytes(out) });
  state.steps.extract = { at: new Date().toISOString(), game, stems: after, tokenSkins: tokenAfter, out };
  return { out, manifest, libraryIndex, stems: after, tokenSkins: tokenAfter, ran: true };
}

function step4(args, state) {
  step(4, STEP_NAMES[3]);
  const official = path.join(args.server, '.cache', 'gamedata', 'excel', 'skin_table.json');
  const skinsMeta = path.join(args.server, 'data', 'skins-local.json');
  const skinIndex = path.join(args.server, 'tools', 'assets', 'local-skin-index.json');
  const extras = [...args.catalogue];
  // 仓库自带的目录表排在第一：它的名字最全，且不依赖服务器的官方 gamedata 缓存。
  const sources = [CATALOGUE_LOCAL, official, ...extras, skinsMeta, skinIndex].filter((p) => existsSync(p));
  const sig = signature('catalogue', sources.map((p) => [p, Math.round(mtime(p))]), Math.round(mtime(CATALOGUE_PY)));
  const fresh = existsSync(CATALOGUE_OUT) && mtime(CATALOGUE_OUT) > Math.max(0, ...sources.map(mtime));
  if (fresh && state.steps.catalogue?.sig === sig && !args.force) {
    const doc = readJson(CATALOGUE_OUT) || {};
    done(`跳过（已存在）：${CATALOGUE_OUT}（${doc.count || '?'} 个 skinId，${doc.named || 0} 个有名字）`, { status: '跳过' });
    return { file: CATALOGUE_OUT, sig };
  }
  // `skin-catalogue.py` 把 --skins-meta / --skin-index / --skin-table / --local-catalogue 当**显式路径**：
  // 给了但文件不在就直接退出（码 1）。所以这里一律先 existsSync 再加参数，缺的只警告、不传。
  // 三个都缺时退回只用仓库自带的 catalogue/skins.json，273 个名字与分组照样全有。
  const argv = ['--out', CATALOGUE_OUT];
  const absent = [];
  if (existsSync(skinsMeta)) argv.push('--skins-meta', skinsMeta);
  else absent.push(skinsMeta);
  if (existsSync(skinIndex)) argv.push('--skin-index', skinIndex);
  else absent.push(skinIndex);
  if (existsSync(CATALOGUE_LOCAL)) argv.push('--local-catalogue', CATALOGUE_LOCAL);
  if (existsSync(official)) argv.push('--skin-table', official);
  for (const e of extras) argv.push('--extra', e);
  if (absent.length) {
    log(`      警告：${absent.join('、')} 不在，本步只用剩下的来源（${sources.length} 个）`);
    if (!existsSync(CATALOGUE_LOCAL)) {
      log('      既没有提取元数据、也没有仓库目录表 catalogue/skins.json —— 这一版目录表不会有显示名');
    }
  }
  run(args.pythonPath || 'python', [CATALOGUE_PY, ...argv], { dry: args.dryRun });
  const doc = readJson(CATALOGUE_OUT) || {};
  if (args.dryRun) done('（dry-run）');
  else done(`${doc.count || '?'} 个 skinId（${doc.named || 0} 个有名字，来源 ${sources.length} 个）`,
    { bytes: existsSync(CATALOGUE_OUT) ? statSync(CATALOGUE_OUT).size : null });
  state.steps.catalogue = { sig, at: new Date().toISOString() };
  return { file: CATALOGUE_OUT, sig };
}

/** 构建报告里的包 → 真的还在磁盘上的那些（构建过后有人删过文件夹就重跑）。 */
function readPackages() {
  const report = readJson(REPORT_FILE);
  if (!report || !Array.isArray(report.packages) || !report.packages.length) return null;
  const out = [];
  for (const p of report.packages) {
    if (!p || typeof p.id !== 'string' || typeof p.dir !== 'string') return null;
    if (!PACKAGE_ID.test(p.id) || !existsSync(path.join(p.dir, 'plugin.json')) || !existsSync(path.join(p.dir, 'assets.json'))) return null;
    out.push({ ...p, bytes: dirBytes(p.dir), files: countFiles(p.dir) });
  }
  return out;
}

function step5(args, state, python, catalogue) {
  step(5, STEP_NAMES[4]);
  const skinsMeta = path.join(args.server, 'data', 'skins-local.json');
  const skinIndex = path.join(args.server, 'tools', 'assets', 'local-skin-index.json');
  const argv = ['--server', args.server, '--out', OUT_DIR,
    '--skin-index', skinIndex, '--skins-meta', skinsMeta, '--skin-table', catalogue,
    '--split', args.split, '--split-target', String(args.splitTarget)];
  if (args.have) argv.push('--have', args.have);
  if (args.illust === 'none') argv.push('--images', 'small');
  else argv.push('--images', 'all', '--illust-format', args.illust, '--illust-quality', String(args.illustQuality));
  if (args.illust === 'webp') {
    argv.push('--illust-method', String(args.illustMethod));
    if (args.jobs !== null) argv.push('--jobs', String(args.jobs));
  }

  const tokenMeta = path.join(args.server, 'data', 'token-skins-local.json');
  const sig = signature('build', 'local-only', args.illust, args.illustQuality, args.illustMethod, args.jobs ?? 'auto',
    args.split, args.splitTarget, args.have ? [args.have, Math.round(mtime(args.have))] : 'no-have',
    existsSync(tokenMeta) ? ['token-skins', Math.round(mtime(tokenMeta))] : 'no-token-skins',
    Math.round(mtime(catalogue)), Math.round(mtime(BUILD_PY)));
  const fresh = existsSync(REPORT_FILE) && mtime(REPORT_FILE) > Math.max(mtime(BUILD_PY), mtime(catalogue), mtime(tokenMeta));
  if (fresh && state.steps.build?.sig === sig && !args.force && !args.forceBuild) {
    const packages = readPackages();
    if (packages) {
      const skins = packages.reduce((n, p) => n + (p.skins || 0), 0);
      const bytes = packages.reduce((n, p) => n + p.bytes, 0);
      done(`跳过（已存在）：${packages.length} 个包 / ${skins} 套 / ${human(bytes)}`, { status: '跳过', bytes });
      return { sig, packages };
    }
    log('（构建报告里的包已经不在了，重新构建）');
  }
  if (!args.have) log('      来源：提取里的全部皮肤（没有 --have，不跳过任何一套）');
  else log(`      --have：跳过 ${args.have} 里已经有的那批`);
  run(python, [BUILD_PY, ...argv], { dry: args.dryRun });
  if (args.dryRun) { done('（dry-run）'); return { sig, packages: null }; }
  const packages = readPackages();
  if (!packages) { log(`构建跑完了但没有可用的 ${REPORT_FILE}`); process.exit(1); }
  const skins = packages.reduce((n, p) => n + (p.skins || 0), 0);
  const bytes = packages.reduce((n, p) => n + p.bytes, 0);
  done(`${packages.length} 个包 / ${skins} 套 / ${packages.reduce((n, p) => n + (p.chars || 0), 0)} 个干员 / ${human(bytes)}`, { bytes });
  state.steps.build = { sig, at: new Date().toISOString(), packages: packages.map((p) => p.id) };
  return { sig, packages };
}

function step6(args, state, server, build) {
  step(6, STEP_NAMES[5]);
  const tool = path.join(server, 'tools', 'plugin.mjs');
  const packages = build.packages || [];
  let skipped = 0;
  const bytes = [];
  for (const p of packages) {
    const sig = signature(build.sig, p.id);
    const lock = path.join(p.dir, 'plugin.lock.json');
    const assetsJson = path.join(p.dir, 'assets.json');
    const pluginJson = path.join(p.dir, 'plugin.json');
    const fresh = existsSync(lock) && mtime(lock) >= Math.max(mtime(assetsJson), mtime(pluginJson));
    if (fresh && state.steps[`pack:${p.id}`]?.sig === sig && !args.force && !args.forceBuild) {
      skipped += 1;
      bytes.push(human(statSync(lock).size));
      continue;
    }
    run(process.execPath, [tool, 'pack', p.dir], { dry: args.dryRun });
    if (!args.dryRun && !existsSync(lock)) { log(`pack 跑完了 ${p.id} 却没有 plugin.lock.json`); process.exit(1); }
    if (!args.dryRun) state.steps[`pack:${p.id}`] = { sig, at: new Date().toISOString() };
    bytes.push(args.dryRun ? '—' : human(statSync(lock).size));
  }
  const total = packages.reduce((n, p) => n + dirBytes(p.dir), 0);
  done(`${packages.length} 个包（${skipped} 个跳过）：plugin.lock.json ${bytes.join(' / ')}`,
    { status: skipped === packages.length && packages.length ? '跳过' : '完成', bytes: total });
  return packages;
}

function step7(args, server, packages) {
  step(7, STEP_NAMES[6]);
  const tool = path.join(server, 'tools', 'plugin.mjs');
  const out = [];
  for (const p of packages) {
    if (args.dryRun) {
      log(`      $ ${process.execPath} "${tool}" check ${p.dir}`);
      log(`      $ ${process.execPath} "${tool}" check ${p.dir} --strict`);
      out.push({ id: p.id, problems: null, warnings: null, strict: null });
      continue;
    }
    const plain = checkOutput(process.execPath, [tool, 'check', p.dir]);
    const strict = checkOutput(process.execPath, [tool, 'check', p.dir, '--strict']);
    const a = parseCheck(plain.text);
    const b = parseCheck(strict.text);
    if (plain.status !== 0 || strict.status !== 0) {
      log(`check 失败（${p.id}）：check 退出码 ${plain.status}，check --strict 退出码 ${strict.status}`);
      log(`原始命令：${process.execPath} "${tool}" check ${p.dir} --strict`);
      process.exit(1);
    }
    log(`      ${p.id}：check ${a ? `${a.problems} problem / ${a.warnings} warning` : '?'}，`
      + `--strict ${b ? `${b.problems} problem / ${b.warnings} warning` : '?'}`);
    out.push({ id: p.id, problems: a?.problems ?? null, warnings: a?.warnings ?? null, strict: b?.problems ?? null });
  }
  if (args.dryRun) done('（dry-run）');
  else {
    const bad = out.filter((r) => r.problems || r.warnings || r.strict);
    done(bad.length ? `${bad.length} 个包还有 problem/warning` : `${packages.length} 个包全部 0 problem / 0 warning`);
  }
  return out;
}

function step8(args, state, server, packages) {
  step(8, STEP_NAMES[7]);
  const pluginsDir = path.join(server, 'plugins');
  const installed = [];
  for (const p of packages) {
    const dest = path.join(pluginsDir, p.id);
    if (!path.resolve(dest).startsWith(path.resolve(pluginsDir) + path.sep)) {
      log(`拒绝写入 ${dest}：不在 ${pluginsDir} 下`);
      process.exit(1);
    }
    const doneKey = `install:${p.id}`;
    const srcLock = path.join(p.dir, 'plugin.lock.json');
    const dstLock = path.join(dest, 'plugin.lock.json');
    const srcManifest = path.join(p.dir, 'plugin.json');
    const dstManifest = path.join(dest, 'plugin.json');
    const sig = existsSync(srcLock) ? signature(p.id, statSync(srcLock).size, Math.round(mtime(srcLock))) : null;
    const same = sig !== null && state.steps[doneKey]?.sig === sig
      && existsSync(dstLock) && readFileSync(srcLock).equals(readFileSync(dstLock))
      && existsSync(dstManifest) && readFileSync(srcManifest).equals(readFileSync(dstManifest))
      && countFiles(dest) === countFiles(p.dir);
    if (same && !args.force && !args.forceBuild) {
      log(`      ${p.id}：跳过（已存在，与构建产物逐字节一致，${human(dirBytes(dest))}）`);
      installed.push({ id: p.id, dir: dest, bytes: dirBytes(dest), skipped: true });
      continue;
    }
    if (args.dryRun) {
      log(`      $ rm -rf "${dest}" && cp -r "${p.dir}" "${dest}"`);
      installed.push({ id: p.id, dir: dest, bytes: null, skipped: false });
      continue;
    }
    if (existsSync(dest)) rmSync(dest, { recursive: true, force: true });
    mkdirSync(path.dirname(dest), { recursive: true });
    cpSync(p.dir, dest, { recursive: true });
    state.steps[doneKey] = { sig, at: new Date().toISOString() };
    const bytes = dirBytes(dest);
    log(`      ${p.id}：已装到 ${dest}（${countFiles(dest)} 个文件 / ${human(bytes)}）`);
    installed.push({ id: p.id, dir: dest, bytes, skipped: false });
  }
  // 上一轮拆出来的包如果这一轮不再需要，就从 plugins/ 里删掉（只删 id 对得上的插件目录）。
  const keep = new Set(installed.map((i) => i.id));
  const removed = [];
  let names = [];
  try { names = readdirSync(pluginsDir); } catch { /* no plugins/ */ }
  for (const name of names) {
    if (!PACKAGE_ID.test(name) || keep.has(name)) continue;
    const dir = path.join(pluginsDir, name);
    const manifest = readJson(path.join(dir, 'plugin.json'));
    if (!manifest || manifest.id !== name) continue;
    if (args.dryRun) { log(`      $ rm -rf "${dir}"（上一轮的包，这次不需要）`); removed.push(name); continue; }
    rmSync(dir, { recursive: true, force: true });
    removed.push(name);
  }
  if (removed.length) log(`      已删掉上一轮的包：${removed.join('、')}`);
  const bytes = installed.reduce((n, i) => n + (i.bytes || 0), 0);
  done(`${installed.length} 个包（${installed.filter((i) => i.skipped).length} 个跳过）`
    + `${removed.length ? `，删掉 ${removed.length} 个旧包` : ''}`,
    { status: installed.every((i) => i.skipped) && installed.length && !removed.length ? '跳过' : '完成', bytes });
  return installed;
}

function step9(args, build, check, installed) {
  step(9, STEP_NAMES[8]);
  done('汇总如下');
  const skipped = results.filter((r) => r.status === '跳过');
  log('');
  const pad = (s, n) => {
    let width = 0;
    for (const ch of String(s)) width += ch.charCodeAt(0) > 0x2e80 ? 2 : 1;
    return String(s) + ' '.repeat(Math.max(0, n - width));
  };
  log(`  ${pad('步骤', 26)}${pad('结果', 34)}${pad('用时', 10)}体积`);
  for (const r of results) {
    log(`  ${pad(`[${r.n}/9] ${r.name}`, 26)}${pad(r.status, 34)}${pad(`${(r.seconds || 0).toFixed(1)}s`, 10)}${human(r.bytes)}`);
  }
  const seconds = results.reduce((n, r) => n + (r.seconds || 0), 0);
  const packages = build.packages || [];
  const totalBuild = packages.reduce((n, p) => n + dirBytes(p.dir), 0);
  log(`  ${pad('合计', 26)}${pad(`${results.length - skipped.length} 步执行 / ${skipped.length} 步跳过`, 34)}`
    + `${pad(`${seconds.toFixed(1)}s`, 10)}${human(totalBuild)}`);
  log('');
  log('  产出的包：');
  const width = Math.max(24, ...packages.map((p) => p.id.length));
  log(`  ${pad('id', width + 2)}${pad('显示名', 30)}${pad('套数', 6)}${pad('干员', 6)}${pad('文件', 7)}${pad('体积', 12)}check`);
  for (const p of packages) {
    const c = (check || []).find((x) => x.id === p.id);
    const status = c && (c.problems || c.warnings || c.strict) ? `${c.problems} problem / ${c.warnings} warning` : '0 problem / 0 warning';
    log(`  ${pad(p.id, width + 2)}${pad(p.name || '', 30)}${pad(p.skins ?? '?', 6)}${pad(p.chars ?? '?', 6)}`
      + `${pad(countFiles(p.dir), 7)}${pad(human(dirBytes(p.dir)), 12)}${status}`);
  }
  const totalSkins = packages.reduce((n, p) => n + (p.skins || 0), 0);
  log(`  ${pad('合计', width + 2)}${pad(`${packages.length} 个包`, 30)}${pad(totalSkins, 6)}`
    + `${pad(packages.reduce((n, p) => n + (p.chars || 0), 0), 6)}`
    + `${pad(packages.reduce((n, p) => n + countFiles(p.dir), 0), 7)}${pad(human(totalBuild), 12)}`);
  log('');
  log(`  插件目录    ${OUT_DIR}${packages.length > 1 ? `（拆成 ${packages.length} 个包，见上表）` : ''}`);
  for (const i of installed || []) log(`  已装到      ${i.dir}（${human(i.bytes)}）`);
  log(`  目录表      ${CATALOGUE_OUT}（${readJson(CATALOGUE_OUT)?.count ?? '?'} 个 skinId，`
    + `${readJson(CATALOGUE_OUT)?.named ?? '?'} 个有名字；第一优先来源 `
    + `${existsSync(CATALOGUE_LOCAL) ? '仓库自带 catalogue/skins.json' : '官方表/提取元数据'}）`);
  log(`  素材来源    本机提取 ${path.join(args.server, 'public', 'assets', 'local')}`
    + `${args.have ? `（--have ${args.have} 命中的跳过）` : '（提取里的全部）'}`);
  log('');
  log('  下一步怎么做：');
  log('    1) 服主（唯一能做这件事的人）：包已经在 plugins/ 下；服务器不用重启，刷新页面即可。');
  log('    2) 每个玩家在自己浏览器里开启：设置 → 外观插件 → 打开它。谁开谁看得到，各开各的。');
  for (const p of packages.length > 1 ? packages : []) log(`         ${p.id} —— ${p.name}`);
  log('    3) 房主无关：这些包 scope 只有 personal，房间面板上没有它们的开关。');
  log('    4) 没开启的人看到默认外观，包括看别人的棋子。');
  log(`    5) 核对：node "${path.join(args.server, 'tools', 'plugin.mjs')}" list 应列出 `
    + `${packages.map((p) => p.id).join('、')}；GET /plugins/index.json 有它们且不含任何磁盘路径。`);
}

// ---- main ---------------------------------------------------------------------------------------------------------

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!existsSync(EXTRACT_PY) || !existsSync(SKINS_PY) || !existsSync(BUILD_PY) || !existsSync(CATALOGUE_PY)) {
    log(`仓库不完整：需要 extract/extract.py、extract/skins.py、tools/build-plugin.py、tools/skin-catalogue.py（${REPO}）`);
    process.exit(1);
  }
  const state = loadState();
  if (args.dryRun) log('（--dry-run：只打印将执行的命令，不写任何东西）');
  confirmOrExit(args);
  if (!args.yes && process.stdin.isTTY) await ask();

  const server = args.server;
  const persist = () => { if (!args.dryRun) saveState(state); };
  const client = step1(args, state);
  const python = step2(args, state);
  args.pythonPath = python;
  persist();

  step3(args, state, client, python);
  persist();
  const catalogue = step4(args, state);
  persist();
  const build = step5(args, state, python, catalogue.file);
  persist();
  step6(args, state, server, build);
  persist();
  const check = step7(args, server, build.packages || []);
  const installed = step8(args, state, server, build.packages || []);
  step9(args, build, check, installed);
  persist();
  return 0;
}

main().then((code) => { process.exitCode = code; }, (err) => {
  log(`未捕获的错误：${err?.stack || err}`);
  process.exitCode = 1;
});
