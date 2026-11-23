#!/usr/bin/env python3
"""Laravel Project Compressor

Zips a Laravel (or Laravel + Android/Capacitor) project while skipping
vendor/, node_modules/, caches, logs, build artifacts and other junk.

Requires Python 3.8+ and the standard library only (tkinter).
"""
from __future__ import annotations

import fnmatch
import heapq
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

APP_TITLE = "Laravel Project Compressor"
CONFIG_PATH = Path.home() / ".laravel_compressor.json"

# ============================================================
# EXCLUSION RULES  (all comparisons are done in lower case)
# ============================================================

# Directory names skipped at ANY depth.
EXCLUDED_DIR_NAMES = {
    "vendor", "node_modules", "build",
    ".git", ".svn", ".hg", ".idea", ".vscode", ".phpunit.cache", ".nyc_output",
    "coverage", "__pycache__", ".pytest_cache",
    # Gradle / Android / Kotlin / Flutter caches
    ".gradle", ".gradle-cache", ".gradle-wrapper", ".kotlin", "kotlin-js-store",
    ".cxx", ".externalnativebuild", ".dart_tool",
}

# Only skipped when somewhere below an "android" folder.
ANDROID_ONLY_DIR_NAMES = {"intermediates", "generated", "outputs"}

# Multi-segment folders, matched against the end of the relative path.
PATH_RULES = {
    "storage/framework/cache",
    "storage/framework/sessions",
    "storage/framework/views",
    "storage/framework/testing",
    "storage/logs",
    "bootstrap/cache",
    "android/app/release",
    "android/app/debug",
    "android/app/src/main/assets/public",  # compiled web assets
    "android/capacitor-cordova-android-plugins/src/main/libs",
}
PATH_SUFFIXES = tuple("/" + p for p in PATH_RULES)

# Skipped folders that Laravel needs to exist: keep their .gitignore so the
# empty folder is recreated when the archive is extracted.
STUB_DIRS = {
    "storage/framework/cache", "storage/framework/sessions",
    "storage/framework/views", "storage/framework/testing",
    "storage/logs", "bootstrap/cache",
}
STUB_SUFFIXES = tuple("/" + p for p in STUB_DIRS)

# Files that live inside a skipped folder but must still be archived.
KEEP_FILES = ("public/build/manifest.json", "public/build/.vite/manifest.json")

# Hidden folders that are worth keeping (everything else starting with "." goes).
KEEP_HIDDEN_DIRS = {".github", ".well-known", ".devcontainer", ".husky", ".circleci", ".gitlab"}

EXCLUDED_FILES = {
    ".ds_store", "thumbs.db", "desktop.ini",
    ".phpunit.result.cache", ".env.local.php", "local.properties",
}
EXCLUDED_SUFFIXES = (
    ".log", ".tmp", ".temp", ".cache", ".pid",
    ".class", ".dex", ".apk", ".aab", ".jar", ".so", ".aar",
    ".map", ".min.js", ".min.css",
    ".pyc", ".pyo",
)
KEEP_FILE_NAMES = {"gradle-wrapper.jar"}  # would otherwise match ".jar"
ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".dist", ".template")

# Already-compressed formats: store them instead of wasting CPU on deflate.
STORED_SUFFIXES = (
    ".zip", ".gz", ".tgz", ".7z", ".rar", ".xz", ".bz2",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif",
    ".mp3", ".mp4", ".m4a", ".mov", ".webm", ".mkv", ".ogg",
    ".woff", ".woff2", ".pdf", ".docx", ".xlsx", ".pptx",
)

LEVELS = {"Fast": 1, "Balanced": 6, "Maximum": 9}


