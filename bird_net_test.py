

LONGITUDE =  172.72602916819974
LATITUDE =  -43.62674558206582

import sys
from birdnetlib import Recording
from birdnetlib.analyzer import Analyzer
from datetime import datetime
import sqlite3

# Load and initialize the BirdNET-Analyzer models.
analyzer = Analyzer()

recording = Recording(
    analyzer,
    sys.argv[1],
    lat=LATITUDE,
    lon=LONGITUDE,
    date=datetime(year=2022, month=5, day=10), # use date or week_48
    min_conf=0.25,
)
recording.analyze()
for dec in recording.detections:
    print(dec['common_name'])
