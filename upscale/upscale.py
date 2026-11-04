"""AI video upscaler: Real-ESRGAN on your graphics card, then NVENC encoding.

  upscale.cmd                        drag a video onto it, it asks for the size
  python upscale.py VIDEO --to 4k    2k | 4k | 8k   [--model photo|anime] [--check]

Needs ffmpeg + ffprobe (C:\\ffmpeg\\bin or on PATH). The first run downloads
realesrgan-ncnn-vulkan (45 MB, github.com/xinntao/Real-ESRGAN) into this folder.
The video is done in small chunks, so the disk only ever holds a few hundred frames,
and an interrupted run continues where it stopped.
"""
import argparse, json, os, shutil, subprocess, sys, time, urllib.request, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_URL = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip'
TOOL_DIR = os.path.join(HERE, 'realesrgan')
TARGETS = {'2k': 1440, '4k': 2160, '8k': 4320}
MODELS = {'photo': 'realesrgan-x4plus', 'anime': 'realesr-animevideov3'}
CHUNK = {1440: 300, 2160: 150, 4320: 50}  # frames per chunk: keeps temporary PNGs to a few GB


def find(name):
    for p in (os.path.join(r'C:\ffmpeg\bin', name + '.exe'), shutil.which(name)):
        if p and os.path.exists(p):
            return p
    sys.exit(f'{name} was not found. Install ffmpeg into C:\\ffmpeg\\bin or add it to PATH.')


FFMPEG, FFPROBE = find('ffmpeg'), find('ffprobe')


def run(cmd, quiet=True):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        raise RuntimeError(f'{os.path.basename(cmd[0])} failed:\n' + (r.stderr or r.stdout)[-1500:])
    return r


def tool():
    def exe():
        for root, _, files in os.walk(TOOL_DIR):
            if 'realesrgan-ncnn-vulkan.exe' in files:
                return os.path.join(root, 'realesrgan-ncnn-vulkan.exe')
    if exe():
        return exe()
    print('Downloading Real-ESRGAN (45 MB, one time only)...')
    z = os.path.join(HERE, 'realesrgan.zip')
    urllib.request.urlretrieve(TOOL_URL, z)
    with zipfile.ZipFile(z) as f:
        f.extractall(TOOL_DIR)
    os.remove(z)
    if not exe():
        sys.exit('The Real-ESRGAN download did not contain realesrgan-ncnn-vulkan.exe.')
    return exe()


