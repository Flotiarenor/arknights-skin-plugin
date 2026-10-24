#!/usr/bin/env node
// tools/merge-bundles.mjs — 把客户端的「基础 AB 树」与 Unity 热更目录合成一份提取器能读的视图。
//
// 官方客户端把资产分两层：StreamingAssets/AB/Windows（安装时的那份）和
// PersistentData/Bundles（游戏内热更下载的那份，Unity 的 persistentDataPath）。客户端运行时先读热更、
// 再读基础树；而 extract/skins.py 只接受**一个** AB 根，所以热更新的皮肤（联动款等）不会被提取，
// 除非先把两层合成一份。
//
// 合并不复制素材：同一卷上全部用硬链接（热更文件覆盖同名的旧文件），另一卷上才退回复制。
// 输出目录默认在基础树旁边（`<…>/AB/Windows__merged`），保证同卷。
//
// 用法：
//   node tools/merge-bundles.mjs --ab "<…>/Arknights_Data/StreamingAssets/AB/Windows" [--out <目录>] [--dry-run]
//   node tools/merge-bundles.mjs --ab <…> --persistent "<…>/Arknights_Data/PersistentData/Bundles"
//
// 然后把 --game 指到输出目录：
//   python extract/skins.py --server <检出> --game "<输出目录>/Windows" --only library
//   python extract/skins.py --server <检出> --game "<输出目录>/Windows" --only skins
// （deploy.mjs 的 --game 也接受这个目录。）
import fs from 'node:fs';
import path from 'node:path';

const arg = (name, fallback = null) => {
  const i = process.argv.indexOf(name);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
};
const flag = (name) => process.argv.includes(name);

const ab = arg('--ab');
if (!ab) {
  console.error('用法：node tools/merge-bundles.mjs --ab "<…>/StreamingAssets/AB/Windows" [--out <目录>] [--dry-run]');
  process.exit(2);
}
const abRoot = path.resolve(ab);
if (!fs.existsSync(abRoot) || !fs.statSync(abRoot).isDirectory()) {
  console.error(`--ab ${ab} 不是一个目录`);
  process.exit(2);
}
// 热更目录：<Arknights_Data>/PersistentData/Bundles，与 StreamingAssets 同级（AB/Windows 往上三层）
const arkData = path.dirname(path.dirname(path.dirname(abRoot)));
const autoPersistent = path.join(arkData, 'PersistentData', 'Bundles');
const persistent = path.resolve(arg('--persistent', autoPersistent));
const outRoot = path.resolve(arg('--out', `${abRoot}__merged`));
const dryRun = flag('--dry-run');

const hasPersistent = fs.existsSync(persistent) && fs.statSync(persistent).isDirectory();
if (!hasPersistent && !arg('--persistent')) {
  console.log(`没有热更目录（${persistent}），不需要合并：直接把 --game 指到 ${abRoot}`);
  process.exit(0);
}
if (!hasPersistent) {
  console.error(`--persistent ${persistent} 不是一个目录`);
  process.exit(2);
}
if (outRoot === abRoot || abRoot.startsWith(outRoot + path.sep)) {
  console.error(`--out ${outRoot} 不能是 --ab 本身或它的上级`);
  process.exit(2);
}

const walk = (root, fn) => {
  for (const e of fs.readdirSync(root, { withFileTypes: true })) {
    const p = path.join(root, e.name);
    if (e.isDirectory()) walk(p, fn);
    else fn(p);
  }
};

let linked = 0;
let replaced = 0;
let copied = 0;

const place = (src, rel) => {
  const dst = path.join(outRoot, rel);
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  if (fs.existsSync(dst)) {
    fs.unlinkSync(dst);
    replaced++;
  } else {
    linked++;
  }
  try {
    fs.linkSync(src, dst);
  } catch {
    fs.copyFileSync(src, dst);
    copied++;
  }
};

console.log(`基础树  ${abRoot}`);
console.log(`热更    ${persistent}`);
console.log(`输出    ${outRoot}${dryRun ? '（--dry-run，不写）' : ''}`);
if (dryRun) {
  let base = 0;
  let hot = 0;
  walk(abRoot, () => base++);
  walk(persistent, () => hot++);
  console.log(`基础 ${base} 个文件，热更 ${hot} 个文件；实际合并会写成 ${base} 个硬链接（热更覆盖同名）`);
  process.exit(0);
}

if (fs.existsSync(outRoot)) fs.rmSync(outRoot, { recursive: true, force: true });
fs.mkdirSync(outRoot, { recursive: true });
walk(abRoot, (src) => place(src, path.relative(abRoot, src)));
walk(persistent, (src) => place(src, path.relative(persistent, src)));

console.log(`完成：${linked + replaced} 个文件（${replaced} 个被热更覆盖，${copied} 个跨卷复制）`);
console.log(`下一步：--game "${outRoot}"（它就是一个 AB 根，下面有 skinpack/、chararts/ 等）`);
