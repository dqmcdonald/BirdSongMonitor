"""
Unit tests for proc_recordings.py.

birdnetlib is mocked at module level so the BirdNET model never loads here.
End-to-end tests that exercise the real model live in test_integration.py.
"""
import os
import sqlite3
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

# ------------------------------------------------------------------
# Mock birdnetlib *before* importing proc_recordings to avoid loading
# the BirdNET model (a several-second operation).
# ------------------------------------------------------------------
for _mod in ("birdnetlib", "birdnetlib.analyzer"):
    sys.modules.setdefault(_mod, MagicMock())

import pytest  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import proc_recordings  # noqa: E402  (import after sys.modules patch)


# ===========================================================================
# extract_date_and_event
# ===========================================================================

class TestExtractDateAndEvent:

    def test_old_format_defaults_to_sunrise(self):
        dt, event = proc_recordings.extract_date_and_event("2026_03_12_07_06.WAV")
        assert dt == datetime(2026, 3, 12, 7, 6)
        assert event == "Sunrise"

    def test_old_format_with_leading_path(self):
        dt, event = proc_recordings.extract_date_and_event("/some/dir/2026_01_01_00_00.WAV")
        assert dt == datetime(2026, 1, 1, 0, 0)
        assert event == "Sunrise"

    def test_sr_maps_to_sunrise(self):
        dt, event = proc_recordings.extract_date_and_event("SR_2026_03_12_07_06.WAV")
        assert dt == datetime(2026, 3, 12, 7, 6)
        assert event == "Sunrise"

    def test_ss_maps_to_sunset(self):
        dt, event = proc_recordings.extract_date_and_event("SS_2026_04_03_19_02.WAV")
        assert dt == datetime(2026, 4, 3, 19, 2)
        assert event == "Sunset"

    def test_no_maps_to_noon(self):
        dt, event = proc_recordings.extract_date_and_event("NO_2026_03_12_12_00.WAV")
        assert dt == datetime(2026, 3, 12, 12, 0)
        assert event == "Noon"

    def test_da_maps_to_day(self):
        dt, event = proc_recordings.extract_date_and_event("DA_2026_01_03_12_00.WAV")
        assert dt == datetime(2026, 1, 3, 12, 0)
        assert event == "Day"

    @pytest.mark.parametrize("fname,expected_dt,expected_event", [
        ("SR_2026_03_12_07_06.WAV", datetime(2026, 3, 12, 7, 6),  "Sunrise"),
        ("SR_2026_03_17_07_12.WAV", datetime(2026, 3, 17, 7, 12), "Sunrise"),
        ("SR_2026_04_03_07_33.WAV", datetime(2026, 4, 3, 7, 33),  "Sunrise"),
        ("SR_2026_04_29_07_03.WAV", datetime(2026, 4, 29, 7, 3),  "Sunrise"),
        ("SR_2026_05_03_07_07.WAV", datetime(2026, 5, 3, 7, 7),   "Sunrise"),
    ])
    def test_sr_filenames_from_test_recordings(self, fname, expected_dt, expected_event):
        dt, event = proc_recordings.extract_date_and_event(fname)
        assert dt == expected_dt
        assert event == expected_event

    @pytest.mark.parametrize("fname,expected_dt,expected_event", [
        ("SS_2026_03_12_19_43.WAV", datetime(2026, 3, 12, 19, 43), "Sunset"),
        ("SS_2026_04_03_19_02.WAV", datetime(2026, 4, 3, 19, 2),   "Sunset"),
        ("SS_2026_05_03_17_14.WAV", datetime(2026, 5, 3, 17, 14),  "Sunset"),
    ])
    def test_ss_filenames_from_test_recordings(self, fname, expected_dt, expected_event):
        dt, event = proc_recordings.extract_date_and_event(fname)
        assert dt == expected_dt
        assert event == expected_event

    @pytest.mark.parametrize("fname,expected_dt,expected_event", [
        ("DA_2026_01_03_12_00.WAV", datetime(2026, 1, 3, 12, 0),   "Day"),
        ("DA_2026_03_02_12_11.WAV", datetime(2026, 3, 2, 12, 11),  "Day"),
        ("DA_2026_03_05_12_45.WAV", datetime(2026, 3, 5, 12, 45),  "Day"),
        ("DA_2026_03_06_12_53.WAV", datetime(2026, 3, 6, 12, 53),  "Day"),
        ("DA_2026_03_12_10_38.WAV", datetime(2026, 3, 12, 10, 38), "Day"),
        ("DA_2026_03_26_12_45.WAV", datetime(2026, 3, 26, 12, 45), "Day"),
        ("DA_2026_03_27_12_15.WAV", datetime(2026, 3, 27, 12, 15), "Day"),
        ("DA_2026_04_03_13_41.WAV", datetime(2026, 4, 3, 13, 41),  "Day"),
        ("DA_2026_05_03_09_36.WAV", datetime(2026, 5, 3, 9, 36),   "Day"),
    ])
    def test_da_filenames_from_test_recordings(self, fname, expected_dt, expected_event):
        dt, event = proc_recordings.extract_date_and_event(fname)
        assert dt == expected_dt
        assert event == expected_event

    def test_invalid_format_raises_value_error(self):
        with pytest.raises(ValueError, match="Unexpected filename format"):
            proc_recordings.extract_date_and_event("badname.WAV")

    def test_too_few_components_raises(self):
        with pytest.raises(ValueError):
            proc_recordings.extract_date_and_event("2026_03_12.WAV")

    def test_too_many_components_raises(self):
        with pytest.raises(ValueError):
            proc_recordings.extract_date_and_event("SR_2026_03_12_07_06_extra.WAV")


