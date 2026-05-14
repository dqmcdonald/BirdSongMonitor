# A script to list the species and their counts found in the DB. 
# If the -a option is used then all detections are listed

# D. Q. McDonald   August 2025



import sys
import os
import os.path
import sqlite3
import argparse
import subprocess
import tempfile
import wave
from datetime import datetime, timedelta

def _parse_date(date_str: str) -> str:
    """Accept YYYY-MM-DD or DD-MM-YYYY and return YYYY-MM-DD."""
    if not date_str:
        return date_str
    parts = date_str.split('-')
    if len(parts) == 3 and len(parts[0]) == 2:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return date_str


def _date_clause(date_from: str, date_to: str):
    clause, params = "", ()
    if date_from:
        clause += " AND DATE(date) >= ?"
        params += (date_from,)
    if date_to:
        clause += " AND DATE(date) <= ?"
        params += (date_to,)
    return clause, params


def _fmt_time(s: float) -> str:
    return f"{int(s)//60}:{int(s)%60:02d}"


def play_detection(wav_dir: str, file_name: str, start_time: float, end_time: float):
    wav_path = os.path.join(wav_dir, file_name)
    if not os.path.exists(wav_path):
        print(f"  Audio file not found: {wav_path}", file=sys.stderr)
        return

    with wave.open(wav_path, 'r') as wf:
        params = wf.getparams()
        rate = wf.getframerate()
        start_frame = int(start_time * rate)
        end_frame = int(end_time * rate)
        wf.setpos(start_frame)
        frames = wf.readframes(end_frame - start_frame)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            tmp_path = tmp.name
        with wave.open(tmp_path, 'w') as wf_out:
            wf_out.setparams(params)
            wf_out.writeframes(frames)
        subprocess.run(['afplay', tmp_path], check=True)
    except FileNotFoundError:
        print("Error: 'afplay' not found (macOS only).", file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"  Playback error: {e}", file=sys.stderr)
    finally:
        if tmp_path:
            os.unlink(tmp_path)


def open_db( db_name: str):
    # open database and return connection

    conn = sqlite3.connect(db_name)
    return conn


def resolve_species(conn: sqlite3.Connection, pattern: str) -> str:
    """Match pattern case-insensitively against DB species names.

    Returns the resolved name, or the original pattern if nothing matches
    (so the caller can still print 'Unknown species').  Prompts the user
    when more than one species matches.
    """
    cur = conn.cursor()
    all_names = [
        row[0] for row in cur.execute(
            "SELECT DISTINCT common_name FROM detection "
            "WHERE common_name != 'DUMMY' ORDER BY common_name"
        ).fetchall()
    ]

    lower = pattern.lower()
    matches = [n for n in all_names if lower in n.lower()]

    if not matches:
        return pattern

    if len(matches) == 1:
        return matches[0]

    # Prefer an exact case-insensitive match to avoid a prompt.
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


def list_db( conn, list_all :bool, confidence : float, species : str,
    event : str, date_from: str = "", date_to: str = "") :
    # Selects all data from the db and lists it


    print()
    print(f"Detected Species with confidence > {confidence:.2f}")
    if date_from and date_to:
        print(f"Date range: {date_from} to {date_to}")
    elif date_from:
        print(f"From: {date_from}")
    elif date_to:
        print(f"To: {date_to}")
    cur = conn.cursor()
    dc, dp = _date_clause(date_from, date_to)

    if len(event) > 0:
        print(f"For event: {event}")
        res = cur.execute(f"""
            SELECT common_name, COUNT(*) FROM detection
            WHERE confidence > ? AND event = ? AND common_name != 'DUMMY' {dc}
            GROUP BY common_name ORDER BY COUNT(*) DESC ;""",
            (confidence, event) + dp)
    else:
        res = cur.execute(f"""
            SELECT common_name, COUNT(*) FROM detection
            WHERE confidence > ? AND common_name != 'DUMMY' {dc}
            GROUP BY common_name ORDER BY COUNT(*) DESC ;""",
            (confidence,) + dp)

    species_list = [(row[0], int(row[1])) for row in res.fetchall()]
    species_set = {s[0] for s in species_list}

    for name, count in species_list:
        print(f"    {name:30s}:{count:3d}")

    if list_all:
        print()
        print(f"Detections with confidence > {confidence:.2f}")
        if len(event) > 0:
            res = cur.execute(
                f"SELECT * FROM detection WHERE confidence > ? AND event = ? {dc}",
                (confidence, event) + dp)
        else:
            res = cur.execute(
                f"SELECT * FROM detection WHERE confidence > ? {dc}",
                (confidence,) + dp)
        for row in res.fetchall():
            print(row)

    if len(species) > 0:

        if species in species_set:

            if len(event) > 0:
                rows = cur.execute(f"""
                    SELECT file_name, event, date, scientific_name,
                           start_time, end_time, confidence
                    FROM detection
                    WHERE confidence > ? AND common_name = ? AND event = ? {dc}
                    ORDER BY date, start_time
                """, (confidence, species, event) + dp).fetchall()
            else:
                rows = cur.execute(f"""
                    SELECT file_name, event, date, scientific_name,
                           start_time, end_time, confidence
                    FROM detection
                    WHERE confidence > ? AND common_name = ? {dc}
                    ORDER BY date, start_time
                """, (confidence, species) + dp).fetchall()

            sci_name = rows[0][3] if rows else ""
            print()
            print(f"{species} ({sci_name}) — {len(rows)} detections "
                  f"with confidence > {confidence:.2f}")
            print()
            print(f"  {'Date/Time':<22} {'Event':<10} {'Segment':<14} {'Conf':>6}  File")
            print(f"  {'-'*22} {'-'*10} {'-'*14} {'-'*6}  {'-'*30}")
            for file_name, event, date, _, start_time, end_time, conf in rows:
                segment = f"{_fmt_time(start_time)}–{_fmt_time(end_time)}"
                print(f"  {str(date):<22} {event:<10} {segment:<14} {conf:>6.3f}  {file_name}")
        else:
            print(f"Unknown species: {species}")

