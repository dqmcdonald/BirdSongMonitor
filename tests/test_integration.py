"""
End-to-end integration tests.

These run proc_recordings.py against the real test_recordings/ directory using
the genuine BirdNET model.  Each WAV file takes a few seconds to analyse, so
the full suite takes 1–5 minutes depending on hardware.

Run just the integration suite:
    pytest tests/test_integration.py -v

Skip them during fast iteration:
    pytest -m "not integration"
"""
import os
import sqlite3
import subprocess
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_RECORDINGS_DIR = os.path.join(PROJECT_ROOT, "test_recordings")
PROC_SCRIPT  = os.path.join(PROJECT_ROOT, "proc_recordings.py")
QUERY_SCRIPT = os.path.join(PROJECT_ROOT, "query_detections.py")

# Exact set of WAV files present in test_recordings/
EXPECTED_WAV_FILES = {
    "DA_2026_01_03_12_00.WAV", "DA_2026_03_02_12_11.WAV", "DA_2026_03_05_12_45.WAV",
    "DA_2026_03_06_12_53.WAV", "DA_2026_03_12_10_38.WAV", "DA_2026_03_26_12_45.WAV",
    "DA_2026_03_27_12_15.WAV", "DA_2026_04_03_13_41.WAV", "DA_2026_05_03_09_36.WAV",
    "SR_2026_03_12_07_06.WAV", "SR_2026_03_17_07_12.WAV", "SR_2026_04_03_07_33.WAV",
    "SR_2026_04_29_07_03.WAV", "SR_2026_05_03_07_07.WAV",
    "SS_2026_03_12_19_43.WAV", "SS_2026_04_03_19_02.WAV", "SS_2026_05_03_17_14.WAV",
}

EVENT_BY_PREFIX = {
    "SR": "Sunrise",
    "SS": "Sunset",
    "DA": "Day",
}


