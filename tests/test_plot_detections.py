"""
Unit tests for the data-loading and helper functions in plot_detections.py.
Matplotlib is forced to the non-interactive Agg backend so no windows open.
All tests run against the in-memory fixture DB defined in conftest.py.
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")  # must be set before pyplot is imported anywhere

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import plot_detections  # noqa: E402


# ===========================================================================
# _event_filter
# ===========================================================================

class TestEventFilter:

    def test_all_returns_empty_clause(self):
        clause, params = plot_detections._event_filter("All")
        assert clause == ""
        assert params == ()

    def test_sunrise_clause_and_param(self):
        clause, params = plot_detections._event_filter("Sunrise")
        assert "event = ?" in clause
        assert params == ("Sunrise",)

    def test_sunset_clause(self):
        clause, params = plot_detections._event_filter("Sunset")
        assert params == ("Sunset",)

    def test_day_clause(self):
        clause, params = plot_detections._event_filter("Day")
        assert params == ("Day",)


# ===========================================================================
# _parse_date
# ===========================================================================

class TestParseDate:

    def test_yyyy_mm_dd_passthrough(self):
        assert plot_detections._parse_date("2026-03-12") == "2026-03-12"

    def test_dd_mm_yyyy_converted(self):
        assert plot_detections._parse_date("12-03-2026") == "2026-03-12"

    def test_empty_string_passthrough(self):
        assert plot_detections._parse_date("") == ""


# ===========================================================================
# _date_filter
# ===========================================================================

class TestDateFilter:

    def test_no_dates(self):
        clause, params = plot_detections._date_filter("", "")
        assert clause == ""
        assert params == ()

    def test_from_and_to(self):
        clause, params = plot_detections._date_filter("2026-01-01", "2026-12-31")
        assert "DATE(date) >=" in clause
        assert "DATE(date) <=" in clause
        assert "2026-01-01" in params
        assert "2026-12-31" in params


# ===========================================================================
# _species_filter
# ===========================================================================

class TestSpeciesFilter:

    def test_empty_species_excludes_dummy(self):
        clause, params = plot_detections._species_filter("")
        assert "DUMMY" in clause
        assert params == ()

    def test_specific_species_adds_equality(self):
        clause, params = plot_detections._species_filter("Silvereye")
        assert "common_name = ?" in clause
        assert params == ("Silvereye",)


# ===========================================================================
# _default_out
# ===========================================================================

class TestDefaultOut:

    def test_daily_plot_has_no_type_suffix(self):
        assert plot_detections._default_out("mysite.db", "daily", None) == "mysite.png"

    def test_heatmap_gets_suffix(self):
        assert plot_detections._default_out("mysite.db", "heatmap", None) == "mysite_heatmap.png"

    def test_accumulation_gets_suffix(self):
        assert plot_detections._default_out("x.db", "accumulation", None) == "x_accumulation.png"

    def test_explicit_path_overrides_default(self):
        result = plot_detections._default_out("mysite.db", "daily", "/tmp/out.png")
        assert result == "/tmp/out.png"


# ===========================================================================
# load_daily_counts
# ===========================================================================

class TestLoadDailyCounts:

    def test_returns_dates_and_species_dict(self, fixture_db_path):
        dates, counts = plot_detections.load_daily_counts(fixture_db_path, 0.25, "", "All")
        assert len(dates) > 0
        assert isinstance(counts, dict)
        assert "Eurasian Blackbird" in counts

    def test_single_species_filter(self, fixture_db_path):
        dates, counts = plot_detections.load_daily_counts(
            fixture_db_path, 0.25, "Silvereye", "All")
        assert "Silvereye" in counts
        assert len(counts) == 1

    def test_event_filter_excludes_other_events(self, fixture_db_path):
        dates, counts = plot_detections.load_daily_counts(
            fixture_db_path, 0.25, "", "Sunrise")
        # Silvereye only appears in Day recordings
        assert "Silvereye" not in counts
        assert "Eurasian Blackbird" in counts

    def test_empty_result_for_impossible_confidence(self, fixture_db_path):
        dates, counts = plot_detections.load_daily_counts(
            fixture_db_path, 0.99, "", "All")
        assert dates == []
        assert counts == {}

    def test_january_date_range_returns_silvereye_only(self, fixture_db_path):
        dates, counts = plot_detections.load_daily_counts(
            fixture_db_path, 0.25, "", "All",
            date_from="2026-01-01", date_to="2026-01-31")
        assert "Silvereye" in counts
        assert "Eurasian Blackbird" not in counts

    def test_date_list_length_matches_all_species_lists(self, fixture_db_path):
        dates, counts = plot_detections.load_daily_counts(
            fixture_db_path, 0.25, "", "All")
        for sp, vals in counts.items():
            assert len(vals) == len(dates), f"Length mismatch for {sp}"


# ===========================================================================
# load_heatmap_data
# ===========================================================================

class TestLoadHeatmapData:

    def test_returns_three_values_when_data_present(self, fixture_db_path):
        result = plot_detections.load_heatmap_data(
            fixture_db_path, 0.25, "", "All", 10)
        assert len(result) == 3
        species_list, hours, matrix = result
        assert len(species_list) > 0

    def test_matrix_shape_matches_species_and_hours(self, fixture_db_path):
        species_list, hours, matrix = plot_detections.load_heatmap_data(
            fixture_db_path, 0.25, "", "All", 10)
        assert matrix.shape == (len(species_list), len(hours))

    def test_blackbird_in_top_species(self, fixture_db_path):
        species_list, _, _ = plot_detections.load_heatmap_data(
            fixture_db_path, 0.25, "", "All", 10)
        assert "Eurasian Blackbird" in species_list

    def test_active_hours_only_includes_hours_with_data(self, fixture_db_path):
        _, hours, matrix = plot_detections.load_heatmap_data(
            fixture_db_path, 0.25, "", "All", 10)
        import numpy as np
        for i, h in enumerate(hours):
            assert matrix[:, i].sum() > 0

    def test_empty_result_returns_two_values(self, fixture_db_path):
        # Known behaviour: load_heatmap_data returns ([], []) when there are
        # no matching species, which is inconsistent with the 3-tuple returned
        # when data is present.  main() would raise ValueError here.
        result = plot_detections.load_heatmap_data(
            fixture_db_path, 0.99, "", "All", 10)
        assert len(result) == 2


# ===========================================================================
# load_topn_data
# ===========================================================================

class TestLoadTopnData:

    def test_returns_list_of_name_count_pairs(self, fixture_db_path):
        rows = plot_detections.load_topn_data(fixture_db_path, 0.25, "", "All", 10)
        assert len(rows) > 0
        for name, count in rows:
            assert isinstance(name, str)
            assert isinstance(count, int)

    def test_blackbird_is_top_species(self, fixture_db_path):
        rows = plot_detections.load_topn_data(fixture_db_path, 0.25, "", "All", 10)
        assert rows[0][0] == "Eurasian Blackbird"

    def test_n_limit_respected(self, fixture_db_path):
        rows = plot_detections.load_topn_data(fixture_db_path, 0.25, "", "All", 2)
        assert len(rows) <= 2

    def test_event_filter_sunrise_only(self, fixture_db_path):
        rows = plot_detections.load_topn_data(fixture_db_path, 0.25, "", "Sunrise", 10)
        names = [r[0] for r in rows]
        assert "Silvereye" not in names  # Silvereye only in Day


# ===========================================================================
# load_accumulation_data
# ===========================================================================

class TestLoadAccumulationData:

    def test_returns_dates_and_counts(self, fixture_db_path):
        dates, counts = plot_detections.load_accumulation_data(
            fixture_db_path, 0.25, "", "All")
        assert len(dates) > 0
        assert len(counts) > 0

    def test_counts_are_monotonically_non_decreasing(self, fixture_db_path):
        _, counts = plot_detections.load_accumulation_data(
            fixture_db_path, 0.25, "", "All")
        for i in range(1, len(counts)):
            assert counts[i] >= counts[i - 1]

    def test_final_count_equals_total_unique_species(self, fixture_db_path):
        _, counts = plot_detections.load_accumulation_data(
            fixture_db_path, 0.25, "", "All")
        # 4 species in fixture above the 0.25 threshold
        assert counts[-1] == 4

    def test_empty_for_impossible_confidence(self, fixture_db_path):
        dates, counts = plot_detections.load_accumulation_data(
            fixture_db_path, 0.99, "", "All")
        assert dates == []
        assert counts == []

    def test_date_range_restricts_species(self, fixture_db_path):
        _, counts = plot_detections.load_accumulation_data(
            fixture_db_path, 0.25, "", "All",
            date_from="2026-01-01", date_to="2026-01-31")
        # Only Silvereye is in January
        assert counts[-1] == 1


# ===========================================================================
# load_confidence_data
# ===========================================================================

class TestLoadConfidenceData:

    def test_returns_dict_of_species_to_conf_list(self, fixture_db_path):
        data = plot_detections.load_confidence_data(
            fixture_db_path, 0.25, "", "All", 10)
        assert len(data) > 0
        assert "Eurasian Blackbird" in data
        assert isinstance(data["Eurasian Blackbird"], list)

    def test_all_confidence_values_above_threshold(self, fixture_db_path):
        data = plot_detections.load_confidence_data(
            fixture_db_path, 0.50, "", "All", 10)
        for sp, confs in data.items():
            for c in confs:
                assert c > 0.50, f"{sp} has conf {c} <= 0.50"

    def test_blackbird_has_five_detections(self, fixture_db_path):
        data = plot_detections.load_confidence_data(
            fixture_db_path, 0.25, "", "All", 10)
        assert len(data["Eurasian Blackbird"]) == 5

    def test_empty_for_impossible_confidence(self, fixture_db_path):
        data = plot_detections.load_confidence_data(
            fixture_db_path, 0.99, "", "All", 10)
        assert data == {}


# ===========================================================================
# load_event_comparison_data
# ===========================================================================

class TestLoadEventComparisonData:

    def test_returns_data_dict_and_species_list(self, fixture_db_path):
        data, top_species = plot_detections.load_event_comparison_data(
            fixture_db_path, 0.25, "", 10)
        assert len(top_species) > 0
        assert len(data) > 0

    def test_all_three_events_present(self, fixture_db_path):
        data, _ = plot_detections.load_event_comparison_data(
            fixture_db_path, 0.25, "", 10)
        assert "Sunrise" in data
        assert "Sunset" in data
        assert "Day" in data

    def test_blackbird_count_by_event(self, fixture_db_path):
        data, top_species = plot_detections.load_event_comparison_data(
            fixture_db_path, 0.25, "", 10)
        # Blackbird: 3 Sunrise + 2 Day detections, 0 Sunset
        assert data["Sunrise"].get("Eurasian Blackbird", 0) == 3
        assert data["Day"].get("Eurasian Blackbird", 0) == 2

    def test_empty_for_impossible_confidence(self, fixture_db_path):
        data, top_species = plot_detections.load_event_comparison_data(
            fixture_db_path, 0.99, "", 10)
        assert data == {}
        assert top_species == []