# ===========================================================================
# create_db
# ===========================================================================

class TestCreateDb:

    def _chdir(self, tmp_path):
        """Context manager that changes cwd then restores it."""
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            orig = os.getcwd()
            os.chdir(tmp_path)
            try:
                yield
            finally:
                os.chdir(orig)

        return _ctx()

    def test_creates_db_file(self, tmp_path):
        recordings_dir = str(tmp_path / "mysite")
        os.makedirs(recordings_dir)
        with self._chdir(tmp_path):
            conn = proc_recordings.create_db(recordings_dir)
            conn.close()
        assert (tmp_path / "mysite.db").exists()

    def test_creates_detection_table(self, tmp_path):
        recordings_dir = str(tmp_path / "site")
        os.makedirs(recordings_dir)
        with self._chdir(tmp_path):
            conn = proc_recordings.create_db(recordings_dir)
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='detection'"
            )
            assert cur.fetchone() is not None
            conn.close()

    def test_detection_table_has_eight_columns(self, tmp_path):
        recordings_dir = str(tmp_path / "cols")
        os.makedirs(recordings_dir)
        with self._chdir(tmp_path):
            conn = proc_recordings.create_db(recordings_dir)
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(detection)")
            cols = [row[1] for row in cur.fetchall()]
            conn.close()
        assert cols == [
            "file_name", "event", "date", "common_name",
            "scientific_name", "start_time", "end_time", "confidence",
        ]

    def test_existing_db_is_not_recreated(self, tmp_path):
        recordings_dir = str(tmp_path / "site2")
        os.makedirs(recordings_dir)
        with self._chdir(tmp_path):
            conn = proc_recordings.create_db(recordings_dir)
            conn.execute(
                "INSERT INTO detection VALUES(?,?,?,?,?,?,?,?)",
                ("f.WAV", "Sunrise", "2026-01-01", "Robin", "Erithacus", 0, 3, 0.9),
            )
            conn.commit()
            conn.close()

            conn2 = proc_recordings.create_db(recordings_dir)
            count = conn2.execute("SELECT COUNT(*) FROM detection").fetchone()[0]
            conn2.close()

        assert count == 1


# ===========================================================================
# load_processed_files
# ===========================================================================

class TestLoadProcessedFiles:

    def _make_db(self, tmp_path, rows=None):
        db_path = str(tmp_path / "t.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE detection("
            "file_name,event,date,common_name,scientific_name,"
            "start_time,end_time,confidence)"
        )
        if rows:
            conn.executemany("INSERT INTO detection VALUES(?,?,?,?,?,?,?,?)", rows)
        conn.commit()
        return conn

    def test_empty_db_returns_empty_set(self, tmp_path):
        conn = self._make_db(tmp_path)
        assert proc_recordings.load_processed_files(conn) == set()
        conn.close()

    def test_returns_unique_filenames(self, tmp_path):
        rows = [
            ("file1.WAV", "Sunrise", "2026-01-01", "DUMMY", "DUMMY", 0, 0, 0),
            ("file1.WAV", "Sunrise", "2026-01-01", "Robin", "Erithacus", 0, 3, 0.9),
            ("file2.WAV", "Sunset",  "2026-01-02", "DUMMY", "DUMMY", 0, 0, 0),
        ]
        conn = self._make_db(tmp_path, rows)
        result = proc_recordings.load_processed_files(conn)
        assert result == {"file1.WAV", "file2.WAV"}
        conn.close()

    def test_multiple_files_all_returned(self, tmp_path):
        rows = [
            (f"f{i}.WAV", "Sunrise", "2026-01-01", "DUMMY", "DUMMY", 0, 0, 0)
            for i in range(5)
        ]
        conn = self._make_db(tmp_path, rows)
        result = proc_recordings.load_processed_files(conn)
        assert result == {f"f{i}.WAV" for i in range(5)}
        conn.close()


