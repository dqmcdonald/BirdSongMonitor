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
from collections import defaultdict
from datetime import datetime, timedelta

def _parse_date(date_str: str) -> str:
    """Accept DD/MM/YYYY or YYYY-MM-DD and return YYYY-MM-DD for SQLite."""
    if not date_str:
        return date_str
    if '/' in date_str:
        parts = date_str.split('/')
        if len(parts) == 3:
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return date_str


def _fmt_date(date_str: str) -> str:
    """Convert YYYY-MM-DD to DD/MM/YYYY for display."""
    if not date_str:
        return date_str
    parts = date_str.split('-')
    if len(parts) == 3:
        return f"{parts[2]}/{parts[1]}/{parts[0]}"
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


def _where(confidence: float, species: str, event: str, dc: str):
    """Return (where_clause_str, params_tuple) for standard detection filters."""
    conds = ["confidence > ?", "common_name != 'DUMMY'"]
    p: tuple = (confidence,)
    if species:
        conds.append("common_name = ?")
        p += (species,)
    if event:
        conds.append("event = ?")
        p += (event,)
    return " AND ".join(conds) + dc, p


def _print_header(label: str, confidence: float, species: str, event: str,
                  date_from: str, date_to: str):
    print()
    print(f"{label} (confidence > {confidence:.2f})")
    if date_from and date_to:
        print(f"Date range: {_fmt_date(date_from)} to {_fmt_date(date_to)}")
    elif date_from:
        print(f"From: {_fmt_date(date_from)}")
    elif date_to:
        print(f"To: {_fmt_date(date_to)}")
    if event:
        print(f"For event: {event}")
    if species:
        print(f"Species: {species}")
    print()


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
                dt = datetime.strptime(str(date), "%Y-%m-%d %H:%M:%S")
                date_display = dt.strftime("%d/%m/%Y %H:%M:%S")
                print(f"  {date_display:<22} {event:<10} {segment:<14} {conf:>6.3f}  {file_name}")
        else:
            print(f"Unknown species: {species}")

def avg_detections(conn, confidence: float, species: str, event: str,
                   date_from: str, date_to: str, monthly: bool = False):
    """Print average detections per day per species, optionally pivoted by month."""
    cur = conn.cursor()
    dc, dp = _date_clause(date_from, date_to)

    conditions = ["confidence > ?", "common_name != 'DUMMY'"]
    params: tuple = (confidence,)
    if species:
        conditions.append("common_name = ?")
        params += (species,)
    if event:
        conditions.append("event = ?")
        params += (event,)
    where = " AND ".join(conditions) + dc
    params += dp

    print()
    print(f"Average detections per day (confidence > {confidence:.2f})")
    if date_from and date_to:
        print(f"Date range: {_fmt_date(date_from)} to {_fmt_date(date_to)}")
    elif date_from:
        print(f"From: {_fmt_date(date_from)}")
    elif date_to:
        print(f"To: {_fmt_date(date_to)}")
    if event:
        print(f"For event: {event}")

    if not monthly:
        rows = cur.execute(f"""
            SELECT common_name,
                   CAST(COUNT(*) AS REAL) / COUNT(DISTINCT DATE(date)) AS avg_per_day,
                   COUNT(DISTINCT DATE(date)) AS obs_days
            FROM detection
            WHERE {where}
            GROUP BY common_name
            ORDER BY avg_per_day DESC
        """, params).fetchall()

        if not rows:
            print("  No data found.")
            return

        print()
        print(f"  {'Species':<35} {'Avg/day':>8}  {'Days':>5}")
        print(f"  {'-'*35} {'-'*8}  {'-'*5}")
        for name, avg, days in rows:
            print(f"  {name:<35} {avg:>8.2f}  {days:>5}")

    else:
        # Monthly pivot: total detections / distinct recording days per month
        rows = cur.execute(f"""
            SELECT common_name,
                   strftime('%Y-%m', date) AS month,
                   CAST(COUNT(*) AS REAL) / COUNT(DISTINCT DATE(date)) AS avg_per_day
            FROM detection
            WHERE {where}
            GROUP BY common_name, strftime('%Y-%m', date)
            ORDER BY common_name, month
        """, params).fetchall()

        if not rows:
            print("  No data found.")
            return

        all_months = sorted({r[1] for r in rows})
        cell: dict[str, dict[str, float]] = {}
        for name, month, avg in rows:
            cell.setdefault(name, {})[month] = avg

        # Sort species by overall mean avg descending
        species_order = sorted(cell.keys(),
                               key=lambda n: -sum(cell[n].values()) / len(cell[n]))

        col_w = 8
        name_w = 35
        print()
        header = f"  {'Species':<{name_w}}" + "".join(f" {m:>{col_w}}" for m in all_months)
        print(header)
        print(f"  {'-'*name_w}" + "".join(f" {'-'*col_w}" for _ in all_months))
        for name in species_order:
            row_str = f"  {name:<{name_w}}"
            for m in all_months:
                val = cell[name].get(m)
                row_str += f" {val:>{col_w}.2f}" if val is not None else f" {'—':>{col_w}}"
            print(row_str)


