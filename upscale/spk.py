"""Speaker voices for the Video Dubbing page on this computer (used by ../server.py, one process per job).

The page's model, WavLM base plus SV (Xenova/wavlm-base-plus-sv; full precision, as the 8-bit one crashes DirectML), on the graphics card through
onnxruntime DirectML (NVIDIA, AMD or Intel; the strongest one) or the processor. One voice print per line; the page groups them.

  python spk.py JOB_FOLDER      reads args.json {lengths} + audio.f32 (the clips one after another), writes result.json
"""
import json, os, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # run with python -I, which leaves this folder out
import asr  # noqa: E402
import separate as sp  # noqa: E402

URL = 'https://huggingface.co/Xenova/wavlm-base-plus-sv/resolve/main/onnx/model.onnx'
MODEL = os.path.join(HERE, 'models', 'wavlm-base-plus-sv-fp32.onnx')


def missing():
    return sp.missing()[:1] + ([] if os.path.isfile(MODEL) else ['speaker model (400 MB)'])


def run(folder, log, stop):
    sp.runtime(log)  # onnxruntime (graphics card build) in upscale/pylib
    return asr.run_script(os.path.abspath(__file__), folder, log, stop, 'Speaker recognition')


def session(ort, path):
    """The strongest graphics card through DirectML (or CUDA, CoreML), else the processor."""
    have = ort.get_available_providers()
    tries = ([[('DmlExecutionProvider', {'performance_preference': 'high_performance'}), 'CPUExecutionProvider']] if 'DmlExecutionProvider' in have else []) \
        + ([['CUDAExecutionProvider', 'CPUExecutionProvider']] if 'CUDAExecutionProvider' in have else []) \
        + ([['CoreMLExecutionProvider', 'CPUExecutionProvider']] if 'CoreMLExecutionProvider' in have else []) + [['CPUExecutionProvider']]
    for provs in tries:
        try:
            s = ort.InferenceSession(path, providers=provs)
            where = {'DmlExecutionProvider': 'graphics card (DirectML)', 'CUDAExecutionProvider': 'NVIDIA graphics card',
                     'CoreMLExecutionProvider': 'Apple chip'}.get(s.get_providers()[0], 'processor')
            return s, where
        except Exception:
            continue
    raise RuntimeError('Could not load the model.')


def job(folder):
    sys.path.insert(0, sp.PYLIB)
    import numpy as np
    import onnxruntime as ort
    a = json.load(open(os.path.join(folder, 'args.json'), encoding='utf-8'))
    if not os.path.isfile(MODEL):
        asr.say('Downloading the speaker model (100 MB, one time)...', 0)
        os.makedirs(os.path.dirname(MODEL), exist_ok=True)
        urllib.request.urlretrieve(URL, MODEL + '.part')
        os.replace(MODEL + '.part', MODEL)
    s, where = session(ort, MODEL)
    names = {i.name for i in s.get_inputs()}
    audio = np.fromfile(os.path.join(folder, 'audio.f32'), np.float32)
    out, at, n = [], 0, len(a['lengths'])
    for i, ln in enumerate(a['lengths']):
        if not ln:
            out.append(None)
        else:
            x = audio[at:at + ln][None]
            at += ln
            feed = {'input_values': x}
            if 'attention_mask' in names:
                feed['attention_mask'] = np.ones(x.shape, np.int64)
            e = s.run(None, feed)
            emb = dict(zip([o.name for o in s.get_outputs()], e)).get('embeddings', e[-1])
            out.append(emb.reshape(-1).astype(float).tolist())
        asr.say(f'Finding the speakers on the {where}: {i + 1} of {n}', (i + 1) / max(1, n))
    json.dump({'embs': out, 'device': where}, open(os.path.join(folder, 'result.json'), 'w'))


if __name__ == '__main__':
    job(sys.argv[1])
