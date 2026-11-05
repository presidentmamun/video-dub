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
# websites whose Video Dubbing page may use this helper (besides the page served here); more with VD_ORIGINS="https://a,https://b"
ORIGINS = {'https://iwate-bd.org', 'https://www.iwate-bd.org'} | {o.strip().rstrip('/') for o in os.environ.get('VD_ORIGINS', '').split(',') if o.strip()}
JOBS_DIR = os.path.join(HERE, 'upscale', 'jobs')
JOBS, LOCK = {}, threading.Lock()
NOWIN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def _out(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=NOWIN)
        return r.stdout if r.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def gpu_info():
    """The strongest graphics card. NVIDIA via nvidia-smi on every system; otherwise
    Windows: AMD/Intel Arc from WMI; macOS: Apple or AMD from system_profiler; Linux: lspci."""
    out = _out(['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'], 10).strip()
    if out:
        try:
            name, mem = out.splitlines()[0].rsplit(',', 1)
            return {'name': name.strip(), 'vram_gb': round(int(mem) / 1024, 1)}
        except ValueError:
            pass
    if sys.platform == 'win32':
        try:
            cards = json.loads(_out(['powershell', '-NoProfile', '-Command',
                                     'Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json']) or '[]')
        except ValueError:
            cards = []
        for c in cards if isinstance(cards, list) else [cards]:
            n = c.get('Name') or ''
            if any(k in n.lower() for k in ('radeon', 'amd', 'arc')):
                return {'name': n, 'vram_gb': round((c.get('AdapterRAM') or 0) / 2**30, 1)}  # AdapterRAM caps at 4 GB
    elif sys.platform == 'darwin':
        try:
            cards = json.loads(_out(['system_profiler', 'SPDisplaysDataType', '-json']) or '{}').get('SPDisplaysDataType', [])
        except ValueError:
            cards = []
        if cards:
            name = cards[0].get('sppci_model', 'Mac graphics')
            mem = _out(['sysctl', '-n', 'hw.memsize']).strip()
            # Apple chips share memory with the system: count about half of it for the graphics
            vram = round(int(mem) / 2**31, 1) if mem.isdigit() and 'apple' in name.lower() else 0
            return {'name': name, 'vram_gb': vram}
    else:
        for line in _out(['lspci']).splitlines():
            low = line.lower()
            if ('vga' in low or '3d' in low) and any(k in low for k in ('nvidia', 'amd', 'radeon', 'arc')):
                return {'name': line.split(': ', 1)[-1], 'vram_gb': 0}
    return None


GPU = gpu_info()


def status():
    need, blocker = [], None
    if not (up.FFMPEG and up.FFPROBE):
        if up.FF_URL:
            need.append('ffmpeg (150-200 MB)')
        else:  # macOS: we do not download ffmpeg there
            blocker = 'install ffmpeg first with: brew install ffmpeg (then restart serve.command).'
    
    if not up.tool_path():
        need.append('Real-ESRGAN (45-50 MB)')
    sizes = ['2k', '4k'] + (['8k'] if GPU and GPU['vram_gb'] >= 6 else [])  # vram 0 = unknown: no 8K
    return {'gpu': GPU, 'sizes': sizes if GPU and not blocker else [], 'setup': need, 'blocker': blocker}