def first_last_seen(conn, confidence: float, species: str, event: str,
                    date_from: str, date_to: str):
    cur = conn.cursor()
    dc, dp = _date_clause(date_from, date_to)
    where, params = _where(confidence, species, event, dc)
    params += dp

    rows = cur.execute(f"""
        SELECT common_name,
               MIN(DATE(date)) AS first_seen,
               MAX(DATE(date)) AS last_seen,
               COUNT(DISTINCT DATE(date)) AS days
        FROM detection
        WHERE {where}
        GROUP BY common_name
        ORDER BY first_seen
    """, params).fetchall()

    _print_header("First and last detection dates", confidence, species, event, date_from, date_to)
    if not rows:
        print("  No data found.")
        return
    print(f"  {'Species':<35} {'First seen':>12} {'Last seen':>12} {'Days':>5}")
    print(f"  {'-'*35} {'-'*12} {'-'*12} {'-'*5}")
    for name, first, last, days in rows:
        print(f"  {name:<35} {_fmt_date(first):>12} {_fmt_date(last):>12} {days:>5}")


def conf_stats(conn, confidence: float, species: str, event: str,
               date_from: str, date_to: str):
    cur = conn.cursor()
    dc, dp = _date_clause(date_from, date_to)
    where, params = _where(confidence, species, event, dc)
    params += dp

    rows = cur.execute(f"""
        SELECT common_name,
               MIN(confidence), MAX(confidence), AVG(confidence), COUNT(*)
        FROM detection
        WHERE {where}
        GROUP BY common_name
        ORDER BY AVG(confidence) DESC
    """, params).fetchall()

    _print_header("Confidence score summary", confidence, species, event, date_from, date_to)
    if not rows:
        print("  No data found.")
        return
    print(f"  {'Species':<35} {'Min':>6} {'Max':>6} {'Mean':>6} {'Count':>6}")
    print(f"  {'-'*35} {'-'*6} {'-'*6} {'-'*6} {'-'*6}")
    for name, mn, mx, avg, cnt in rows:
        print(f"  {name:<35} {mn:>6.3f} {mx:>6.3f} {avg:>6.3f} {cnt:>6}")


def life_list(conn, confidence: float, species: str, event: str,
              date_from: str, date_to: str):
    cur = conn.cursor()
    dc, dp = _date_clause(date_from, date_to)
    where, params = _where(confidence, species, event, dc)
    params += dp

    rows = cur.execute(f"""
        SELECT common_name,
               MIN(DATE(date)) AS first_date,
               COUNT(DISTINCT DATE(date)) AS obs_days,
               COUNT(*) AS total
        FROM detection
        WHERE {where}
        GROUP BY common_name
        ORDER BY first_date, common_name
    """, params).fetchall()

    _print_header("Species life list", confidence, species, event, date_from, date_to)
    if not rows:
        print("  No data found.")
        return

    by_date: dict = defaultdict(list)
    for name, first_date, obs_days, total in rows:
        by_date[first_date].append((name, obs_days, total))

    print(f"  {'Date':<12} {'Species':<35} {'Days':>5} {'Total':>7}")
    print(f"  {'-'*12} {'-'*35} {'-'*5} {'-'*7}")
    for date in sorted(by_date):
        for name, obs_days, total in by_date[date]:
            rare = " *" if obs_days == 1 else ""
            print(f"  {_fmt_date(date):<12} {name:<35} {obs_days:>5} {total:>7}{rare}")
    print("\n  * = detected on only one day")


