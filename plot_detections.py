from __future__ import annotations

# Plot bird detection data from a BirdNET SQLite database.
# Usage: python plot_detections.py <db> [options]
#
# --plot choices:
#   daily       stacked bar of detections per day (default)
#   heatmap     species x hour-of-day detection heatmap
#   confidence  confidence score histograms per species
#   accumulation  cumulative unique-species count over time
#   topn        horizontal bar chart of top-N species by total detections
#   events      grouped bar comparing detections across recording events

import sys
import os.path
import sqlite3
import argparse
from io import BytesIO
from datetime import datetime
from itertools import groupby

import numpy as np
import requests
from PIL import Image
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.cm as cm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fetch_species_image(species: str):
    # Return a PIL Image for the species, or None if none can be found.
    # Checks bird_photos/<species>.png first; falls back to Wikipedia.
    local_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "bird_photos",
        species.replace(" ", "_") + ".png",
    )
    if os.path.exists(local_path):
        return Image.open(local_path).convert("RGB")

    headers = {"User-Agent": "BirdSongMonitor/1.0"}
    try:
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "titles": species,
                "prop": "pageimages",
                "pithumbsize": 300,
                "format": "json",
                "redirects": 1,
            },
            headers=headers,
            timeout=10,
        )
        r.raise_for_status()
        pages = r.json()["query"]["pages"]
        img_url = next(iter(pages.values())).get("thumbnail", {}).get("source")
        if not img_url:
            return None
        img_data = requests.get(img_url, headers=headers, timeout=10)
        img_data.raise_for_status()
        return Image.open(BytesIO(img_data.content)).convert("RGB")
    except Exception as e:
        print(f"Warning: could not fetch image for '{species}': {e}", file=sys.stderr)
        return None


def _event_filter(event: str):
    """Return (sql_clause, params_tuple) for an optional event filter."""
    if event != "All":
        return "AND event = ?", (event,)
    return "", ()


def _parse_date(date_str: str) -> str:
    """Accept YYYY-MM-DD or DD-MM-YYYY and return YYYY-MM-DD."""
    if not date_str:
        return date_str
    parts = date_str.split('-')
    if len(parts) == 3 and len(parts[0]) == 2:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return date_str


def _date_filter(date_from: str, date_to: str):
    """Return (sql_clause, params_tuple) for an optional date range filter."""
    clause, params = "", ()
    if date_from:
        clause += " AND DATE(date) >= ?"
        params += (date_from,)
    if date_to:
        clause += " AND DATE(date) <= ?"
        params += (date_to,)
    return clause, params


def _species_filter(species: str):
    """Return (sql_clause, params_tuple) for an optional species filter."""
    if species:
        return "AND common_name = ?", (species,)
    return "AND common_name != 'DUMMY'", ()


def _build_subtitle(event: str, species: str, confidence: float,
                    date_from: str = "", date_to: str = "") -> str:
    parts = [f"confidence > {confidence:.2f}"]
    if event and event != "All":
        parts.append(f"Event: {event}")
    if species:
        parts.append(f"Species: {species}")
    if date_from or date_to:
        parts.append(f"Dates: {date_from or 'start'} to {date_to or 'end'}")
    return "  |  ".join(parts)


def _add_subtitle(ax, subtitle: str) -> None:
    if subtitle:
        ax.text(0.5, 1.0, subtitle, transform=ax.transAxes,
                ha="center", va="bottom", fontsize=9, color="#444444", style="italic",
                clip_on=False)


def resolve_species(db_name: str, pattern: str) -> str:
    """Match pattern case-insensitively against DB species names.

    Returns the resolved name, or the original pattern if nothing matches.
    Prompts the user when more than one species matches.
    """
    conn = sqlite3.connect(db_name)
    all_names = [
        row[0] for row in conn.execute(
            "SELECT DISTINCT common_name FROM detection "
            "WHERE common_name != 'DUMMY' ORDER BY common_name"
        ).fetchall()
    ]
    conn.close()

    lower = pattern.lower()
    matches = [n for n in all_names if lower in n.lower()]

    if not matches:
        return pattern

    if len(matches) == 1:
        return matches[0]

    exact = [m for m in matches if m.lower() == lower]
    if len(exact) == 1:
        return exact[0]

    print(f"\nMultiple species match '{pattern}':")
    for i, name in enumerate(matches, 1):
        print(f"  {i}. {name}")
    while True:
        choice = input(f"Select [1-{len(matches)}] or q to quit: ").strip()
        if choice.lower() == 'q':
            sys.exit("Cancelled.")
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(matches):
                return matches[idx]
        except ValueError:
            pass
        print(f"  Enter a number between 1 and {len(matches)}.")


