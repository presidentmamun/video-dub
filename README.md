# Video Dubbing

Dub a video into another language, right on your own computer. Nothing is uploaded.

- **Speech → text:** Whisper (Transformers.js, WebGPU or CPU)
- **Translation:** NLLB-200 (200 languages)
- **New voice:** Kokoro (English, many voices) or MMS-TTS (Bengali, Hindi, Arabic, French, …)
- **Speakers:** finds who is speaking and gives men and women matching voices
- **Background:** keeps music and sounds, removes the original voices (UVR MDX-Net)
- **Picture:** quick sharpen/2K in the browser, or AI upscale to 2K/4K/8K with Real-ESRGAN on your graphics card
- **Output:** dubbed video, subtitles (.srt), audio (.wav)

## Run

Double-click **serve.cmd**. It starts a small local server on `http://localhost:8000` (this computer only)
and opens the page. Python 3.8+ is needed; serve.cmd offers to install it with winget if it is missing.

Opening `index.html` directly also works, but then models are not cached and the AI upscale option is off.

The first run downloads the AI models (about 1.3 GB) into the browser cache. The first AI upscale
downloads Real-ESRGAN (45 MB) and, if missing, ffmpeg (200 MB) into `upscale/`.

## Upscale from the command line

```
python upscale/upscale.py VIDEO --to 4k --model photo   # 2k | 4k | 8k, photo | anime
```

Or drag a video onto `upscale/upscale.cmd`.
