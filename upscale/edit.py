"""Edits from the Video Dubbing page, made with this computer's own ffmpeg (used by ../server.py).

The page builds the ffmpeg arguments (the same recipe it runs in the browser) and sends them with the files.
This module only accepts that recipe: known options, known filters and files inside the job folder,
so a web page can never make ffmpeg read or write anything else.
The H.264 encoder is swapped for the fastest one that works here: NVIDIA NVENC, AMD AMF, Intel Quick Sync,
Apple VideoToolbox, or else the CPU with all its cores.
"""
import json, os, re, subprocess, sys, threading

import upscale as up

NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
NAME_OK = re.compile(r'^[a-z0-9][a-z0-9_-]{0,30}\.[a-z0-9]{1,5}$')
OUTPUTS = {'edit.mp4', 'edit.mkv', 'edit.m4a'}
FILTERS = {
    'split', 'asplit', 'crop', 'boxblur', 'overlay', 'trim', 'atrim', 'setpts', 'asetpts', 'concat', 'deshake', 'transpose',
    'hflip', 'vflip', 'cas', 'eq', 'lut3d', 'unsharp', 'gblur', 'reverse', 'areverse', 'scale', 'pad', 'setsar', 'framerate',
    'minterpolate', 'drawbox', 'afftdn', 'atempo', 'volume', 'aformat', 'sidechaincompress', 'amix', 'loudnorm', 'apad',
    'aevalsrc', 'fps', 'format', 'colorspace', 'null', 'anull', 'aresample',
}
NUM = re.compile(r'^\d+(\.\d+)?$')
WORD = re.compile(r'^[a-z0-9+-]{1,20}$')
KB = re.compile(r'^\d{1,6}k$')
MAP = re.compile(r'^(\[[a-z0-9]{1,12}\]|\d{1,2}:[va](:\d)?)$')
VALUES = {  # option -> allowed value (a set, a pattern, or a check done below)
    '-to': NUM, '-t': NUM, '-ss': NUM, '-f': {'concat'}, '-safe': {'0', '1'}, '-loop': {'1'}, '-stream_loop': {'-1'},
    '-map': MAP, '-c:v': {'libx264', 'copy'}, '-c:a': {'aac', 'copy'}, '-c': {'copy'}, '-preset': WORD, '-crf': NUM,
    '-b:v': KB, '-maxrate': KB, '-bufsize': KB, '-b:a': KB, '-colorspace': WORD, '-color_primaries': WORD,
    '-color_trc': WORD, '-color_range': WORD, '-movflags': {'+faststart'}, '-i': 'file', '-filter_complex': 'graph',
}
FLAGS = {'-hide_banner', '-an', '-vn'}
LIST_LINE = re.compile(r'^(ffconcat version 1\.0|file (b|s\d{1,5})\.png|duration \d+(\.\d+)?)$')


def graph_parts(g):
    """Split a filtergraph on , and ; that are not inside '...'."""
    parts, cur, q = [], '', False
    for ch in g:
        if ch == "'":
            q = not q
        if ch in ',;' and not q:
            parts.append(cur)
            cur = ''
        else:
            cur += ch
    return parts + [cur]


def check_graph(g):
    for part in graph_parts(g):
        f = re.sub(r'^(\[[a-z0-9:]{1,12}\])+', '', part.strip())  # input labels like [v3] or [0:v]
        f = re.sub(r'(\[[a-z0-9]{1,12}\])+$', '', f)
        name = re.split(r'[=@]', f, 1)[0]
        if name not in FILTERS:
            raise ValueError(f'filter not allowed: {name[:30]}')
        if 'file' in f.lower() and f != 'lut3d=file=lut.cube:interp=tetrahedral':
            raise ValueError('only lut.cube may be read by a filter')


