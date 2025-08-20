# A script to list the species and their counts found in the DB. 
# If the -a option is used then all detections are listed

# D. Q. McDonald   August 2025


DB_NAME = "birdmon.db"

import sys
import os.path
import sqlite3
import argparse

def open_db():
    # open database and return connection

    conn = sqlite3.connect(DB_NAME)
    return conn


def list_db( conn, list_all :bool ) :
    # Selects all data from the db and lists it

    print()
    print("Detected Species:")
    cur = conn.cursor()
    res = cur.execute("SELECT DISTINCT common_name, COUNT(common_name) FROM detection GROUP BY common_name ORDER BY COUNT(common_name) DESC;") 
    for row in res.fetchall():
        print(f"    {row[0]:30s}:{row[1]:3d}")

    if list_all:
        print()

        print("All data:")
        cur = conn.cursor()
        res = cur.execute("SELECT * FROM detection")
        for row in res.fetchall():
            print(row)
    

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--all', action='store_true', 
        help="list all detections in the database")
    args = parser.parse_args()

    conn = open_db() 


    list_db(conn, args.all )


if __name__ == '__main__':
    main()
