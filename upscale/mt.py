"""Translation for the Video Dubbing page on this computer (used by ../server.py, one process per job).

The page's model, NLLB-200 distilled 600M, in CTranslate2 form (JustFrederik/nllb-200-distilled-600M-ct2-int8, the same
weights; licence CC-BY-NC 4.0 like the original): on an NVIDIA graphics card through CUDA, otherwise on every processor
core. Like the page it translates sentence by sentence (NLLB sometimes drops a sentence when given several), greedy,
up to 300 tokens each; sentences are sent in batches, which is what makes it fast.
The first time it adds sentencepiece to upscale/pylib-asr and downloads the model (about 620 MB).

  python mt.py JOB_FOLDER      reads args.json {texts, src (code or list of codes), tgt}, writes result.json
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # run with python -I, which leaves this folder out
import asr  # noqa: E402
REPO = 'JustFrederik/nllb-200-distilled-600M-ct2-int8'
MODEL = os.path.join(HERE, 'models', 'nllb-600m-ct2')
NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def missing():
    need = asr.missing()
    if not os.path.isdir(os.path.join(asr.PYLIB, 'sentencepiece')):
        need.append('translation tools (a few MB)')
    if not os.path.isfile(os.path.join(MODEL, 'model.bin')):
        need.append('translation model (about 620 MB)')
    return need


def setup(log):
    asr.setup(log)
    if not os.path.isdir(os.path.join(asr.PYLIB, 'sentencepiece')):
        log('Setting up translation (one time)...', 0)
        r = subprocess.run([sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check', '--target', asr.PYLIB, '--no-deps', 'sentencepiece'],
                           capture_output=True, text=True, creationflags=NOWIN)
        if r.returncode != 0:
            raise RuntimeError('Could not install translation:\n' + (r.stderr or r.stdout)[-600:])


def run(folder, log, stop):
    setup(log)
    return asr.run_script(os.path.abspath(__file__), folder, log, stop, 'Translation')


def job(folder):
    sys.path.insert(0, asr.PYLIB)
    asr.cuda_paths()
    import ctranslate2, sentencepiece
    a = json.load(open(os.path.join(folder, 'args.json'), encoding='utf-8'))
    if not os.path.isfile(os.path.join(MODEL, 'model.bin')):
        asr.say('Downloading the translation model (about 620 MB, one time)...', 0)
        from huggingface_hub import snapshot_download
        snapshot_download(REPO, local_dir=MODEL, allow_patterns=['model.bin', 'config.json', 'shared_vocabulary.txt', 'sentencepiece.bpe.model'])
    asr.say('Loading the translation model...', 0)
    where = 'processor'
    tr = None
    if ctranslate2.get_cuda_device_count() > 0:
        try:
            tr, where = ctranslate2.Translator(MODEL, device='cuda', compute_type='int8_float16'), 'NVIDIA graphics card'
            tr.translate_batch([['eng_Latn', '▁Hi', '</s>']], target_prefix=[['ben_Beng']], max_decoding_length=4)  # a missing CUDA library shows up only here
        except Exception:
            tr, where = None, 'processor'
    if tr is None:
        tr = ctranslate2.Translator(MODEL, device='cpu', compute_type='int8', intra_threads=os.cpu_count() or 4)
    sp = sentencepiece.SentencePieceProcessor(model_file=os.path.join(MODEL, 'sentencepiece.bpe.model'))
    texts, src, tgt = a['texts'], a['src'], a['tgt']
    out = [None] * len(texts)
    jobs = []  # (line, sentence) still to translate, grouped by source language
    for i, t in enumerate(texts):
        sl = src[i] if isinstance(src, list) else src
        if sl == tgt:
            out[i] = t
            continue
        parts = [x for x in re.split(r'(?<=[.?!।。？！])\s+', t) if x.strip()]
        out[i] = [''] * len(parts)
        jobs += [(i, k, sl, s) for k, s in enumerate(parts)]
    done, B = 0, 24
    for b in range(0, len(jobs), B):
        batch = jobs[b:b + B]
        source = [[sl] + sp.encode(s, out_type=str) + ['</s>'] for _, _, sl, s in batch]
        res = tr.translate_batch(source, target_prefix=[[tgt]] * len(batch), beam_size=1, max_decoding_length=300)
        for (i, k, sl, s), r, x in zip(batch, res, source):
            toks = [y for y in r.hypotheses[0] if y != tgt]
            if len(toks) > 2 * len(x) + 10:  # far longer than the sentence: NLLB is looping ("ঘুরতে ঘুরতে ঘুরতে ..."), try again carefully
                r2 = tr.translate_batch([x], target_prefix=[[tgt]], beam_size=4, repetition_penalty=1.3, no_repeat_ngram_size=3,
                                        max_decoding_length=2 * len(x) + 10)[0]
                toks = [y for y in r2.hypotheses[0] if y != tgt]
            out[i][k] = re.sub(r'^[-–—\s]+', '', sp.decode(toks))
        done += len(batch)
        asr.say(f'Translating on the {where}: {done} of {len(jobs)} sentences', done / max(1, len(jobs)))
    result = [x if isinstance(x, str) else ' '.join(x) for x in out]
    json.dump({'texts': result, 'device': where}, open(os.path.join(folder, 'result.json'), 'w', encoding='utf-8'), ensure_ascii=False)


if __name__ == '__main__':
    job(sys.argv[1])
