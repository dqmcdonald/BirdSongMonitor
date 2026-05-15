"""
Unit tests for query_detections.py helper functions and query modes.
All tests run against the in-memory fixture DB defined in conftest.py.

Fixture species summary (threshold 0.25):
  Eurasian Blackbird  — 5 detections, 4 distinct days
  European Starling   — 2 detections, both on 2026-03-12 (obs_days = 1)
  Common Chaffinch    — 2 detections (0.65, 0.48) on 2 days
  Silvereye           — 2 detections on 2 days (Jan + Mar)
"""
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import query_detections  # noqa: E402


# ===========================================================================
# _parse_date
# ===========================================================================

class TestParseDate:

    def test_yyyy_mm_dd_passthrough(self):
        assert query_detections._parse_date("2026-03-12") == "2026-03-12"

    def test_dd_mm_yyyy_converted(self):
        assert query_detections._parse_date("12-03-2026") == "2026-03-12"

    def test_empty_string_passthrough(self):
        assert query_detections._parse_date("") == ""

    def test_none_passthrough(self):
        assert query_detections._parse_date(None) is None

    def test_single_digit_day_month(self):
        assert query_detections._parse_date("03-01-2026") == "2026-01-03"


# ===========================================================================
# _date_clause
# ===========================================================================

class TestDateClause:

    def test_no_dates_returns_empty(self):
        clause, params = query_detections._date_clause("", "")
        assert clause == ""
        assert params == ()

    def test_from_only(self):
        clause, params = query_detections._date_clause("2026-01-01", "")
        assert "DATE(date) >=" in clause
        assert params == ("2026-01-01",)

    def test_to_only(self):
        clause, params = query_detections._date_clause("", "2026-12-31")
        assert "DATE(date) <=" in clause
        assert params == ("2026-12-31",)

    def test_both_dates(self):
        clause, params = query_detections._date_clause("2026-01-01", "2026-12-31")
        assert "DATE(date) >=" in clause
        assert "DATE(date) <=" in clause
        assert params == ("2026-01-01", "2026-12-31")


# ===========================================================================
# _fmt_time
# ===========================================================================

class TestFmtTime:

    def test_zero(self):
        assert query_detections._fmt_time(0.0) == "0:00"

    def test_under_a_minute(self):
        assert query_detections._fmt_time(45.0) == "0:45"

    def test_exactly_one_minute(self):
        assert query_detections._fmt_time(60.0) == "1:00"

    def test_minute_and_half(self):
        assert query_detections._fmt_time(90.0) == "1:30"

    def test_single_digit_seconds_zero_padded(self):
        assert query_detections._fmt_time(61.0) == "1:01"


# ===========================================================================
# _where
# ===========================================================================

class TestWhere:

    def test_confidence_and_dummy_filter_always_present(self):
        clause, params = query_detections._where(0.25, "", "", "")
        assert "confidence > ?" in clause
        assert "common_name != 'DUMMY'" in clause
        assert params[0] == 0.25

    def test_species_filter_appended(self):
        clause, params = query_detections._where(0.25, "Silvereye", "", "")
        assert "common_name = ?" in clause
        assert "Silvereye" in params

    def test_event_filter_appended(self):
        clause, params = query_detections._where(0.25, "", "Sunrise", "")
        assert "event = ?" in clause
        assert "Sunrise" in params

    def test_date_clause_appended(self):
        clause, params = query_detections._where(0.25, "", "", " AND DATE(date) >= ?")
        assert "DATE(date) >=" in clause


# ===========================================================================
# list_db
# ===========================================================================