def _default_out(db_name: str, plot_type: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    stem = os.path.splitext(db_name)[0]
    suffix = "" if plot_type == "daily" else f"_{plot_type}"
    return stem + suffix + ".png"


# ---------------------------------------------------------------------------
# daily — stacked bar of detections per day
# ---------------------------------------------------------------------------

def load_daily_counts(db_name: str, confidence: float, species: str, event: str,
                      date_from: str = "", date_to: str = ""):
    conn = sqlite3.connect(db_name)
    cur = conn.cursor()
    ec, ep = _event_filter(event)
    sc, sp = _species_filter(species)
    dc, dp = _date_filter(date_from, date_to)

    if species:
        res = cur.execute(f"""
            SELECT DATE(date), COUNT(*)
            FROM detection
            WHERE confidence > ? {sc} {ec} {dc}
            GROUP BY DATE(date)
            ORDER BY DATE(date)
        """, (confidence,) + sp + ep + dp)
        rows = res.fetchall()
        conn.close()
        dates = [datetime.strptime(r[0], "%Y-%m-%d") for r in rows]
        return dates, {species: [r[1] for r in rows]}

    res = cur.execute(f"""
        SELECT DATE(date), common_name, COUNT(*)
        FROM detection
        WHERE confidence > ? {sc} {ec} {dc}
        GROUP BY DATE(date), common_name
        ORDER BY DATE(date), common_name
    """, (confidence,) + sp + ep + dp)
    rows = res.fetchall()
    conn.close()

    if not rows:
        return [], {}

    all_date_strs = sorted(set(r[0] for r in rows))
    dates = [datetime.strptime(d, "%Y-%m-%d") for d in all_date_strs]
    date_idx = {d: i for i, d in enumerate(all_date_strs)}

    totals: dict[str, int] = {}
    for _, sp_name, cnt in rows:
        totals[sp_name] = totals.get(sp_name, 0) + cnt
    species_order = sorted(totals, key=lambda s: totals[s], reverse=True)

    n = len(dates)
    species_counts: dict[str, list] = {s: [0] * n for s in species_order}
    for date_str, sp_name, cnt in rows:
        species_counts[sp_name][date_idx[date_str]] = cnt

    return dates, species_counts


def plot_daily(dates, species_counts, confidence, label, species, event, img, out_path=None, *, fig=None, color="steelblue", date_from="", date_to=""):
    all_species = list(species_counts.keys())
    multi = len(all_species) > 1

    if fig is None:
        fig, ax = plt.subplots(figsize=(16 if multi else 12, 6 if multi else 5))
    else:
        ax = fig.add_subplot(1, 1, 1)

    if multi:
        def species_color(i):
            return cm.tab20(i) if i < 20 else cm.tab20b((i - 20) % 20)

        bottom = [0] * len(dates)
        for i, sp in enumerate(all_species):
            counts = species_counts[sp]
            ax.bar(dates, counts, width=0.8, bottom=bottom,
                   color=species_color(i), label=sp, edgecolor="white", linewidth=0.2)
            bottom = [b + c for b, c in zip(bottom, counts)]

        ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0,
                  fontsize=7, ncol=2, frameon=True)
    else:
        ax.bar(dates, species_counts[all_species[0]], width=0.8,
               color=color, edgecolor="white", linewidth=0.4)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate(rotation=45)

    ax.set_xlabel("Date")
    ax.set_ylabel("Detections")
    subtitle = _build_subtitle(event, species, confidence, date_from, date_to)
    ax.set_title(f"Daily detections — {label}", pad=28)
    _add_subtitle(ax, subtitle)
    ax.yaxis.grid(True, linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)

    if img is not None:
        ax_img = ax.inset_axes([0.88, 0.55, 0.11, 0.40])
        ax_img.imshow(img)
        ax_img.axis("off")
        for spine in ax_img.spines.values():
            spine.set_visible(True)
            spine.set_linewidth(0.8)

    if out_path:
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        print(f"Saved plot to {out_path}")
        plt.close(fig)
    return fig


# ---------------------------------------------------------------------------
# heatmap — species × hour-of-day
# ---------------------------------------------------------------------------

