# Plot daily bird detection counts from a BirdNET SQLite database.
# Usage: python plot_detections.py <db> [-c CONFIDENCE] [-s SPECIES] [-o output.png]

import sys
import os.path
import sqlite3
import argparse
from io import BytesIO
from datetime import datetime

import requests
from PIL import Image
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.cm as cm


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

    # No local photo — try the MediaWiki pageimages API.
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


def load_daily_counts(db_name: str, confidence: float, species: str, event: str):
    # Query the detection table, grouping rows by calendar day.
    # DATE() strips the time portion from the stored datetime string.
    # Returns (dates, species_counts) where species_counts is an ordered dict
    # mapping species name → list of counts aligned to the dates list.
    conn = sqlite3.connect(db_name)
    cur = conn.cursor()

    event_clause = "AND event = ?" if event != "All" else ""
    event_params = (event,) if event != "All" else ()

    if species:
        # Single-species mode: one entry in the dict.
        res = cur.execute(f"""
            SELECT DATE(date), COUNT(*)
            FROM detection
            WHERE confidence > ? AND common_name = ? {event_clause}
            GROUP BY DATE(date)
            ORDER BY DATE(date)
        """, (confidence, species) + event_params)
        rows = res.fetchall()
        conn.close()
        dates = [datetime.strptime(r[0], "%Y-%m-%d") for r in rows]
        return dates, {species: [r[1] for r in rows]}

    # All-species mode: one entry per species, counts aligned to a shared date list.
    res = cur.execute(f"""
        SELECT DATE(date), common_name, COUNT(*)
        FROM detection
        WHERE confidence > ? AND common_name != 'DUMMY' {event_clause}
        GROUP BY DATE(date), common_name
        ORDER BY DATE(date), common_name
    """, (confidence,) + event_params)
    rows = res.fetchall()
    conn.close()

    if not rows:
        return [], {}

    # Build a complete, sorted list of every date that appears in the data.
    all_date_strs = sorted(set(r[0] for r in rows))
    dates = [datetime.strptime(d, "%Y-%m-%d") for d in all_date_strs]
    date_idx = {d: i for i, d in enumerate(all_date_strs)}

    # Sort species by total count descending so the most common species sits at
    # the bottom of the stacked bar (where it is easiest to read).
    totals: dict[str, int] = {}
    for _, sp, cnt in rows:
        totals[sp] = totals.get(sp, 0) + cnt
    species_order = sorted(totals, key=lambda s: totals[s], reverse=True)

    n = len(dates)
    species_counts: dict[str, list] = {sp: [0] * n for sp in species_order}
    for date_str, sp, cnt in rows:
        species_counts[sp][date_idx[date_str]] = cnt

    return dates, species_counts


def plot(dates: list, species_counts: dict, confidence: float, db_name: str,
         species: str, event: str, img, out_path: str):

    all_species = list(species_counts.keys())
    multi = len(all_species) > 1

    # Wider figure when a legend sits to the right of the chart.
    fig, ax = plt.subplots(figsize=(16 if multi else 12, 6 if multi else 5))

    if multi:
        # Assign a unique colour to each species using tab20 + tab20b (40 total).
        def species_color(i):
            if i < 20:
                return cm.tab20(i)
            return cm.tab20b((i - 20) % 20)

        bottom = [0] * len(dates)
        for i, sp in enumerate(all_species):
            counts = species_counts[sp]
            ax.bar(dates, counts, width=0.8, bottom=bottom,
                   color=species_color(i), label=sp, edgecolor="white", linewidth=0.2)
            bottom = [b + c for b, c in zip(bottom, counts)]

        # Legend outside the chart on the right, two columns for compactness.
        ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0,
                  fontsize=7, ncol=2, frameon=True)
    else:
        ax.bar(dates, species_counts[all_species[0]], width=0.8,
               color="steelblue", edgecolor="white", linewidth=0.4)

    # AutoDateLocator picks sensible tick intervals (days/weeks/months)
    # depending on the total date span of the data.
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate(rotation=45)

    ax.set_xlabel("Date")
    ax.set_ylabel("Detections")
    species_label = f" — {species}" if species else ""
    event_label = f" [{event}]" if event != "All" else ""
    ax.set_title(
        f"Daily detections{species_label}{event_label} — {os.path.basename(db_name)}  "
        f"(confidence > {confidence:.2f})"
    )
    # Draw horizontal grid lines behind the bars for easier reading.
    ax.yaxis.grid(True, linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)

    if img is not None:
        # Place the bird photo as a square inset in the upper-right corner.
        # Coordinates are in axes-fraction units: [left, bottom, width, height].
        ax_img = ax.inset_axes([0.88, 0.55, 0.11, 0.40])
        ax_img.imshow(img)
        ax_img.axis("off")
        # Thin border so the photo stands out against the chart background.
        for spine in ax_img.spines.values():
            spine.set_visible(True)
            spine.set_linewidth(0.8)

    # bbox_inches='tight' ensures the outside legend is included in the saved image.
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved plot to {out_path}")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(
        prog="plot_detections",
        description="Plot daily bird detections from a BirdNET SQLite database",
    )
    parser.add_argument("db_name", help="Path to the SQLite database")
    parser.add_argument(
        "-c", "--confidence",
        dest="confidence",
        type=float,
        default=0.25,
        help="Minimum confidence threshold (default: 0.25)",
    )
    parser.add_argument(
        "-o", "--output",
        dest="output",
        default=None,
        help="Output PNG path (default: <db_name>.png)",
    )
    parser.add_argument(
        "-s", "--species",
        dest="species",
        default="",
        help="Filter by common name (e.g. \"Silvereye\")",
    )
    parser.add_argument(
        "-e", "--event",
        dest="event",
        default="All",
        choices=["All", "Sunrise", "Sunset", "Day"],
        help="Filter by recording event (default: All)",
    )
    args = parser.parse_args()

    if not os.path.exists(args.db_name):
        print(f"Error: database not found: {args.db_name}", file=sys.stderr)
        sys.exit(1)

    # Default output filename matches the database name (ranui.db → ranui.png).
    out_path = args.output or os.path.splitext(args.db_name)[0] + ".png"

    dates, species_counts = load_daily_counts(args.db_name, args.confidence, args.species, args.event)

    if not dates:
        print("No detections found above the confidence threshold.")
        sys.exit(0)

    # Fetch a bird photo only when a single species is being plotted.
    img = fetch_species_image(args.species) if args.species else None

    plot(dates, species_counts, args.confidence, args.db_name, args.species, args.event, img, out_path)


if __name__ == "__main__":
    main()