def cooccurrence(conn, confidence: float, species: str, event: str,
                 date_from: str, date_to: str, top_n: int = 20):
    cur = conn.cursor()
    # Build date clause with explicit alias to avoid ambiguity in JOINs
    a_dc = ""
    a_dp: tuple = ()
    if date_from:
        a_dc += " AND DATE(a.date) >= ?"
        a_dp += (date_from,)
    if date_to:
        a_dc += " AND DATE(a.date) <= ?"
        a_dp += (date_to,)

    event_clause = "AND a.event = ?" if event else ""
    event_params = (event,) if event else ()

    _print_header("Species co-occurrence (same recording)", confidence, species, event, date_from, date_to)

    if species:
        rows = cur.execute(f"""
            SELECT b.common_name, COUNT(DISTINCT a.file_name) AS shared_files
            FROM detection a
            JOIN detection b
              ON a.file_name = b.file_name AND b.common_name != a.common_name
            WHERE a.common_name = ?
              AND a.confidence > ? AND b.confidence > ?
              AND b.common_name != 'DUMMY'
              {event_clause} {a_dc}
            GROUP BY b.common_name
            ORDER BY shared_files DESC
            LIMIT ?
        """, (species, confidence, confidence) + event_params + a_dp + (top_n,)).fetchall()

        if not rows:
            print("  No data found.")
            return
        print(f"  {'Co-occurring species':<35} {'Shared files':>12}")
        print(f"  {'-'*35} {'-'*12}")
        for name, files in rows:
            print(f"  {name:<35} {files:>12}")
    else:
        rows = cur.execute(f"""
            SELECT a.common_name, b.common_name, COUNT(DISTINCT a.file_name) AS shared_files
            FROM detection a
            JOIN detection b
              ON a.file_name = b.file_name AND a.common_name < b.common_name
            WHERE a.confidence > ? AND b.confidence > ?
              AND a.common_name != 'DUMMY' AND b.common_name != 'DUMMY'
              {event_clause} {a_dc}
            GROUP BY a.common_name, b.common_name
            ORDER BY shared_files DESC
            LIMIT ?
        """, (confidence, confidence) + event_params + a_dp + (top_n,)).fetchall()

        if not rows:
            print("  No data found.")
            return
        print(f"  {'Species A':<35} {'Species B':<35} {'Shared files':>12}")
        print(f"  {'-'*35} {'-'*35} {'-'*12}")
        for name_a, name_b, files in rows:
            print(f"  {name_a:<35} {name_b:<35} {files:>12}")


def detection_streaks(conn, confidence: float, species: str, event: str,
                      date_from: str, date_to: str):
    cur = conn.cursor()
    dc, dp = _date_clause(date_from, date_to)
    where, params = _where(confidence, species, event, dc)
    params += dp

    rows = cur.execute(f"""
        SELECT common_name, DATE(date) AS day
        FROM detection
        WHERE {where}
        GROUP BY common_name, DATE(date)
        ORDER BY common_name, day
    """, params).fetchall()

    _print_header("Detection streaks", confidence, species, event, date_from, date_to)
    if not rows:
        print("  No data found.")
        return

    species_dates: dict = defaultdict(list)
    for name, day in rows:
        species_dates[name].append(datetime.strptime(day, '%Y-%m-%d').date())

    results = []
    for name, dates in species_dates.items():
        dates = sorted(dates)
        if len(dates) == 1:
            results.append((name, 1, 0, 1))
            continue
        max_streak = cur_streak = 1
        max_gap = 0
        for i in range(1, len(dates)):
            gap = (dates[i] - dates[i - 1]).days
            if gap == 1:
                cur_streak += 1
                if cur_streak > max_streak:
                    max_streak = cur_streak
            else:
                cur_streak = 1
                if gap > max_gap:
                    max_gap = gap
        results.append((name, max_streak, max_gap, len(dates)))

    results.sort(key=lambda x: -x[1])

    print(f"  {'Species':<35} {'Max streak':>10} {'Max gap':>8} {'Days':>5}")
    print(f"  {'-'*35} {'-'*10} {'-'*8} {'-'*5}")
    for name, streak, gap, days in results:
        gap_str = str(gap) if gap > 0 else "—"
        print(f"  {name:<35} {streak:>10} {gap_str:>8} {days:>5}")
    print("\n  Max streak = longest consecutive-day run; Max gap = longest gap (days) between detections")


def extract_detections(conn, wav_dir: str, confidence: float, species: str,
                       event: str, date_from: str, date_to: str, out_dir: str = "extracted"):
    dc, dp = _date_clause(date_from, date_to)
    cur = conn.cursor()

    conds = ["confidence > ?", "common_name != 'DUMMY'"]
    params: tuple = (confidence,)
    if species:
        conds.append("common_name = ?")
        params += (species,)
    if event:
        conds.append("event = ?")
        params += (event,)
    where = " AND ".join(conds) + dc
    params += dp

    rows = cur.execute(f"""
        SELECT file_name, common_name, date, start_time, end_time, confidence
        FROM detection
        WHERE {where}
        ORDER BY common_name, date, start_time
    """, params).fetchall()

    if not rows:
        print("No detections to extract.")
        return

    os.makedirs(out_dir, exist_ok=True)
    print(f"\nExtracting {len(rows)} detections to '{out_dir}'...\n")

    extracted = skipped = 0
    for file_name, common_name, date, start_time, end_time, conf in rows:
        wav_path = os.path.join(wav_dir, file_name)
        if not os.path.exists(wav_path):
            print(f"  Skipped (not found): {wav_path}", file=sys.stderr)
            skipped += 1
            continue

        safe_name = common_name.replace(' ', '_').replace('/', '_')
        file_stem = os.path.splitext(file_name)[0]
        out_name = f"{safe_name}_{file_stem}_{int(start_time)}s-{int(end_time)}s.wav"
        out_path = os.path.join(out_dir, out_name)

        try:
            with wave.open(wav_path, 'r') as wf:
                wav_params = wf.getparams()
                rate = wf.getframerate()
                wf.setpos(int(start_time * rate))
                frames = wf.readframes(int(end_time * rate) - int(start_time * rate))
            with wave.open(out_path, 'w') as wf_out:
                wf_out.setparams(wav_params)
                wf_out.writeframes(frames)
            dt = datetime.strptime(str(date), "%Y-%m-%d %H:%M:%S")
            print(f"  {dt.strftime('%d/%m/%Y %H:%M:%S')}  "
                  f"{_fmt_time(start_time)}-{_fmt_time(end_time)}  "
                  f"conf:{conf:.3f}  -> {out_name}")
            extracted += 1
        except Exception as e:
            print(f"  Error extracting {out_name}: {e}", file=sys.stderr)
            skipped += 1

    print(f"\nExtracted {extracted} file(s)" +
          (f" ({skipped} skipped)" if skipped else "") + ".")


