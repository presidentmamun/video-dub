"""English voices (Kokoro 82M) for the Video Dubbing page on this computer (used by ../server.py, one process per job).

kokoro-onnx with the Kokoro v1.0 model and voices (the page's voices: af_heart, bm_george ...; "a" = American, "b" = British
English). It tries the graphics card through DirectML first; one Kokoro layer (ConvTranspose) does not run there today, so on
most computers it runs on every processor core, still much faster than the browser. The full-precision model is used: on the
processor it is about 3.5 times faster than the 8-bit one.
The first time it installs kokoro-onnx (with espeak-ng) into upscale/pylib-tts (about 180 MB) and downloads the model (350 MB).

  python kokoro.py JOB_FOLDER      reads args.json {voices, texts}, writes audio.f32 + result.json {lengths, sr, device}
"""
import json, os, subprocess, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # run with python -I, which leaves this folder out
import asr  # noqa: E402
import separate as sp  # noqa: E402

PYLIB = os.path.join(HERE, 'pylib-tts')
DIR = os.path.join(HERE, 'models', 'kokoro')
REL = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/'
FILES = ['kokoro-v1.0.onnx', 'voices-v1.0.bin']
NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def missing():
    need = [] if os.path.isdir(os.path.join(PYLIB, 'kokoro_onnx')) else ['English voice tools (about 180 MB)']
    return need + ([] if all(os.path.isfile(os.path.join(DIR, f)) for f in FILES) else ['English voice model (350 MB)'])


def run(folder, log, stop):
    sp.runtime(log)  # onnxruntime (graphics card build) in upscale/pylib
    if not os.path.isdir(os.path.join(PYLIB, 'kokoro_onnx')):
        log('Setting up the English voices (about 180 MB, one time)...', 0)
        r = subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--target', PYLIB, 'kokoro-onnx'],
                           capture_output=True, text=True, creationflags=NOWIN)
        if r.returncode != 0:
            raise RuntimeError('Could not install the English voices:\n' + (r.stderr or r.stdout)[-600:])
    return asr.run_script(os.path.abspath(__file__), folder, log, stop, 'English voices')


def job(folder):
    sys.path.insert(0, sp.PYLIB)  # onnxruntime with DirectML first, kokoro-onnx and espeak-ng next
    sys.path.insert(1, PYLIB)
    import numpy as np
    import onnxruntime as ort
    from kokoro_onnx import Kokoro
    a = json.load(open(os.path.join(folder, 'args.json'), encoding='utf-8'))
    for f in FILES:
        p = os.path.join(DIR, f)
        if not os.path.isfile(p):
            asr.say('Downloading the English voice model (one time)...', 0)
            os.makedirs(DIR, exist_ok=True)
            urllib.request.urlretrieve(REL + f, p + '.part')
            os.replace(p + '.part', p)
    model, voices = os.path.join(DIR, FILES[0]), os.path.join(DIR, FILES[1])
    k, where = None, 'processor'
    if 'DmlExecutionProvider' in ort.get_available_providers():
        try:  # a short test line: the graphics card is used only if Kokoro really runs there
            k = Kokoro.from_session(ort.InferenceSession(model, providers=[('DmlExecutionProvider', {'performance_preference': 'high_performance'})]), voices)
            k.create('Test.', voice='af_heart', lang='en-us')
            where = 'graphics card (DirectML)'
        except Exception:
            k = None
    if k is None:
        o = ort.SessionOptions()
        o.intra_op_num_threads = os.cpu_count() or 4
        k = Kokoro.from_session(ort.InferenceSession(model, sess_options=o, providers=['CPUExecutionProvider']), voices)
    out, lengths, sr, n = [], [], 24000, len(a['texts'])
    for i, (text, voice) in enumerate(zip(a['texts'], a['voices'])):
        if not text.strip():
            lengths.append(0)
        else:
            w, sr = k.create(text, voice=voice, lang='en-gb' if voice.startswith('b') else 'en-us')
            w = np.asarray(w, np.float32).reshape(-1)
            out.append(w)
            lengths.append(len(w))
        asr.say(f'Making voices on the {where}: {i + 1} of {n}', (i + 1) / max(1, n))
    (np.concatenate(out) if out else np.zeros(0, np.float32)).tofile(os.path.join(folder, 'audio.f32'))
    json.dump({'lengths': lengths, 'sr': sr, 'device': where}, open(os.path.join(folder, 'result.json'), 'w'))


if __name__ == '__main__':
    job(sys.argv[1])
