"""AI video upscaler: Real-ESRGAN on your graphics card, then NVENC encoding.

  upscale.cmd                        drag a video onto it, it asks for the size
  python upscale.py VIDEO --to 4k    2k | 4k | 8k   [--model photo|anime] [--check]

Also used by ../server.py when the web page picks "AI upscale".
Works on Windows, Linux and macOS. The first run downloads realesrgan-ncnn-vulkan
(45-50 MB, github.com/xinntao/Real-ESRGAN) into this folder, and ffmpeg too when it is
missing (Windows and Linux; on macOS install it with: brew install ffmpeg).
The video is done in small chunks, so the disk only ever holds a few hundred frames,
and an interrupted run continues where it stopped.
"""
import argparse, json, os, shutil, stat, subprocess, sys, tarfile, time, urllib.request, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
WIN, MAC = sys.platform == 'win32', sys.platform == 'darwin'
EXE = '.exe' if WIN else ''
_REL = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-'
TOOL_URL = _REL + ('windows.zip' if WIN else 'macos.zip' if MAC else 'ubuntu.zip')
TOOL_EXE = 'realesrgan-ncnn-vulkan' + EXE
TOOL_DIR = os.path.join(HERE, 'realesrgan')
TARGETS = {'2k': 1440, '4k': 2160, '8k': 4320}
MODELS = {'photo': 'realesrgan-x4plus', 'anime': 'realesr-animevideov3'}
CHUNK = {1440: 300, 2160: 150, 4320: 50}  # frames per chunk: keeps temporary PNGs to a few GB
NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class Stopped(Exception):
    pass


_FF = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-'
FF_URL = None if MAC else _FF + ('win64-gpl.zip' if WIN else 'linux64-gpl.tar.xz')  # macOS: use Homebrew
FF_DIR = os.path.join(HERE, 'ffmpeg')


def find(name):
    for root, _, files in os.walk(FF_DIR):  # our own copy, set up on first use
        if name + EXE in files:
            return os.path.join(root, name + EXE)
    extra = ['C:/ffmpeg/bin'] if WIN else ['/opt/homebrew/bin', '/usr/local/bin', '/usr/bin']
    for p in [os.path.join(d, name + EXE) for d in extra] + [shutil.which(name)]:
        if p and os.path.exists(p):
            return p
    return None


FFMPEG, FFPROBE = find('ffmpeg'), find('ffprobe')


