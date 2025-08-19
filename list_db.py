

DB_NAME = "birdmon.db"

import sys
import os.path
import sqlite3

def open_db():
    # open database and return connection

    conn = sqlite3.connect(DB_NAME)
    return conn


def list_db( conn ) :
    # Selects all data from the db and lists it

    print("Detected Species:")
    cur = conn.cursor()
    res = cur.execute("SELECT DISTINCT common_name, COUNT(common_name) FROM detection GROUP BY common_name;") 
    for row in res.fetchall():
        print(f"{row[0]:30s} :  {row[1]:5d}")

    print()

    print("All data:")
    cur = conn.cursor()
    res = cur.execute("SELECT * FROM detection")
    for row in res.fetchall():
        print(row)
    

def main():
    conn = open_db() 

    list_db(conn)



if __name__ == '__main__':
    main()