class ExclusionRules:
    def __init__(self, include_env: bool = False, extra: str = ""):
        self.include_env = include_env
        self.extra = [p.strip().lower() for p in extra.split(",") if p.strip()]

    def _extra_match(self, name: str, rel: str) -> bool:
        for p in self.extra:
            if (fnmatch.fnmatchcase(name, p) or fnmatch.fnmatchcase(rel, p)
                    or fnmatch.fnmatchcase(rel, "*/" + p)):
                return True
        return False

    def dir_reason(self, name: str, rel: str):
        n, r = name.lower(), rel.lower()
        if n in EXCLUDED_DIR_NAMES:
            return n
        if n.startswith(".") and n not in KEEP_HIDDEN_DIRS:
            return "hidden folder"
        if n in ANDROID_ONLY_DIR_NAMES and "/android/" in "/" + r + "/":
            return n
        if r in PATH_RULES or r.endswith(PATH_SUFFIXES):
            return r
        if self.extra and self._extra_match(n, r):
            return "custom"
        return None

    def file_reason(self, name: str, rel: str):
        n = name.lower()
        if n in KEEP_FILE_NAMES:
            return None
        if n in EXCLUDED_FILES:
            return n
        if n.endswith(EXCLUDED_SUFFIXES):
            return "extension"
        if (not self.include_env and (n == ".env" or n.startswith(".env."))
                and not n.endswith(ENV_TEMPLATE_SUFFIXES)):
            return ".env"
        if self.extra and self._extra_match(n, rel.lower()):
            return "custom"
        return None


# ============================================================
# ENGINE
# ============================================================

class Cancelled(Exception):
    pass


@dataclass
class ScanResult:
    files: list = field(default_factory=list)  # (abs_path, rel_path, size)
    total_bytes: int = 0
    skipped_dirs: Counter = field(default_factory=Counter)
    skipped_files: int = 0
    skipped_links: int = 0
    errors: list = field(default_factory=list)

    @property
    def skipped_total(self) -> int:
        return sum(self.skipped_dirs.values()) + self.skipped_files + self.skipped_links


def scan_project(src: str, rules: ExclusionRules, cancel: threading.Event,
                 report, skip_abs=frozenset()) -> ScanResult:
    """Walk `src` once, pruning excluded folders before descending into them."""
    res = ScanResult()
    last = 0.0

    def add(path: str, rel: str):
        size = os.stat(path).st_size
        res.files.append((path, rel, size))
        res.total_bytes += size

    stack = [(src, "")]
    while stack:
        if cancel.is_set():
            raise Cancelled
        cur, rel = stack.pop()
        try:
            with os.scandir(cur) as it:
                entries = list(it)
        except OSError as exc:
            res.errors.append(f"{rel or '.'}: {exc.strerror or exc}")
            continue

        for entry in entries:
            name = entry.name
            rel_e = f"{rel}/{name}" if rel else name
            try:
                if entry.is_symlink():
                    res.skipped_links += 1
                elif entry.is_dir(follow_symlinks=False):
                    if rules.dir_reason(name, rel_e):
                        res.skipped_dirs[name] += 1
                        low = rel_e.lower()
                        if low in STUB_DIRS or low.endswith(STUB_SUFFIXES):
                            gi = os.path.join(entry.path, ".gitignore")
                            if os.path.isfile(gi):
                                add(gi, rel_e + "/.gitignore")
                    else:
                        stack.append((entry.path, rel_e))
                elif entry.is_file(follow_symlinks=False):
                    if (os.path.normcase(entry.path) in skip_abs
                            or rules.file_reason(name, rel_e)):
                        res.skipped_files += 1
                    else:
                        size = entry.stat(follow_symlinks=False).st_size
                        res.files.append((entry.path, rel_e, size))
                        res.total_bytes += size
            except OSError as exc:
                res.errors.append(f"{rel_e}: {exc.strerror or exc}")

        now = time.monotonic()
        if now - last > 0.08:
            report(("scan", len(res.files), res.skipped_total))
            last = now

    # Files that sit inside an otherwise-skipped folder.
    for keep in KEEP_FILES:
        p = os.path.join(src, *keep.split("/"))
        if os.path.isfile(p):
            try:
                add(p, keep)
            except OSError as exc:
                res.errors.append(f"{keep}: {exc.strerror or exc}")
    return res