class TestListDb:

    def test_lists_species_names_and_counts(self, fixture_conn, capsys):
        query_detections.list_db(fixture_conn, False, 0.25, "", "", "", "")
        out = capsys.readouterr().out
        assert "Eurasian Blackbird" in out
        assert "European Starling" in out
        assert "Silvereye" in out

    def test_filters_by_event_sunrise(self, fixture_conn, capsys):
        query_detections.list_db(fixture_conn, False, 0.25, "", "Sunrise", "", "")
        out = capsys.readouterr().out
        assert "Eurasian Blackbird" in out
        # Silvereye only in Day recordings
        assert "Silvereye" not in out

    def test_filters_to_january_only(self, fixture_conn, capsys):
        query_detections.list_db(fixture_conn, False, 0.25, "", "", "2026-01-01", "2026-01-31")
        out = capsys.readouterr().out
        assert "Silvereye" in out
        assert "Eurasian Blackbird" not in out

    def test_species_detail_shows_scientific_name(self, fixture_conn, capsys):
        query_detections.list_db(fixture_conn, False, 0.25, "Eurasian Blackbird", "", "", "")
        out = capsys.readouterr().out
        assert "Turdus merula" in out

    def test_unknown_species_shows_message(self, fixture_conn, capsys):
        query_detections.list_db(fixture_conn, False, 0.25, "Unicorn Bird", "", "", "")
        out = capsys.readouterr().out
        assert "Unknown species" in out

    def test_high_confidence_filters_low_conf_species(self, fixture_conn, capsys):
        # At 0.84: only Blackbird (0.85, 0.90) has detections above threshold
        query_detections.list_db(fixture_conn, False, 0.84, "", "", "", "")
        out = capsys.readouterr().out
        assert "Eurasian Blackbird" in out
        assert "Silvereye" not in out

    def test_list_all_shows_raw_rows(self, fixture_conn, capsys):
        query_detections.list_db(fixture_conn, True, 0.25, "", "", "", "")
        out = capsys.readouterr().out
        # list_all=True also prints individual detection tuples
        assert "Detections with confidence" in out


# ===========================================================================
# avg_detections
# ===========================================================================

class TestAvgDetections:

    def test_shows_header_and_species(self, fixture_conn, capsys):
        query_detections.avg_detections(fixture_conn, 0.25, "", "", "", "")
        out = capsys.readouterr().out
        assert "Average detections per day" in out
        assert "Eurasian Blackbird" in out

    def test_monthly_pivot_shows_months(self, fixture_conn, capsys):
        query_detections.avg_detections(fixture_conn, 0.25, "", "", "", "", monthly=True)
        out = capsys.readouterr().out
        assert "2026-03" in out

    def test_no_data_above_threshold(self, fixture_conn, capsys):
        query_detections.avg_detections(fixture_conn, 0.99, "", "", "", "")
        out = capsys.readouterr().out
        assert "No data found" in out

    def test_event_filter_restricts_output(self, fixture_conn, capsys):
        query_detections.avg_detections(fixture_conn, 0.25, "", "Sunset", "", "")
        out = capsys.readouterr().out
        # Only Starling has Sunset detections
        assert "European Starling" in out
        assert "Eurasian Blackbird" not in out


# ===========================================================================
# first_last_seen
# ===========================================================================

class TestFirstLastSeen:

    def test_shows_dates_and_species(self, fixture_conn, capsys):
        query_detections.first_last_seen(fixture_conn, 0.25, "", "", "", "")
        out = capsys.readouterr().out
        assert "Eurasian Blackbird" in out
        # Blackbird first seen 2026-03-02
        assert "2026-03-02" in out

    def test_no_data_message(self, fixture_conn, capsys):
        query_detections.first_last_seen(fixture_conn, 0.99, "", "", "", "")
        out = capsys.readouterr().out
        assert "No data found" in out

    def test_silvereye_spans_jan_to_mar(self, fixture_conn, capsys):
        query_detections.first_last_seen(fixture_conn, 0.25, "Silvereye", "", "", "")
        out = capsys.readouterr().out
        assert "2026-01-03" in out
        assert "2026-03-12" in out


# ===========================================================================
# conf_stats
# ===========================================================================

class TestConfStats:

    def test_shows_min_max_mean(self, fixture_conn, capsys):
        query_detections.conf_stats(fixture_conn, 0.25, "", "", "", "")
        out = capsys.readouterr().out
        assert "Min" in out
        assert "Max" in out
        assert "Mean" in out
        assert "Eurasian Blackbird" in out

    def test_no_data_message(self, fixture_conn, capsys):
        query_detections.conf_stats(fixture_conn, 0.99, "", "", "", "")
        out = capsys.readouterr().out
        assert "No data found" in out

    def test_blackbird_stats_include_all_detections(self, fixture_conn, capsys):
        query_detections.conf_stats(fixture_conn, 0.25, "Eurasian Blackbird", "", "", "")
        out = capsys.readouterr().out
        # Blackbird: conf values 0.85, 0.90, 0.78, 0.62, 0.73 → min 0.620
        assert "0.620" in out


# ===========================================================================
# life_list
# ===========================================================================