def main():
    parser = argparse.ArgumentParser(prog='query_detections',
                    description='List observations in bird monitoring database')
    parser.add_argument('db_name',
        help="Database name")
    parser.add_argument('-a', '--all', action='store_true', 
        help="list all detections in the database")
    parser.add_argument('-c', '--confidence', dest="confidence",
        type=float, default=0.75, help="minimum confidence threshold (default: 0.75)")
    parser.add_argument('-e', '--event', dest="event", 
        default="", help="specific event to list data for", 
        choices=['Sunrise','Sunset','Day'])
    parser.add_argument('-s', '--species', dest="species",
        default="", help="common name of species to list")
    parser.add_argument('--from', dest="date_from", default="",
        metavar="DATE", help="start date inclusive (DD/MM/YYYY)")
    parser.add_argument('--to', dest="date_to", default="",
        metavar="DATE", help="end date inclusive (DD/MM/YYYY)")
    parser.add_argument('-A', '--avg', action='store_true',
        help="show average detections per day per species")
    parser.add_argument('-m', '--monthly', action='store_true',
        help="with --avg, break down averages by month (pivot table)")
    parser.add_argument('--first-last', action='store_true',
        help="show first and last detection date per species")
    parser.add_argument('--conf-stats', action='store_true',
        help="show min/max/mean confidence score per species")
    parser.add_argument('--life-list', action='store_true',
        help="life list: species ordered by date first detected (* = seen on one day only)")
    parser.add_argument('--cooccur', action='store_true',
        help="show top species co-occurrences within the same recording file")
    parser.add_argument('--streaks', action='store_true',
        help="show longest consecutive-day detection streak and longest gap per species")
    parser.add_argument('-p', '--play', action='store_true',
        help="play audio for each detection (requires -s; uses afplay on macOS)")
    parser.add_argument('--extract', action='store_true',
        help="extract matching detections as individual WAV files")
    parser.add_argument('--extract-dir', dest="extract_dir", default="extracted",
        metavar="DIR",
        help="output directory for extracted WAV files (default: extracted/)")
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

    if args.avg:
        avg_detections(conn, args.confidence, species, args.event,
                       date_from, date_to, monthly=args.monthly)

    if args.first_last:
        first_last_seen(conn, args.confidence, species, args.event, date_from, date_to)

    if args.conf_stats:
        conf_stats(conn, args.confidence, species, args.event, date_from, date_to)

    if args.life_list:
        life_list(conn, args.confidence, species, args.event, date_from, date_to)

    if args.cooccur:
        cooccurrence(conn, args.confidence, species, args.event, date_from, date_to)

    if args.streaks:
        detection_streaks(conn, args.confidence, species, args.event, date_from, date_to)

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
                t_start = (rec_start + timedelta(seconds=start_time)).strftime("%d/%m/%Y %H:%M:%S")
                t_end   = (rec_start + timedelta(seconds=end_time)).strftime("%H:%M:%S")
                print(f"  {t_start}–{t_end}  conf:{conf:.3f}")
                play_detection(recordings_dir, file_name, start_time, end_time)
        except KeyboardInterrupt:
            print("\nStopped.")

    if args.extract:
        recordings_dir = args.recordings_dir or os.path.splitext(args.db_name)[0]
        if not os.path.isdir(recordings_dir):
            sys.exit(f"Error: recordings directory not found: {recordings_dir}")
        extract_detections(conn, recordings_dir, args.confidence, species,
                           args.event, date_from, date_to, out_dir=args.extract_dir)


if __name__ == '__main__':
    main()