# ===========================================================================
# process_rec
# ===========================================================================

class TestProcessRec:

    def _make_db(self, tmp_path):
        db_path = str(tmp_path / "pr.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE detection("
            "file_name,event,date,common_name,scientific_name,"
            "start_time,end_time,confidence)"
        )
        conn.commit()
        return conn

    def test_skips_already_processed_file(self, tmp_path):
        conn = self._make_db(tmp_path)
        processed = {"SR_2026_03_12_07_06.WAV"}
        proc_recordings.process_rec("SR_2026_03_12_07_06.WAV", conn, processed, 0.25)
        assert conn.execute("SELECT COUNT(*) FROM detection").fetchone()[0] == 0
        conn.close()

    def test_skips_invalid_filename_silently(self, tmp_path):
        conn = self._make_db(tmp_path)
        proc_recordings.process_rec("bad_file_name.WAV", conn, set(), 0.25)
        assert conn.execute("SELECT COUNT(*) FROM detection").fetchone()[0] == 0
        conn.close()

    def test_inserts_dummy_sentinel_when_no_detections(self, tmp_path):
        conn = self._make_db(tmp_path)
        mock_rec = MagicMock()
        mock_rec.detections = []
        with patch.object(proc_recordings, "Recording", return_value=mock_rec):
            proc_recordings.process_rec("SR_2026_03_12_07_06.WAV", conn, set(), 0.25)
        rows = conn.execute(
            "SELECT common_name, confidence FROM detection"
        ).fetchall()
        assert rows == [("DUMMY", 0.0)]
        conn.close()

    def test_inserts_dummy_plus_detections(self, tmp_path):
        conn = self._make_db(tmp_path)
        mock_rec = MagicMock()
        mock_rec.detections = [
            {
                "common_name": "Eurasian Blackbird",
                "scientific_name": "Turdus merula",
                "start_time": 3.0,
                "end_time": 6.0,
                "confidence": 0.85,
            }
        ]
        with patch.object(proc_recordings, "Recording", return_value=mock_rec):
            proc_recordings.process_rec("SR_2026_03_12_07_06.WAV", conn, set(), 0.25)
        rows = conn.execute(
            "SELECT common_name, confidence FROM detection ORDER BY confidence"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0] == ("DUMMY", 0.0)
        assert rows[1][0] == "Eurasian Blackbird"
        assert abs(rows[1][1] - 0.85) < 1e-9
        conn.close()

    def test_file_added_to_processed_set_implicitly(self, tmp_path):
        conn = self._make_db(tmp_path)
        mock_rec = MagicMock()
        mock_rec.detections = []
        with patch.object(proc_recordings, "Recording", return_value=mock_rec):
            proc_recordings.process_rec("SR_2026_03_12_07_06.WAV", conn, set(), 0.25)
        # The DUMMY sentinel means load_processed_files will now return the file
        result = proc_recordings.load_processed_files(conn)
        assert "SR_2026_03_12_07_06.WAV" in result
        conn.close()

    def test_event_stored_correctly_for_sr(self, tmp_path):
        conn = self._make_db(tmp_path)
        mock_rec = MagicMock()
        mock_rec.detections = []
        with patch.object(proc_recordings, "Recording", return_value=mock_rec):
            proc_recordings.process_rec("SR_2026_03_12_07_06.WAV", conn, set(), 0.25)
        event = conn.execute("SELECT event FROM detection").fetchone()[0]
        assert event == "Sunrise"
        conn.close()

    def test_event_stored_correctly_for_da(self, tmp_path):
        conn = self._make_db(tmp_path)
        mock_rec = MagicMock()
        mock_rec.detections = []
        with patch.object(proc_recordings, "Recording", return_value=mock_rec):
            proc_recordings.process_rec("DA_2026_03_12_10_38.WAV", conn, set(), 0.25)
        event = conn.execute("SELECT event FROM detection").fetchone()[0]
        assert event == "Day"
        conn.close()

    def test_analyze_error_is_swallowed(self, tmp_path):
        conn = self._make_db(tmp_path)
        mock_rec = MagicMock()
        mock_rec.analyze.side_effect = RuntimeError("BirdNET exploded")
        with patch.object(proc_recordings, "Recording", return_value=mock_rec):
            proc_recordings.process_rec("SR_2026_03_12_07_06.WAV", conn, set(), 0.25)
        assert conn.execute("SELECT COUNT(*) FROM detection").fetchone()[0] == 0
        conn.close()
