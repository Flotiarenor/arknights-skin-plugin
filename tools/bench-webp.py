#!/usr/bin/env python3
"""立绘 WebP 转码的基准测试：`method`（Pillow 编码档位）与多进程并行的耗时/体积。

只做测量，不写插件、不改素材：每张图读出字节、在内存里编码、只统计**编码后的字节数**，
结果写 `--emit-json`（可选）并打印表格。用来给 `build-plugin.py --illust-method / --jobs` 的默认值定档。

  python tools/bench-webp.py --extract <local 目录> [--stems <文件>] [--limit N]
                             [--methods 6,5,4] [--qualities 85] [--jobs 1,4,8,16]
                             [--method-for-jobs 5] [--repeat 1] [--emit-json <文件>]

`--extract` 就是 `build-plugin.py --extract` 的那个 `public/assets/local`：立绘取
`spine/op/<charId>/<stem>/illust.{png,jpg,webp}`，其次 `library/opillust/<id>/illust.*`。
`--stems` 给了就只测那些（每行 `stem` 或 `charId/stem`），不给就测提取里全部有立绘的皮肤。
"""
import argparse
import io
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.stdout.reconfigure(encoding='utf-8')

ILLUSTR_NAMES = ('illust.png', 'illust.jpg', 'illust.webp')
IMAGE_EXT = ('.png', '.jpg', '.webp')


def say(text=''):
    print(text, flush=True)


def has_alpha(im):
    """这张图是不是带透明通道（WebP 要按 RGBA 编，否则透明处会变黑）。"""
    return im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info)


def encode(raw, quality, method):
    """一张图的字节 → WebP 字节（与 build-plugin.py 的立绘路径同一套参数）。"""
    from PIL import Image
    with Image.open(io.BytesIO(raw)) as src:
        im = src.convert('RGBA' if has_alpha(src) else 'RGB')
    buf = io.BytesIO()
    im.save(buf, format='WEBP', quality=quality, method=method)
    return buf.getvalue()


def encode_path(job):
    """子进程的活：读一张图、编码、只回报编码后的字节数（不落盘）。"""
    path, quality, method = job
    with open(path, 'rb') as fh:
        return len(encode(fh.read(), quality, method))


def scan_extract(root):
    """提取里的立绘：{ stem: 路径 }（模型目录优先，其次 library/opillust）。"""
    out = {}
    stems = set()
    op = os.path.join(root, 'spine', 'op')
    if os.path.isdir(op):
        for char_id in sorted(os.listdir(op)):
            cdir = os.path.join(op, char_id)
            if not os.path.isdir(cdir):
                continue
            for stem in sorted(os.listdir(cdir)):
                sdir = os.path.join(cdir, stem)
                if not os.path.isdir(sdir):
                    continue
                found = next((os.path.join(sdir, n) for n in ILLUSTR_NAMES if os.path.isfile(os.path.join(sdir, n))), None)
                if found:
                    out[f'{char_id}/{stem}'] = found
                    stems.add(stem)
    lib = os.path.join(root, 'library', 'opillust')
    if os.path.isdir(lib):
        for skin_id in sorted(os.listdir(lib)):
            found = next((os.path.join(lib, skin_id, n) for n in ILLUSTR_NAMES
                          if os.path.isfile(os.path.join(lib, skin_id, n))), None)
            if found and skin_id not in stems:
                out.setdefault(skin_id, found)
    return out


def pick(all_illust, stems_file, limit):
    if stems_file:
        with open(stems_file, encoding='utf-8') as fh:
            wanted = [line.strip() for line in fh if line.strip() and not line.startswith('#')]
        chosen = []
        for want in wanted:
            hit = all_illust.get(want)
            if not hit:
                hits = [v for k, v in all_illust.items() if k.endswith('/' + want)]
                hit = hits[0] if hits else None
            if not hit:
                raise SystemExit(f'--stems {stems_file}：{want} 在提取里没有立绘')
            chosen.append(hit)
    else:
        chosen = [all_illust[k] for k in sorted(all_illust)]
    return chosen[:limit] if limit else chosen


def human(n):
    return f'{n / 1048576:.2f} MiB'


