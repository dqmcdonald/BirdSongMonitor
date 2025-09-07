# Script to query the bird song detection database

# D.Q. McDonald August 2025



import sys
import os.path
import sqlite3
import argparse

def open_db( db_name: str):
    # open database and return connection

    conn = sqlite3.connect(db_name)
    return conn


def query_db( conn, args ) :
    # Make a query of the database


    return

    

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('db_name', help="Database name")
    parser.add_argument('-a', '--all', action='store_true', 
        help="list all detections in the database")
    args = parser.parse_args()

    conn = open_db(args.db_name) 

    query_db(conn, args)



if __name__ == '__main__':
    main()
