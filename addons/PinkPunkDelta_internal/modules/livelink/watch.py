"""Watches the PPD_Procreate folder in Google Drive: a PSD saved there from Procreate (Share >
PSD > Save to Files) is imported like an upload. Runs in a thread and never touches bpy."""
import glob
import json
import os
import re
import string
import threading
import time

FOLDER = "PPD_Procreate"
EVERY = 3.0             # seconds between looks at the folder
FIND_EVERY = 20.0       # seconds between looks for the folder itself
TRIES = 5


def drive_root(blend):
    """The Drive mount a .blend lies in ('' = none): what is above My Drive, Shared drives or
    the hidden folder of shortcuts."""
    m = re.match(r"(.+?)[\\/](\.shortcut-targets-by-id|My Drive|Shared drives)[\\/]", blend)
    return m.group(1) if m else ""


def folders(blend=""):
    """Every <drive>/My Drive/PPD_Procreate (My Drive has other names in other languages)."""
    roots = [f"{c}:\\" for c in string.ascii_uppercase if os.path.isdir(f"{c}:\\")]
    root = drive_root(blend)
    if root:
        roots.insert(0, root)
    out = []
    for r in roots:
        for p in glob.glob(os.path.join(glob.escape(r), "*", FOLDER)):
            if os.path.isdir(p) and not any(os.path.samefile(p, q) for q in out):
                out.append(p)
    return out


def names_of(stem):
    """The name a copy may stand for: 'Wheel 2', 'Wheel (1)' and 'Wheel-1' are Wheel too."""
    yield stem
    short = re.sub(r"(\s*\(\d+\)|[\s\-]+\d+)$", "", stem)
    if short and short != stem:
        yield short


class Watcher:
    def __init__(self, link, find, log, record, where=folders):
        """link: the LinkServer. find(name) -> the object's full name or ''. record: the json
        file that remembers what was imported, so nothing is imported twice."""
        self.link, self.find, self.log = link, find, log
        self.record, self.where = record, where
        self.paths = []
        self.seen = {}          # path -> stamp at the last look: imported once it is still
        self.tries = {}
        self.told = set()
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
        found = 0.0
        while not self.quit.is_set():
            try:
                if not found or time.time() - found > FIND_EVERY:
                    new = self.where(self.link.blend)
                    for p in new:
                        if p not in self.paths:
                            self.log(f"Watching {p}")
                    self.paths, found = new, time.time()
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
        for d in self.paths:
            for e in os.scandir(d):
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

    def _import(self, path, stamp):
        stem = os.path.splitext(os.path.basename(path))[0]
        name = next((n for n in map(self.find, names_of(stem)) if n), "")
        key = f"{path}{stamp}"
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