def pick_gpu(exe, work):
    """Real-ESRGAN lists the graphics cards it sees; prefer NVIDIA/AMD over the built-in Intel chip."""
    tiny, out = os.path.join(work, 'gpu-in.png'), os.path.join(work, 'gpu-out.png')
    run([FFMPEG, '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=gray:s=16x16', '-frames:v', '1', tiny])
    r = subprocess.run([exe, '-i', tiny, '-o', out, '-n', 'realesr-animevideov3', '-s', '2'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=os.path.dirname(exe))
    gpus = []
    for line in (r.stderr + r.stdout).splitlines():
        if line.startswith('[') and ' ' in line and line[1:line.index(' ')].isdigit():
            gpus.append((int(line[1:line.index(' ')]), line[line.index(' ') + 1:line.index(']')]))
    for f in (tiny, out):
        if os.path.exists(f):
            os.remove(f)
    gpus = list(dict(gpus).items())
    for want in ('NVIDIA', 'AMD', 'Radeon'):
        for i, name in gpus:
            if want.lower() in name.lower():
                return i, name
    return (gpus[0] if gpus else (0, 'default'))


def probe(src):
    r = run([FFPROBE, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
             'stream=width,height,r_frame_rate:format=duration', '-of', 'json', src])
    j = json.loads(r.stdout)
    s = j['streams'][0]
    num, den = (s['r_frame_rate'].split('/') + ['1'])[:2]
    has_audio = bool(json.loads(run([FFPROBE, '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index',
                                     '-of', 'json', src]).stdout).get('streams'))
    return int(s['width']), int(s['height']), s['r_frame_rate'], float(num) / float(den), float(j['format']['duration']), has_audio


def encoder(height):
    """hevc_nvenc handles up to 8K on RTX cards; fall back to the CPU encoder when NVENC is missing."""
    try:
        run([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', f'color=s=256x{256}', '-frames:v', '1', '-c:v', 'hevc_nvenc', '-f', 'null', '-'])
        return ['-c:v', 'hevc_nvenc', '-preset', 'p5', '-rc', 'vbr', '-cq', '20', '-b:v', '0', '-tag:v', 'hvc1'], 'NVIDIA NVENC'
    except RuntimeError:
        return ['-c:v', 'libx265', '-preset', 'medium', '-crf', '20', '-tag:v', 'hvc1'], 'CPU (libx265, slow)'


def fmt(sec):
    sec = int(sec)
    return f'{sec // 3600}h {sec // 60 % 60:02d}m' if sec >= 3600 else f'{sec // 60}m {sec % 60:02d}s'


def main():
    ap = argparse.ArgumentParser(description='Upscale a video with Real-ESRGAN.')
    ap.add_argument('video')
    ap.add_argument('--to', choices=TARGETS, default='4k')
    ap.add_argument('--model', choices=MODELS, default='photo', help='photo = real camera video, anime = cartoons (faster)')
    ap.add_argument('--check', action='store_true', help='only show what would happen')
    a = ap.parse_args()

    src = os.path.abspath(a.video)
    if not os.path.exists(src):
        sys.exit('File not found: ' + src)
    w, h, rate, fps, dur, has_audio = probe(src)
    H = TARGETS[a.to]
    if H <= h:
        sys.exit(f'The video is already {h}p, which is not smaller than {a.to.upper()} ({H}p).')
    model = MODELS[a.model]
    scale = 4 if model == 'realesrgan-x4plus' else min(4, max(2, -(-H // h)))  # x4plus only works at 4x
    total = max(1, round(dur * fps))
    base = os.path.splitext(src)[0]
    out = f'{base}-{a.to}.mp4'
    work = f'{base}-{a.to}-work'
    enc, enc_name = encoder(H)
    print(f'{os.path.basename(src)}: {w}x{h}, {fps:.2f} fps, {fmt(dur)}, about {total} frames')
    print(f'Plan: Real-ESRGAN {model} x{scale}, then resize to {H}p, encode with {enc_name}')
    print(f'Output: {out}')
    if a.check:
        return

    exe = tool()
    os.makedirs(work, exist_ok=True)
    gpu, gpu_name = pick_gpu(exe, work)
    print(f'Graphics card: {gpu_name}')
    step = CHUNK[H]
    secs = step / fps
    n_chunks = int(-(-dur // secs))
    parts, t0, done_frames = [], time.time(), 0
    for k in range(n_chunks):
        part = os.path.join(work, f'part{k:05d}.mp4')
        parts.append(part)
        if os.path.exists(part):  # finished in an earlier run
            continue
        fin, fout = os.path.join(work, 'in'), os.path.join(work, 'out')
        for d in (fin, fout):
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d)
        # -ss before -i is frame-accurate when re-encoding; fps= keeps a constant frame rate
        run([FFMPEG, '-v', 'error', '-ss', f'{k * secs:.6f}', '-t', f'{secs:.6f}', '-i', src, '-map', '0:v:0',
             '-vf', f'fps={rate}', '-frames:v', str(step), os.path.join(fin, '%08d.png')])
        n = len(os.listdir(fin))
        if n == 0:
            parts.pop()
            break
        run([exe, '-i', fin, '-o', fout, '-n', model, '-s', str(scale), '-g', str(gpu), '-f', 'png'])
        tmp = part + '.tmp.mp4'
        run([FFMPEG, '-v', 'error', '-y', '-framerate', rate, '-i', os.path.join(fout, '%08d.png'),
             '-vf', f'scale=-2:{H}:flags=lanczos,format=yuv420p', *enc, tmp])
        os.replace(tmp, part)
        done_frames += n
        el = time.time() - t0
        left = el / done_frames * max(0, total - (k + 1) * step)
        print(f'  chunk {k + 1}/{n_chunks} done · {min(total, (k + 1) * step)}/{total} frames · about {fmt(left)} left', flush=True)

    print('Joining chunks and adding the sound...')
    lst = os.path.join(work, 'list.txt')
    with open(lst, 'w', encoding='utf-8') as f:
        f.writelines(f"file '{p.replace(chr(92), '/')}'\n" for p in parts)
    cmd = [FFMPEG, '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst]
    if has_audio:
        cmd += ['-i', src, '-map', '0:v', '-map', '1:a', '-c:a', 'copy']
    cmd += ['-c:v', 'copy', '-shortest', out]
    try:
        run(cmd)
    except RuntimeError:  # audio codec not allowed in MP4: convert it to AAC
        if not has_audio:
            raise
        cmd[cmd.index('-c:a') + 1] = 'aac'
        run(cmd)
    shutil.rmtree(work, ignore_errors=True)
    print(f'Done in {fmt(time.time() - t0)}: {out}')


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as e:
        sys.exit(str(e))
    except KeyboardInterrupt:
        sys.exit('\nStopped. Run the same command again to continue where it stopped.')
