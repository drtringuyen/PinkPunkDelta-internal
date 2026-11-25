"""The Wi-Fi server the iPad talks to. Runs in threads and never touches bpy: what needs Blender
is queued as a job for the main thread (core.tick). Based on Procreate Live Link 1.0.0 (GPL-3.0),
with a token in every address: only who scanned the QR code gets in."""
import hmac
import json
import os
import queue
import re
import shutil
import socket
import tempfile
import threading
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import psd

MAX_UPLOAD = 2 * 1024 ** 3
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".psd", ".bmp", ".tga", ".webp"}
MIME = {"image/png": ".png", "image/jpeg": ".jpg", "image/tiff": ".tif",
        "image/vnd.adobe.photoshop": ".psd", "image/x-photoshop": ".psd",
        "application/photoshop": ".psd", "image/webp": ".webp"}


class Job:
    def __init__(self, payload):
        self.payload = payload
        self.result = "Blender did not answer"
        self.done = threading.Event()
        self.cancelled = False


class LinkServer:
    def __init__(self, port, web_dir, token):
        self.port, self.web_dir, self.token = port, web_dir, token
        self.jobs = queue.Queue()
        self.state = {"blend": "", "objects": [], "log": []}
        self.psd_files = {}             # full name -> path
        self.blend = ""                 # for the folder watcher
        self.names = {}                 # every name an object answers to -> its full name
        self.staging = tempfile.mkdtemp(prefix="ppd_livelink_")
        self.httpd = None
        self.requests = []              # the last uploads, for debugging (no key in it)

    def start(self):
        server = self

        class Handler(_Handler):
            link = server

        self.httpd = _Server(("0.0.0.0", self.port), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        self.httpd = None
        while True:
            try:
                j = self.jobs.get_nowait()
            except queue.Empty:
                break
            j.result = "The link was stopped in Blender"
            j.done.set()

    def cleanup(self):
        shutil.rmtree(self.staging, ignore_errors=True)

    def submit(self, payload, timeout=180):
        job = Job(payload)
        self.jobs.put(job)
        if not job.done.wait(timeout):
            job.cancelled = True
            return "Blender is busy (timed out). Send it again"
        return job.result

    def stage(self, ext):
        os.makedirs(self.staging, exist_ok=True)
        return os.path.join(self.staging, uuid.uuid4().hex + ext)

    def receive(self, stem, ext, data):
        """One received file, unpacked in this thread so Blender does not freeze on it."""
        item = {"stem": stem, "psd": ext == ".psd", "files": {}, "note": ""}
        if ext == ".psd":
            found, _size, unused = psd.read_layers(data, ("SHD", "TEX"))
            for kind, px in found.items():
                if not px[:, :, 3].any():
                    item["note"] += f" {kind} layer is empty, its file was kept."
                    continue
                item["files"][kind] = self.stage(".png")
                psd.write_png(item["files"][kind], px)
            extra = [n for n in unused if n.casefold() not in
                     ("uv layout", "alb", "nor", "background", "background color")]
            if extra:
                item["note"] += " Not used: " + ", ".join(extra[:4]) + \
                    " (put it in a group named SHD or TEX)."
            if not found:
                return f"⚠ {stem}: no layer or group named SHD or TEX"
            if not item["files"]:
                return f"⚠ {stem}:{item['note']}"
        else:
            path = self.stage(ext)
            with open(path, "wb") as f:
                f.write(data)
            item["files"][""] = path        # the kind comes from its name
        return self.submit(item)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False     # a second Blender must not steal the port


def split_name(filename):
    filename = os.path.basename(filename.replace("\\", "/")).strip()
    stem, ext = os.path.splitext(filename)
    return (stem.strip(), ext.lower()) if ext.lower() in IMAGE_EXTS else (filename, "")


def sniff_ext(data):
    head = bytes(data[:8])
    for magic, ext in ((b"\x89PNG", ".png"), (b"\xff\xd8\xff", ".jpg"), (b"8BPS", ".psd"),
                       (b"II*\0", ".tif"), (b"MM\0*", ".tif")):
        if head.startswith(magic):
            return ext
    return ""


def _filename(header):
    m = re.search(r"filename\*\s*=\s*utf-8''([^;\r\n]+)", header, re.I)
    if m:
        return urllib.parse.unquote(m.group(1).strip())
    m = re.search(r'filename\s*=\s*"((?:[^"\\]|\\.)*)"', header, re.I)
    return m.group(1) if m else ""


def parse_upload(ctype, body, query):
    """[(stem, ext, bytes)] of a multipart form or a raw body."""
    out = []
    m = re.search(r'boundary="?([^";]+)"?', ctype or "", re.I)
    if (ctype or "").lower().startswith("multipart/") and m:
        sep = b"--" + m.group(1).encode("latin-1")
        pos = body.find(sep)
        while pos >= 0:
            start = pos + len(sep)
            if body[start:start + 2] == b"--":
                break
            nxt = body.find(b"\r\n" + sep, start)
            if nxt < 0:
                break
            head_end = body.find(b"\r\n\r\n", start, nxt)
            if head_end >= 0:
                head = body[start:head_end].decode("utf-8", "replace")
                data = body[head_end + 4:nxt]
                name = _filename(head)
                mt = re.search(r"content-type:\s*([^;\s]+)", head, re.I)
                stem, ext = split_name(name or query.get("name") or "Untitled")
                ext = sniff_ext(data) or ext or MIME.get(mt.group(1).lower() if mt else "", "")
                if data and ext:
                    out.append((stem, ext, data))
            pos = nxt + 2
    elif body:
        stem, ext = split_name(query.get("name") or "Untitled")
        ext = sniff_ext(body) or ext
        if ext:
            out.append((stem, ext, body))
    return out


class _Handler(BaseHTTPRequestHandler):
    link = None
    server_version = "PPDLiveLink"
    timeout = 120

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        body = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _open(self):
        u = urllib.parse.urlparse(self.path)
        self.route = urllib.parse.unquote(u.path)
        self.query = {k: v[-1] for k, v in urllib.parse.parse_qs(u.query).items()}
        if hmac.compare_digest(self.query.get("t", "").encode(), self.link.token.encode()):
            return True
        self.close_connection = True
        self._send(403, "Scan the QR code in Blender (PPD > 03.LiveLink) again")
        return False

    def do_GET(self):
        if not self._open():
            return
        if self.route == "/":
            with open(os.path.join(self.link.web_dir, "index.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif self.route == "/state":
            self._send(200, json.dumps(self.link.state), "application/json; charset=utf-8")
        elif self.route.startswith("/psd/"):
            self._psd(os.path.splitext(self.route[5:])[0])
        else:
            self._send(404, "Not found")

    def _psd(self, name):
        path = self.link.psd_files.get(name, "")
        if not os.path.isfile(path):
            self._send(404, "Press Prepare PSD in Blender first")
            return
        with open(path, "rb") as f:
            self.send_response(200)
            self.send_header("Content-Type", "image/vnd.adobe.photoshop")
            self.send_header("Content-Length", str(os.fstat(f.fileno()).st_size))
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''"
                             + urllib.parse.quote(name + ".psd"))
            self.end_headers()
            shutil.copyfileobj(f, self.wfile, 1 << 20)

    def _body(self):
        """The whole upload. An iPad Shortcut that sends a file as the body streams it
        (chunked), without a Content-Length."""
        data = bytearray()

        def read(n):
            if len(data) + n > MAX_UPLOAD:
                raise ValueError("The file is larger than 2 GB")
            while n > 0:
                part = self.rfile.read(min(n, 1 << 20))
                if not part:
                    raise ValueError("The upload was cut off, send it again")
                data.extend(part)
                n -= len(part)

        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            while True:
                line = self.rfile.readline(1024)
                if not line:
                    raise ValueError("The upload was cut off, send it again")
                size = line.split(b";")[0].strip()
                if not re.fullmatch(rb"[0-9A-Fa-f]{1,8}", size):
                    raise ValueError("The upload was damaged, send it again")
                if not int(size, 16):
                    break
                read(int(size, 16))
                self.rfile.readline(1024)       # the line end after each chunk
            while self.rfile.readline(1024).strip():
                pass                            # trailers
        else:
            n = self.headers.get("Content-Length", "")
            read(int(n) if n.isdigit() else 0)
        if not data:
            raise ValueError("The iPad sent an empty file. Use Send back on the LiveLink page")
        return data

    def do_POST(self):
        if not self._open():
            return
        if self.route != "/upload":
            self._send(404, "Not found")
            return
        note = {k: self.headers.get(k, "") for k in (
            "User-Agent", "Content-Type", "Content-Length", "Transfer-Encoding", "Expect")}
        self.link.requests = self.link.requests[-9:] + [note]
        try:
            data = self._body()
            note["received"] = len(data)
        except ValueError as e:
            note["error"] = str(e)
            self.close_connection = True
            self._send(400, f"⚠ {e}")
            return
        files = parse_upload(self.headers.get("Content-Type", ""), bytes(data), self.query)
        del data
        if not files:
            self._send(400, "No image received. In the Shortcut, the form field must be a File")
            return
        msgs = []
        for stem, ext, body in files:
            note["file"] = stem + ext
            if ext == ".psd" and self.query.get("object"):
                stem = self.query["object"]     # Send back beside that object on the page
            try:
                msgs.append(self.link.receive(stem, ext, body))
            except Exception as e:
                msgs.append(f"⚠ {stem}: {e}")
        self._send(200, "\n".join(msgs))


def local_ips():
    """This PC's addresses, the best guess for the Wi-Fi first."""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))        # no packet is sent
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            if info[4][0] not in ips:
                ips.append(info[4][0])
    except OSError:
        pass
    return [ip for ip in ips if not ip.startswith("127.")] or ["127.0.0.1"]
