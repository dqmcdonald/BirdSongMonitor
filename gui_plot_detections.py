"""Tkinter GUI front-end for BirdSong Monitor plots."""

from __future__ import annotations

import argparse
import calendar
import datetime
import os
import sqlite3
import threading
import tkinter as tk
import wave
import webbrowser
from tkinter import ttk, filedialog, messagebox, colorchooser

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from query_detections import play_detection, extract_detections, _expand_clip_window
from upload_to_inaturalist import load_location, upload_observation, extract_clip
from plot_detections import (
    _parse_date,
    fetch_species_image,
    load_daily_counts,          load_missing_dates, plot_daily,
    load_heatmap_data,          plot_heatmap,
    load_confidence_data,       plot_confidence,
    load_accumulation_data,     plot_accumulation,
    load_topn_data,             plot_topn,
    load_event_comparison_data, plot_event_comparison,
    load_cooccurrence_data,     plot_cooccurrence,
)

PLOT_TYPES = ["daily", "heatmap", "confidence", "accumulation", "topn", "events", "cooccurrence"]
TAB_LABELS = ["Daily", "Heatmap", "Confidence", "Accumulation", "Top-N", "Events", "Co-occurrence"]
COLORMAPS  = ["YlOrRd", "viridis", "plasma", "Blues", "Greens", "Oranges", "hot", "cool", "RdYlBu"]
PALETTES   = ["tab10", "tab20", "tab20b", "tab20c", "Set1", "Set2", "Set3", "Paired", "Dark2", "Accent"]
STYLES     = ["default"] + sorted(s for s in plt.style.available if not s.startswith("_"))

TAB_HELP = {
    "daily":        "Stacked bar chart of detections per day. Uses Color (single species) or Colormap (multiple species).",
    "heatmap":      "Species × hour-of-day detection heatmap. Uses Top-N and Colormap settings.",
    "confidence":   "Confidence score histograms per species. Uses Top-N setting.",
    "accumulation": "Cumulative unique-species count over time.",
    "topn":         "Horizontal bar chart of the top-N species by total detections.",
    "events":       "Grouped bar chart comparing detections across recording events (Sunrise / Sunset / Day).",
    "cooccurrence": "Symmetric heatmap of how often species pairs were detected in the same recording file. Diagonal = files where that species appeared. Uses Top-N and Colormap settings.",
}

# Which appearance controls are relevant for each tab
APPEARANCE_RELEVANT: dict[str, set[str]] = {
    "daily":        {"color", "colormap"},
    "heatmap":      {"colormap"},
    "confidence":   set(),
    "accumulation": {"color", "linewidth"},
    "topn":         {"color"},
    "events":       set(),
    "cooccurrence": {"colormap"},
}


# ---------------------------------------------------------------------------
# Tooltip
# ---------------------------------------------------------------------------

class _Tooltip:
    """Show a tooltip label after a short hover delay."""

    _DELAY = 600
    _WRAP  = 260

    def __init__(self, widget: tk.Widget, text: str):
        self._widget = widget
        self._text   = text
        self._job:  str | None = None
        self._win: tk.Toplevel | None = None
        widget.bind("<Enter>",       self._schedule, add="+")
        widget.bind("<Leave>",       self._cancel,   add="+")
        widget.bind("<ButtonPress>", self._cancel,   add="+")

    def _schedule(self, _=None):
        self._cancel()
        self._job = self._widget.after(self._DELAY, self._show)

    def _cancel(self, _=None):
        if self._job:
            self._widget.after_cancel(self._job)
            self._job = None
        if self._win:
            self._win.destroy()
            self._win = None

    def _show(self):
        x = self._widget.winfo_rootx() + 16
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._win = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw, text=self._text, justify=tk.LEFT,
            background="#ffffe0", foreground="black",
            relief=tk.SOLID, borderwidth=1,
            font=("TkSmallCaptionFont",), wraplength=self._WRAP, padx=12, pady=4,
        ).pack()


def _tip(widget: tk.Widget, text: str) -> tk.Widget:
    _Tooltip(widget, text)
    return widget


# ---------------------------------------------------------------------------
# Date picker dialog
# ---------------------------------------------------------------------------

