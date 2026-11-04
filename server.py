"""Local server for Video Dubbing. Start it with serve.cmd.

Serves the page on http://localhost:8000 and lets the page use this PC's graphics card
for AI upscaling (upscale/upscale.py). Listens on 127.0.0.1 only, so nothing outside
this computer can reach it. Uses only Python's standard library: no pip install needed.
ffmpeg and Real-ESRGAN are downloaded automatically the first time AI upscaling is used.
"""
import http.server, json, os, shutil, subprocess, sys, threading, time, urllib.parse, uuid, webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'upscale'))
import upscale as up  # noqa: E402

PORT = int(os.environ.get('VD_PORT', 8000))
JOBS_DIR = os.path.join(HERE, 'upscale', 'jobs')
JOBS, LOCK = {}, threading.Lock()
NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def gpu_info():
    """The strongest graphics card: NVIDIA via nvidia-smi, otherwise AMD/Intel Arc from Windows."""
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
                           capture_output=True, text=True, timeout=10, creationflags=NOWIN)
        if r.returncode == 0 and r.stdout.strip():
            name, mem = r.stdout.strip().splitlines()[0].rsplit(',', 1)
            return {'name': name.strip(), 'vram_gb': round(int(mem) / 1024, 1)}
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command',
                            'Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json'],
                           capture_output=True, text=True, timeout=20, creationflags=NOWIN)
        cards = json.loads(r.stdout or '[]')
        for c in cards if isinstance(cards, list) else [cards]:
            n = c.get('Name') or ''
            if any(k in n.lower() for k in ('radeon', 'amd', 'arc')):
                return {'name': n, 'vram_gb': round((c.get('AdapterRAM') or 0) / 2**30, 1)}  # AdapterRAM caps at 4 GB
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


GPU = gpu_info()


def status():
    need = []
    if not (up.FFMPEG and up.FFPROBE):
        need.append('ffmpeg (200 MB)')
    if not up.tool_path():
        need.append('Real-ESRGAN (45 MB)')
    sizes = ['2k', '4k'] + (['8k'] if GPU and GPU['vram_gb'] >= 6 else [])
    return {'gpu': GPU, 'sizes': sizes if GPU else [], 'setup': need}


def start_job(path, to, model):
    jid = os.path.basename(os.path.dirname(path))
    job = {'state': 'running', 'text': 'Starting…', 'frac': 0, 'stop': False, 'out': None, 'name': None}
    with LOCK:
        JOBS[jid] = job

    def log(text, frac=None):
        job['text'] = text
        if frac is not None:
            job['frac'] = frac

    def work():
        try:
            job['out'] = up.upscale(path, to, model, out=os.path.join(os.path.dirname(path), f'result-{to}.mp4'),
                                    log=log, stop=lambda: job['stop'])
            job['state'] = 'done'
        except up.Stopped:
            job['state'], job['text'] = 'stopped', 'Cancelled.'
        except Exception as e:  # report every failure to the page
            job['state'], job['text'] = 'error', str(e)[-800:]
    threading.Thread(target=work, daemon=True).start()
    return jid


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=HERE, **k)

    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def api_ok(self):
        # The page sends this header; other websites cannot (a custom header needs CORS, which we never allow)
        if self.headers.get('X-VD') != '1':
            self.send_json({'error': 'forbidden'}, 403)
            return False
        return True

    def job(self, parts):
        j = JOBS.get(parts[2]) if len(parts) > 2 else None
        if not j:
            self.send_json({'error': 'no such job'}, 404)
        return j

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path.strip('/').split('/')
        if p[0] != 'api':
            if u.path.startswith(('/upscale/jobs', '/upscale/ffmpeg', '/upscale/realesrgan')):
                return self.send_error(404)
            return super().do_GET()
        if p[1:2] == ['status']:
            return self.send_json(status())
        if p[1:2] == ['job']:
            j = self.job(p)
            if not j:
                return
            if p[3:4] == ['file']:  # the finished video (no custom header: used by <video> and download links)
                if j['state'] != 'done':
                    return self.send_error(404)
                size = os.path.getsize(j['out'])
                self.send_response(200)
                self.send_header('Content-Type', 'video/mp4')
                self.send_header('Content-Length', str(size))
                self.send_header('Content-Disposition', f'attachment; filename="{j["name"]}"' if 'dl' in u.query else 'inline')
                self.end_headers()
                with open(j['out'], 'rb') as f:
                    shutil.copyfileobj(f, self.wfile, 1 << 20)
                return
            return self.send_json({k: j[k] for k in ('state', 'text', 'frac')})
        self.send_error(404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path.strip('/').split('/')
        if p[:1] != ['api'] or not self.api_ok():
            return
        q = dict(urllib.parse.parse_qsl(u.query))
        if p[1:2] == ['upscale']:
            to, model = q.get('to', '4k'), q.get('model', 'photo')
            if to not in status()['sizes'] or model not in up.MODELS:
                return self.send_json({'error': 'This size is not available on this computer.'}, 400)
            name = urllib.parse.unquote(self.headers.get('X-Name', 'video.mp4'))  # in a header, not the URL
            jid = uuid.uuid4().hex[:12]
            d = os.path.join(JOBS_DIR, jid)
            os.makedirs(d)
            ext = os.path.splitext(name)[1].lower() or '.mp4'
            path = os.path.join(d, 'input' + (ext if ext.isascii() and len(ext) <= 5 else '.mp4'))
            left = int(self.headers.get('Content-Length', 0))
            with open(path, 'wb') as f:
                while left > 0:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
            start_job(path, to, model)
            JOBS[jid]['name'] = os.path.splitext(os.path.basename(name))[0] + f'-{to}.mp4'
            return self.send_json({'id': jid})
        if p[1:2] == ['job'] and p[3:4] == ['stop']:
            j = self.job(p)
            if j:
                j['stop'] = True
                self.send_json({'ok': True})
            return
        self.send_error(404)


def clean_old_jobs():
    """Results stay one day, then they are removed."""
    if os.path.isdir(JOBS_DIR):
        for d in os.listdir(JOBS_DIR):
            full = os.path.join(JOBS_DIR, d)
            if time.time() - os.path.getmtime(full) > 86400:
                shutil.rmtree(full, ignore_errors=True)


if __name__ == '__main__':
    clean_old_jobs()
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    url = f'http://localhost:{PORT}/'
    print(f'Video Dubbing is running at {url}')
    print(f'Graphics card for AI upscaling: {GPU["name"] + " (" + str(GPU["vram_gb"]) + " GB)" if GPU else "none found (browser options still work)"}')
    print('Keep this window open while you use the page. Close it to stop.')
    if '--no-browser' not in sys.argv:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