def check(args, folder):
    """Raise ValueError unless args is a recipe the page makes. Returns the output file name."""
    if not args or not all(isinstance(a, str) for a in args) or len(args) > 400:
        raise ValueError('bad arguments')
    out = args[-1]
    if out not in OUTPUTS:
        raise ValueError('bad output name')
    i = 0
    while i < len(args) - 1:
        a = args[i]
        if a in FLAGS:
            i += 1
            continue
        rule = VALUES.get(a)
        if rule is None or i + 1 >= len(args) - 1:
            raise ValueError(f'option not allowed: {a[:30]}')
        v = args[i + 1]
        if rule == 'file':
            if not NAME_OK.match(v) or not os.path.isfile(os.path.join(folder, v)):
                raise ValueError(f'unknown file: {v[:40]}')
            if v == 'list.txt':
                with open(os.path.join(folder, v), encoding='utf-8') as f:
                    if not all(LIST_LINE.match(line.strip()) for line in f if line.strip()):
                        raise ValueError('bad subtitle list')
        elif rule == 'graph':
            check_graph(v)
        elif isinstance(rule, set):
            if v not in rule:
                raise ValueError(f'value not allowed for {a}')
        elif not rule.match(v):
            raise ValueError(f'value not allowed for {a}')
        i += 2
    return out


# ---- encoders: tested once, the fastest working one is used ----
CANDIDATES = ([('h264_nvenc', 'NVIDIA NVENC'), ('h264_amf', 'AMD AMF'), ('h264_qsv', 'Intel Quick Sync')] if sys.platform == 'win32'
              else [('h264_videotoolbox', 'Apple VideoToolbox')] if sys.platform == 'darwin'
              else [('h264_nvenc', 'NVIDIA NVENC'), ('h264_qsv', 'Intel Quick Sync')])


def hw_args(name, crf, rate):
    """Encoder options for a quality (crf) or for a bitrate (rate = [b, maxrate, bufsize])."""
    q = str(int(float(crf)) + 2) if crf else '23'
    if name == 'h264_nvenc':
        return ['-c:v', name, '-preset', 'p4', '-rc', 'vbr', '-profile:v', 'high'] + (
            ['-b:v', rate[0], '-maxrate', rate[1], '-bufsize', rate[2]] if rate else ['-cq', q, '-b:v', '0'])
    if name == 'h264_amf':
        return ['-c:v', name, '-quality', 'balanced', '-profile:v', 'high'] + (
            ['-rc', 'vbr_peak', '-b:v', rate[0], '-maxrate', rate[1], '-bufsize', rate[2]] if rate else ['-rc', 'cqp', '-qp_i', q, '-qp_p', q, '-qp_b', q])
    if name == 'h264_qsv':
        return ['-c:v', name, '-preset', 'faster', '-profile:v', 'high'] + (
            ['-b:v', rate[0], '-maxrate', rate[1], '-bufsize', rate[2]] if rate else ['-global_quality', q])
    if name == 'h264_videotoolbox':
        return ['-c:v', name, '-profile:v', 'high', '-allow_sw', '1'] + (['-b:v', rate[0], '-maxrate', rate[1]] if rate else ['-q:v', '62'])
    return ['-c:v', 'libx264', '-preset', 'veryfast', '-profile:v', 'high'] + (
        ['-b:v', rate[0], '-maxrate', rate[1], '-bufsize', rate[2]] if rate else ['-crf', crf or '21'])


_enc, _lock = None, threading.Lock()


def encoder():
    """(name, label) of the fastest H.264 encoder that really works here; tested once (a driver can be listed but broken)."""
    global _enc
    with _lock:
        if _enc is None:
            _enc = ('libx264', 'processor, all cores')
            if up.FFMPEG:
                for name, label in CANDIDATES:
                    try:
                        r = subprocess.run([up.FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=640x360:r=30:d=0.5', '-pix_fmt', 'yuv420p',
                                            *hw_args(name, None, None), '-f', 'null', '-'], capture_output=True, timeout=30, creationflags=NOWIN)
                        if r.returncode == 0:
                            _enc = (name, label)
                            break
                    except (OSError, subprocess.SubprocessError):
                        pass
        return _enc