class _DatePickerDialog(tk.Toplevel):
    """Modal calendar dialog.  .result is 'DD/MM/YYYY', '' (cleared), or None (cancelled)."""

    def __init__(self, parent: tk.Tk, initial: str = ""):
        super().__init__(parent)
        self.title("Pick a date")
        self.resizable(False, False)
        self.result: str | None = None
        self.transient(parent)

        today = datetime.date.today()
        try:
            if initial:
                if '/' in initial:
                    self._selected = datetime.datetime.strptime(initial, "%d/%m/%Y").date()
                else:
                    self._selected = datetime.date.fromisoformat(initial)
            else:
                self._selected = today
        except ValueError:
            self._selected = today
        self._year  = self._selected.year
        self._month = self._selected.month

        self._build()
        self.grab_set()
        self.wait_window()

    def _build(self):
        hdr = ttk.Frame(self, padding=(4, 6, 4, 2))
        hdr.pack(fill=tk.X)
        ttk.Button(hdr, text="◀", width=2, command=self._prev_month).pack(side=tk.LEFT)
        self._hdr_lbl = ttk.Label(hdr, anchor=tk.CENTER, width=16)
        self._hdr_lbl.pack(side=tk.LEFT, expand=True)
        ttk.Button(hdr, text="▶", width=2, command=self._next_month).pack(side=tk.RIGHT)

        grid = ttk.Frame(self, padding=(4, 2))
        grid.pack()
        for col, name in enumerate(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]):
            ttk.Label(grid, text=name, width=4, anchor=tk.CENTER,
                      font=("TkDefaultFont", 9, "bold")).grid(row=0, column=col, pady=(0, 2))

        self._cells: list[tk.Label] = []
        for i in range(42):
            cell = tk.Label(grid, width=4, anchor=tk.CENTER,
                            font=("TkDefaultFont", 9), relief=tk.FLAT, padx=2, pady=2)
            cell.grid(row=i // 7 + 1, column=i % 7, padx=1, pady=1)
            self._cells.append(cell)
        self._cell_default_bg = self._cells[0].cget("bg")

        # Detect dark background so text remains readable
        try:
            r, g, b = self._cells[0].winfo_rgb(self._cell_default_bg)
            _dark = (0.299 * r + 0.587 * g + 0.114 * b) / 65535 < 0.5
        except Exception:
            _dark = False
        self._cell_fg    = "white"   if _dark else "black"
        self._today_bg   = "#1a3a5c" if _dark else "#ddeeff"
        self._today_fg   = "white"   if _dark else "black"

        foot = ttk.Frame(self, padding=(4, 2, 4, 6))
        foot.pack(fill=tk.X)
        ttk.Button(foot, text="Clear",  command=self._clear).pack(side=tk.LEFT, padx=2)
        ttk.Button(foot, text="Today",  command=lambda: self._select(datetime.date.today())).pack(side=tk.LEFT, padx=2)
        ttk.Button(foot, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=2)

        self._refresh()

    def _refresh(self):
        today = datetime.date.today()
        self._hdr_lbl.config(
            text=datetime.date(self._year, self._month, 1).strftime("%B %Y"))
        first_wd   = datetime.date(self._year, self._month, 1).weekday()
        days_in    = calendar.monthrange(self._year, self._month)[1]
        for i, cell in enumerate(self._cells):
            day = i - first_wd + 1
            if day < 1 or day > days_in:
                cell.config(text="", bg=self._cell_default_bg, cursor="arrow", relief=tk.FLAT)
                cell.unbind("<Button-1>")
            else:
                d        = datetime.date(self._year, self._month, day)
                selected = (d == self._selected)
                cell.config(
                    text=str(day),
                    bg="steelblue" if selected else (self._today_bg if d == today else self._cell_default_bg),
                    fg="white" if selected else (self._today_fg if d == today else self._cell_fg),
                    cursor="hand2",
                    relief=tk.RAISED if selected else tk.FLAT,
                )
                cell.bind("<Button-1>", lambda _e, dt=d: self._select(dt))

    def _prev_month(self):
        self._month -= 1
        if self._month < 1:
            self._month, self._year = 12, self._year - 1
        self._refresh()

    def _next_month(self):
        self._month += 1
        if self._month > 12:
            self._month, self._year = 1, self._year + 1
        self._refresh()

    def _select(self, date: datetime.date):
        self.result = date.strftime("%d/%m/%Y")
        self.destroy()

    def _clear(self):
        self.result = ""
        self.destroy()


# ---------------------------------------------------------------------------
# iNaturalist upload confirmation dialog
# ---------------------------------------------------------------------------

class _UploadDialog(tk.Toplevel):
    """Confirm iNaturalist upload settings before starting."""

    def __init__(self, parent: tk.Tk, species_list: list[str], has_wav_dir: bool):
        super().__init__(parent)
        self.title("Upload to iNaturalist")
        self.resizable(False, False)
        self.transient(parent)
        self.confirmed    = False
        self.attach_audio = tk.BooleanVar(value=False)
        self.dry_run      = tk.BooleanVar(value=False)
        self._token_var   = tk.StringVar(value=os.environ.get("INATURALIST_TOKEN", ""))

        f = ttk.Frame(self, padding=14)
        f.pack(fill=tk.BOTH, expand=True)

        sp_str = ", ".join(species_list) if len(species_list) <= 3 else f"{len(species_list)} species"
        ttk.Label(f, text="Upload detections to iNaturalist?",
                  font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W)
        ttk.Label(f, text=f"Species: {sp_str}").pack(anchor=tk.W, pady=(6, 0))
        ttk.Label(f, text="One observation will be created per species per day.",
                  foreground="gray").pack(anchor=tk.W, pady=(2, 6))

        tok_f = ttk.Frame(f)
        tok_f.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(tok_f, text="API token:").pack(side=tk.LEFT)
        ttk.Entry(tok_f, textvariable=self._token_var, width=38, show="*").pack(
            side=tk.LEFT, padx=(6, 0))
        _tok_link = tk.Label(f, text="Get your token from iNaturalist",
                             foreground="blue", cursor="hand2")
        _tok_link.pack(anchor=tk.W, pady=(0, 6))
        _tok_link.bind("<Button-1>", lambda _: webbrowser.open(
            "https://www.inaturalist.org/users/api_token"))

        ttk.Checkbutton(
            f, text="Attach audio clip (best detection per observation)",
            variable=self.attach_audio,
            state=tk.NORMAL if has_wav_dir else tk.DISABLED,
        ).pack(anchor=tk.W)
        if not has_wav_dir:
            ttk.Label(f, text="WAV directory not set — audio unavailable.",
                      foreground="gray").pack(anchor=tk.W, padx=(20, 0))

        ttk.Checkbutton(
            f, text="Dry run (preview without uploading)",
            variable=self.dry_run,
        ).pack(anchor=tk.W, pady=(6, 0))

        btn_f = ttk.Frame(f)
        btn_f.pack(fill=tk.X, pady=(14, 0))
        ttk.Button(btn_f, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_f, text="Upload", command=self._ok).pack(side=tk.RIGHT)

        self.grab_set()
        self.wait_window()

    @property
    def token(self) -> str:
        return self._token_var.get().strip()

    def _ok(self):
        if not self.token and not self.dry_run.get():
            import tkinter.messagebox as _mb
            _mb.showerror("No token",
                          "Please paste your iNaturalist API token before uploading.",
                          parent=self)
            return
        self.confirmed = True
        self.destroy()


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class App:
    def __init__(self, root: tk.Tk, args: argparse.Namespace | None = None):
        self.root = root
        self.root.title("BirdSong Monitor")
        self.root.minsize(960, 640)

        # Shared controls
        self.db_path        = tk.StringVar(value=args.db_name    if args and args.db_name    else "")
        self.confidence     = tk.DoubleVar(value=args.confidence if args                     else 0.75)
        self.event          = tk.StringVar(value=args.event      if args and args.event      else "All")
        self._initial_species = args.species if args and args.species else ""
        self.date_from      = tk.StringVar()
        self.date_to        = tk.StringVar()
        self.site           = tk.StringVar(value=args.site       if args and args.site       else "")
        self.recordings_dir = tk.StringVar()

        # Plot-specific controls
        self.top_n      = tk.IntVar(value=20)
        self.cmap       = tk.StringVar(value="YlOrRd")
        self.plot_color = tk.StringVar(value="steelblue")
        self.linewidth  = tk.DoubleVar(value=1.5)
        self.plot_style = tk.StringVar(value="default")

        self._figs:    dict[str, Figure]             = {}
        self._canvases: dict[str, FigureCanvasTkAgg] = {}

        # Playback state
        self._daily_dates: list = []
        self._stop_event   = threading.Event()
        self._play_thread: threading.Thread | None = None

        self._build()
        self._update_controls()
        self._load_species()

        # Re-plot automatically when colormap or style changes
        self.cmap.trace_add("write",       lambda *_: self._plot(silent=True))
        self.plot_style.trace_add("write", lambda *_: self._plot(silent=True))
        self.db_path.trace_add("write", lambda *_: self._on_db_changed())

        if self.db_path.get():
            self.root.after(100, self._plot)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build(self):
        ctrl = ttk.Frame(self.root, padding=6)
        ctrl.pack(side=tk.TOP, fill=tk.X)
        self._build_controls(ctrl)

        # Status bar (pack before notebook so it stays anchored at bottom)
        sb = ttk.Frame(self.root, relief=tk.SUNKEN, padding=(4, 2))
        sb.pack(side=tk.BOTTOM, fill=tk.X)
        self._status_lbl = ttk.Label(sb, text="Click a bar in the Daily chart to play detections.", anchor=tk.W)
        self._status_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._cancel_btn = ttk.Button(sb, text="Cancel", command=self._cancel_playback, state=tk.DISABLED)
        self._cancel_btn.pack(side=tk.RIGHT, padx=(4, 0))

        nb_frame = ttk.Frame(self.root)
        nb_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))
        self._build_notebook(nb_frame)

    def _build_controls(self, parent: ttk.Frame):
        # Row 1 — database, confidence, event
        r1 = ttk.Frame(parent)
        r1.pack(fill=tk.X, pady=2)

        _tip(ttk.Label(r1, text="Database:"),
             "Path to the SQLite detection database.").pack(side=tk.LEFT)
        _tip(ttk.Entry(r1, textvariable=self.db_path, width=34),
             "Path to the SQLite detection database (.db file).").pack(side=tk.LEFT, padx=2)
        _tip(ttk.Button(r1, text="Browse…", command=self._browse),
             "Open a file browser to select the database.").pack(side=tk.LEFT, padx=(0, 12))

        _tip(ttk.Label(r1, text="WAV dir:"),
             "Directory containing the WAV recording files (used for audio playback).").pack(side=tk.LEFT)
        _tip(ttk.Entry(r1, textvariable=self.recordings_dir, width=26),
             "Directory containing WAV files. Auto-derived from database path; override if needed.").pack(
            side=tk.LEFT, padx=2)
        _tip(ttk.Button(r1, text="Browse…", command=self._browse_recordings),
             "Browse for the directory containing WAV recording files.").pack(side=tk.LEFT, padx=(0, 12))

        _tip(ttk.Label(r1, text="Confidence:"),
             "Minimum BirdNET confidence score (0–1). Detections below this value are excluded.").pack(side=tk.LEFT)
        vcmd = (self.root.register(self._validate_conf_key), "%P")
        self._conf_entry = _tip(
            ttk.Entry(r1, width=5, validate="key", validatecommand=vcmd),
            "Minimum BirdNET confidence score (0–1). Press Enter or Tab to apply.",
        )
        self._conf_entry.insert(0, f"{self.confidence.get():.2f}")
        self._conf_entry.bind("<Return>", self._commit_confidence)
        self._conf_entry.bind("<FocusOut>", self._commit_confidence)
        self._conf_entry.pack(side=tk.LEFT, padx=(2, 12))

        _tip(ttk.Label(r1, text="Event:"),
             "Filter detections by recording event type.").pack(side=tk.LEFT)
        self._event_combo = _tip(ttk.Combobox(
            r1, textvariable=self.event, width=9,
            values=["All", "Sunrise", "Sunset", "Day"], state="readonly",
        ), "Filter detections by recording event type: Sunrise, Sunset, Day, or All.")
        self._event_combo.pack(side=tk.LEFT, padx=2)
        self._event_combo.bind("<<ComboboxSelected>>", lambda _: self._plot(silent=True))

        # Row 2 — species listbox (left) + dates/site/top-n/buttons (right)
        r2 = ttk.Frame(parent)
        r2.pack(fill=tk.X, pady=2)

        # Species multi-select listbox
        sp_lf = _tip(ttk.LabelFrame(r2, text="Species", padding=(4, 2)),
                     "Select one or more species to filter plots. "
                     "No selection = all species shown.")
        sp_lf.pack(side=tk.LEFT, padx=(0, 8), anchor=tk.N)

        self._species_search_var = tk.StringVar()
        _sp_search = _tip(ttk.Entry(sp_lf, textvariable=self._species_search_var, width=24),
                          "Type to scroll the species list to the first partial name match.")
        _sp_search.pack(fill=tk.X, pady=(0, 2))
        self._species_search_var.trace_add("write", lambda *_: self._species_scroll_to_match())

        sp_list_frame = ttk.Frame(sp_lf)
        sp_list_frame.pack()
        self._species_listbox = tk.Listbox(
            sp_list_frame, selectmode=tk.MULTIPLE, height=5, width=24,
            exportselection=False, activestyle="none",
        )
        _sp_scroll = ttk.Scrollbar(sp_list_frame, orient=tk.VERTICAL,
                                   command=self._species_listbox.yview)
        self._species_listbox.configure(yscrollcommand=_sp_scroll.set)
        self._species_listbox.pack(side=tk.LEFT, fill=tk.Y)
        _sp_scroll.pack(side=tk.LEFT, fill=tk.Y)
        self._species_listbox.bind("<<ListboxSelect>>", lambda _: self._plot(silent=True))

        sp_btn_frame = ttk.Frame(sp_lf)
        sp_btn_frame.pack(fill=tk.X, pady=(2, 0))
        _tip(ttk.Button(sp_btn_frame, text="All", command=self._species_select_all, width=7),
             "Select all species in the list.").pack(side=tk.LEFT, padx=2)
        _tip(ttk.Button(sp_btn_frame, text="None", command=self._species_select_none, width=7),
             "Deselect all species (shows all species).").pack(side=tk.LEFT, padx=2)

        # Right side: dates, site, top-n, action buttons stacked in two sub-rows
        r2_right = ttk.Frame(r2)
        r2_right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Sub-row a: date pickers
        r2a = ttk.Frame(r2_right)
        r2a.pack(fill=tk.X, pady=1)

        _tip(ttk.Label(r2a, text="From:"),
             "Start date filter, inclusive. Leave blank for no lower bound.").pack(side=tk.LEFT)
        df_entry = _tip(ttk.Entry(r2a, textvariable=self.date_from, width=10),
             "Start date filter (DD/MM/YYYY). Leave blank for no lower bound.")
        df_entry.pack(side=tk.LEFT, padx=(2, 1))
        df_entry.bind("<Return>",   lambda _: self._plot(silent=True))
        df_entry.bind("<FocusOut>", lambda _: self._plot(silent=True))
        _tip(ttk.Button(r2a, text="▾", width=2,
                        command=lambda: self._pick_date(self.date_from)),
             "Open calendar to pick start date.").pack(side=tk.LEFT, padx=(0, 8))

        _tip(ttk.Label(r2a, text="To:"),
             "End date filter, inclusive. Leave blank for no upper bound.").pack(side=tk.LEFT)
        dt_entry = _tip(ttk.Entry(r2a, textvariable=self.date_to, width=10),
             "End date filter (DD/MM/YYYY). Leave blank for no upper bound.")
        dt_entry.pack(side=tk.LEFT, padx=(2, 1))
        dt_entry.bind("<Return>",   lambda _: self._plot(silent=True))
        dt_entry.bind("<FocusOut>", lambda _: self._plot(silent=True))
        _tip(ttk.Button(r2a, text="▾", width=2,
                        command=lambda: self._pick_date(self.date_to)),
             "Open calendar to pick end date.").pack(side=tk.LEFT, padx=(0, 8))

        # Sub-row b: site, top-n, action buttons
        r2b = ttk.Frame(r2_right)
        r2b.pack(fill=tk.X, pady=1)

        _tip(ttk.Label(r2b, text="Site:"),
             "Site name shown in plot titles. Defaults to the database filename if left blank.").pack(side=tk.LEFT)
        site_entry = _tip(ttk.Entry(r2b, textvariable=self.site, width=14),
             "Site name shown in plot titles. Defaults to the database filename if left blank.")
        site_entry.pack(side=tk.LEFT, padx=(2, 8))
        site_entry.bind("<Return>",   lambda _: self._plot(silent=True))
        site_entry.bind("<FocusOut>", lambda _: self._plot(silent=True))

        ttk.Separator(r2b, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        _tip(ttk.Label(r2b, text="Top-N:"),
             "Number of species to include in heatmap, confidence, top-N, and events plots.").pack(side=tk.LEFT)
        _tip(ttk.Spinbox(r2b, from_=1, to=100, textvariable=self.top_n, width=5),
             "Number of species to include in heatmap, confidence, top-N, and events plots.").pack(
            side=tk.LEFT, padx=(2, 12))

        _tip(ttk.Button(r2b, text="Plot", command=self._plot),
             "Generate the chart for the active tab using the current settings.").pack(side=tk.LEFT, padx=4)
        _tip(ttk.Button(r2b, text="Save…", command=self._save),
             "Save the current plot to a PNG, PDF, or SVG file.").pack(side=tk.LEFT, padx=4)
        _tip(ttk.Button(r2b, text="Extract…", command=self._extract),
             "Extract detections shown in the current graph as individual WAV clips.").pack(side=tk.LEFT, padx=4)
        _tip(ttk.Button(r2b, text="iNaturalist…", command=self._upload_inaturalist),
             "Upload detections for the selected species to iNaturalist (one observation per day).").pack(side=tk.LEFT, padx=4)

        # Row 3 — appearance group
        grp = ttk.LabelFrame(parent, text="Appearance", padding=(6, 2))
        grp.pack(fill=tk.X, pady=(4, 2))

        self._color_lbl = _tip(ttk.Label(grp, text="Color:"),
            "Bar/line colour for single-species daily, accumulation, and top-N plots.")
        self._color_lbl.pack(side=tk.LEFT)
        self._color_btn = _tip(
            tk.Canvas(grp, width=24, height=24, highlightthickness=1,
                      highlightbackground="gray", cursor="hand2"),
            "Click to choose the bar/line colour for single-species daily, accumulation, and top-N plots.",
        )
        self._color_swatch = self._color_btn.create_rectangle(
            2, 2, 22, 22, fill=self.plot_color.get(), outline="")
        self._color_btn.bind("<Button-1>", lambda e: self._pick_color()
                             if self._color_btn["cursor"] == "hand2" else None)
        self._color_btn.pack(side=tk.LEFT, padx=(2, 12))

        self._lw_lbl = _tip(ttk.Label(grp, text="Line width:"),
            "Line width for the accumulation step plot.")
        self._lw_lbl.pack(side=tk.LEFT)
        self._lw_spin = _tip(
            ttk.Spinbox(grp, from_=0.5, to=10.0, increment=0.5,
                        textvariable=self.linewidth, width=5, format="%.1f"),
            "Line width for the accumulation step plot.",
        )
        self._lw_spin.pack(side=tk.LEFT, padx=(2, 12))
        self._lw_spin.bind("<<Increment>>",  lambda _: self._plot(silent=True))
        self._lw_spin.bind("<<Decrement>>",  lambda _: self._plot(silent=True))
        self._lw_spin.bind("<Return>",       lambda _: self._plot(silent=True))
        self._lw_spin.bind("<FocusOut>",     lambda _: self._plot(silent=True))

        self._cmap_lbl = _tip(ttk.Label(grp, text="Colormap:"),
            "Matplotlib colormap used for multi-species daily bars and the heatmap.")
        self._cmap_lbl.pack(side=tk.LEFT)
        self._cmap_combo = _tip(
            ttk.Combobox(grp, textvariable=self.cmap, width=10,
                         values=COLORMAPS, state="readonly"),
            "Matplotlib colormap used for multi-species daily bars and the heatmap.",
        )
        self._cmap_combo.pack(side=tk.LEFT, padx=(2, 12))

        _tip(ttk.Label(grp, text="Style:"),
             "Matplotlib style sheet applied to all plots.").pack(side=tk.LEFT)
        _tip(
            ttk.Combobox(grp, textvariable=self.plot_style, width=18,
                         values=STYLES, state="readonly"),
            "Matplotlib style sheet applied to all plots.",
        ).pack(side=tk.LEFT, padx=2)

    def _build_notebook(self, parent: ttk.Frame):
        self._nb = ttk.Notebook(parent)
        self._nb.pack(fill=tk.BOTH, expand=True)
        self._nb.bind("<<NotebookTabChanged>>", self._on_tab_change)

        for plot_type, label in zip(PLOT_TYPES, TAB_LABELS):
            tab = ttk.Frame(self._nb)
            self._nb.add(tab, text=label)
            _tip(tab, TAB_HELP[plot_type])

            fig = Figure(figsize=(10, 6))
            canvas = FigureCanvasTkAgg(fig, master=tab)
            toolbar = NavigationToolbar2Tk(canvas, tab)
            toolbar.update()
            canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

            self._figs[plot_type]    = fig
            self._canvases[plot_type] = canvas

            if plot_type == "daily":
                canvas.mpl_connect("button_press_event", self._on_daily_click)

    # ------------------------------------------------------------------
    # Control state
    # ------------------------------------------------------------------

    def _on_tab_change(self, _=None):
        self._update_controls()
        self._plot(silent=True)

    def _update_controls(self):
        tab      = self._active_tab()
        relevant = APPEARANCE_RELEVANT[tab]

        def _state(name):
            return tk.NORMAL if name in relevant else tk.DISABLED

        def _cstate(name):
            return "readonly" if name in relevant else tk.DISABLED

        self._color_lbl.config(state=_state("color"))
        self._color_btn.config(cursor="hand2" if _state("color") == tk.NORMAL else "")
        self._lw_lbl.config(state=_state("linewidth"))
        self._lw_spin.config(state=_state("linewidth"))
        self._cmap_lbl.config(state=_state("colormap"))
        self._cmap_combo.config(state=_cstate("colormap"))

        # Swap combobox options and label between qualitative palettes (daily)
        # and sequential colormaps (heatmap).
        if tab == "daily":
            self._cmap_combo.config(values=PALETTES)
            self._cmap_lbl.config(text="Palette:")
            if self.cmap.get() not in PALETTES:
                self.cmap.set(PALETTES[0])
        else:
            self._cmap_combo.config(values=COLORMAPS)
            self._cmap_lbl.config(text="Colormap:")
            if self.cmap.get() not in COLORMAPS:
                self.cmap.set(COLORMAPS[0])

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _validate_conf_key(self, value):
        """Allow only partial numeric input while typing (e.g. "0.", "0.2")."""
        if value == "":
            return True
        try:
            float(value)
            return True
        except ValueError:
            return value in (".", "-")

    def _commit_confidence(self, event=None):
        try:
            v = float(self._conf_entry.get())
        except ValueError:
            self._conf_entry.delete(0, tk.END)
            self._conf_entry.insert(0, f"{self.confidence.get():.2f}")
            return
        v = max(0.0, min(1.0, v))
        self.confidence.set(v)
        self._conf_entry.delete(0, tk.END)
        self._conf_entry.insert(0, f"{v:.2f}")
        self._plot(silent=True)

    def _pick_color(self):
        _, hex_color = colorchooser.askcolor(
            color=self.plot_color.get(), title="Choose color", parent=self.root)
        if hex_color:
            self.plot_color.set(hex_color)
            self._color_btn.itemconfig(self._color_swatch, fill=hex_color)
            self._plot(silent=True)

    def _on_db_changed(self):
        self._load_species()
        db = self.db_path.get().strip()
        if db:
            self.recordings_dir.set(os.path.splitext(db)[0])

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Open database",
            filetypes=[("SQLite databases", "*.db"), ("All files", "*.*")],
        )
        if path:
            self.db_path.set(path)
            self._plot()

    def _browse_recordings(self):
        path = filedialog.askdirectory(title="Select recordings directory", parent=self.root)
        if path:
            self.recordings_dir.set(path)

    def _active_tab(self) -> str:
        return PLOT_TYPES[self._nb.index(self._nb.select())]

    def _load_species(self):
        self._species_listbox.delete(0, tk.END)
        db = self.db_path.get().strip()
        if not db or not os.path.exists(db):
            return
        try:
            conn  = sqlite3.connect(db)
            names = [row[0] for row in conn.execute(
                "SELECT DISTINCT common_name FROM detection "
                "WHERE common_name != 'DUMMY' ORDER BY common_name"
            ).fetchall()]
            conn.close()
            for name in names:
                self._species_listbox.insert(tk.END, name)
            if self._initial_species:
                lower = self._initial_species.lower()
                for i, name in enumerate(names):
                    if name.lower() == lower:
                        self._species_listbox.selection_set(i)
                        self._species_listbox.see(i)
                        self._initial_species = ""
                        break
        except Exception:
            pass

    def _get_selected_species(self) -> list[str]:
        """Return selected species names, or [] meaning 'all species'."""
        indices = self._species_listbox.curselection()
        if not indices:
            return []
        return [self._species_listbox.get(i) for i in indices]

    def _species_scroll_to_match(self):
        query = self._species_search_var.get().lower()
        if not query:
            return
        for i in range(self._species_listbox.size()):
            if query in self._species_listbox.get(i).lower():
                self._species_listbox.see(i)
                self._species_listbox.activate(i)
                return

    def _species_select_all(self):
        self._species_listbox.select_set(0, tk.END)
        self._plot(silent=True)

    def _species_select_none(self):
        self._species_listbox.selection_clear(0, tk.END)
        self._plot(silent=True)

    def _pick_date(self, var: tk.StringVar):
        dlg = _DatePickerDialog(self.root, initial=var.get().strip())
        if dlg.result is not None:
            var.set(dlg.result)
            self._plot(silent=True)

    def _plot(self, silent: bool = False):
        db = self.db_path.get().strip()
        if not db:
            if not silent:
                messagebox.showerror("No database", "Please select a database file first.",
                                     parent=self.root)
            return
        if not os.path.exists(db):
            if not silent:
                messagebox.showerror("Not found", f"Database not found:\n{db}", parent=self.root)
            return

        sp        = self._get_selected_species()
        conf      = round(self.confidence.get(), 3)
        event     = self.event.get()
        date_from = _parse_date(self.date_from.get().strip())
        date_to   = _parse_date(self.date_to.get().strip())
        label     = self.site.get().strip() or os.path.basename(db)
        n         = self.top_n.get()
        cmap      = self.cmap.get()
        color     = self.plot_color.get()
        linewidth = self.linewidth.get()

        plot_type = self._active_tab()
        fig       = self._figs[plot_type]
        fig.clear()

        try:
            with plt.style.context(self.plot_style.get()):
                self._render(plot_type, fig, db, conf, event, sp,
                             date_from, date_to, label, n, cmap, color, linewidth)
        except Exception as exc:
            messagebox.showerror("Plot error", str(exc), parent=self.root)
            return

        self._canvases[plot_type].draw()

    def _render(self, plot_type, fig, db, conf, event, species,
                date_from, date_to, label, n, cmap, color, linewidth):
        if plot_type == "daily":
            dates, counts = load_daily_counts(db, conf, species, event, date_from, date_to)
            self._daily_dates = dates  # used by click-to-play
            if not dates:
                messagebox.showinfo("No data", "No detections found above the confidence threshold.",
                                    parent=self.root)
                return
            missing = load_missing_dates(db, date_from, date_to)
            single_sp = species[0] if isinstance(species, list) and len(species) == 1 else (species if isinstance(species, str) and species else None)
            img = fetch_species_image(single_sp) if single_sp else None
            plot_daily(dates, counts, conf, label, species, event, img, fig=fig,
                       color=color, cmap=cmap, date_from=date_from, date_to=date_to,
                       missing_dates=missing)

        elif plot_type == "heatmap":
            sp_list, hours, matrix = load_heatmap_data(
                db, conf, species, event, n, date_from, date_to)
            plot_heatmap(sp_list, hours, matrix, conf, label, species, event, cmap, fig=fig,
                         date_from=date_from, date_to=date_to)

        elif plot_type == "confidence":
            data = load_confidence_data(db, conf, species, event, n, date_from, date_to)
            plot_confidence(data, conf, label, species, event, fig=fig,
                            date_from=date_from, date_to=date_to)

        elif plot_type == "accumulation":
            dates, counts = load_accumulation_data(
                db, conf, species, event, date_from, date_to)
            plot_accumulation(dates, counts, conf, label, species, event, fig=fig,
                              color=color, linewidth=linewidth,
                              date_from=date_from, date_to=date_to)

        elif plot_type == "topn":
            data = load_topn_data(db, conf, species, event, n, date_from, date_to)
            plot_topn(data, conf, label, species, event, n, fig=fig, color=color,
                      date_from=date_from, date_to=date_to)

        elif plot_type == "events":
            data, top_sp = load_event_comparison_data(db, conf, species, n, date_from, date_to)
            plot_event_comparison(data, top_sp, conf, label, species, fig=fig,
                                  date_from=date_from, date_to=date_to)

        elif plot_type == "cooccurrence":
            row_sp, col_sp, matrix = load_cooccurrence_data(db, conf, species, event, n, date_from, date_to)
            plot_cooccurrence(row_sp, col_sp, matrix, conf, label, species, event, cmap, fig=fig,
                              date_from=date_from, date_to=date_to)

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    def _on_daily_click(self, event):
        if event.inaxes is None or event.xdata is None:
            return
        if not self._daily_dates:
            return

        clicked_dt = mdates.num2date(event.xdata).replace(tzinfo=None)
        nearest = min(self._daily_dates, key=lambda d: abs((d - clicked_dt).total_seconds()))

        # Ignore clicks more than half a day away from any bar
        if abs((nearest - clicked_dt).total_seconds()) > 43200:
            return

        self._start_playback(nearest.strftime("%Y-%m-%d"))

    def _start_playback(self, date_str: str):
        # Stop any in-progress playback first
        self._stop_event.set()
        if self._play_thread and self._play_thread.is_alive():
            self._play_thread.join(timeout=3.0)

        recordings_dir = self.recordings_dir.get().strip()
        if not recordings_dir:
            db = self.db_path.get().strip()
            recordings_dir = os.path.splitext(db)[0]

        if not os.path.isdir(recordings_dir):
            messagebox.showerror(
                "Recordings not found",
                f"WAV directory not found:\n{recordings_dir}\n\n"
                "Set the 'WAV dir' field in the controls.",
                parent=self.root,
            )
            return

        db   = self.db_path.get().strip()
        conf = round(self.confidence.get(), 3)
        sp   = self._get_selected_species()
        ev   = self.event.get()

        conn = sqlite3.connect(db)
        cur  = conn.cursor()
        ec   = "AND event = ?" if ev != "All" else ""
        ep   = (ev,)           if ev != "All" else ()
        if sp:
            placeholders = ",".join("?" * len(sp))
            sc   = f"AND common_name IN ({placeholders})"
            spar = tuple(sp)
        else:
            sc   = "AND common_name != 'DUMMY'"
            spar = ()

        rows = cur.execute(
            f"SELECT file_name, common_name, start_time, end_time, confidence, date "
            f"FROM detection "
            f"WHERE confidence > ? {sc} {ec} AND DATE(date) = ? "
            f"ORDER BY start_time",
            (conf,) + spar + ep + (date_str,),
        ).fetchall()
        conn.close()

        if not rows:
            display_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%Y")
            self._status_lbl.config(text=f"No detections on {display_date}.")
            return

        self._stop_event.clear()
        self._cancel_btn.config(state=tk.NORMAL)
        self._play_thread = threading.Thread(
            target=self._playback_worker,
            args=(rows, recordings_dir, date_str),
            daemon=True,
        )
        self._play_thread.start()

    def _playback_worker(self, rows, recordings_dir: str, date_str: str):
        display_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%Y")
        n = len(rows)
        for i, (file_name, common_name, start_time, end_time, conf, rec_date) in enumerate(rows, 1):
            if self._stop_event.is_set():
                break
            rec_start = datetime.datetime.strptime(str(rec_date), "%Y-%m-%d %H:%M:%S")
            wav_path = os.path.join(recordings_dir, file_name)
            try:
                with wave.open(wav_path, 'r') as _wf:
                    clip_s, clip_e = _expand_clip_window(start_time, end_time,
                                                         _wf.getnframes(), _wf.getframerate())
            except Exception:
                clip_s, clip_e = start_time, end_time
            t_start = (rec_start + datetime.timedelta(seconds=clip_s)).strftime("%H:%M:%S")
            t_end   = (rec_start + datetime.timedelta(seconds=clip_e)).strftime("%H:%M:%S")
            msg = f"Playing {i}/{n}: {common_name}  conf:{conf:.3f}  {display_date} {t_start}–{t_end}"
            self.root.after(0, lambda m=msg: self._status_lbl.config(text=m))
            play_detection(recordings_dir, file_name, start_time, end_time)
        self.root.after(0, self._on_playback_done)

    def _on_playback_done(self):
        self._cancel_btn.config(state=tk.DISABLED)
        self._status_lbl.config(text="Click a bar in the Daily chart to play detections.")

    def _cancel_playback(self):
        self._stop_event.set()
        self._cancel_btn.config(state=tk.DISABLED)
        self._status_lbl.config(text="Playback cancelled.")

    def _upload_inaturalist(self):
        db = self.db_path.get().strip()
        if not db or not os.path.exists(db):
            messagebox.showerror("No database", "Please select a database file first.",
                                 parent=self.root)
            return

        species = self._get_selected_species()
        if not species:
            messagebox.showerror(
                "No species selected",
                "Please select at least one species in the Species list before uploading.",
                parent=self.root,
            )
            return

        recordings_dir = self.recordings_dir.get().strip() or os.path.splitext(db)[0]
        has_wav_dir    = os.path.isdir(recordings_dir)

        dlg = _UploadDialog(self.root, species, has_wav_dir)
        if not dlg.confirmed:
            return

        token        = dlg.token
        attach_audio = dlg.attach_audio.get()
        dry_run      = dlg.dry_run.get()
        conf         = round(self.confidence.get(), 3)
        event        = self.event.get()
        date_from    = _parse_date(self.date_from.get().strip())
        date_to      = _parse_date(self.date_to.get().strip())
        lat, lon, place_name = load_location(db, None, None)

        self._status_lbl.config(text="Dry run — previewing iNaturalist upload…" if dry_run
                                else "Uploading to iNaturalist…")
        threading.Thread(
            target=self._upload_worker,
            args=(db, species, conf, event, date_from, date_to,
                  token, lat, lon, place_name, attach_audio,
                  recordings_dir if attach_audio else "", dry_run),
            daemon=True,
        ).start()

    def _upload_worker(self, db, species_list, conf, event, date_from, date_to,
                       token, lat, lon, place_name, attach_audio, recordings_dir, dry_run):
        ev_clause  = "AND event = ?" if event and event != "All" else ""
        ev_params  = (event,)        if event and event != "All" else ()
        date_clause, date_params = "", ()
        if date_from:
            date_clause += " AND DATE(date) >= ?"
            date_params  += (date_from,)
        if date_to:
            date_clause += " AND DATE(date) <= ?"
            date_params  += (date_to,)

        uploaded = failed = 0
        dry_run_lines: list[str] = []

        for species in species_list:
            conn = sqlite3.connect(db)
            rows = conn.execute(f"""
                SELECT file_name, date, start_time, end_time, confidence, scientific_name, event
                FROM detection
                WHERE confidence > ? AND common_name = ? AND common_name != 'DUMMY'
                {ev_clause} {date_clause}
                ORDER BY date, confidence DESC
            """, (conf, species) + ev_params + date_params).fetchall()
            conn.close()

            by_date: dict[str, list] = {}
            for row in rows:
                by_date.setdefault(str(row[1])[:10], []).append(row)

            for day, day_rows in sorted(by_date.items()):
                file_name, det_date, start_time, end_time, best_conf, sci_name, evt = day_rows[0]
                dt = datetime.datetime.strptime(str(det_date), "%Y-%m-%d %H:%M:%S")

                if dry_run:
                    dry_run_lines.append(
                        f"{day}  {species} ({sci_name})\n"
                        f"  time={dt.strftime('%H:%M:%S')}  event={evt}  "
                        f"conf={best_conf:.3f}  detections={len(day_rows)}\n"
                        f"  lat={lat:.5f}  lon={lon:.5f}  place={place_name!r}\n"
                        + ("  + audio clip would be attached\n" if attach_audio else "")
                    )
                    uploaded += 1
                    continue

                self.root.after(0, lambda sp=species, d=day:
                                self._status_lbl.config(text=f"Uploading {sp} — {d}…"))

                audio_path = None
                if attach_audio and recordings_dir:
                    audio_path = extract_clip(recordings_dir, file_name, start_time, end_time)

                obs_id = upload_observation(
                    token=token, species=species, sci_name=sci_name,
                    observed_on=day, time_str=dt.strftime("%H:%M:%S"),
                    lat=lat, lon=lon, place_name=place_name,
                    confidence=best_conf, n_detections=len(day_rows),
                    event=evt, audio_path=audio_path, dry_run=False,
                )

                if audio_path and os.path.exists(audio_path):
                    os.unlink(audio_path)

                if obs_id:
                    uploaded += 1
                else:
                    failed += 1

        if dry_run:
            summary = f"Dry run: {uploaded} observation(s) would be uploaded.\n\n"
            summary += "\n".join(dry_run_lines)
            self.root.after(0, lambda s=summary: self._show_dry_run_result(s))
            self.root.after(0, lambda n=uploaded: self._status_lbl.config(
                text=f"Dry run complete — {n} observation(s) would be uploaded."))
        else:
            msg = f"Uploaded {uploaded} observation(s) to iNaturalist"
            if failed:
                msg += f" ({failed} failed — check console)"
            self.root.after(0, lambda m=msg: self._status_lbl.config(text=m))

    def _show_dry_run_result(self, text: str):
        win = tk.Toplevel(self.root)
        win.title("Dry Run Preview")
        win.transient(self.root)
        win.geometry("620x420")

        txt = tk.Text(win, wrap=tk.WORD, padx=8, pady=8, font=("TkFixedFont", 10))
        sb  = ttk.Scrollbar(win, orient=tk.VERTICAL, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(fill=tk.BOTH, expand=True)
        txt.insert("1.0", text)
        txt.config(state=tk.DISABLED)

        ttk.Button(win, text="Close", command=win.destroy).pack(pady=6)

    def _save(self):
        plot_type = self._active_tab()
        path = filedialog.asksaveasfilename(
            title="Save plot",
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"), ("SVG", "*.svg")],
            parent=self.root,
        )
        if not path:
            return
        self._figs[plot_type].savefig(path, dpi=150, bbox_inches="tight")
        messagebox.showinfo("Saved", f"Saved to:\n{path}", parent=self.root)

    def _extract(self):
        db = self.db_path.get().strip()
        if not db or not os.path.exists(db):
            messagebox.showerror("No database", "Please select a database file first.",
                                 parent=self.root)
            return

        recordings_dir = self.recordings_dir.get().strip()
        if not recordings_dir:
            recordings_dir = os.path.splitext(db)[0]
        if not os.path.isdir(recordings_dir):
            messagebox.showerror(
                "Recordings not found",
                f"WAV directory not found:\n{recordings_dir}\n\n"
                "Set the 'WAV dir' field in the controls.",
                parent=self.root,
            )
            return

        out_dir = filedialog.askdirectory(
            title="Select output directory for extracted WAV clips",
            parent=self.root,
        )
        if not out_dir:
            return

        sp        = self._get_selected_species()
        conf      = round(self.confidence.get(), 3)
        event     = self.event.get()
        date_from = _parse_date(self.date_from.get().strip())
        date_to   = _parse_date(self.date_to.get().strip())

        self._status_lbl.config(text="Extracting detections…")
        threading.Thread(
            target=self._extract_worker,
            args=(db, recordings_dir, conf, sp, event, date_from, date_to, out_dir),
            daemon=True,
        ).start()

    def _extract_worker(self, db, wav_dir, confidence, species, event,
                        date_from, date_to, out_dir):
        try:
            conn = sqlite3.connect(db)
            ev   = event if event != "All" else ""
            extracted, skipped = extract_detections(
                conn, wav_dir, confidence, species, ev, date_from, date_to, out_dir)
            conn.close()
            msg = f"Extracted {extracted} clip(s) to {out_dir}"
            if skipped:
                msg += f"  ({skipped} skipped — WAV not found)"
            self.root.after(0, lambda m=msg: self._status_lbl.config(text=m))
            if extracted == 0 and skipped == 0:
                self.root.after(0, lambda: messagebox.showinfo(
                    "No detections", "No detections matched the current filters.",
                    parent=self.root))
        except Exception as exc:
            err = str(exc)
            self.root.after(0, lambda: messagebox.showerror(
                "Extract error", err, parent=self.root))
            self.root.after(0, lambda: self._status_lbl.config(text="Extraction failed."))


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="gui_plot_detections",
        description="BirdSong Monitor — interactive plot GUI",
    )
    parser.add_argument("db_name", nargs="?", default=None,
                        help="SQLite database to open on launch")
    parser.add_argument("-c", "--confidence", type=float, default=0.75,
                        metavar="CONF",
                        help="minimum confidence threshold (default: 0.75)")
    parser.add_argument("-e", "--event", default=None,
                        choices=["All", "Sunrise", "Sunset", "Day"],
                        help="recording event filter (default: All)")
    parser.add_argument("-s", "--species", default=None,
                        metavar="NAME",
                        help="species common name filter (partial match supported)")
    parser.add_argument("--site", default=None,
                        metavar="NAME",
                        help="site label shown in plot titles")
    args = parser.parse_args()

    root = tk.Tk()
    App(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