def write_zip(res: ScanResult, dest: Path, level: int, root_name: str,
              cancel: threading.Event, report) -> None:
    """Write to <dest>.part and rename on success so a failure never leaves a broken zip."""
    tmp = dest.with_name(dest.name + ".part")
    total_b = max(res.total_bytes, 1)
    n = len(res.files)
    done_b = 0
    last = 0.0
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=level,
                             strict_timestamps=False) as zf:
            for i, (abs_p, rel, size) in enumerate(res.files, 1):
                if cancel.is_set():
                    raise Cancelled
                arc = f"{root_name}/{rel}" if root_name else rel
                ctype = zipfile.ZIP_STORED if rel.lower().endswith(STORED_SUFFIXES) \
                    else zipfile.ZIP_DEFLATED
                try:
                    zf.write(abs_p, arc, compress_type=ctype)
                except OSError as exc:
                    res.errors.append(f"{rel}: {exc.strerror or exc}")
                done_b += size
                now = time.monotonic()
                if now - last > 0.06 or i == n:
                    report(("zip", i, n, done_b, total_b))
                    last = now
        os.replace(tmp, dest)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


# ============================================================
# HELPERS
# ============================================================

def fmt_size(n: float) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def fmt_elapsed(sec: float) -> str:
    if sec < 60:
        return f"{sec:.1f}s"
    m, s = divmod(int(sec), 60)
    return f"{m}m {s:02d}s"


def enable_hidpi():
    if sys.platform.startswith("win"):
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def pick_font(root, candidates, fallback):
    available = set(tkfont.families(root))
    return next((c for c in candidates if c in available), fallback)


# ============================================================
# GUI
# ============================================================