def status():
    if not up.FFMPEG:
        return {'ready': bool(up.FF_URL), 'gpu': False, 'label': 'processor (ffmpeg is set up the first time)'}
    name, label = encoder()
    return {'ready': True, 'gpu': name != 'libx264', 'label': label}


def probe(path):
    j = json.loads(up.run([up.FFPROBE, '-v', 'error', '-show_entries',
                           'stream=codec_type,width,height,avg_frame_rate,r_frame_rate,color_range,color_space:format=duration',
                           '-of', 'json', path]).stdout)
    v = next((s for s in j.get('streams', []) if s.get('codec_type') == 'video'), {})
    rate = v.get('avg_frame_rate') if v.get('avg_frame_rate', '0/0') != '0/0' else v.get('r_frame_rate', '30/1')
    num, den = (rate.split('/') + ['1'])[:2]
    fps = float(num) / float(den) if float(den) else 30
    tags = ', '.join(x for x in (v.get('color_range'), v.get('color_space')) if x and x != 'unknown')
    return {'w': v.get('width', 0), 'h': v.get('height', 0), 'fps': fps, 'dur': float(j.get('format', {}).get('duration') or 0),
            'audio': any(s.get('codec_type') == 'audio' for s in j.get('streams', [])), 'tags': tags}


def run(args, folder, total, log, stop):
    """Run the checked recipe in its folder with the fastest encoder; falls back to the CPU if the graphics card fails."""
    up.ensure_ffmpeg(log)
    out = check(args, folder)
    args = ['1' if (a == '0' and i and args[i - 1] == '-safe') else a for i, a in enumerate(args)]  # safe concat lists only
    tries = [(args, 'ffmpeg')]
    if '-c:v' in args and args[args.index('-c:v') + 1] == 'libx264':
        k = args.index('-c:v')
        opts, j = {}, k + 2
        while j < len(args) - 1 and args[j] in ('-preset', '-crf', '-b:v', '-maxrate', '-bufsize'):
            opts[args[j]] = args[j + 1]
            j += 2
        rate = [opts['-b:v'], opts.get('-maxrate', opts['-b:v']), opts.get('-bufsize', opts['-b:v'])] if '-b:v' in opts else None
        small = opts.get('-preset') == 'veryfast' and opts.get('-crf') == '24'  # "Smaller file": the CPU encoder on purpose
        name, label = encoder()
        cpu = (args[:k] + hw_args('libx264', opts.get('-crf'), rate) + args[j:], 'the processor')
        tries = [cpu] if small or name == 'libx264' else [(args[:k] + hw_args(name, opts.get('-crf'), rate) + args[j:], label), cpu]
    err = ''
    for n, (cmd, label) in enumerate(tries):
        log(('Making the video' if n == 0 else 'The graphics card failed, making it with the processor') + '...', 0)
        p = subprocess.Popen([up.FFMPEG, '-y', '-nostats', '-progress', 'pipe:1', *cmd], cwd=folder, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', creationflags=NOWIN)
        tail = []
        t = threading.Thread(target=lambda: tail.extend(p.stderr.read().splitlines()[-20:]), daemon=True)
        t.start()
        for line in p.stdout:
            if stop():
                p.kill()
                raise up.Stopped()
            if line.startswith('out_time_us=') and line[12:].strip().isdigit() and total:
                done = int(line[12:]) / 1e6 / total
                log(f'Making the video with {label}: {min(99, int(done * 100))}%', min(1, done))
        code = p.wait()
        t.join(5)
        if code == 0:
            log(f'Made with {label}', 1)
            return os.path.join(folder, out)
        err = '\n'.join(tail)
    raise RuntimeError('ffmpeg could not make the video:\n' + err[-800:])
