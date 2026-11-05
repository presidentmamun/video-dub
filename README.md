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
- macOS / Linux: `curl -fsSL https://raw.githubusercontent.com/presidentmamun/video-dub/main/helper.sh | sh`

The helper answers only its own page and the websites in `ORIGINS` in `server.py` (add more with `VD_ORIGINS`).

The browser AI models in `models/` are Real-ESRGAN's compact models (realesr-animevideov3, realesr-general-x4v3),
converted to ONNX.

## Upscale from the command line

```
python upscale/upscale.py VIDEO --to 4k --model photo   # 2k | 4k | 8k, photo | anime
```

Or drag a video onto `upscale/upscale.cmd` (Windows), or run `./upscale/upscale.sh VIDEO --to 4k` (macOS / Linux).

On macOS the first run of the Real-ESRGAN tool may be blocked by Gatekeeper; allow it in
System Settings > Privacy & Security, then run again.
