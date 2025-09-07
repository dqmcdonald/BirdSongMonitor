# Process a directory of bird monitor recordings in the directory that's
# the single argument to this script
# Any detections are added to a SQLite DB

# D. Q. McDonald   
# August 2025



LONGITUDE =  172.72602916819974
LATITUDE =  -43.62674558206582

import sys
import os.path
from birdnetlib import Recording
from birdnetlib.analyzer import Analyzer
from datetime import datetime
import sqlite3
import glob

# Load and initialize the BirdNET-Analyzer event.
analyzer = Analyzer()



def create_db(recordings_dir):
    # create database and table if it doesn't already exist
    # return connection

    base_name = os.path.basename(recordings_dir)

    db_name = base_name + ".db"
    db_exists = os.path.exists(db_name)

    conn = sqlite3.connect(db_name)
    if not db_exists:
        cur = conn.cursor()
        cur.execute("CREATE TABLE detection(file_name,event,date,common_name,scientific_name, start_time,end_time, confidence)")

        conn.commit()
    return conn

def extract_date_and_event( filename: str ) -> (datetime,str):
    # parse the date and event (sunrise, noon, sunset) out of the filename
    name = os.path.basename(filename)
    base_name = os.path.splitext(name)[0]
    components = base_name.split('_')
    event = "Sunrise" # defailt
    if len(components) == 5:
        i=0
    else:
        # Event is the first field for newer file formats
        event = components[0]
        if event == "SR":
            event = "Sunrise"
        if event == "SS":
            event = "Sunset"
        if event == "NO":
            event = "Noon"
        i=1
    return (datetime(year=int(components[i]),month=int(components[i+1]),
            day=int(components[i+2]),hour=int(components[i+3]), 
            minute=int(components[i+4])), event )

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

    (dt,event) = extract_date_and_event(filename)

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
            INSERT into detection VALUES(?,?,?,?,?,?,?,?) """,
            (base_name, event,dt, dec["common_name"],dec["scientific_name"],
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


    conn = create_db(sys.argv[1]) 

    print()
    print("Setup done, about to process files")

    proc_recordings(sys.argv[1], conn)



if __name__ == '__main__':
    main()