class TestLifeList:

    def test_shows_all_species(self, fixture_conn, capsys):
        query_detections.life_list(fixture_conn, 0.25, "", "", "", "")
        out = capsys.readouterr().out
        for name in ("Eurasian Blackbird", "European Starling", "Silvereye"):
            assert name in out

    def test_single_day_species_marked_with_asterisk(self, fixture_conn, capsys):
        query_detections.life_list(fixture_conn, 0.25, "", "", "", "")
        out = capsys.readouterr().out
        # Starling: both detections on 2026-03-12 → obs_days = 1 → marked *
        assert "detected on only one day" in out
        lines = [l for l in out.splitlines() if "European Starling" in l]
        assert any("*" in l for l in lines)

    def test_no_data_message(self, fixture_conn, capsys):
        query_detections.life_list(fixture_conn, 0.99, "", "", "", "")
        out = capsys.readouterr().out
        assert "No data found" in out

    def test_silvereye_first_seen_january(self, fixture_conn, capsys):
        query_detections.life_list(fixture_conn, 0.25, "", "", "", "")
        out = capsys.readouterr().out
        lines = [l for l in out.splitlines() if "Silvereye" in l]
        assert any("2026-01-03" in l for l in lines)


# ===========================================================================
# cooccurrence
# ===========================================================================

class TestCooccurrence:

    def test_overall_pairs_include_blackbird_starling(self, fixture_conn, capsys):
        query_detections.cooccurrence(fixture_conn, 0.25, "", "", "", "")
        out = capsys.readouterr().out
        # Blackbird + Starling share SR_2026_03_12
        assert "Eurasian Blackbird" in out
        assert "European Starling" in out

    def test_species_cooccurrence_for_blackbird(self, fixture_conn, capsys):
        query_detections.cooccurrence(fixture_conn, 0.25, "Eurasian Blackbird", "", "", "")
        out = capsys.readouterr().out
        # Blackbird co-occurs with Starling, Chaffinch, and Silvereye
        assert "European Starling" in out or "Common Chaffinch" in out

    def test_no_data_message(self, fixture_conn, capsys):
        query_detections.cooccurrence(fixture_conn, 0.99, "", "", "", "")
        out = capsys.readouterr().out
        assert "No data found" in out


# ===========================================================================
# detection_streaks
# ===========================================================================

class TestDetectionStreaks:

    def test_header_and_species_present(self, fixture_conn, capsys):
        query_detections.detection_streaks(fixture_conn, 0.25, "", "", "", "")
        out = capsys.readouterr().out
        assert "Max streak" in out
        assert "Eurasian Blackbird" in out

    def test_footer_legend_present(self, fixture_conn, capsys):
        query_detections.detection_streaks(fixture_conn, 0.25, "", "", "", "")
        out = capsys.readouterr().out
        assert "longest consecutive" in out

    def test_no_data_message(self, fixture_conn, capsys):
        query_detections.detection_streaks(fixture_conn, 0.99, "", "", "", "")
        out = capsys.readouterr().out
        assert "No data found" in out

    def test_blackbird_appears_with_correct_day_count(self, fixture_conn, capsys):
        query_detections.detection_streaks(fixture_conn, 0.25, "Eurasian Blackbird", "", "", "")
        out = capsys.readouterr().out
        # Blackbird detected on 4 distinct days
        assert "4" in out


# ===========================================================================
# resolve_species
# ===========================================================================

class TestResolveSpecies:

    def test_exact_match_returned(self, fixture_conn):
        result = query_detections.resolve_species(fixture_conn, "Eurasian Blackbird")
        assert result == "Eurasian Blackbird"

    def test_partial_case_insensitive_match(self, fixture_conn):
        result = query_detections.resolve_species(fixture_conn, "blackbird")
        assert result == "Eurasian Blackbird"

    def test_case_insensitive_exact_match(self, fixture_conn):
        result = query_detections.resolve_species(fixture_conn, "eurasian blackbird")
        assert result == "Eurasian Blackbird"

    def test_no_match_returns_original_pattern(self, fixture_conn):
        result = query_detections.resolve_species(fixture_conn, "Unicorn Bird")
        assert result == "Unicorn Bird"

    def test_partial_match_for_silvereye(self, fixture_conn):
        result = query_detections.resolve_species(fixture_conn, "silver")
        assert result == "Silvereye"
