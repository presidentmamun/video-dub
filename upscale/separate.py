"""Voice / music split for the Video Dubbing page, on this computer's graphics card (used by ../server.py).

The same model (UVR MDX-Net Inst HQ 3) and the same steps as the page does in the browser, so the result matches:
STFT with n_fft 6144, the model, inverse STFT; 120-second parts with 1 second of overlap.
Runs with onnxruntime: DirectML on Windows (NVIDIA, AMD or Intel graphics), CoreML on macOS, CUDA or the CPU on Linux.
The first time it installs onnxruntime and numpy into upscale/pylib (about 60 MB) and downloads the model (67 MB).
"""
import os, subprocess, sys, urllib.request

import upscale as up

HERE = os.path.dirname(os.path.abspath(__file__))
PYLIB = os.path.join(HERE, 'pylib')
MODEL_URL = 'https://huggingface.co/masszhou/mdxnet/resolve/main/UVR-MDX-NET-Inst_HQ_3.onnx'
MODEL = os.path.join(HERE, 'models', 'UVR-MDX-NET-Inst_HQ_3.onnx')
ORT_PKG = 'onnxruntime-directml' if sys.platform == 'win32' else 'onnxruntime'
NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
NFFT, HOP, DF, DT = 6144, 1024, 3072, 256
CH = HOP * (DT - 1)
TRIM = NFFT // 2
GEN = CH - 2 * TRIM
PART, MARGIN, BG_SR, VOX_SR = 120, 1, 24000, 16000


def missing():
    """What still has to be set up the first time (shown on the page)."""
    need = []
    if not os.path.isdir(os.path.join(PYLIB, 'onnxruntime')):
        need.append('AI runtime (about 60 MB)')
    if not os.path.isfile(MODEL):
        need.append('voice/music model (67 MB)')
    return need


def runtime(log):
    if PYLIB not in sys.path:
        sys.path.insert(0, PYLIB)
    if not os.path.isdir(os.path.join(PYLIB, 'onnxruntime')):  # our own copy, with the graphics card build (not a CPU one on the system)
        log('Setting up the AI runtime (about 60 MB, one time)...', 0)
        r = subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--target', PYLIB, ORT_PKG, 'numpy'],
                           capture_output=True, text=True, creationflags=NOWIN)
        if r.returncode != 0:
            raise RuntimeError('Could not install the AI runtime:\n' + (r.stderr or r.stdout)[-600:])
        import importlib
        importlib.invalidate_caches()
    import numpy as np
    import onnxruntime as ort
    if not os.path.isfile(MODEL):
        os.makedirs(os.path.dirname(MODEL), exist_ok=True)
        log('Downloading the voice/music model (67 MB, one time)...', 0)
        urllib.request.urlretrieve(MODEL_URL, MODEL + '.part')
        os.replace(MODEL + '.part', MODEL)
    return np, ort


_sess = None


def session(ort):
    global _sess
    if _sess is None:
        have = ort.get_available_providers()
        if 'DmlExecutionProvider' in have:
            provs = [('DmlExecutionProvider', {'performance_preference': 'high_performance'}), 'CPUExecutionProvider']
        elif 'CUDAExecutionProvider' in have:
            provs = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        elif 'CoreMLExecutionProvider' in have:
            provs = ['CoreMLExecutionProvider', 'CPUExecutionProvider']
        else:
            provs = ['CPUExecutionProvider']
        _sess = ort.InferenceSession(MODEL, providers=provs)
    return _sess


def device_label(ort):
    p = session(ort).get_providers()[0]
    return {'DmlExecutionProvider': 'graphics card (DirectML)', 'CUDAExecutionProvider': 'NVIDIA graphics card (CUDA)',
            'CoreMLExecutionProvider': 'Apple chip (CoreML)'}.get(p, 'processor')


