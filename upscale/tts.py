"""New voices (MMS text to speech) for the Video Dubbing page on this computer (used by ../server.py, one process per job).

The page's MMS / VITS models (Xenova/mms-tts-*, PRAMSSS/mms-tts-bengali-webgpu), full precision, on the graphics card through
onnxruntime DirectML (NVIDIA, AMD or Intel; the strongest one) or the processor. The text is cleaned like the page does:
Bengali digits to 0-9, characters the model does not know become spaces; then the VITS tokenizer (a blank between letters).

  python tts.py JOB_FOLDER      reads args.json {model, texts}, writes audio.f32 (all lines one after another) + result.json
"""
import json, os, re, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # run with python -I, which leaves this folder out
import asr  # noqa: E402
import separate as sp  # noqa: E402
import spk  # noqa: E402

ROOT = os.path.join(HERE, 'models', 'mms')
FILES = ['onnx/model.onnx', 'vocab.json', 'tokenizer_config.json', 'config.json']
REPO_OK = re.compile(r'^[A-Za-z0-9_.-]{1,40}/[A-Za-z0-9_.-]{1,80}$')


def missing():
    return sp.missing()[:1]


def run(folder, log, stop):
    sp.runtime(log)
    return asr.run_script(os.path.abspath(__file__), folder, log, stop, 'Voice making')


def fetch(repo):
    if not REPO_OK.match(repo) or not re.search(r'mms-tts', repo):
        raise RuntimeError('Unknown voice model.')
    d = os.path.join(ROOT, repo.replace('/', '__'))
    for f in FILES:
        p = os.path.join(d, f)
        if not os.path.isfile(p):
            asr.say('Downloading the voice model (one time)...', 0)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            urllib.request.urlretrieve(f'https://huggingface.co/{repo}/resolve/main/{f}', p + '.part')
            os.replace(p + '.part', p)
    return d


def job(folder):
    sys.path.insert(0, sp.PYLIB)
    import numpy as np
    import onnxruntime as ort
    a = json.load(open(os.path.join(folder, 'args.json'), encoding='utf-8'))
    d = fetch(a['model'])
    vocab = json.load(open(os.path.join(d, 'vocab.json'), encoding='utf-8'))
    tc = json.load(open(os.path.join(d, 'tokenizer_config.json'), encoding='utf-8'))
    sr = json.load(open(os.path.join(d, 'config.json'), encoding='utf-8')).get('sampling_rate', 16000)
    pad = vocab.get(tc.get('pad_token'), 0)
    s, where = spk.session(ort, os.path.join(d, 'onnx', 'model.onnx'))
    names = {i.name for i in s.get_inputs()}
    has = lambda c: c in vocab

    def clean(t):  # the page's cleaning: Bengali digits → 0-9, unknown characters → space
        t = re.sub('[০-৯]', lambda m: str('০১২৩৪৫৬৭৮৯'.index(m.group(0))), t)
        t = ''.join(c if has(c) else c.lower() if has(c.lower()) else ' ' for c in t)
        return re.sub(r'\s+', ' ', t).strip()

    out, lengths, n = [], [], len(a['texts'])
    for i, text in enumerate(a['texts']):
        t = clean(text)
        if tc.get('normalize') and not tc.get('is_uroman'):
            t = ''.join(c if has(c) else c.lower() for c in t)
        ids = [vocab[c] for c in t if c in vocab]
        if tc.get('add_blank', True):
            ids = [pad] + [x for c in ids for x in (c, pad)]
        if not t or not ids:
            lengths.append(0)
        else:
            x = np.array([ids], np.int64)
            feed = {'input_ids': x}
            if 'attention_mask' in names:
                feed['attention_mask'] = np.ones_like(x)
            w = s.run(None, feed)[0].reshape(-1).astype(np.float32)
            out.append(w)
            lengths.append(len(w))
        asr.say(f'Making voices on the {where}: {i + 1} of {n}', (i + 1) / max(1, n))
    (np.concatenate(out) if out else np.zeros(0, np.float32)).tofile(os.path.join(folder, 'audio.f32'))
    json.dump({'lengths': lengths, 'sr': sr, 'device': where}, open(os.path.join(folder, 'result.json'), 'w'))


if __name__ == '__main__':
    job(sys.argv[1])
