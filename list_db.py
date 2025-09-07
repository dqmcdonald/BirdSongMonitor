# A script to list the species and their counts found in the DB. 
# If the -a option is used then all detections are listed

# D. Q. McDonald   August 2025



import sys
import os.path
import sqlite3
import argparse

def open_db( db_name: str):
    # open database and return connection

    conn = sqlite3.connect(db_name)
    return conn


def list_db( conn, list_all :bool, confidence : float, species : str,
    event : str) :
    # Selects all data from the db and lists it


    print()
    print(f"Detected Species with confidence > {confidence:.2f}")
    species_list = []
    cur = conn.cursor()
    if len(event) > 0:
        print(f"For event: {event}")
        res = cur.execute("""
            SELECT DISTINCT common_name, COUNT(IIF((confidence > ? AND
            event==?), 1, NULL)) FROM detection GROUP BY 
            common_name ORDER BY COUNT(common_name) DESC ;""",
            (confidence,event) ) 

    else:
        res = cur.execute("""
            SELECT DISTINCT common_name, COUNT(IIF(confidence > ?, 1, NULL)) FROM
        detection GROUP BY common_name ORDER BY COUNT(common_name) 
        DESC ;""", (confidence,) ) 

    for row in res.fetchall():
        species_list.append((row[0],int(row[1])))

    species_list.sort(key=lambda pair: pair[1],reverse=True)

    for k in range(len(species_list)):
        print(f"    {species_list[k][0]:30s}:{species_list[k][1]:3d}")

    species_set = set(species_list)

    if list_all:
        print()

        print(f"Detections with confidence > {confidence:.2f}")
        cur = conn.cursor()
        res = cur.execute("SELECT * FROM detection WHERE confidence > ?",
            (confidence,))
        for row in res.fetchall():
            print(row)

    if len(species) > 0:

        if species in species_set:

            print()

            print(f"{species} detections with confidence > {confidence:.2f}")
            cur = conn.cursor()
            res = cur.execute("""
            SELECT * FROM detection WHERE (confidence > ? AND common_name =
            ?) ;""", (confidence,species))
            for row in res.fetchall():
                print(row)
        else:
            print(f"Unknown species: {species}")

def main():
    parser = argparse.ArgumentParser(prog='listdb',
                    description='List observations in bird monitoring database')
    parser.add_argument('db_name', 
        help="Database name")
    parser.add_argument('-a', '--all', action='store_true', 
        help="list all detections in the database")
    parser.add_argument('-c', '--confidence', dest="confidence", 
        default=0.25, help="minimum confidence level")
    parser.add_argument('-e', '--event', dest="event", 
        default="", help="specific event to list data for", 
        choices=['Sunrise','Sunset','Noon'])
    parser.add_argument('-s', '--species', dest="species", 
        default="", help="common name of species to list")
    args = parser.parse_args()

    conn = open_db(args.db_name) 


    list_db(conn, args.all, float(args.confidence), args.species, args.event )


if __name__ == '__main__':
    main()
