"""Watches the PPD_Procreate folder of this PC: a PSD the iPad saves there (Procreate: Share > PSD >
Save to Files) is imported like an upload and then removed - the artwork stays in Procreate.
Runs in a thread and never touches bpy."""
import json
import os
import re
import threading

FOLDER = "PPD_Procreate"
EVERY = 3.0             # seconds between looks at the folder
TRIES = 5


def folder():
    """The fixed folder on this PC, made when missing. Shared on the network, so the iPad saves
    straight into it."""
    path = os.path.join(os.environ.get("SystemDrive", os.path.expanduser("~")) + os.sep, FOLDER)
    os.makedirs(path, exist_ok=True)
    return path


def names_of(stem):
    """The name a copy may stand for: 'Wheel 2', 'Wheel (1)' and 'Wheel-1' are Wheel too."""
    yield stem
    short = re.sub(r"(\s*\(\d+\)|[\s\-]+\d+)$", "", stem)
    if short and short != stem:
        yield short


class Watcher:
    def __init__(self, link, find, log, record, where=folder):
        """link: the LinkServer. find(name) -> the object's full name or ''. record: the json
        file that remembers what was imported, so nothing is imported twice."""
        self.link, self.find, self.log = link, find, log
        self.record, self.where = record, where
        self.path = ""
        self.seen = {}          # path -> stamp at the last look: imported once it is still
        self.tries = {}
        self.told = set()
        self.layer_key = {}     # path+stamp -> the key in its UV layer's name
        self.quit = threading.Event()
        try:
            with open(record, encoding="utf-8") as f:
                self.done = json.load(f)
        except (OSError, ValueError):
            self.done = {}

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.quit.set()

    def _run(self):
        while not self.quit.is_set():
            try:
                self.path = self.where()
                self.tell("watching", f"Watching {self.path}")
                self.look()
            except Exception as e:
                self.tell(f"folder:{e}", f"⚠ {FOLDER}: {e}")
            self.quit.wait(EVERY)

    def tell(self, key, text):
        if key not in self.told:
            self.told.add(key)
            self.log(text)

    def look(self):
        files = []
        for e in os.scandir(self.path):
            if e.name.lower().endswith(".psd") and not e.name.startswith((".", "~")):
                st = os.stat(e.path)
                files.append((st.st_mtime, st.st_size, e.path))
        for mtime, size, path in sorted(files):     # the newest last: it wins
            stamp = [round(mtime, 2), size]
            if self.quit.is_set():
                return
            if self.done.get(path) == stamp:
                continue
            still = self.seen.get(path) == stamp
            self.seen[path] = stamp
            if still and size:
                self._import(path, stamp)

    @staticmethod
    def _uv_key(path):
        from .server import uv_key
        try:
            with open(path, "rb") as f:
                return uv_key(f.read())
        except OSError:
            return ""

    def _import(self, path, stamp):
        stem = os.path.splitext(os.path.basename(path))[0]
        name = next((n for n in map(self.find, names_of(stem)) if n), "")
        key = f"{path}{stamp}"
        if not name and key not in self.layer_key:
            self.layer_key[key] = self._uv_key(path)    # the canvas was renamed in Procreate
        if not name and self.layer_key.get(key):
            name = self.find(stem, self.layer_key[key])
        if not name:            # left alone: another .blend may be waiting for it
            self.tell(key, f"{stem}.psd: no object of that name in this .blend")
            return
        if self.tries.get(key, 0) >= TRIES:
            return
        self.tries[key] = self.tries.get(key, 0) + 1
        self.tell("read" + key, f"Reading {stem}.psd")
        try:
            with open(path, "rb") as f:
                data = f.read()
            if len(data) != stamp[1]:
                return          # still being written
            msg = self.link.receive(name, ".psd", data)
        except Exception as e:
            if self.tries[key] >= TRIES:
                self.log(f"⚠ {stem}.psd: {e}")
            return
        if not msg.startswith(("✓", "⚠")):
            self.tries[key] -= 1        # Blender is busy or the link stopped: again later
            return
        if msg.startswith("⚠"):
            self.log(msg)
        self.done[path] = stamp
        tmp = self.record + ".part"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.done, f, indent=1)
        os.replace(tmp, self.record)
        if msg.startswith("✓"):
            try:
                st = os.stat(path)
                if [round(st.st_mtime, 2), st.st_size] == stamp:    # not saved again meanwhile
                    os.remove(path)
            except OSError:
                pass                        # still open on the iPad: it is not imported again
