# Process a directory of bird monitor recordings in the directory that's
# the single argument to this script
# Any detections are added to a SQLite DB

# D. Q. McDonald   
# August 2025



LONGITUDE =  172.72602916819974
LATITUDE =  -43.62674558206582
DB_NAME = "birdmon.db"

import sys
import os.path
from birdnetlib import Recording
from birdnetlib.analyzer import Analyzer
from datetime import datetime
import sqlite3
import glob

# Load and initialize the BirdNET-Analyzer models.
analyzer = Analyzer()



def create_db():
    # create database and table if it doesn't already exist
    # return connection
    db_exists = os.path.exists(DB_NAME)

    conn = sqlite3.connect(DB_NAME)
    if not db_exists:
        cur = conn.cursor()
        cur.execute("CREATE TABLE detection(file_name,date,common_name,scientific_name, start_time,end_time, confidence)")

        conn.commit()
    return conn

def extract_date( filename: str ) -> datetime:
    # parse the date out of the filename
    name = os.path.basename(filename)
    base_name = os.path.splitext(name)[0]
    components = base_name.split('_')

    return datetime(year=int(components[0]),month=int(components[1]),
        day=int(components[2]),hour=int(components[3]), 
        minute=int(components[4]))

def file_in_database( filename: str, conn )  -> bool :
    # Returns true if the file is already in the database

    cur = conn.cursor()
    res = cur.execute("SELECT COUNT(*) FROM detection WHERE file_name = ?",
        (filename,))

    total_rows = cur.fetchone()[0]
    file_exists = total_rows > 0
    return file_exists



def process_rec(filename: str, conn ):
    # process the single file given by 'filename' into DB represented by 
    # 'conn'

    dt = extract_date(filename)

    # return if this file is already in the DB:
    base_name = os.path.basename(filename)
    if file_in_database(base_name, conn ):
        print(f"   {base_name} already in database")
        return

    recording = Recording(
        analyzer,
        filename,
        lat=LATITUDE,
        lon=LONGITUDE,
        date=dt,
        min_conf=0.25
    )
    recording.analyze()
    print()
    print(f"  Detections in file: {base_name}")
    cur = conn.cursor()
    for dec in recording.detections:
        cur.execute("""
            INSERT into detection VALUES(?,?,?,?,?,?,?) """,
            (base_name, dt, dec["common_name"],dec["scientific_name"],
             dec["start_time"],dec["end_time"],dec["confidence"]))
        
        print(f"    {dec['common_name']:<20}  {dec['start_time']:3.0f} {dec['confidence']:3.2f}")
    conn.commit()


def proc_recordings(directory: str, conn ):
    # process all the recordings in the given directory

    print()
    print(f"""Processing all files in {directory}/ """)
    for f in glob.glob(directory + "/*"):
        process_rec(f, conn)
    

def main():

    if len(sys.argv) < 2:
        print()
        sys.exit("Error: Specify a directory to process")

    if not os.path.exists(sys.argv[1]):
        print()
        sys.exit(f"Error: directory {sys.argv[1]} does not exist")


    conn = create_db() 

    print()
    print("Setup done, about to process files")

    proc_recordings(sys.argv[1], conn)



if __name__ == '__main__':
    main()
