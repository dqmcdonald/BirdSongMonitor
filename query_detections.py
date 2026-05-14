# A script to list the species and their counts found in the DB. 
# If the -a option is used then all detections are listed

# D. Q. McDonald   August 2025



import sys
import os.path
import sqlite3
import argparse

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


def open_db( db_name: str):
    # open database and return connection

    conn = sqlite3.connect(db_name)
    return conn


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
            def fmt(s):
                return f"{int(s)//60}:{int(s)%60:02d}"

            for file_name, event, date, _, start_time, end_time, conf in rows:
                segment = f"{fmt(start_time)}–{fmt(end_time)}"
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
    args = parser.parse_args()

    if not os.path.exists(args.db_name):
        sys.exit(f"Error: database not found: {args.db_name}")

    conn = open_db(args.db_name)

    list_db(conn, args.all, args.confidence, args.species,
            args.event, _parse_date(args.date_from), _parse_date(args.date_to))


if __name__ == '__main__':
    main()