def load_heatmap_data(db_name: str, confidence: float, species: str, event: str, n: int,
                      date_from: str = "", date_to: str = ""):
    ec, ep = _event_filter(event)
    sc, sp = _species_filter(species)
    dc, dp = _date_filter(date_from, date_to)
    conn = sqlite3.connect(db_name)
    cur = conn.cursor()

    if not species:
        top = cur.execute(f"""
            SELECT common_name FROM detection
            WHERE confidence > ? {sc} {ec} {dc}
            GROUP BY common_name ORDER BY COUNT(*) DESC LIMIT ?
        """, (confidence,) + sp + ep + dp + (n,)).fetchall()
        top_species = [r[0] for r in top]
    else:
        top_species = [species]

    if not top_species:
        conn.close()
        return [], []

    placeholders = ",".join("?" * len(top_species))
    rows = cur.execute(f"""
        SELECT common_name, CAST(strftime('%H', date) AS INTEGER), COUNT(*)
        FROM detection
        WHERE confidence > ? AND common_name IN ({placeholders}) {ec} {dc}
        GROUP BY common_name, strftime('%H', date)
    """, (confidence,) + tuple(top_species) + ep + dp).fetchall()
    conn.close()

    sp_idx = {sp: i for i, sp in enumerate(top_species)}
    matrix = np.zeros((len(top_species), 24), dtype=int)
    for sp_name, hour, count in rows:
        if sp_name in sp_idx:
            matrix[sp_idx[sp_name], hour] = count

    # Keep only columns (hours) that have at least one detection.
    active_hours = [h for h in range(24) if matrix[:, h].sum() > 0]
    matrix = matrix[:, active_hours]

    return top_species, active_hours, matrix


def plot_heatmap(species_list, hours, matrix, confidence, label, species, event, cmap, out_path=None, *, fig=None, date_from="", date_to=""):
    if not species_list:
        print("No data for heatmap.")
        return

    n_sp = len(species_list)
    n_h = len(hours)
    if fig is None:
        fig, ax = plt.subplots(figsize=(max(6, n_h * 0.6 + 2), max(4, n_sp * 0.35 + 1.5)))
    else:
        ax = fig.add_subplot(1, 1, 1)

    im = ax.imshow(matrix, aspect="auto", cmap=cmap, interpolation="nearest")
    ax.set_yticks(range(n_sp))
    ax.set_yticklabels(species_list, fontsize=8)
    ax.set_xticks(range(n_h))
    ax.set_xticklabels([f"{h:02d}:00" for h in hours],
                       rotation=45, ha="right", fontsize=8)
    ax.set_xlabel("Hour of day")
    fig.colorbar(im, ax=ax, label="Detections")

    subtitle = _build_subtitle(event, species, confidence, date_from, date_to)
    ax.set_title(f"Detection heatmap — {label}", pad=28)
    _add_subtitle(ax, subtitle)
    fig.tight_layout()
    if out_path:
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        print(f"Saved plot to {out_path}")
        plt.close(fig)
    return fig


# ---------------------------------------------------------------------------
# confidence — histogram of confidence scores per species
# ---------------------------------------------------------------------------

def load_confidence_data(db_name: str, confidence: float, species: str, event: str, n: int,
                         date_from: str = "", date_to: str = ""):
    ec, ep = _event_filter(event)
    dc, dp = _date_filter(date_from, date_to)
    conn = sqlite3.connect(db_name)
    cur = conn.cursor()

    if species:
        rows = cur.execute(f"""
            SELECT common_name, confidence FROM detection
            WHERE confidence > ? AND common_name = ? {ec} {dc}
        """, (confidence, species) + ep + dp).fetchall()
    else:
        top = cur.execute(f"""
            SELECT common_name FROM detection
            WHERE confidence > ? AND common_name != 'DUMMY' {ec} {dc}
            GROUP BY common_name ORDER BY COUNT(*) DESC LIMIT ?
        """, (confidence,) + ep + dp + (n,)).fetchall()
        top_species = [r[0] for r in top]

        if not top_species:
            conn.close()
            return {}

        placeholders = ",".join("?" * len(top_species))
        rows = cur.execute(f"""
            SELECT common_name, confidence FROM detection
            WHERE confidence > ? AND common_name IN ({placeholders}) {ec} {dc}
        """, (confidence,) + tuple(top_species) + ep + dp).fetchall()

    conn.close()
    data: dict[str, list] = {}
    for sp_name, conf in rows:
        data.setdefault(sp_name, []).append(conf)
    return data


