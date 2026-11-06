"""Speech recognition for the Video Dubbing page on this computer (used by ../server.py, one process per job).

faster-whisper (CTranslate2) with the same Whisper models as the page (base / small), plus large-v3-turbo (NVIDIA only, about 1.6 GB): on an NVIDIA graphics card through
CUDA, otherwise on every processor core. It follows the page's own steps: speech windows from the page, language found by
voting (or per line with "several languages"), made-up lines over music dropped, Bengali written in Devanagari fixed.
The first time it installs faster-whisper into upscale/pylib-asr (about 330 MB) and downloads the model.

  python asr.py JOB_FOLDER      reads args.json + audio.f32 (16 kHz mono float32), writes result.json, prints progress
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PYLIB = os.path.join(HERE, 'pylib-asr')
MODELS = os.path.join(HERE, 'models', 'whisper')
NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
SIZES = {'onnx-community/whisper-base': 'base', 'onnx-community/whisper-small': 'small', 'large-v3-turbo': 'large-v3-turbo'}
SR = 16000


CUDA_LIB = os.path.join(HERE, 'pylib-cuda')  # NVIDIA's cuBLAS for CTranslate2, our own copy (no CUDA install needed)


def has_nvidia():
    try:
        return subprocess.run(['nvidia-smi', '-L'], capture_output=True, timeout=10, creationflags=NOWIN).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def missing():
    need = [] if os.path.isdir(os.path.join(PYLIB, 'faster_whisper')) else ['speech recognition (about 330 MB)']
    if has_nvidia() and not os.path.isdir(os.path.join(CUDA_LIB, 'nvidia', 'cublas')):
        need.append('NVIDIA libraries (about 550 MB)')
    return need


def pip(target, pkgs, what, log):
    log(f'Setting up {what} (one time)...', 0)
    r = subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--target', target, *pkgs],
                       capture_output=True, text=True, creationflags=NOWIN)
    if r.returncode != 0:
        raise RuntimeError(f'Could not install {what}:\n' + (r.stderr or r.stdout)[-600:])


def setup(log):
    if not os.path.isdir(os.path.join(PYLIB, 'faster_whisper')):
        pip(PYLIB, ['faster-whisper'], 'speech recognition (about 330 MB)', log)
    if has_nvidia() and not os.path.isdir(os.path.join(CUDA_LIB, 'nvidia', 'cublas')):
        try:
            pip(CUDA_LIB, ['nvidia-cublas-cu12'], 'the NVIDIA libraries (about 550 MB)', log)
        except RuntimeError:
            pass  # then the processor is used


def cuda_paths():
    """Let CTranslate2 find our cuBLAS (it loads it by name, from PATH)."""
    import glob
    dirs = glob.glob(os.path.join(CUDA_LIB, 'nvidia', '*', 'bin'))
    for d in dirs:
        try:
            os.add_dll_directory(d)
        except (OSError, AttributeError):
            pass
    os.environ['PATH'] = os.pathsep.join(dirs + [os.environ.get('PATH', '')])


def run(folder, log, stop):
    """Called by server.py: runs this file in its own process (its libraries never mix with the helper's) and follows it."""
    setup(log)
    return run_script(os.path.abspath(__file__), folder, log, stop, 'Speech recognition')


def run_script(script, folder, log, stop, what):
    """Run an AI step (script JOB_FOLDER) in its own process; its JSON lines are the progress, result.json the answer."""
    p = subprocess.Popen([sys.executable, '-I', script, folder], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding='utf-8', errors='replace', creationflags=NOWIN)
    err = []
    import threading
    t = threading.Thread(target=lambda: err.extend(p.stderr.read().splitlines()[-15:]), daemon=True)
    t.start()
    for line in p.stdout:
        if stop():
            p.kill()
            import upscale as up
            raise up.Stopped()
        try:
            m = json.loads(line)
            log(m['text'], m.get('frac'))
        except ValueError:
            pass
    code = p.wait()
    t.join(5)
    if code != 0 or not os.path.isfile(os.path.join(folder, 'result.json')):
        raise RuntimeError(what + ' failed:\n' + '\n'.join(err)[-800:])
    return folder


# ---- the job itself (in its own process) ----
def say(text, frac=None):
    print(json.dumps({'text': text, 'frac': frac}), flush=True)


def clean(t):  # what Whisper makes up over music and noise: sound tags
    return re.sub(r'\s+', ' ', re.sub(r'\[[^\]]*\]|\([^)]*\)|♪+', ' ', t)).strip()


def junk(t):  # no word of two letters, a letter repeated, or a short phrase repeated
    return not re.search(r'[^\W\d_]{2}', t) or re.search(r'(.)\1{5,}', t) or re.search(r'(\S.{0,15}?)(\s*\1){3,}', t)


def to_bengali(t):  # Whisper sometimes writes Bengali in Devanagari letters; the two alphabets sit 0x80 apart
    dev = len(re.findall('[ऀ-ॿ]', t))
    ben = len(re.findall('[ঀ-৿]', t))
    if dev <= ben:
        return t
    return ''.join(chr(ord(c) + 0x80) if 'ऀ' <= c <= 'ॿ' and c not in '।॥' else c for c in t)


def job(folder):
    sys.path.insert(0, PYLIB)
    cuda_paths()
    import numpy as np
    from faster_whisper import WhisperModel
    a = json.load(open(os.path.join(folder, 'args.json'), encoding='utf-8'))
    audio = np.fromfile(os.path.join(folder, 'audio.f32'), np.float32)
    size = SIZES.get(a.get('model'), 'base')
    say(f'Loading the speech model ({size})...', 0)
    model, where = None, 'processor'
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            model, where = WhisperModel(size, device='cuda', compute_type='float16', download_root=MODELS), 'NVIDIA graphics card'
            list(model.transcribe(np.zeros(SR, np.float32), language='en', beam_size=1)[0])  # a missing CUDA library shows up only here
    except Exception:
        model, where = None, 'processor'
    if model is None:
        if size == 'large-v3-turbo':  # far too slow on a processor
            size = 'small'
            say('No NVIDIA graphics card: using the accurate model (small) instead...', 0)
        model = WhisperModel(size, device='cpu', compute_type='int8', cpu_threads=os.cpu_count() or 4, download_root=MODELS)
    langs = a.get('langs') or {}  # page code -> Whisper language name
    name2code = {v: k for k, v in langs.items()}
    windows, multi, task = a['windows'], a.get('multi'), a.get('task') or 'transcribe'
    language = name2code.get(a.get('language')) if a.get('language') else None
    only = set(a.get('transcribeOnly') or [])
    clip = lambda w: audio[round(w[0] * SR):round(w[1] * SR)]

    def detect(w):  # [(code, probability)] best first, only the page's languages
        _, _, probs = model.detect_language(audio=clip(w))
        sc = [(c, p) for c, p in probs if c in langs]
        z = sum(p for _, p in sc) or 1
        return sorted(((c, p / z) for c, p in sc), key=lambda x: -x[1])

    found = None
    if not language and not multi:  # one language for the whole video: vote over the longest pieces
        votes = {}
        pick = sorted(windows, key=lambda w: -(w[1] - w[0]))[:5]
        for w in pick:
            for c, p in detect(w):
                votes[c] = votes.get(c, 0) + p / len(pick)
        code, prob = max(votes.items(), key=lambda x: x[1]) if votes else ('en', 0)
        found = {'code': code, 'prob': prob}
        language = code
    res, seen, prev = [], {}, None
    for i, (s, e) in enumerate(windows):
        lang, code = language, None
        if multi:  # each piece in its own language; short pieces keep the last one unless sure
            best = (detect([s, e]) or [('en', 0)])[0]
            code = best[0] if e - s >= 1.5 or not prev or best[1] > 0.6 else prev
            prev, lang = code, code
            seen[code] = seen.get(code, 0) + 1
        t = 'transcribe' if code and code in only else task
        cap = min(440, int((e - s) * 14) + 16)

        def go(tk):
            segs, _ = model.transcribe(clip([s, e]), language=lang, task=tk, beam_size=1, best_of=1, temperature=0.0,
                                       condition_on_previous_text=False, max_new_tokens=cap, vad_filter=False)
            return list(segs)
        out = go(t)
        if t != task and junk(clean(' '.join(x.text for x in out))):  # written down badly: let Whisper translate it instead
            t = task
            out = go(t)
        for x in out:
            cs, ce = s + x.start, min(e, s + x.end)
            text = x.text.strip()
            if code == 'bn' or lang == 'bn':
                text = to_bengali(text)
            res.append({'s': cs, 'e': max(ce, cs + 0.3), 't': text, **({'lang': code, 'task': t} if code else {})})
        say(f'Recognizing speech on the {where}: {i + 1} of {len(windows)}', (i + 1) / len(windows))
    if multi:
        found = {'multi': seen}
    kept = []
    for c in res:  # drop made-up pieces, and a line repeated many times (a loop, not speech)
        c['t'] = clean(c['t'])
        if not c['t'] or junk(c['t']) or c['e'] - c['s'] > 30:
            continue
        if len(kept) >= 2 and kept[-1]['t'] == c['t'] and kept[-2]['t'] == c['t']:  # three in a row: a loop, not speech
            continue
        kept.append(c)
    json.dump({'chunks': kept, 'found': found, 'dropped': len(res) - len(kept), 'device': where},
              open(os.path.join(folder, 'result.json'), 'w', encoding='utf-8'), ensure_ascii=False)


if __name__ == '__main__':
    job(sys.argv[1])
