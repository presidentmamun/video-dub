# Video Dubbing

Dub a video into another language, right on your own computer. Nothing is uploaded.

- **Speech → text:** Whisper (Transformers.js, WebGPU or CPU)
- **Translation:** NLLB-200 (200 languages)
- **New voice:** Kokoro (English, many voices) or MMS-TTS (Bengali, Hindi, Arabic, French, …)
- **Speakers:** finds who is speaking and gives men and women matching voices
- **Background:** keeps music and sounds, removes the original voices (UVR MDX-Net)
- **Picture:** quick sharpen/2K in the browser; AI upscale in the browser (WebGPU, up to 4K, no install);
  or the fastest AI upscale to 2K/4K/8K with Real-ESRGAN on your graphics card through the helper
- **Output:** dubbed video, subtitles (.srt), audio (.wav)

## Run

| System | Start | AI upscale |
|---|---|---|
| Windows | double-click **serve.cmd** | NVIDIA or AMD graphics card |
| macOS | double-click **serve.command** (or `./serve.sh`) | Apple chip (M1/M2/...) or AMD; first `brew install ffmpeg` |
| Linux | `./serve.sh` | NVIDIA or AMD card with Vulkan drivers |

It starts a small local server on `http://localhost:8000` (this computer only) and opens the page.
Python 3.8+ is needed; on Windows serve.cmd offers to install it with winget.

Opening `index.html` directly also works, but then models are not cached and the AI upscale option is off.

The first run downloads the AI models (about 1.3 GB) into the browser cache. The first AI upscale
downloads Real-ESRGAN (45-50 MB) and, on Windows and Linux, ffmpeg (150-200 MB) if it is missing.

## Using the page from a website (the helper)

The page can be put on any website (it is one file). There, "AI upscale in the browser" works for everyone.
For the fastest AI upscale a visitor runs the helper once; it installs this project and starts `server.py --helper`
on `127.0.0.1:8000`, and the website's page talks to it (Chrome asks once to allow access to this device):

- Windows: the page's **Get the helper** button downloads `video-dub-helper.cmd`
- macOS / Linux: `curl -fsSL https://raw.githubusercontent.com/presidentmamun/video-dub/master/helper.sh | sh`

The helper answers only its own page and the websites in `ORIGINS` in `server.py` (add more with `VD_ORIGINS`).

When the helper is connected it also separates voices from music (`upscale/separate.py`): the same model and steps
as the browser, on the graphics card through onnxruntime (DirectML on Windows, CoreML on macOS, CUDA or CPU on Linux).
On an RTX 3070 Ti a 52-minute video takes about 3 minutes instead of about 20 in the browser. The first time it installs
onnxruntime and numpy into `upscale/pylib` and downloads the model (67 MB) into `upscale/models`.

Every AI step works the same way: the helper first, on the strongest hardware, else the browser as before.

| Step | Helper (`upscale/…`) | Hardware, first that works |
|---|---|---|
| Voices from music | `separate.py`, UVR MDX-Net | DirectML (NVIDIA, AMD, Intel), CoreML, CUDA, CPU |
| Speech recognition | `asr.py`, faster-whisper base/small | NVIDIA CUDA, else every CPU core |
| Speakers | `spk.py`, WavLM base plus SV (full precision) | DirectML, CPU |
| Translation | `mt.py`, NLLB-200 600M (CTranslate2) | NVIDIA CUDA, else every CPU core |
| New voices (MMS) | `tts.py`, MMS / VITS | DirectML, CPU |
| New voices (English, Kokoro) | `kokoro.py`, Kokoro 82M v1.0 (full precision) | DirectML if it runs there, else every CPU core |
| Editing | `edit.py`, ffmpeg | NVENC, AMF, Quick Sync, VideoToolbox, CPU |

Each AI step runs in its own process, so its libraries (in `upscale/pylib`, `upscale/pylib-asr` and `upscale/pylib-tts`) never mix and its
memory is given back when it ends. A 60-second clip dubs from English to Bengali in about 45 seconds on an RTX 3070 Ti.

The browser AI models in `models/` are Real-ESRGAN's compact models (realesr-animevideov3, realesr-general-x4v3),
converted to ONNX.

## Edit and look

Step 4 of the page edits the video: trim, cut, speed, crop to a shape, flip and turn, logo, title, moving line,
subtitles, colour (including channel orders such as BGR and colour models such as HSV), blurred boxes, sound and music,
steadying, 60 fps, intro and outro, and sizes for each platform. The page builds one ffmpeg recipe and makes it in the
fastest way the device has ("Make it with" can choose one):

1. **The helper** (`upscale/edit.py`): this computer's ffmpeg with the graphics card encoder that really works here
   (NVIDIA NVENC, AMD AMF, Intel Quick Sync, Apple VideoToolbox, tested once at start) or else every CPU core.
   It accepts only the page's own recipe: known options and filters, files inside the job folder.
2. **The browser's graphics card**: WebCodecs decodes the MP4, a canvas and WebGL draw each frame (the same code as the
   preview), and the browser's H.264 encoder writes it. ffmpeg only makes the sound, at the same time.
   Not for backwards, steadying, 60 fps or a colour standard change: those use the processor.
3. **The browser's processor**: ffmpeg.wasm, on every core when the page is cross-origin isolated.
   `coi-sw.js` (a service worker next to the page) adds the two headers for that inside the browser, so no web server
   setting is needed. Without the file, or in Safari, the page uses one core.

## Upscale from the command line

```
python upscale/upscale.py VIDEO --to 4k --model photo   # 2k | 4k | 8k, photo | anime
```

Or drag a video onto `upscale/upscale.cmd` (Windows), or run `./upscale/upscale.sh VIDEO --to 4k` (macOS / Linux).

On macOS the first run of the Real-ESRGAN tool may be blocked by Gatekeeper; allow it in
System Settings > Privacy & Security, then run again.
