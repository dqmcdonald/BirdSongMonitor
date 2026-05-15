"""
Shared fixtures for the BirdSongMonitor test suite.

fixture_db_path / fixture_conn  — a small SQLite DB with known detections,
used by unit tests for query_detections and plot_detections so they run fast
without touching BirdNET.  The data mirrors filenames that exist in
test_recordings/ and covers four species, three events, and three months.
"""
import os
import sqlite3
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_RECORDINGS_DIR = os.path.join(PROJECT_ROOT, "test_recordings")

sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------
# Four species:
#   Eurasian Blackbird  — 5 detections across 4 days (highest count)
#   European Starling   — 2 detections, both on 2026-03-12 (obs_days = 1)
#   Common Chaffinch    — 2 detections on different days
#   Silvereye           — 2 detections (Jan + Mar)
#
# Columns: file_name, event, date, common_name, scientific_name,
#          start_time, end_time, confidence

FIXTURE_DETECTIONS = [
    # SR_2026_03_12 — Sunrise, Blackbird + Starling
    ("SR_2026_03_12_07_06.WAV", "Sunrise", "2026-03-12 07:06:00",
     "DUMMY", "DUMMY", 0.0, 0.0, 0.0),
    ("SR_2026_03_12_07_06.WAV", "Sunrise", "2026-03-12 07:06:00",
     "Eurasian Blackbird", "Turdus merula", 3.0, 6.0, 0.85),
    ("SR_2026_03_12_07_06.WAV", "Sunrise", "2026-03-12 07:06:00",
     "European Starling", "Sturnus vulgaris", 9.0, 12.0, 0.72),

    # SR_2026_03_17 — Sunrise, Blackbird + Chaffinch
    ("SR_2026_03_17_07_12.WAV", "Sunrise", "2026-03-17 07:12:00",
     "DUMMY", "DUMMY", 0.0, 0.0, 0.0),
    ("SR_2026_03_17_07_12.WAV", "Sunrise", "2026-03-17 07:12:00",
     "Eurasian Blackbird", "Turdus merula", 0.0, 3.0, 0.90),
    ("SR_2026_03_17_07_12.WAV", "Sunrise", "2026-03-17 07:12:00",
     "Common Chaffinch", "Fringilla coelebs", 6.0, 9.0, 0.65),

    # SR_2026_04_03 — Sunrise, Blackbird only
    ("SR_2026_04_03_07_33.WAV", "Sunrise", "2026-04-03 07:33:00",
     "DUMMY", "DUMMY", 0.0, 0.0, 0.0),
    ("SR_2026_04_03_07_33.WAV", "Sunrise", "2026-04-03 07:33:00",
     "Eurasian Blackbird", "Turdus merula", 0.0, 3.0, 0.78),

    # SS_2026_03_12 — Sunset, Starling only (same calendar day as SR above)
    ("SS_2026_03_12_19_43.WAV", "Sunset", "2026-03-12 19:43:00",
     "DUMMY", "DUMMY", 0.0, 0.0, 0.0),
    ("SS_2026_03_12_19_43.WAV", "Sunset", "2026-03-12 19:43:00",
     "European Starling", "Sturnus vulgaris", 0.0, 3.0, 0.68),

    # SS_2026_04_03 — Sunset, no detections
    ("SS_2026_04_03_19_02.WAV", "Sunset", "2026-04-03 19:02:00",
     "DUMMY", "DUMMY", 0.0, 0.0, 0.0),

    # DA_2026_01_03 — Day, Silvereye
    ("DA_2026_01_03_12_00.WAV", "Day", "2026-01-03 12:00:00",
     "DUMMY", "DUMMY", 0.0, 0.0, 0.0),
    ("DA_2026_01_03_12_00.WAV", "Day", "2026-01-03 12:00:00",
     "Silvereye", "Zosterops lateralis", 0.0, 3.0, 0.55),

    # DA_2026_03_02 — Day, Blackbird + Chaffinch (Chaffinch conf 0.48 < 0.50)
    ("DA_2026_03_02_12_11.WAV", "Day", "2026-03-02 12:11:00",
     "DUMMY", "DUMMY", 0.0, 0.0, 0.0),
    ("DA_2026_03_02_12_11.WAV", "Day", "2026-03-02 12:11:00",
     "Eurasian Blackbird", "Turdus merula", 3.0, 6.0, 0.62),
    ("DA_2026_03_02_12_11.WAV", "Day", "2026-03-02 12:11:00",
     "Common Chaffinch", "Fringilla coelebs", 9.0, 12.0, 0.48),

    # DA_2026_03_05 — Day, no detections
    ("DA_2026_03_05_12_45.WAV", "Day", "2026-03-05 12:45:00",
     "DUMMY", "DUMMY", 0.0, 0.0, 0.0),

    # DA_2026_03_12 — Day, Blackbird + Silvereye
    ("DA_2026_03_12_10_38.WAV", "Day", "2026-03-12 10:38:00",
     "DUMMY", "DUMMY", 0.0, 0.0, 0.0),
    ("DA_2026_03_12_10_38.WAV", "Day", "2026-03-12 10:38:00",
     "Eurasian Blackbird", "Turdus merula", 6.0, 9.0, 0.73),
    ("DA_2026_03_12_10_38.WAV", "Day", "2026-03-12 10:38:00",
     "Silvereye", "Zosterops lateralis", 12.0, 15.0, 0.61),
]


@pytest.fixture(scope="session")
def fixture_db_path(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("db") / "fixture.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE detection("
        "file_name TEXT, event TEXT, date TEXT, common_name TEXT,"
        "scientific_name TEXT, start_time REAL, end_time REAL, confidence REAL)"
    )
    conn.executemany("INSERT INTO detection VALUES(?,?,?,?,?,?,?,?)", FIXTURE_DETECTIONS)
    conn.commit()
    conn.close()
    return str(db_path)


@pytest.fixture(scope="session")
def fixture_conn(fixture_db_path):
    conn = sqlite3.connect(fixture_db_path)
    yield conn
    conn.close()