def start_job(jid, task, name):
    """Run task(log, stop) -> output path in a thread; the page follows it through /api/job/<id>."""
    job = {'state': 'running', 'text': 'Starting...', 'frac': 0, 'stop': False, 'out': None, 'name': name}
    with LOCK:
        JOBS[jid] = job

    def log(text, frac=None):
        job['text'] = text
        if frac is not None:
            job['frac'] = frac

    def work():
        try:
            job['out'] = task(log, lambda: job['stop'])
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

    def log_message(self, fmt, *a):
        if os.environ.get('VD_DEBUG'):  # VD_DEBUG=1: show each request
            print(self.command, self.path, '| Origin:', self.headers.get('Origin'), file=sys.stderr)

    def send_json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def origin_ok(self):
        o = self.headers.get('Origin')
        return not o or o in ORIGINS or urllib.parse.urlparse(o).hostname in ('localhost', '127.0.0.1')

    def end_headers(self):
        o = self.headers.get('Origin') if hasattr(self, 'headers') else None
        if o and o in ORIGINS:  # only the listed websites may read the answers
            self.send_header('Access-Control-Allow-Origin', o)
            self.send_header('Vary', 'Origin')
        super().end_headers()

    def do_OPTIONS(self):  # the browser asks first before a website may send the X-VD header
        if not self.origin_ok():
            return self.send_error(403)
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST')
        self.send_header('Access-Control-Allow-Headers', 'X-VD, X-Name, Content-Type')
        self.send_header('Access-Control-Allow-Private-Network', 'true')
        self.send_header('Access-Control-Max-Age', '600')
        self.end_headers()

    def api_ok(self):
        # The page sends this header; other websites cannot (a custom header needs CORS, allowed only for ORIGINS)
        if self.headers.get('X-VD') != '1' or not self.origin_ok():
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
            if not self.api_ok():
                return
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
            info = {k: j[k] for k in ('state', 'text', 'frac')}
            if j['state'] == 'done':
                info['size'] = os.path.getsize(j['out'])
            return self.send_json(info)
        self.send_error(404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path.strip('/').split('/')
        if p[:1] != ['api'] or not self.api_ok():
            return
        q = dict(urllib.parse.parse_qsl(u.query))
        if p[1:2] in (['upscale'], ['shrink']):
            name = urllib.parse.unquote(self.headers.get('X-Name', 'video.mp4'))  # in a header, not the URL
            stem = os.path.splitext(os.path.basename(name))[0]
            if p[1] == 'upscale':
                to, model = q.get('to', '4k'), q.get('model', 'photo')
                if to not in status()['sizes'] or model not in up.MODELS:
                    return self.send_json({'error': 'This size is not available on this computer.'}, 400)
            else:
                height = int(q.get('h', '1080')) if q.get('h', '1080').isdigit() else 0
                if height not in up.SHARE_KBPS:
                    return self.send_json({'error': 'Unknown size.'}, 400)
            jid = uuid.uuid4().hex[:12]
            d = os.path.join(JOBS_DIR, jid)
            os.makedirs(d)
            src = JOBS.get(q.get('from', ''), {}).get('out')  # shrink a result that is already here
            if not src:
                ext = os.path.splitext(name)[1].lower() or '.mp4'
                src = os.path.join(d, 'input' + (ext if ext.isascii() and len(ext) <= 5 else '.mp4'))
                left = int(self.headers.get('Content-Length', 0))
                with open(src, 'wb') as f:
                    while left > 0:
                        chunk = self.rfile.read(min(left, 1 << 20))
                        if not chunk:
                            break
                        f.write(chunk)
                        left -= len(chunk)
            if p[1] == 'upscale':
                out = os.path.join(d, f'result-{to}.mp4')
                start_job(jid, lambda log, stop: up.upscale(src, to, model, out=out, log=log, stop=stop), f'{stem}-{to}.mp4')
            else:
                out = os.path.join(d, f'result-{height}p.mp4')
                start_job(jid, lambda log, stop: up.shrink(src, height, out=out, log=log, stop=stop), f'{stem}-{height}p.mp4')
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
    # never share the port with an older copy that is still running (Windows lets two programs bind it otherwise)
    http.server.ThreadingHTTPServer.allow_reuse_address = sys.platform != 'win32'
    try:
        srv = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    except OSError:
        print(f'Port {PORT} is already in use: Video Dubbing (or another program) is already running.')
        print(f'Close the other window, or open http://localhost:{PORT}/ if it is Video Dubbing.')
        sys.exit(1)
    url = f'http://localhost:{PORT}/'
    print(f'Video Dubbing is running at {url}')
    print(f'Graphics card for AI upscaling: {GPU["name"] + " (" + str(GPU["vram_gb"]) + " GB)" if GPU else "none found (browser options still work)"}')
    print('Keep this window open while you use the page. Close it to stop.')
    if '--helper' in sys.argv:
        print('Helper mode: go back to the Video Dubbing page and press "Connect to the helper".')
    elif '--no-browser' not in sys.argv:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
