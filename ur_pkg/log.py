"""Tiny colored logger (no deps). Module-level `Log` + `Log.get(name)` facade."""
import os
import time


class _Log:
    _instance = None

    def __init__(self):
        self.verbose = False
        self._file = None
        if _Log._instance is None:
            _Log._instance = self

    @classmethod
    def get(cls, name="ur"):
        if cls._instance is None:
            cls._instance = _Log()
        return cls._instance

    def setup(self, verbose: bool = False, log_dir: str = "logs"):
        self.verbose = verbose
        os.makedirs(log_dir, exist_ok=True)
        name = time.strftime("ur_%Y%m%d_%H%M%S.log")
        self._file = open(os.path.join(log_dir, name), "a", encoding="utf-8")

    def _emit(self, tag, color, msg):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {tag} {msg}"
        print(f"\033[{color}m{line}\033[0m", flush=True)
        if self._file:
            self._file.write(line + "\n")
            self._file.flush()

    def info(self, msg):
        self._emit("INFO ", "0;36", msg)

    def ok(self, msg):
        self._emit(" OK  ", "0;32", msg)

    def warn(self, msg):
        self._emit("WARN ", "0;33", msg)

    def err(self, msg):
        self._emit("ERROR", "0;31", msg)

    def debug(self, msg):
        if self.verbose:
            self._emit("DBG  ", "0;37", msg)

    def line(self):
        print("-" * 70, flush=True)

    def banner(self):
        try:
            from ur_pkg import __version__
        except ImportError:
            __version__ = "?"
        self.line()
        self.info(f"ur  v{__version__}  —  autonomous EURUSD trader")
        self.line()


Log = _Log()