def main(argv):
    ap = argparse.ArgumentParser(description='立绘 WebP 的 method / 并行基准（只测量，不写插件）')
    ap.add_argument('--extract', required=True, help='提取产物里的 public/assets/local')
    ap.add_argument('--stems', help='只测这些（每行 stem 或 charId/stem）；默认提取里全部有立绘的皮肤')
    ap.add_argument('--limit', type=int, default=0, help='只测前 N 张')
    ap.add_argument('--methods', default='6,5,4', help='要测的 Pillow method（逗号分隔；默认 6,5,4）')
    ap.add_argument('--qualities', default='85', help='要测的 quality（逗号分隔；默认 85）')
    ap.add_argument('--jobs', default='1,4,8,16', help='并行的 worker 数（逗号分隔；默认 1,4,8,16）')
    ap.add_argument('--method-for-jobs', type=int, default=None,
                    help='并行那一组用哪个 method（默认取 --methods 里最后一个）')
    ap.add_argument('--repeat', type=int, default=1, help='每组重复几次，取最快那次')
    ap.add_argument('--emit-json', help='把结果写成一个 JSON 文件')
    args = ap.parse_args(argv)

    root = os.path.abspath(args.extract)
    if not os.path.isdir(root):
        raise SystemExit(f'--extract {args.extract} 不是一个目录')
    all_illust = scan_extract(root)
    paths = pick(all_illust, args.stems, args.limit)
    if not paths:
        raise SystemExit(f'{root} 里找不到任何立绘')
    total_src = sum(os.path.getsize(p) for p in paths)
    cpus = os.cpu_count() or 1
    methods = [int(x) for x in args.methods.split(',') if x.strip()]
    qualities = [int(x) for x in args.qualities.split(',') if x.strip()]
    jobs = [int(x) for x in args.jobs.split(',') if x.strip()]
    method_for_jobs = args.method_for_jobs if args.method_for_jobs is not None else methods[-1]

    say(f'基准：{len(paths)} 张立绘 / 源图 {human(total_src)} / 逻辑 CPU {cpus}')
    say(f'  method {methods}，quality {qualities}，jobs {jobs}（并行那组 method {method_for_jobs}，重复 {args.repeat} 次取最快）')
    say()

    report = {'images': len(paths), 'source_bytes': total_src, 'cpus': cpus, 'serial': [], 'parallel': []}

    say('  单进程：method × quality')
    say(f'    {"method":<8}{"quality":<9}{"耗时 s":>10}{"s/张":>9}{"体积":>12}{"KB/张":>9}')
    for method in methods:
        for quality in qualities:
            best = None
            for _ in range(max(1, args.repeat)):
                started = time.perf_counter()
                total_bytes = 0
                for path in paths:
                    with open(path, 'rb') as fh:
                        total_bytes += len(encode(fh.read(), quality, method))
                seconds = time.perf_counter() - started
                if best is None or seconds < best[0]:
                    best = (seconds, total_bytes)
            seconds, total_bytes = best
            report['serial'].append({'method': method, 'quality': quality, 'seconds': seconds,
                                     'bytes': total_bytes, 'per_image_seconds': seconds / len(paths)})
            say(f'    {method:<8}{quality:<9}{seconds:>10.1f}{seconds / len(paths):>9.2f}'
                f'{human(total_bytes):>12}{total_bytes / len(paths) / 1024:>9.0f}')

    say()
    say(f'  多进程：method {method_for_jobs} × quality {qualities[0]}')
    say(f'    {"jobs":<8}{"耗时 s":>10}{"s/张":>9}{"体积":>12}{"加速比":>9}')
    baseline = next((r['seconds'] for r in report['serial']
                     if r['method'] == method_for_jobs and r['quality'] == qualities[0]), None)
    for n in jobs:
        best = None
        for _ in range(max(1, args.repeat)):
            started = time.perf_counter()
            if n <= 1:
                total_bytes = sum(encode_path((p, qualities[0], method_for_jobs)) for p in paths)
            else:
                with ProcessPoolExecutor(max_workers=n) as pool:
                    total_bytes = sum(pool.map(encode_path,
                                               ((p, qualities[0], method_for_jobs) for p in paths), chunksize=1))
            seconds = time.perf_counter() - started
            if best is None or seconds < best[0]:
                best = (seconds, total_bytes)
        seconds, total_bytes = best
        speed = (baseline / seconds) if baseline else None
        report['parallel'].append({'jobs': n, 'method': method_for_jobs, 'quality': qualities[0],
                                   'seconds': seconds, 'bytes': total_bytes, 'speedup': speed})
        say(f'    {n:<8}{seconds:>10.1f}{seconds / len(paths):>9.2f}{human(total_bytes):>12}'
            f'{(f"{speed:.2f}x" if speed else "—"):>9}')

    if args.emit_json:
        out = os.path.abspath(args.emit_json)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, 'w', encoding='utf-8', newline='\n') as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1)
            fh.write('\n')
        say()
        say(f'  结果：{out}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
