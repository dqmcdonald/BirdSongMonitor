"""Process a directory of bird song recordings through BirdNET and store
detections in a SQLite database, then report the detections found,
highlighting the species that are least common in the database.

Usage: proc_recordings.py <directory> [-c CONFIDENCE] [-r REPORT_CONFIDENCE]

D. Q. McDonald — August 2025
"""

import argparse
import glob
import math
import os.path
import sqlite3
import sys
from datetime import datetime

from birdnetlib import Recording
from birdnetlib.analyzer import Analyzer
from tqdm import tqdm

# Recording location: Christchurch, New Zealand
LONGITUDE = 172.72602916819974
LATITUDE = -43.62674558206582

# Module-level so the model is loaded once; initialisation takes several seconds.
analyzer = Analyzer()


def create_db(recordings_dir):
    """Create or open the SQLite database for the given recordings directory."""
    # DB is named after the directory and created in the current working directory.
    # Existence must be checked before sqlite3.connect(), which creates the file.
    base_name = os.path.basename(recordings_dir)

    db_name = base_name + ".db"
    db_exists = os.path.exists(db_name)

    conn = sqlite3.connect(db_name)
    if not db_exists:
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE detection("
            "file_name,event,date,common_name,scientific_name,"
            "start_time,end_time,confidence)"
        )
        conn.commit()
    return conn


def extract_date_and_event(filename: str) -> (datetime, str):
    """Parse the recording datetime and event type from a WAV filename."""
    # Two filename formats are supported:
    #   Old (5 components): YYYY_MM_DD_HH_MM.WAV           — event defaults to Sunrise
    #   New (6 components): EVENT_YYYY_MM_DD_HH_MM.WAV     — SR/SS/NO/DA prefix
    name = os.path.basename(filename)
    base_name = os.path.splitext(name)[0]
    components = base_name.split('_')
    event = "Sunrise"
    if len(components) == 5:
        i = 0
    elif len(components) == 6:
        event = components[0]
        if event == "SR":
            event = "Sunrise"
        if event == "SS":
            event = "Sunset"
        if event == "NO":
            event = "Noon"
        if event == "DA":
            event = "Day"
        i = 1
    else:
        raise ValueError(f"Unexpected filename format: {name} ({len(components)} components)")
    return (datetime(year=int(components[i]), month=int(components[i+1]),
                     day=int(components[i+2]), hour=int(components[i+3]),
                     minute=int(components[i+4])), event)


def load_processed_files(conn) -> set:
    """Return the set of filenames already present in the database."""
    # Load all previously processed filenames in one query so per-file checks
    # are O(1) set lookups rather than individual DB round-trips.
    cur = conn.cursor()
    return {row[0] for row in cur.execute("SELECT DISTINCT file_name FROM detection")}


def process_rec(filename: str, conn, processed: set, confidence: float):
    """Analyze a single WAV file and insert its detections into the database."""
    base_name = os.path.basename(filename)

    try:
        (dt, event) = extract_date_and_event(filename)
    except (ValueError, IndexError) as e:
        tqdm.write(f"   Skipping {base_name}: {e}")
        return

    if base_name in processed:
        return

    try:
        recording = Recording(
            analyzer,
            filename,
            lat=LATITUDE,
            lon=LONGITUDE,
            date=dt,
            min_conf=confidence
        )
        recording.analyze()
    except (OSError, RuntimeError, ValueError) as e:
        tqdm.write(f"   Error analyzing {base_name}: {e}")
        return
    cur = conn.cursor()

    # Sentinel row: marks the file as processed even when BirdNET finds nothing,
    # so it is skipped on the next run without being re-analysed.
    cur.execute("""
    INSERT into detection VALUES(?,?,?,?,?,?,?,?) """,
        (base_name, event, dt, "DUMMY", "DUMMY", 0.0, 0.0, 0.0))
    if recording.detections:
        tqdm.write(f"  {base_name}")
        for dec in recording.detections:
            cur.execute("""
                INSERT into detection VALUES(?,?,?,?,?,?,?,?) """,
                (base_name, event, dt, dec["common_name"], dec["scientific_name"],
                 dec["start_time"], dec["end_time"], dec["confidence"]))
            tqdm.write(
                f"    {dec['common_name']:<20}  "
                f"{dec['start_time']:3.0f} {dec['confidence']:3.2f}"
            )
    conn.commit()


def proc_recordings(directory: str, conn, confidence: float):
    """Process all WAV files in directory and record detections in the database."""
    files = sorted(glob.glob(directory + "/*.WAV") + glob.glob(directory + "/*.wav"))
    processed = load_processed_files(conn)
    for f in tqdm(files, desc="Processing", unit="file"):
        process_rec(f, conn, processed, confidence)


def rare_threshold(counts) -> int:
    """Return the count at or below which a species is considered rare.

    Rare is defined as the bottom quartile of the per-species count
    distribution, so the least common species in the database are always
    flagged.  Returns 0 when there are no counts.
    """
    counts = sorted(counts)
    if not counts:
        return 0
    # Index of the 25th-percentile element (at least the single rarest species).
    k = max(0, math.ceil(0.25 * len(counts)) - 1)
    return counts[k]


def report_detections(conn, report_confidence: float):
    """Print a report of all detections at or above the reporting confidence.

    Species are listed from least to most common across the whole database,
    and those in the bottom quartile of occurrence (the rarest) are highlighted.
    """
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT common_name, COUNT(*) AS cnt FROM detection "
        "WHERE common_name != 'DUMMY' AND confidence >= ? "
        "GROUP BY common_name ORDER BY cnt ASC, common_name ASC",
        (report_confidence,),
    ).fetchall()

    print(f"\nDetection report (confidence >= {report_confidence:.2f})")
    print("=" * 45)

    if not rows:
        print("No detections at or above the reporting confidence.")
        return

    threshold = rare_threshold([cnt for _, cnt in rows])

    print(f"{'Species':<32}{'Count':>7}")
    print("-" * 45)
    for common_name, cnt in rows:
        marker = "*" if cnt <= threshold else " "
        print(f"{marker} {common_name:<30}{cnt:>7}")
    print("-" * 45)
    print("* = least common in the database")


def main():
    """Parse command-line arguments and run the recording processor."""
    parser = argparse.ArgumentParser(
        prog='proc_recordings',
        description=(
            'Process bird song recordings through BirdNET and store '
            'detections in a SQLite database'
        ),
    )
    parser.add_argument('directory', help='Directory of WAV recordings to process')
    parser.add_argument('-c', '--confidence', dest='confidence', type=float,
                        default=0.25,
                        help='Minimum confidence threshold (default: 0.25)')
    parser.add_argument('-r', '--report-confidence', dest='report_confidence',
                        type=float, default=0.7,
                        help='Confidence threshold for the post-run detection '
                             'report (default: 0.7)')
    args = parser.parse_args()

    if not os.path.exists(args.directory):
        sys.exit(f"Error: directory {args.directory} does not exist")

    conn = create_db(args.directory)
    proc_recordings(args.directory, conn, args.confidence)
    report_detections(conn, args.report_confidence)


if __name__ == '__main__':
    main()