def plot_confidence(data, confidence, label, species, event, out_path=None, *, fig=None, date_from="", date_to=""):
    if not data:
        print("No confidence data found.")
        return

    species_list = sorted(data, key=lambda s: len(data[s]), reverse=True)
    n = len(species_list)
    cols = min(3, n)
    rows = (n + cols - 1) // cols

    if fig is None:
        fig, axes = plt.subplots(rows, cols, figsize=(cols * 5, rows * 3), squeeze=False)
    else:
        axes = fig.subplots(rows, cols, squeeze=False)

    for idx, sp in enumerate(species_list):
        ax = axes[idx // cols][idx % cols]
        vals = data[sp]
        mean = np.mean(vals)
        std  = np.std(vals)
        ax.hist(vals, bins=20, range=(confidence, 1.0),
                color="steelblue", edgecolor="white", linewidth=0.4)
        ax.axvline(mean, color="crimson", linewidth=1.2, linestyle="--")
        ax.axvspan(max(confidence, mean - std), min(1.0, mean + std),
                   alpha=0.12, color="crimson")
        ax.set_title(sp, fontsize=9)
        ax.set_xlabel("Confidence", fontsize=8)
        ax.set_ylabel("Count", fontsize=8)
        ax.tick_params(labelsize=7)
        ax.text(0.97, 0.95, f"μ={mean:.3f}\nσ={std:.3f}",
                transform=ax.transAxes, fontsize=7,
                ha="right", va="top",
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="crimson", alpha=0.8))

    for idx in range(n, rows * cols):
        axes[idx // cols][idx % cols].set_visible(False)

    subtitle = _build_subtitle(event, species, confidence, date_from, date_to)
    fig.suptitle(f"Confidence distributions — {label}", fontsize=11)
    fig.text(0.5, 0.96, subtitle, ha="center", va="top",
             fontsize=9, color="#444444", style="italic")
    fig.tight_layout(rect=[0, 0, 1, 0.90])
    if out_path:
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        print(f"Saved plot to {out_path}")
        plt.close(fig)
    return fig


# ---------------------------------------------------------------------------
# accumulation — cumulative unique species over time
# ---------------------------------------------------------------------------

def load_accumulation_data(db_name: str, confidence: float, species: str, event: str,
                           date_from: str = "", date_to: str = ""):
    ec, ep = _event_filter(event)
    sc, sp = _species_filter(species)
    dc, dp = _date_filter(date_from, date_to)
    conn = sqlite3.connect(db_name)
    cur = conn.cursor()

    rows = cur.execute(f"""
        SELECT DATE(date), common_name FROM detection
        WHERE confidence > ? {sc} {ec} {dc}
        GROUP BY DATE(date), common_name
        ORDER BY DATE(date)
    """, (confidence,) + sp + ep + dp).fetchall()
    conn.close()

    if not rows:
        return [], []

    seen: set = set()
    dates, counts = [], []
    for date_str, grp in groupby(rows, key=lambda r: r[0]):
        for _, sp_name in grp:
            seen.add(sp_name)
        dates.append(datetime.strptime(date_str, "%Y-%m-%d"))
        counts.append(len(seen))

    return dates, counts


def plot_accumulation(dates, counts, confidence, label, species, event, out_path=None, *, fig=None, color="steelblue", linewidth=1.5, date_from="", date_to=""):
    if not dates:
        print("No accumulation data found.")
        return

    if fig is None:
        fig, ax = plt.subplots(figsize=(12, 5))
    else:
        ax = fig.add_subplot(1, 1, 1)

    ax.step(dates, counts, where="post", color=color, linewidth=linewidth)
    ax.fill_between(dates, counts, step="post", alpha=0.15, color=color)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate(rotation=45)

    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative species")
    ax.yaxis.grid(True, linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)

    subtitle = _build_subtitle(event, species, confidence, date_from, date_to)
    ax.set_title(f"Species accumulation — {label}", pad=28)
    _add_subtitle(ax, subtitle)
    fig.tight_layout()
    if out_path:
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        print(f"Saved plot to {out_path}")
        plt.close(fig)
    return fig


# ---------------------------------------------------------------------------
# topn — horizontal bar chart of top-N species
# ---------------------------------------------------------------------------

def load_topn_data(db_name: str, confidence: float, species: str, event: str, n: int,
                   date_from: str = "", date_to: str = ""):
    ec, ep = _event_filter(event)
    sc, sp = _species_filter(species)
    dc, dp = _date_filter(date_from, date_to)
    conn = sqlite3.connect(db_name)
    cur = conn.cursor()

    rows = cur.execute(f"""
        SELECT common_name, COUNT(*) as total FROM detection
        WHERE confidence > ? {sc} {ec} {dc}
        GROUP BY common_name ORDER BY total DESC LIMIT ?
    """, (confidence,) + sp + ep + dp + (n,)).fetchall()
    conn.close()
    return rows


def plot_topn(data, confidence, label, species, event, n, out_path=None, *, fig=None, color="steelblue", date_from="", date_to=""):
    if not data:
        print("No data for top-N chart.")
        return

    names = [r[0] for r in reversed(data)]
    counts = [r[1] for r in reversed(data)]

    if fig is None:
        fig, ax = plt.subplots(figsize=(10, max(4, len(names) * 0.4 + 1)))
    else:
        ax = fig.add_subplot(1, 1, 1)

    bars = ax.barh(names, counts, color=color, edgecolor="white")

    for bar, count in zip(bars, counts):
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                str(count), va="center", fontsize=8)

    ax.set_xlabel("Total detections")
    ax.xaxis.grid(True, linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", labelsize=8)

    subtitle = _build_subtitle(event, species, confidence, date_from, date_to)
    ax.set_title(f"Top {len(data)} species — {label}", pad=28)
    _add_subtitle(ax, subtitle)
    fig.tight_layout()
    if out_path:
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        print(f"Saved plot to {out_path}")
        plt.close(fig)
    return fig


# ---------------------------------------------------------------------------
# events — grouped bar comparing detections per recording event
# ---------------------------------------------------------------------------

def load_event_comparison_data(db_name: str, confidence: float, species: str, n: int,
                               date_from: str = "", date_to: str = ""):
    sc, sp = _species_filter(species)
    dc, dp = _date_filter(date_from, date_to)
    conn = sqlite3.connect(db_name)
    cur = conn.cursor()

    top = cur.execute(f"""
        SELECT common_name FROM detection
        WHERE confidence > ? {sc} {dc}
        GROUP BY common_name ORDER BY COUNT(*) DESC LIMIT ?
    """, (confidence,) + sp + dp + (n,)).fetchall()
    top_species = [r[0] for r in top]

    if not top_species:
        conn.close()
        return {}, []

    placeholders = ",".join("?" * len(top_species))
    rows = cur.execute(f"""
        SELECT event, common_name, COUNT(*) FROM detection
        WHERE confidence > ? AND common_name IN ({placeholders}) {dc}
        GROUP BY event, common_name ORDER BY event
    """, (confidence,) + tuple(top_species) + dp).fetchall()
    conn.close()

    data: dict[str, dict] = {}
    for evt, sp_name, count in rows:
        data.setdefault(evt, {})[sp_name] = count

    return data, top_species


def plot_event_comparison(data, top_species, confidence, label, species, out_path=None, *, fig=None, date_from="", date_to=""):
    if not data or not top_species:
        print("No event comparison data found.")
        return

    events = sorted(data.keys())
    x = np.arange(len(top_species))
    bar_width = 0.8 / len(events)

    if fig is None:
        fig, ax = plt.subplots(figsize=(max(10, len(top_species) * 0.6 + 2), 6))
    else:
        ax = fig.add_subplot(1, 1, 1)

    for i, evt in enumerate(events):
        counts = [data[evt].get(sp, 0) for sp in top_species]
        offset = (i - len(events) / 2 + 0.5) * bar_width
        ax.bar(x + offset, counts, width=bar_width, label=evt,
               color=cm.tab10(i), edgecolor="white", linewidth=0.3)

    ax.set_xticks(x)
    ax.set_xticklabels(top_species, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Detections")
    ax.yaxis.grid(True, linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)
    ax.legend(title="Event")
    subtitle = _build_subtitle("All", species, confidence, date_from, date_to)
    ax.set_title(f"Detections by event — {label}", pad=28)
    _add_subtitle(ax, subtitle)
    fig.tight_layout()
    if out_path:
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        print(f"Saved plot to {out_path}")
        plt.close(fig)
    return fig


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="plot_detections",
        description="Plot bird detections from a BirdNET SQLite database",
    )
    parser.add_argument("db_name", help="Path to the SQLite database")
    parser.add_argument(
        "--plot",
        dest="plot",
        default="daily",
        choices=["daily", "heatmap", "confidence", "accumulation", "topn", "events"],
        help="Chart type (default: daily)",
    )
    parser.add_argument(
        "-c", "--confidence",
        dest="confidence",
        type=float,
        default=0.75,
        help="Minimum confidence threshold (default: 0.75)",
    )
    parser.add_argument(
        "-e", "--event",
        dest="event",
        default="All",
        choices=["All", "Sunrise", "Sunset", "Day"],
        help="Filter by recording event (default: All; ignored by --plot events)",
    )
    parser.add_argument(
        "-s", "--species",
        dest="species",
        default="",
        help="Filter by common name (e.g. \"Silvereye\")",
    )
    parser.add_argument(
        "-n", "--top-n",
        dest="n",
        type=int,
        default=20,
        help="Number of species for heatmap/topn/confidence/events (default: 20)",
    )
    parser.add_argument(
        "-o", "--output",
        dest="output",
        default=None,
        help="Output PNG path (default: <db_stem>[_<plot>].png)",
    )
    parser.add_argument(
        "--cmap",
        dest="cmap",
        default="YlOrRd",
        help="Matplotlib colormap for heatmap (default: YlOrRd). "
             "Available: " + ", ".join(sorted(matplotlib.colormaps)) + ".",
    )
    parser.add_argument(
        "--site",
        dest="site",
        default=None,
        help="Site name for plot titles (default: database filename)",
    )
    parser.add_argument(
        "--from",
        dest="date_from",
        default="",
        metavar="DATE",
        help="Start date filter inclusive (YYYY-MM-DD or DD-MM-YYYY)",
    )
    parser.add_argument(
        "--to",
        dest="date_to",
        default="",
        metavar="DATE",
        help="End date filter inclusive (YYYY-MM-DD or DD-MM-YYYY)",
    )
    args = parser.parse_args()

    date_from = _parse_date(args.date_from)
    date_to = _parse_date(args.date_to)

    label = args.site if args.site else os.path.basename(args.db_name)

    if not os.path.exists(args.db_name):
        print(f"Error: database not found: {args.db_name}", file=sys.stderr)
        sys.exit(1)

    species = resolve_species(args.db_name, args.species) if args.species else args.species

    out_path = _default_out(args.db_name, args.plot, args.output)

    if args.plot == "daily":
        dates, species_counts = load_daily_counts(
            args.db_name, args.confidence, species, args.event,
            date_from, date_to)
        if not dates:
            print("No detections found above the confidence threshold.")
            sys.exit(0)
        img = fetch_species_image(species) if species else None
        plot_daily(dates, species_counts, args.confidence, label,
                   species, args.event, img, out_path,
                   date_from=date_from, date_to=date_to)

    elif args.plot == "heatmap":
        species_list, hours, matrix = load_heatmap_data(
            args.db_name, args.confidence, species, args.event, args.n,
            date_from, date_to)
        plot_heatmap(species_list, hours, matrix, args.confidence, label,
                     species, args.event, args.cmap, out_path,
                     date_from=date_from, date_to=date_to)

    elif args.plot == "confidence":
        data = load_confidence_data(
            args.db_name, args.confidence, species, args.event, args.n,
            date_from, date_to)
        plot_confidence(data, args.confidence, label,
                        species, args.event, out_path,
                        date_from=date_from, date_to=date_to)

    elif args.plot == "accumulation":
        dates, counts = load_accumulation_data(
            args.db_name, args.confidence, species, args.event,
            date_from, date_to)
        plot_accumulation(dates, counts, args.confidence, label,
                          species, args.event, out_path,
                          date_from=date_from, date_to=date_to)

    elif args.plot == "topn":
        data = load_topn_data(
            args.db_name, args.confidence, species, args.event, args.n,
            date_from, date_to)
        plot_topn(data, args.confidence, label,
                  species, args.event, args.n, out_path,
                  date_from=date_from, date_to=date_to)

    elif args.plot == "events":
        data, top_species = load_event_comparison_data(
            args.db_name, args.confidence, species, args.n,
            date_from, date_to)
        plot_event_comparison(data, top_species, args.confidence, label,
                              species, out_path,
                              date_from=date_from, date_to=date_to)


if __name__ == "__main__":
    main()