def download(url, dest_dir, label, log):
    """Download a .zip or .tar.xz with progress and unpack it into dest_dir."""
    z = dest_dir + ('.tar.xz' if url.endswith('.tar.xz') else '.zip')
    last = [-1]
    def hook(n, size, total):  # report every 10 %, not every block
        if total > 0:
            pct = min(100, n * size * 100 // total) // 10 * 10
            if pct != last[0]:
                last[0] = pct
                log(f'Setting up {label}: {pct}%', pct / 100)
    urllib.request.urlretrieve(url, z, hook)
    if z.endswith('.zip'):
        with zipfile.ZipFile(z) as f:
            f.extractall(dest_dir)
    else:
        with tarfile.open(z) as f:
            f.extractall(dest_dir)
    os.remove(z)
    if not WIN:  # zip files do not keep the "executable" flag
        for root, _, files in os.walk(dest_dir):
            for n in files:
                if '.' not in n or n.endswith(('.dylib', '.so')):
                    full = os.path.join(root, n)
                    os.chmod(full, os.stat(full).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def ensure_ffmpeg(log=print):
    global FFMPEG, FFPROBE
    if not (FFMPEG and FFPROBE):
        if not FF_URL:
            raise RuntimeError('ffmpeg is needed. Install it with: brew install ffmpeg   (see https://brew.sh)')
        download(FF_URL, FF_DIR, 'ffmpeg (150-200 MB, one time)', log)
        FFMPEG, FFPROBE = find('ffmpeg'), find('ffprobe')
        if not (FFMPEG and FFPROBE):
            raise RuntimeError('The ffmpeg download did not contain ffmpeg.')
    return FFMPEG


def run(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=cwd, creationflags=NOWIN)
    if r.returncode != 0:
        raise RuntimeError(f'{os.path.basename(cmd[0])} failed:\n' + (r.stderr or r.stdout)[-1500:])
    return r


def tool_path():
    for root, _, files in os.walk(TOOL_DIR):
        if TOOL_EXE in files:
            return os.path.join(root, TOOL_EXE)
    return None


def tool(log=print):
    if tool_path():
        return tool_path()
    download(TOOL_URL, TOOL_DIR, 'Real-ESRGAN (45-50 MB, one time)', log)
    if not tool_path():
        raise RuntimeError(f'The Real-ESRGAN download did not contain {TOOL_EXE}.')
    return tool_path()


def pick_gpu(exe, work):
    """Real-ESRGAN lists the graphics cards it sees; prefer NVIDIA/AMD over the built-in Intel chip."""
    tiny, out = os.path.join(work, 'gpu-in.png'), os.path.join(work, 'gpu-out.png')
    run([FFMPEG, '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=gray:s=16x16', '-frames:v', '1', tiny])
    r = subprocess.run([exe, '-i', tiny, '-o', out, '-n', 'realesr-animevideov3', '-s', '2'], capture_output=True,
                       text=True, encoding='utf-8', errors='replace', cwd=os.path.dirname(exe), creationflags=NOWIN)
    gpus = {}
    for line in (r.stderr + r.stdout).splitlines():
        if line.startswith('[') and ' ' in line and line[1:line.index(' ')].isdigit() and ']' in line:
            gpus.setdefault(int(line[1:line.index(' ')]), line[line.index(' ') + 1:line.index(']')])
    for f in (tiny, out):
        if os.path.exists(f):
            os.remove(f)
    for want in ('nvidia', 'amd', 'radeon'):
        for i, name in gpus.items():
            if want in name.lower():
                return i, name
    return next(iter(gpus.items()), (0, 'default'))


def probe(src):
    j = json.loads(run([FFPROBE, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                        'stream=width,height,r_frame_rate:format=duration', '-of', 'json', src]).stdout)
    s = j['streams'][0]
    num, den = (s['r_frame_rate'].split('/') + ['1'])[:2]
    has_audio = bool(json.loads(run([FFPROBE, '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index',
                                     '-of', 'json', src]).stdout).get('streams'))
    return int(s['width']), int(s['height']), s['r_frame_rate'], float(num) / float(den), float(j['format']['duration']), has_audio


def encoder(height):
    """Up to 4K: H.264 at a moderate bitrate, which almost every player can play smoothly.
    8K: HEVC, because H.264 cannot go wider than 4096.
    Tries NVIDIA NVENC, then Apple VideoToolbox (macOS), then the CPU encoder."""
    hevc = height > 2160
    rate = {1440: '8M', 2160: '12M'}.get(height, '40M')
    peak = f'{int(rate[:-1]) * 2}M'
    tag = ['-tag:v', 'hvc1'] if hevc else ['-profile:v', 'high']
    tries = [('hevc_nvenc' if hevc else 'h264_nvenc', ['-preset', 'p5', '-rc', 'vbr', '-b:v', rate, '-maxrate', peak, '-bufsize', peak], 'NVIDIA NVENC')]
    if MAC:
        tries.append(('hevc_videotoolbox' if hevc else 'h264_videotoolbox', ['-b:v', rate, '-maxrate', peak], 'Apple VideoToolbox'))
    for name, opts, label in tries:
        try:
            run([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', 'color=s=256x256', '-frames:v', '1', '-c:v', name, '-f', 'null', '-'])
            return ['-c:v', name, *opts, *tag], f'{label} {"HEVC" if hevc else "H.264"}'
        except RuntimeError:
            pass
    cpu = 'libx265' if hevc else 'libx264'
    return ['-c:v', cpu, '-preset', 'medium', '-crf', '21', '-maxrate', peak, '-bufsize', peak,
            *(['-tag:v', 'hvc1'] if hevc else [])], f'CPU ({cpu}, slow)'


def fmt(sec):
    sec = int(sec)
    return f'{sec // 3600}h {sec // 60 % 60:02d}m' if sec >= 3600 else f'{sec // 60}m {sec % 60:02d}s'


def plain_log(text, frac=None):
    print(text, flush=True)


def upscale(src, to='4k', model='photo', out=None, log=plain_log, stop=lambda: False, check=False):
    """Upscale src to 2k/4k/8k. log(text, fraction 0..1 or None). stop() returning True cancels. Returns the output path."""
    ensure_ffmpeg(log)
    src = os.path.abspath(src)
    w, h, rate, fps, dur, has_audio = probe(src)
    H = TARGETS[to]
    if H <= h:
        raise RuntimeError(f'The video is already {h}p, which is not smaller than {to.upper()} ({H}p).')
    name = MODELS[model]
    scale = 4 if name == 'realesrgan-x4plus' else min(4, max(2, -(-H // h)))  # x4plus only works at 4x
    total = max(1, round(dur * fps))
    base = os.path.splitext(src)[0]
    out = out or f'{base}-{to}.mp4'
    work = f'{base}-{to}-work'
    enc, enc_name = encoder(H)
    log(f'{os.path.basename(src)}: {w}x{h}, {fps:.2f} fps, {fmt(dur)}, about {total} frames', None)
    log(f'Plan: Real-ESRGAN {name} x{scale}, resize to {H}p, encode with {enc_name}', None)
    if check:
        return out

    exe = tool(log)
    os.makedirs(work, exist_ok=True)
    gpu, gpu_name = pick_gpu(exe, work)
    log(f'Graphics card: {gpu_name}', None)
    step = CHUNK[H]
    secs = step / fps
    n_chunks = -(-total // step)  # by frame count, so the last frame gets its own chunk if needed
    parts, t0, done = [], time.time(), 0
    for k in range(n_chunks):
        if stop():
            raise Stopped()
        part = os.path.join(work, f'part{k:05d}.mp4')
        parts.append(part)
        if os.path.exists(part):  # finished in an earlier run
            continue
        fin, fout = os.path.join(work, 'in'), os.path.join(work, 'out')
        for d in (fin, fout):
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d)
        # -ss before -i is frame-accurate when re-encoding; fps= keeps a constant frame rate
        run([FFMPEG, '-v', 'error', '-ss', f'{k * secs:.6f}', '-t', f'{secs + 1 / fps:.6f}', '-i', src, '-map', '0:v:0',
             '-vf', f'fps={rate}', '-frames:v', str(step), os.path.join(fin, '%08d.png')])
        n = len(os.listdir(fin))
        if n == 0:
            parts.pop()
            break
        run([exe, '-i', fin, '-o', fout, '-n', name, '-s', str(scale), '-g', str(gpu), '-f', 'png'], cwd=os.path.dirname(exe))
        tmp = part + '.tmp.mp4'
        run([FFMPEG, '-v', 'error', '-y', '-framerate', rate, '-i', os.path.join(fout, '%08d.png'),
             '-vf', f'scale=-2:{H}:flags=lanczos,format=yuv420p', *enc, tmp])
        os.replace(tmp, part)
        done += n
        left = (time.time() - t0) / done * max(0, total - (k + 1) * step)
        log(f'Upscaling: {min(total, (k + 1) * step)} of {total} frames, about {fmt(left)} left', (k + 1) / n_chunks)

    log('Joining the pieces and adding the sound...', None)
    lst = os.path.join(work, 'list.txt')
    with open(lst, 'w', encoding='utf-8') as f:
        f.writelines(f"file '{p.replace(chr(92), '/')}'\n" for p in parts)
    cmd = [FFMPEG, '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst]
    if has_audio:
        cmd += ['-i', src, '-map', '0:v', '-map', '1:a', '-c:a', 'copy']
    cmd += ['-c:v', 'copy', '-movflags', '+faststart', out]  # no -shortest: audio is often a few ms shorter and would cut the last frame
    try:
        run(cmd)
    except RuntimeError:  # audio codec not allowed in MP4: convert it to AAC
        if not has_audio:
            raise
        cmd[cmd.index('-c:a') + 1] = 'aac'
        run(cmd)
    shutil.rmtree(work, ignore_errors=True)
    log(f'Done in {fmt(time.time() - t0)}: {out}', 1)
    return out


def main():
    ap = argparse.ArgumentParser(description='Upscale a video with Real-ESRGAN.')
    ap.add_argument('video')
    ap.add_argument('--to', choices=TARGETS, default='4k')
    ap.add_argument('--model', choices=MODELS, default='photo', help='photo = real camera video, anime = cartoons (faster)')
    ap.add_argument('--check', action='store_true', help='only show what would happen')
    a = ap.parse_args()
    if not os.path.exists(a.video):
        sys.exit('File not found: ' + a.video)
    upscale(a.video, a.to, a.model, check=a.check)


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as e:
        sys.exit(str(e))
    except KeyboardInterrupt:
        sys.exit('\nStopped. Run the same command again to continue where it stopped.')