def separate(src, out_dir, log, stop):
    """Write music at 24 kHz (bg.f32) and voices at 16 kHz (vox.f32), mono float32, for the whole file."""
    up.ensure_ffmpeg(log)
    np, ort = runtime(log)
    s = session(ort)
    name, label = s.get_inputs()[0].name, device_label(ort)
    win = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(NFFT) / NFFT)).astype(np.float64)
    idx = np.arange(DT)[:, None] * HOP + np.arange(NFFT)[None, :]
    wsum = np.zeros(CH + NFFT)
    for f in range(DT):
        wsum[f * HOP:f * HOP + NFFT] += win * win
    wsum = wsum[NFFT // 2:NFFT // 2 + CH]

    def stft(x):  # (2, CH) → (4, DF, DT): left re/im, right re/im (centred, reflect padding)
        sp = np.fft.rfft(np.pad(x, ((0, 0), (NFFT // 2, NFFT // 2)), mode='reflect')[:, idx] * win, axis=-1)[..., :DF]
        return np.stack([sp[0].real.T, sp[0].imag.T, sp[1].real.T, sp[1].imag.T]).astype(np.float32)

    def istft(o, c):  # one channel back to CH samples
        sp = (o[2 * c] + 1j * o[2 * c + 1]).astype(np.complex128)
        fr = np.fft.irfft(np.vstack([sp, np.zeros((1, DT))]).T, n=NFFT) * win
        y = np.zeros(CH + NFFT)
        for f in range(DT):
            y[f * HOP:f * HOP + NFFT] += fr[f]
        y = y[NFFT // 2:NFFT // 2 + CH]
        return np.where(wsum > 1e-8, y / np.maximum(wsum, 1e-8), 0)

    def resample(a, sr_in, sr_out):  # linear, like the page
        n = int(len(a) * sr_out // sr_in)
        return np.interp(np.arange(n) * (sr_in / sr_out), np.arange(len(a)), a).astype(np.float32)

    _, _, _, _, dur, has_audio = up.probe(src)
    if not has_audio:
        raise RuntimeError('This file has no audio.')
    parts = int(np.ceil(dur / PART))
    bg, vox = np.zeros(int(np.ceil(dur * BG_SR)), np.float32), np.zeros(int(np.ceil(dur * VOX_SR)), np.float32)
    total = sum(int(np.ceil((min(dur, k * PART + PART + MARGIN) - max(0, k * PART - MARGIN)) * 44100 / GEN)) + 1 for k in range(parts))
    done = 0
    for k in range(parts):
        t = k * PART
        ss = max(0, t - MARGIN)
        ln = min(dur, t + PART + MARGIN) - ss
        raw = subprocess.run([up.FFMPEG, '-v', 'error', '-ss', f'{ss:.3f}', '-t', f'{ln:.3f}', '-i', src, '-vn', '-ac', '2', '-ar', '44100',
                              '-f', 'f32le', '-'], capture_output=True, creationflags=NOWIN).stdout
        st = np.frombuffer(raw, np.float32).reshape(-1, 2).T.astype(np.float64)
        n = st.shape[1]
        pad = GEN - n % GEN
        P = np.zeros((2, TRIM + n + pad + TRIM))
        P[:, TRIM:TRIM + n] = st
        out = np.zeros((2, n + pad))
        for i in range(0, n + pad, GEN):
            if stop():
                raise up.Stopped()
            o = s.run(None, {name: stft(P[:, i:i + CH])[None]})[0][0]
            for c in range(2):
                out[c, i:i + GEN] = istft(o, c)[TRIM:CH - TRIM]
            done += 1
            log(f'Separating voice and music on the {label}: {min(99, done * 100 // max(1, total))}%', min(1, done / max(1, total)))
        frm, cnt = round((t - ss) * 44100), round(min(PART, dur - t) * 44100)
        seg = slice(frm, frm + cnt)
        mix = 0.5 * (st[0, seg] + st[1, seg])
        music = 0.5 * (out[0, seg] + out[1, seg])
        voice = mix - music[:len(mix)]
        for arr, sig, sr in ((bg, music, BG_SR), (vox, voice, VOX_SR)):
            r = resample(sig, 44100, sr)
            at = round(t * sr)
            m = min(len(r), len(arr) - at)
            if m > 0:
                arr[at:at + m] += r[:m]
    os.makedirs(out_dir, exist_ok=True)
    bg.tofile(os.path.join(out_dir, 'bg.f32'))
    vox.tofile(os.path.join(out_dir, 'vox.f32'))
    log(f'Done on the {label}', 1)
    return out_dir
