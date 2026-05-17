"""Tkinter GUI front-end for BirdSong Monitor plots."""

from __future__ import annotations

import argparse
import calendar
import datetime
import os
import sqlite3
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from plot_detections import (
    _parse_date,
    fetch_species_image,
    load_daily_counts,          plot_daily,
    load_heatmap_data,          plot_heatmap,
    load_confidence_data,       plot_confidence,
    load_accumulation_data,     plot_accumulation,
    load_topn_data,             plot_topn,
    load_event_comparison_data, plot_event_comparison,
)

PLOT_TYPES = ["daily", "heatmap", "confidence", "accumulation", "topn", "events"]
TAB_LABELS = ["Daily", "Heatmap", "Confidence", "Accumulation", "Top-N", "Events"]
COLORMAPS  = ["YlOrRd", "viridis", "plasma", "Blues", "Greens", "Oranges", "hot", "cool", "RdYlBu"]

TAB_HELP = {
    "daily":        "Stacked bar chart of detections per day.",
    "heatmap":      "Species × hour-of-day detection heatmap. Uses Top-N and Colormap settings.",
    "confidence":   "Confidence score histograms per species. Uses Top-N setting.",
    "accumulation": "Cumulative unique-species count over time.",
    "topn":         "Horizontal bar chart of the top-N species by total detections.",
    "events":       "Grouped bar chart comparing detections across recording events (Sunrise / Sunset / Day).",
}

# Which appearance controls are relevant for each tab
APPEARANCE_RELEVANT: dict[str, set[str]] = {
    "daily":        {"color"},
    "heatmap":      {"colormap"},
    "confidence":   set(),
    "accumulation": {"color", "linewidth"},
    "topn":         {"color"},
    "events":       set(),
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
            background="#ffffe0", relief=tk.SOLID, borderwidth=1,
            font=("TkSmallCaptionFont",), wraplength=self._WRAP, padx=4, pady=2,
        ).pack()


def _tip(widget: tk.Widget, text: str) -> tk.Widget:
    _Tooltip(widget, text)
    return widget


# ---------------------------------------------------------------------------
# Date picker dialog
# ---------------------------------------------------------------------------