def main():
    parser = argparse.ArgumentParser(prog='query_detections',
                    description='List observations in bird monitoring database')
    parser.add_argument('db_name', 
        help="Database name")
    parser.add_argument('-a', '--all', action='store_true', 
        help="list all detections in the database")
    parser.add_argument('-c', '--confidence', dest="confidence",
        type=float, default=0.25, help="minimum confidence threshold (default: 0.25)")
    parser.add_argument('-e', '--event', dest="event", 
        default="", help="specific event to list data for", 
        choices=['Sunrise','Sunset','Day'])
    parser.add_argument('-s', '--species', dest="species",
        default="", help="common name of species to list")
    parser.add_argument('--from', dest="date_from", default="",
        metavar="DATE", help="start date inclusive (YYYY-MM-DD or DD-MM-YYYY)")
    parser.add_argument('--to', dest="date_to", default="",
        metavar="DATE", help="end date inclusive (YYYY-MM-DD or DD-MM-YYYY)")
    parser.add_argument('-p', '--play', action='store_true',
        help="play audio for each detection (requires -s; uses afplay on macOS)")
    parser.add_argument('--recordings-dir', dest="recordings_dir", default=None,
        metavar="DIR",
        help="directory containing WAV files (default: <db_stem>/)")
    args = parser.parse_args()

    if args.play and not args.species:
        sys.exit("Error: --play requires -s to specify a species")

    if not os.path.exists(args.db_name):
        sys.exit(f"Error: database not found: {args.db_name}")

    date_from = _parse_date(args.date_from)
    date_to   = _parse_date(args.date_to)

    conn = open_db(args.db_name)

    species = resolve_species(conn, args.species) if args.species else args.species

    list_db(conn, args.all, args.confidence, species,
            args.event, date_from, date_to)

    if args.play:
        recordings_dir = args.recordings_dir or os.path.splitext(args.db_name)[0]
        if not os.path.isdir(recordings_dir):
            sys.exit(f"Error: recordings directory not found: {recordings_dir}")

        dc, dp = _date_clause(date_from, date_to)
        cur = conn.cursor()
        if args.event:
            rows = cur.execute(f"""
                SELECT file_name, date, start_time, end_time, confidence
                FROM detection
                WHERE confidence > ? AND common_name = ? AND event = ? {dc}
                ORDER BY date, start_time
            """, (args.confidence, species, args.event) + dp).fetchall()
        else:
            rows = cur.execute(f"""
                SELECT file_name, date, start_time, end_time, confidence
                FROM detection
                WHERE confidence > ? AND common_name = ? {dc}
                ORDER BY date, start_time
            """, (args.confidence, species) + dp).fetchall()

        if not rows:
            sys.exit("No detections to play.")

        print(f"\nPlaying {len(rows)} detections — Ctrl+C to stop.\n")
        try:
            for file_name, date, start_time, end_time, conf in rows:
                rec_start = datetime.strptime(str(date), "%Y-%m-%d %H:%M:%S")
                t_start = (rec_start + timedelta(seconds=start_time)).strftime("%Y-%m-%d %H:%M:%S")
                t_end   = (rec_start + timedelta(seconds=end_time)).strftime("%H:%M:%S")
                print(f"  {t_start}–{t_end}  conf:{conf:.3f}")
                play_detection(recordings_dir, file_name, start_time, end_time)
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == '__main__':
    main()