@pytest.fixture(scope="module")
def processed_db(tmp_path_factory):
    """
    Runs proc_recordings.py once against test_recordings/ and yields the path
    to the resulting SQLite database.  Shared across all tests in this module.
    """
    run_dir = tmp_path_factory.mktemp("integration")
    result = subprocess.run(
        [sys.executable, PROC_SCRIPT, TEST_RECORDINGS_DIR],
        cwd=str(run_dir),
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, (
        f"proc_recordings.py exited with code {result.returncode}\n"
        f"stderr:\n{result.stderr}\n"
        f"stdout:\n{result.stdout}"
    )
    db_path = run_dir / "test_recordings.db"
    assert db_path.exists(), "Database file was not created"
    return str(db_path)


@pytest.mark.integration
def test_db_file_is_created(processed_db):
    assert os.path.isfile(processed_db)


@pytest.mark.integration
def test_all_wav_files_have_dummy_sentinel(processed_db):
    """Every WAV file must produce exactly one DUMMY row (the processed sentinel)."""
    conn = sqlite3.connect(processed_db)
    processed = {
        row[0] for row in conn.execute(
            "SELECT DISTINCT file_name FROM detection WHERE common_name = 'DUMMY'"
        ).fetchall()
    }
    conn.close()
    assert processed == EXPECTED_WAV_FILES


@pytest.mark.integration
def test_no_file_has_more_than_one_dummy(processed_db):
    conn = sqlite3.connect(processed_db)
    rows = conn.execute(
        "SELECT file_name, COUNT(*) FROM detection "
        "WHERE common_name = 'DUMMY' GROUP BY file_name HAVING COUNT(*) > 1"
    ).fetchall()
    conn.close()
    assert rows == [], f"Files with duplicate DUMMY rows: {rows}"


@pytest.mark.integration
@pytest.mark.parametrize("wav,expected_event", [
    ("SR_2026_03_12_07_06.WAV", "Sunrise"),
    ("SR_2026_04_03_07_33.WAV", "Sunrise"),
    ("SS_2026_03_12_19_43.WAV", "Sunset"),
    ("SS_2026_04_03_19_02.WAV", "Sunset"),
    ("DA_2026_01_03_12_00.WAV", "Day"),
    ("DA_2026_03_12_10_38.WAV", "Day"),
])
def test_event_correctly_parsed(processed_db, wav, expected_event):
    conn = sqlite3.connect(processed_db)
    row = conn.execute(
        "SELECT event FROM detection WHERE file_name = ? AND common_name = 'DUMMY'",
        (wav,),
    ).fetchone()
    conn.close()
    assert row is not None, f"No DUMMY row for {wav}"
    assert row[0] == expected_event


@pytest.mark.integration
@pytest.mark.parametrize("wav,expected_date_prefix,expected_time", [
    ("SR_2026_03_12_07_06.WAV", "2026-03-12", "07:06"),
    ("DA_2026_01_03_12_00.WAV", "2026-01-03", "12:00"),
    ("SS_2026_05_03_17_14.WAV", "2026-05-03", "17:14"),
])
def test_date_correctly_parsed(processed_db, wav, expected_date_prefix, expected_time):
    conn = sqlite3.connect(processed_db)
    row = conn.execute(
        "SELECT date FROM detection WHERE file_name = ? AND common_name = 'DUMMY'",
        (wav,),
    ).fetchone()
    conn.close()
    assert row is not None
    date_str = str(row[0])
    assert expected_date_prefix in date_str, f"Expected {expected_date_prefix} in '{date_str}'"
    assert expected_time in date_str, f"Expected {expected_time} in '{date_str}'"


@pytest.mark.integration
def test_detections_have_positive_confidence(processed_db):
    conn = sqlite3.connect(processed_db)
    bad = conn.execute(
        "SELECT COUNT(*) FROM detection "
        "WHERE common_name != 'DUMMY' AND confidence <= 0"
    ).fetchone()[0]
    conn.close()
    assert bad == 0, f"{bad} non-DUMMY rows have confidence <= 0"


@pytest.mark.integration
def test_detections_confidence_in_valid_range(processed_db):
    conn = sqlite3.connect(processed_db)
    bad = conn.execute(
        "SELECT COUNT(*) FROM detection "
        "WHERE common_name != 'DUMMY' AND (confidence < 0 OR confidence > 1)"
    ).fetchone()[0]
    conn.close()
    assert bad == 0


@pytest.mark.integration
def test_idempotent_second_run_adds_no_rows(processed_db):
    """Running proc_recordings a second time must not add duplicate rows."""
    first_count = sqlite3.connect(processed_db).execute(
        "SELECT COUNT(*) FROM detection"
    ).fetchone()[0]

    subprocess.run(
        [sys.executable, PROC_SCRIPT, TEST_RECORDINGS_DIR],
        cwd=os.path.dirname(processed_db),
        capture_output=True,
        text=True,
        timeout=60,
    )

    second_count = sqlite3.connect(processed_db).execute(
        "SELECT COUNT(*) FROM detection"
    ).fetchone()[0]

    assert first_count == second_count, (
        f"Row count changed after second run: {first_count} → {second_count}"
    )


@pytest.mark.integration
def test_query_detections_basic_run(processed_db):
    result = subprocess.run(
        [sys.executable, QUERY_SCRIPT, processed_db],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "confidence" in result.stdout.lower()


@pytest.mark.integration
def test_query_detections_conf_stats(processed_db):
    result = subprocess.run(
        [sys.executable, QUERY_SCRIPT, processed_db, "--conf-stats"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "Min" in result.stdout


@pytest.mark.integration
def test_query_detections_life_list(processed_db):
    result = subprocess.run(
        [sys.executable, QUERY_SCRIPT, processed_db, "--life-list"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "Date" in result.stdout


@pytest.mark.integration
def test_query_detections_avg(processed_db):
    result = subprocess.run(
        [sys.executable, QUERY_SCRIPT, processed_db, "--avg"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "Average" in result.stdout


@pytest.mark.integration
def test_query_detections_nonexistent_db_exits_nonzero():
    result = subprocess.run(
        [sys.executable, QUERY_SCRIPT, "/tmp/nonexistent_birdmon.db"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