class _DatePickerDialog(tk.Toplevel):
    """Modal calendar dialog.  .result is 'YYYY-MM-DD', '' (cleared), or None (cancelled)."""

    def __init__(self, parent: tk.Tk, initial: str = ""):
        super().__init__(parent)
        self.title("Pick a date")
        self.resizable(False, False)
        self.result: str | None = None
        self.transient(parent)

        today = datetime.date.today()
        try:
            self._selected = datetime.date.fromisoformat(initial) if initial else today
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
                    bg="steelblue" if selected else ("#ddeeff" if d == today else self._cell_default_bg),
                    fg="white" if selected else "black",
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
        self.result = date.strftime("%Y-%m-%d")
        self.destroy()

    def _clear(self):
        self.result = ""
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
        self.db_path    = tk.StringVar(value=args.db_name    if args and args.db_name    else "")
        self.confidence = tk.DoubleVar(value=args.confidence if args                     else 0.75)
        self.event      = tk.StringVar(value=args.event      if args and args.event      else "All")
        self.species    = tk.StringVar(value=args.species    if args and args.species    else "")
        self.date_from  = tk.StringVar()
        self.date_to    = tk.StringVar()
        self.site       = tk.StringVar(value=args.site       if args and args.site       else "")

        # Plot-specific controls
        self.top_n      = tk.IntVar(value=20)
        self.cmap       = tk.StringVar(value="YlOrRd")
        self.plot_color = tk.StringVar(value="steelblue")
        self.linewidth  = tk.DoubleVar(value=1.5)

        self._figs:    dict[str, Figure]             = {}
        self._canvases: dict[str, FigureCanvasTkAgg] = {}

        self._build()
        self._update_controls()
        self._load_species()

        # Re-plot automatically when colormap changes
        self.cmap.trace_add("write", lambda *_: self._plot(silent=True))
        self.db_path.trace_add("write", lambda *_: self._load_species())

        if self.db_path.get():
            self.root.after(100, self._plot)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build(self):
        ctrl = ttk.Frame(self.root, padding=6)
        ctrl.pack(side=tk.TOP, fill=tk.X)
        self._build_controls(ctrl)

        nb_frame = ttk.Frame(self.root)
        nb_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
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
        _tip(ttk.Combobox(
            r1, textvariable=self.event, width=9,
            values=["All", "Sunrise", "Sunset", "Day"], state="readonly",
        ), "Filter detections by recording event type: Sunrise, Sunset, Day, or All.").pack(side=tk.LEFT, padx=2)

        # Row 2 — species, dates, site, top-n, buttons
        r2 = ttk.Frame(parent)
        r2.pack(fill=tk.X, pady=2)

        _tip(ttk.Label(r2, text="Species:"),
             "Filter by species. Select from the list or leave blank for all species.").pack(side=tk.LEFT)
        self._species_combo = _tip(
            ttk.Combobox(r2, textvariable=self.species, width=22, state="readonly"),
            "Filter by species. Select from the list or leave blank for all species.",
        )
        self._species_combo.pack(side=tk.LEFT, padx=(2, 8))

        _tip(ttk.Label(r2, text="From:"),
             "Start date filter, inclusive. Leave blank for no lower bound.").pack(side=tk.LEFT)
        _tip(ttk.Entry(r2, textvariable=self.date_from, width=10),
             "Start date filter (YYYY-MM-DD). Leave blank for no lower bound.").pack(side=tk.LEFT, padx=(2, 1))
        _tip(ttk.Button(r2, text="▾", width=2,
                        command=lambda: self._pick_date(self.date_from)),
             "Open calendar to pick start date.").pack(side=tk.LEFT, padx=(0, 6))

        _tip(ttk.Label(r2, text="To:"),
             "End date filter, inclusive. Leave blank for no upper bound.").pack(side=tk.LEFT)
        _tip(ttk.Entry(r2, textvariable=self.date_to, width=10),
             "End date filter (YYYY-MM-DD). Leave blank for no upper bound.").pack(side=tk.LEFT, padx=(2, 1))
        _tip(ttk.Button(r2, text="▾", width=2,
                        command=lambda: self._pick_date(self.date_to)),
             "Open calendar to pick end date.").pack(side=tk.LEFT, padx=(0, 8))

        _tip(ttk.Label(r2, text="Site:"),
             "Site name shown in plot titles. Defaults to the database filename if left blank.").pack(side=tk.LEFT)
        _tip(ttk.Entry(r2, textvariable=self.site, width=14),
             "Site name shown in plot titles. Defaults to the database filename if left blank.").pack(side=tk.LEFT, padx=(2, 8))

        ttk.Separator(r2, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        _tip(ttk.Label(r2, text="Top-N:"),
             "Number of species to include in heatmap, confidence, top-N, and events plots.").pack(side=tk.LEFT)
        _tip(ttk.Spinbox(r2, from_=1, to=100, textvariable=self.top_n, width=5),
             "Number of species to include in heatmap, confidence, top-N, and events plots.").pack(
            side=tk.LEFT, padx=(2, 12))

        _tip(ttk.Button(r2, text="Plot", command=self._plot),
             "Generate the chart for the active tab using the current settings.").pack(side=tk.LEFT, padx=4)
        _tip(ttk.Button(r2, text="Save…", command=self._save),
             "Save the current plot to a PNG, PDF, or SVG file.").pack(side=tk.LEFT, padx=4)

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
            "Matplotlib colormap used for the heatmap plot.")
        self._cmap_lbl.pack(side=tk.LEFT)
        self._cmap_combo = _tip(
            ttk.Combobox(grp, textvariable=self.cmap, width=10,
                         values=COLORMAPS, state="readonly"),
            "Matplotlib colormap used for the heatmap plot.",
        )
        self._cmap_combo.pack(side=tk.LEFT, padx=2)

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

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Open database",
            filetypes=[("SQLite databases", "*.db"), ("All files", "*.*")],
        )
        if path:
            self.db_path.set(path)
            self._plot()

    def _active_tab(self) -> str:
        return PLOT_TYPES[self._nb.index(self._nb.select())]

    def _load_species(self):
        db = self.db_path.get().strip()
        if not db or not os.path.exists(db):
            self._species_combo["values"] = [""]
            return
        try:
            conn  = sqlite3.connect(db)
            names = [row[0] for row in conn.execute(
                "SELECT DISTINCT common_name FROM detection "
                "WHERE common_name != 'DUMMY' ORDER BY common_name"
            ).fetchall()]
            conn.close()
            self._species_combo["values"] = [""] + names
        except Exception:
            self._species_combo["values"] = [""]

    def _pick_date(self, var: tk.StringVar):
        dlg = _DatePickerDialog(self.root, initial=var.get().strip())
        if dlg.result is not None:
            var.set(dlg.result)
            self._plot(silent=True)

    def _resolve_species(self, db: str) -> str | None:
        return self.species.get().strip()

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

        sp = self._resolve_species(db)
        if sp is None:
            return

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
            if not dates:
                messagebox.showinfo("No data", "No detections found above the confidence threshold.",
                                    parent=self.root)
                return
            img = fetch_species_image(species) if species else None
            plot_daily(dates, counts, conf, label, species, event, img, fig=fig,
                       color=color, date_from=date_from, date_to=date_to)

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