BG = "#1e1e2e"
CARD = "#262637"
MANTLE = "#181825"
BORDER = "#3a3b52"
SURFACE0 = "#313244"
SURFACE1 = "#45475a"
SURFACE2 = "#585b70"
TEXT = "#cdd6f4"
SUBTEXT = "#a6adc8"
MUTED = "#6c7086"
ACCENT = "#89b4fa"
ACCENT_HOVER = "#b4befe"
GREEN = "#a6e3a1"
YELLOW = "#f9e2af"
RED = "#f38ba8"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("800x740")
        self.minsize(700, 640)
        self.configure(bg=BG)

        ui = pick_font(self, ("Segoe UI", "Inter", "Ubuntu", "Noto Sans", "Cantarell",
                              "DejaVu Sans", "Helvetica"), "TkDefaultFont")
        mono = pick_font(self, ("Cascadia Mono", "Consolas", "JetBrains Mono", "Ubuntu Mono",
                                "DejaVu Sans Mono", "Courier New"), "TkFixedFont")
        self.f_ui = (ui, 10)
        self.f_small = (ui, 9)
        self.f_title = (ui, 18, "bold")
        self.f_stat = (ui, 15, "bold")
        self.f_mono = (mono, 9)

        self.q: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None
        self._busy = False
        self._mode = "compress"
        self._t0 = 0.0
        self._res = None
        self._last_zip = None
        self._dest_touched = False

        self.src_var = tk.StringVar()
        self.dest_var = tk.StringVar()
        self.ts_var = tk.BooleanVar(value=True)
        self.wrap_var = tk.BooleanVar(value=True)
        self.env_var = tk.BooleanVar(value=False)
        self.level_var = tk.StringVar(value="Balanced")
        self.extra_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Select a Laravel project folder to begin.")
        self.badge_var = tk.StringVar()
        self.pct_var = tk.StringVar(value="")
        self.stat_vars = {k: tk.StringVar(value="—") for k in ("files", "size", "skipped", "time")}

        self._setup_style()
        self._build_ui()
        self._load_config()
        self.src_var.trace_add("write", self._on_src_change)
        self._on_src_change()

        self.bind("<Escape>", lambda e: self._cancel() if self._busy else None)
        self.bind("<Control-Return>", lambda e: self._start("compress"))
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._poll)

    # ---------- styling ----------
    def _setup_style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass

        s.configure(".", background=BG, foreground=TEXT, font=self.f_ui)
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=CARD)
        s.configure("TLabel", background=BG, foreground=TEXT)
        s.configure("Card.TLabel", background=CARD, foreground=TEXT)
        s.configure("CardTitle.TLabel", background=CARD, foreground=ACCENT, font=(self.f_ui[0], 9, "bold"))
        s.configure("CardSub.TLabel", background=CARD, foreground=SUBTEXT, font=self.f_small)
        s.configure("Title.TLabel", font=self.f_title, foreground=ACCENT)
        s.configure("Sub.TLabel", font=self.f_small, foreground=SUBTEXT)
        s.configure("Stat.TLabel", background=CARD, foreground=TEXT, font=self.f_stat)

        flat = dict(relief="flat", borderwidth=1, padding=(16, 8), focuscolor=SURFACE0)
        s.configure("TButton", background=SURFACE0, foreground=TEXT, bordercolor=SURFACE0,
                    lightcolor=SURFACE0, darkcolor=SURFACE0, **flat)
        s.map("TButton",
              background=[("disabled", CARD), ("pressed", SURFACE2), ("active", SURFACE1)],
              foreground=[("disabled", MUTED)],
              bordercolor=[("disabled", CARD), ("focus", ACCENT)],
              lightcolor=[("disabled", CARD), ("pressed", SURFACE2), ("active", SURFACE1)],
              darkcolor=[("disabled", CARD), ("pressed", SURFACE2), ("active", SURFACE1)])

        s.configure("Accent.TButton", background=ACCENT, foreground=BG, bordercolor=ACCENT,
                    lightcolor=ACCENT, darkcolor=ACCENT, font=(self.f_ui[0], 10, "bold"),
                    **{**flat, "focuscolor": ACCENT})
        s.map("Accent.TButton",
              background=[("disabled", SURFACE0), ("pressed", ACCENT), ("active", ACCENT_HOVER)],
              foreground=[("disabled", MUTED)],
              bordercolor=[("disabled", SURFACE0), ("active", ACCENT_HOVER)],
              lightcolor=[("disabled", SURFACE0), ("active", ACCENT_HOVER)],
              darkcolor=[("disabled", SURFACE0), ("active", ACCENT_HOVER)])

        s.configure("Danger.TButton", foreground=RED)
        s.map("Danger.TButton", foreground=[("disabled", MUTED), ("active", RED)])

        s.configure("TEntry", fieldbackground=SURFACE0, foreground=TEXT, insertcolor=TEXT,
                    bordercolor=BORDER, lightcolor=SURFACE0, darkcolor=SURFACE0, padding=6)
        s.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
              darkcolor=[("focus", ACCENT)])

        s.configure("TCombobox", fieldbackground=SURFACE0, background=SURFACE1, foreground=TEXT,
                    arrowcolor=TEXT, bordercolor=BORDER, lightcolor=SURFACE0, darkcolor=SURFACE0,
                    selectbackground=SURFACE0, selectforeground=TEXT, padding=5)
        s.map("TCombobox", fieldbackground=[("readonly", SURFACE0)],
              foreground=[("readonly", TEXT)], selectbackground=[("readonly", SURFACE0)],
              selectforeground=[("readonly", TEXT)], bordercolor=[("focus", ACCENT)])
        self.option_add("*TCombobox*Listbox.background", SURFACE0)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", BG)

        s.configure("Card.TCheckbutton", background=CARD, foreground=TEXT, focuscolor=CARD)
        s.map("Card.TCheckbutton",
              background=[("active", CARD)],
              indicatorbackground=[("selected", ACCENT), ("!selected", SURFACE0)],
              indicatorforeground=[("selected", BG)],
              upperbordercolor=[("!selected", SURFACE2)], lowerbordercolor=[("!selected", SURFACE2)])

        s.configure("Accent.Horizontal.TProgressbar", background=ACCENT, troughcolor=SURFACE0,
                    bordercolor=SURFACE0, lightcolor=ACCENT, darkcolor=ACCENT, thickness=10)
        s.configure("Vertical.TScrollbar", background=SURFACE1, troughcolor=MANTLE,
                    bordercolor=MANTLE, arrowcolor=SUBTEXT, lightcolor=SURFACE1, darkcolor=SURFACE1)
        s.map("Vertical.TScrollbar", background=[("active", SURFACE2)])

    # ---------- layout ----------
    def _card(self, parent, title=None):
        outer = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        outer.pack(fill="x", pady=(0, 10))
        inner = ttk.Frame(outer, style="Card.TFrame", padding=(16, 12))
        inner.pack(fill="both", expand=True)
        if title:
            ttk.Label(inner, text=title.upper(), style="CardTitle.TLabel").pack(anchor="w", pady=(0, 8))
        body = ttk.Frame(inner, style="Card.TFrame")
        body.pack(fill="x")
        return body

    def _build_ui(self):
        root = ttk.Frame(self, padding=(18, 16, 18, 14))
        root.pack(fill="both", expand=True)

        # Header
        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 12))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Laravel Project Compressor", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Zip your source without vendor, node_modules, caches, logs or Android build output.",
                  style="Sub.TLabel").grid(row=1, column=0, sticky="w")
        self.badge = ttk.Label(header, textvariable=self.badge_var, style="Sub.TLabel")
        self.badge.grid(row=0, column=1, rowspan=2, sticky="e")

        # Source / destination
        body = self._card(root, "Project")
        body.columnconfigure(1, weight=1)
        self._path_row(body, 0, "Project folder", self.src_var, self._browse_src)
        self.dest_entry = self._path_row(body, 1, "Save archive as", self.dest_var, self._browse_dest)
        self.dest_entry.bind("<Key>", lambda e: setattr(self, "_dest_touched", True))

        # Options
        body = self._card(root, "Options")
        body.columnconfigure(3, weight=1)
        checks = ttk.Frame(body, style="Card.TFrame")
        checks.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        for text, var in (("Append timestamp", self.ts_var),
                          ("Wrap in project folder", self.wrap_var),
                          ("Include .env files (secrets!)", self.env_var)):
            ttk.Checkbutton(checks, text=text, variable=var, style="Card.TCheckbutton").pack(side="left", padx=(0, 18))
        ttk.Label(body, text="Compression", style="Card.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 10))
        ttk.Combobox(body, textvariable=self.level_var, values=list(LEVELS), state="readonly",
                     width=12).grid(row=1, column=1, sticky="w", padx=(0, 24))
        ttk.Label(body, text="Extra exclusions", style="Card.TLabel").grid(row=1, column=2, sticky="w", padx=(0, 10))
        ttk.Entry(body, textvariable=self.extra_var).grid(row=1, column=3, sticky="ew")
        ttk.Label(body, text="Comma-separated names or wildcards, e.g.  *.sql, docs, tests/fixtures",
                  style="CardSub.TLabel").grid(row=2, column=2, columnspan=2, sticky="w", pady=(4, 0))

        # Stats
        body = self._card(root)
        for i, (key, caption) in enumerate((("files", "Files"), ("size", "Size"),
                                            ("skipped", "Skipped items"), ("time", "Elapsed"))):
            body.columnconfigure(i, weight=1, uniform="stat")
            tile = ttk.Frame(body, style="Card.TFrame")
            tile.grid(row=0, column=i, sticky="ew")
            ttk.Label(tile, textvariable=self.stat_vars[key], style="Stat.TLabel").pack(anchor="w")
            ttk.Label(tile, text=caption, style="CardSub.TLabel").pack(anchor="w")

        # Actions
        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=(0, 10))
        self.scan_btn = ttk.Button(actions, text="Scan only", command=lambda: self._start("scan"))
        self.scan_btn.pack(side="left")
        self.compress_btn = ttk.Button(actions, text="Compress", style="Accent.TButton",
                                       command=lambda: self._start("compress"))
        self.compress_btn.pack(side="left", padx=8)
        self.cancel_btn = ttk.Button(actions, text="Cancel", style="Danger.TButton",
                                     command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left")
        self.open_btn = ttk.Button(actions, text="Show in folder", command=self._open_last, state="disabled")
        self.open_btn.pack(side="right")

        # Progress
        prog = ttk.Frame(root)
        prog.pack(fill="x")
        prog.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(prog, style="Accent.Horizontal.TProgressbar", mode="determinate",
                                        maximum=100)
        self.progress.grid(row=0, column=0, sticky="ew")
        ttk.Label(prog, textvariable=self.pct_var, style="Sub.TLabel", width=5,
                  anchor="e").grid(row=0, column=1, padx=(8, 0))
        self.status_label = ttk.Label(root, textvariable=self.status_var, style="Sub.TLabel", wraplength=740)
        self.status_label.pack(fill="x", pady=(6, 8))

        # Log
        log_wrap = tk.Frame(root, bg=MANTLE, highlightbackground=BORDER, highlightthickness=1)
        log_wrap.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(log_wrap, orient="vertical")
        sb.pack(side="right", fill="y")
        self.logbox = tk.Text(log_wrap, height=8, bg=MANTLE, fg=TEXT, insertbackground=TEXT, relief="flat",
                              font=self.f_mono, wrap="word", padx=10, pady=8, state="disabled",
                              yscrollcommand=sb.set, borderwidth=0, highlightthickness=0)
        self.logbox.pack(side="left", fill="both", expand=True)
        sb.config(command=self.logbox.yview)
        for tag, color in (("ok", GREEN), ("warn", YELLOW), ("err", RED), ("dim", MUTED), ("head", ACCENT)):
            self.logbox.tag_configure(tag, foreground=color)

    def _path_row(self, body, row, label, var, browse_cmd):
        ttk.Label(body, text=label, style="Card.TLabel", width=15).grid(row=row, column=0, sticky="w", pady=4)
        entry = ttk.Entry(body, textvariable=var)
        entry.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=4)
        ttk.Button(body, text="Browse…", command=browse_cmd).grid(row=row, column=2, pady=4)
        return entry

    # ---------- small UI helpers ----------
    def log(self, msg: str, tag: str = None):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", msg + "\n", *((tag,) if tag else ()))
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _clear_log(self):
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.configure(state="disabled")

    def _set_status(self, text: str, kind: str = "normal"):
        color = {"normal": SUBTEXT, "ok": GREEN, "warn": YELLOW, "err": RED}[kind]
        self.status_var.set(text)
        self.status_label.configure(foreground=color)

    def _set_busy(self, busy: bool):
        self._busy = busy
        idle = "disabled" if busy else "normal"
        self.scan_btn.config(state=idle)
        self.compress_btn.config(state=idle, text="Working…" if busy else "Compress")
        self.cancel_btn.config(state="normal" if busy else "disabled")

    def _stop_indeterminate(self):
        self.progress.stop()
        self.progress.config(mode="determinate")

    # ---------- source / destination ----------
    def _browse_src(self):
        d = filedialog.askdirectory(title="Select Laravel project folder",
                                    initialdir=self.src_var.get() or None)
        if d:
            self.src_var.set(d)

    def _browse_dest(self):
        src = self.src_var.get().strip()
        f = filedialog.asksaveasfilename(
            title="Save archive as", defaultextension=".zip",
            filetypes=[("Zip archive", "*.zip")],
            initialdir=os.path.dirname(self.dest_var.get()) or src or os.getcwd(),
            initialfile=(Path(src).name + ".zip") if src else "laravel_project.zip")
        if f:
            self._dest_touched = True
            self.dest_var.set(f)

    def _on_src_change(self, *_):
        p = self.src_var.get().strip()
        ok = bool(p) and os.path.isdir(p)
        if not ok:
            self.badge_var.set("")
            return
        if not self._dest_touched:
            pth = Path(p)
            self.dest_var.set(str(pth.parent / f"{pth.name or 'laravel_project'}.zip"))
        laravel = os.path.isfile(os.path.join(p, "artisan")) and os.path.isfile(os.path.join(p, "composer.json"))
        self.badge_var.set("● Laravel project detected" if laravel
                           else "● No artisan file found — not a Laravel project?")
        self.badge.configure(foreground=GREEN if laravel else YELLOW)

    def _final_dest(self) -> Path:
        d = Path(self.dest_var.get().strip()).expanduser()
        if d.suffix.lower() != ".zip":
            d = d.with_name(d.name + ".zip")
        if self.ts_var.get():
            d = d.with_name(f"{d.stem}_{datetime.now():%Y%m%d_%H%M%S}{d.suffix}")
        return d

    # ---------- run control ----------
    def _start(self, mode: str):
        if self._busy:
            return
        src = self.src_var.get().strip()
        if not src or not os.path.isdir(src):
            messagebox.showerror("Invalid source", "Please select a valid project folder.")
            return
        src = os.path.abspath(src)

        dest = None
        if mode == "compress":
            if not self.dest_var.get().strip():
                messagebox.showerror("Missing destination", "Please choose where to save the archive.")
                return
            dest = self._final_dest()
            if not dest.parent.is_dir():
                messagebox.showerror("Invalid destination", f"Folder does not exist:\n{dest.parent}")
                return
            if dest.exists() and not messagebox.askyesno("Overwrite?", f"{dest.name} already exists.\nOverwrite it?"):
                return

        if self.env_var.get() and mode == "compress":
            if not messagebox.askyesno(
                    "Include .env files?",
                    "The archive will contain your .env files (database passwords, API keys).\n\n"
                    "Only continue if you will not share this archive.\n\nContinue?"):
                return

        self._mode = mode
        self._res = None
        self.cancel.clear()
        self._clear_log()
        for v in self.stat_vars.values():
            v.set("—")
        self.pct_var.set("")
        self.open_btn.config(state="disabled")
        self._set_busy(True)
        self._set_status("Scanning files…")
        self.progress.config(mode="indeterminate")
        self.progress.start(12)
        self._t0 = time.monotonic()

        root_name = (Path(src).name or "project") if self.wrap_var.get() else ""
        self.worker = threading.Thread(
            target=self._worker,
            args=(mode, src, dest, LEVELS.get(self.level_var.get(), 6), root_name,
                  ExclusionRules(self.env_var.get(), self.extra_var.get())),
            daemon=True)
        self.worker.start()

    def _cancel(self):
        self.cancel.set()
        self._set_status("Cancelling…", "warn")

    def _worker(self, mode, src, dest, level, root_name, rules):
        q = self.q
        try:
            skip = set()
            if dest:
                a = os.path.abspath(dest)
                skip = {os.path.normcase(a), os.path.normcase(a + ".part")}
            res = scan_project(src, rules, self.cancel, q.put, skip)
            q.put(("scan_done", res))
            if mode == "compress":
                if not res.files:
                    q.put(("error", "No files found to compress (everything was excluded?)."))
                    return
                write_zip(res, dest, level, root_name, self.cancel, q.put)
                q.put(("zip_done", str(dest), os.path.getsize(dest)))
        except Cancelled:
            q.put(("cancelled",))
        except Exception as exc:  # noqa: BLE001
            q.put(("error", f"{type(exc).__name__}: {exc}"))
        finally:
            q.put(("finished",))

    # ---------- queue polling ----------
    def _poll(self):
        try:
            while True:
                self._handle(self.q.get_nowait())
        except queue.Empty:
            pass
        if self._busy:
            self.stat_vars["time"].set(fmt_elapsed(time.monotonic() - self._t0))
        self.after(50, self._poll)

    def _handle(self, msg):
        kind = msg[0]
        if kind == "scan":
            _, n, skipped = msg
            self.stat_vars["files"].set(f"{n:,}")
            self.stat_vars["skipped"].set(f"{skipped:,}")
            self._set_status(f"Scanning… {n:,} files found")

        elif kind == "scan_done":
            res = self._res = msg[1]
            self._stop_indeterminate()
            self.stat_vars["files"].set(f"{len(res.files):,}")
            self.stat_vars["size"].set(fmt_size(res.total_bytes))
            self.stat_vars["skipped"].set(f"{res.skipped_total:,}")
            self.log(f"Found {len(res.files):,} files ({fmt_size(res.total_bytes)}) to archive.", "head")
            if res.skipped_dirs:
                top = ", ".join(f"{n} ×{c}" for n, c in res.skipped_dirs.most_common(10))
                self.log(f"Skipped folders: {top}", "dim")
            extra = []
            if res.skipped_files:
                extra.append(f"{res.skipped_files:,} files (logs, caches, binaries, .env…)")
            if res.skipped_links:
                extra.append(f"{res.skipped_links:,} symlinks")
            if extra:
                self.log("Also skipped: " + ", ".join(extra), "dim")
            big = heapq.nlargest(5, res.files, key=lambda f: f[2])
            if big and big[0][2] >= 1024 * 1024:
                self.log("Largest files:", "dim")
                for _, rel, size in big:
                    self.log(f"  {fmt_size(size):>9}  {rel}", "dim")
            if self._mode == "compress":
                self._set_status("Compressing…")

        elif kind == "zip":
            _, i, n, done_b, total_b = msg
            pct = done_b * 100 / total_b
            self.progress["value"] = pct
            self.pct_var.set(f"{pct:.0f}%")
            self._set_status(f"Compressing… {i:,}/{n:,} files · {fmt_size(done_b)} of {fmt_size(total_b)}")

        elif kind == "zip_done":
            _, path, out_size = msg
            res = self._res
            self._last_zip = path
            self.progress["value"] = 100
            self.pct_var.set("100%")
            self.stat_vars["size"].set(f"{fmt_size(res.total_bytes)} → {fmt_size(out_size)}")
            saved = (1 - out_size / res.total_bytes) * 100 if res.total_bytes else 0
            self.log(f"✓ Archive created: {path}", "ok")
            self.log(f"  {len(res.files):,} files · {fmt_size(out_size)} (saved {saved:.0f}%)", "ok")
            self._set_status(f"Done — {fmt_size(out_size)} written to {path}", "ok")
            self.open_btn.config(state="normal")
            self._report_errors(res)

        elif kind == "cancelled":
            self._stop_indeterminate()
            self.progress["value"] = 0
            self.pct_var.set("")
            self.log("Cancelled. No archive was written.", "warn")
            self._set_status("Cancelled.", "warn")

        elif kind == "error":
            self._stop_indeterminate()
            self.log(f"✗ {msg[1]}", "err")
            self._set_status(f"Error: {msg[1]}", "err")

        elif kind == "finished":
            self.stat_vars["time"].set(fmt_elapsed(time.monotonic() - self._t0))
            if self._mode == "scan" and self._res is not None and self.status_label.cget("foreground") != RED:
                self.progress["value"] = 100
                self.pct_var.set("100%")
                self._set_status(f"Scan complete — {len(self._res.files):,} files "
                                 f"({fmt_size(self._res.total_bytes)}) would be archived.", "ok")
                self._report_errors(self._res)
            self._set_busy(False)

    def _report_errors(self, res: ScanResult):
        if not res.errors:
            return
        self.log(f"⚠ {len(res.errors)} item(s) could not be read:", "warn")
        for e in res.errors[:15]:
            self.log(f"  {e}", "warn")
        if len(res.errors) > 15:
            self.log(f"  … and {len(res.errors) - 15} more", "warn")

    # ---------- misc ----------
    def _open_last(self):
        if not self._last_zip:
            return
        path = os.path.abspath(self._last_zip)
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", f"/select,{path}"])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except OSError:
            pass

    def _load_config(self):
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if os.path.isdir(cfg.get("src", "")):
            self.src_var.set(cfg["src"])
        self.ts_var.set(cfg.get("timestamp", True))
        self.wrap_var.set(cfg.get("wrap", True))
        self.env_var.set(cfg.get("env", False))
        if cfg.get("level") in LEVELS:
            self.level_var.set(cfg["level"])
        self.extra_var.set(cfg.get("extra", ""))

    def _save_config(self):
        cfg = {"src": self.src_var.get().strip(), "timestamp": self.ts_var.get(),
               "wrap": self.wrap_var.get(), "env": self.env_var.get(),
               "level": self.level_var.get(), "extra": self.extra_var.get()}
        try:
            CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _on_close(self):
        if self._busy:
            if not messagebox.askyesno("Quit?", "A job is still running. Cancel it and quit?"):
                return
            self.cancel.set()
            if self.worker:
                self.worker.join(timeout=2)
        self._save_config()
        self.destroy()


if __name__ == "__main__":
    enable_hidpi()
    App().mainloop()
