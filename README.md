# BirdSongMonitor

Python scripts for processing bird song recordings captured at sunrise, sunset, and noon using a custom hardware recorder (Teensy 3.6 + MEMS microphone). Recordings are analysed with [BirdNET](https://github.com/birdnet-team/birdnet) via the `birdnetlib` Python library and results stored in SQLite databases.

Location is hardcoded for Christchurch, New Zealand.

## Dependencies

Install manually with pip — no `requirements.txt` exists.

- `birdnetlib` — Python wrapper for BirdNET-Analyzer
- `matplotlib` — plotting
- `numpy` — array operations (used by `plot_detections.py`)
- `Pillow` (`PIL`) — bird photo handling in `plot_detections.py`
- `requests` — Wikipedia image fallback in `plot_detections.py`
- `tqdm` — progress bar in `proc_recordings.py`

## Scripts

### `proc_recordings.py` — process recordings

Runs BirdNET on every `.WAV` file in a directory and stores detections in a SQLite database named after the directory (`<dirname>.db`), created in the current working directory. Already-processed files are skipped automatically.

```
python proc_recordings.py <directory> [-c CONFIDENCE]
```

| Option | Default | Description |
|--------|---------|-------------|
| `directory` | (required) | Directory of WAV recordings |
| `-c`, `--confidence` | `0.75` | Minimum BirdNET confidence threshold |

### `query_detections.py` — query a database

Lists detected species and their counts, with optional filtering. Use `-a` to dump every individual detection row. Use `-s` to drill into a specific species, `--play` to listen to each detection via `afplay` (macOS only), or `--extract` to save each matching audio segment as its own WAV file. Multiple stat flags can be combined in one run.

```
python query_detections.py <db_name.db> [options]
```

| Option | Default | Description |
|--------|---------|-------------|
| `db_name` | (required) | Path to the SQLite database |
| `-c`, `--confidence` | `0.75` | Minimum confidence threshold |
| `-e`, `--event` | (all) | Filter by event: `Sunrise`, `Sunset`, or `Day` |
| `-s`, `--species` | (all) | Show detailed rows for a single species; accepts partial, case-insensitive names — prompts if ambiguous |
| `-a`, `--all` | off | Dump every detection row |
| `--from DATE` | (none) | Start date inclusive (`DD/MM/YYYY`) |
| `--to DATE` | (none) | End date inclusive (`DD/MM/YYYY`) |
| `-p`, `--play` | off | Play audio for each detection (requires `-s`; macOS only) |
| `--extract` | off | Extract each matching detection as an individual WAV file |
| `--extract-dir DIR` | `extracted/` | Output directory for extracted WAV files |
| `--recordings-dir DIR` | `<db_stem>/` | Directory containing WAV files (for `--play` and `--extract`) |

**Statistics flags** (all respect `-c`, `-e`, `-s`, `--from`, `--to`):

| Option | Description |
|--------|-------------|
| `-A`, `--avg` | Average detections per day per species, sorted by rate descending |
| `-m`, `--monthly` | With `--avg`: pivot the averages by calendar month |
| `--first-last` | First and last detection date per species, sorted by first seen |
| `--conf-stats` | Min / max / mean confidence score per species, sorted by mean descending |
| `--life-list` | Species grouped by the date first detected; `*` marks species seen on only one day |
| `--cooccur` | Top 20 species pairs co-occurring in the same recording file; with `-s`, lists all species sharing files with that species |
| `--streaks` | Longest consecutive-day detection streak and longest gap between detection days per species |

### `plot_detections.py` — visualise detections

Generates PNG charts from a database. Six chart types are available via `--plot`.

```
python plot_detections.py <db_name.db> [options]
```

| Option | Default | Description |
|--------|---------|-------------|
| `db_name` | (required) | Path to the SQLite database |
| `--plot TYPE` | `daily` | Chart type — see below |
| `-c`, `--confidence` | `0.75` | Minimum confidence threshold |
| `-e`, `--event` | `All` | Filter by event: `All`, `Sunrise`, `Sunset`, `Day` |
| `-s`, `--species` | (all) | Limit to a single species; accepts partial, case-insensitive names — prompts if ambiguous |
| `-n`, `--top-n` | `20` | Number of species for heatmap / topn / confidence / events plots |
| `-o`, `--output` | `<db_stem>[_<plot>].png` | Output PNG path |
| `--cmap` | `YlOrRd` | Matplotlib colormap for heatmap |
| `--site NAME` | (db filename) | Site name for plot titles |
| `--from DATE` | (none) | Start date inclusive |
| `--to DATE` | (none) | End date inclusive |

**Chart types (`--plot`):**

| Type | Description |
|------|-------------|
| `daily` | Stacked bar chart of detections per day (default) |
| `heatmap` | Species × hour-of-day detection heatmap |
| `confidence` | Confidence score histograms per species |
| `accumulation` | Cumulative unique-species count over time |
| `topn` | Horizontal bar chart of top-N species by total detections |
| `events` | Grouped bar chart comparing detections across recording events |

For a single-species `daily` plot, a photo is inset from `bird_photos/<Species_Name>.png` or fetched from Wikipedia if no local file exists.

### `gui_plot_detections.py` — interactive plot GUI

Tkinter-based GUI for exploring detections interactively. Provides the same six chart types as `plot_detections.py` in a tabbed window, with live controls and a Save button to export the current plot.

```
python gui_plot_detections.py [db_name.db] [options]
```

| Option | Default | Description |
|--------|---------|-------------|
| `db_name` | (none) | Database to open on launch; can also be selected via Browse |
| `-c`, `--confidence` | `0.75` | Initial confidence threshold |
| `-e`, `--event` | `All` | Initial event filter |
| `-s`, `--species` | (all) | Initial species filter (partial match supported) |
| `--site NAME` | (db filename) | Initial site label for plot titles |

**Controls:**

| Control | Description |
|---------|-------------|
| Database / Browse | Path to the SQLite database |
| Confidence | Slider (0–1) filtering detections by minimum BirdNET score |
| Event | Filter by recording event: All, Sunrise, Sunset, or Day |
| Species | Partial, case-insensitive species name filter — shows a picker if ambiguous |
| From / To | Date range filter (`DD/MM/YYYY`) |
| Site | Label shown in plot titles |
| Top-N | Number of species for heatmap, confidence, top-N, and events charts |
| Plot / Save | Manually regenerate or export the current chart |

**Appearance group** (controls enabled only when relevant to the active tab):

| Control | Applies to |
|---------|-----------|
| Color | Single-species daily bars, accumulation line, top-N bars |
| Line width | Accumulation step-line thickness |
| Colormap | Heatmap colour scale |

Plots regenerate automatically on tab switch, database selection, colormap change, color pick, and linewidth adjustment.

### `species_list.py` — print expected species

Prints the BirdNET species list expected for the Christchurch, NZ location and season (hardcoded to September). No arguments.

```
python species_list.py
```

## Tests

The test suite uses [pytest](https://docs.pytest.org/) and covers `proc_recordings.py`, `query_detections.py`, and `plot_detections.py`.

Install pytest if needed:

```
pip install pytest
```

**Fast unit tests** (no BirdNET model load, ~1 second):

```
pytest -m "not integration"
```

**End-to-end integration tests** — run `proc_recordings.py` against the recordings in `test_recordings/` using the real BirdNET model (~1–5 minutes):

```
pytest tests/test_integration.py -v
```

**Full suite:**

```
pytest
```

The integration tests are tagged `@pytest.mark.integration` and are deselected by default when using `-m "not integration"`. They verify that all 17 test recordings are processed, events and dates are parsed correctly, detections have valid confidence scores, and re-running is idempotent (no duplicate rows).

## WAV Filename Format

Two formats are supported:

- **Old (5 components):** `YYYY_MM_DD_HH_MM.WAV` — event defaults to `Sunrise`
- **New (6 components):** `<EVENT>_YYYY_MM_DD_HH_MM.WAV` — event codes: `SR`=Sunrise, `SS`=Sunset, `DA`=Day

## Database Schema

Single table `detection`:

| Column | Type | Notes |
|--------|------|-------|
| `file_name` | TEXT | Basename of the source WAV |
| `event` | TEXT | `Sunrise`, `Sunset`, or `Day` |
| `date` | TEXT | ISO datetime parsed from filename |
| `common_name` | TEXT | BirdNET common name; `DUMMY` for sentinel rows |
| `scientific_name` | TEXT | BirdNET scientific name; `DUMMY` for sentinel rows |
| `start_time` | REAL | Seconds within the recording |
| `end_time` | REAL | Seconds within the recording |
| `confidence` | REAL | BirdNET confidence 0–1; 0.0 for sentinel rows |

Sentinel `DUMMY` rows mark files that were processed but yielded no detections, preventing re-analysis on subsequent runs. Exclude them in queries: `WHERE confidence > 0 AND common_name != 'DUMMY'`.

## Data Layout

Multiple recording sessions are kept as separate directories, each with its own `.db`:

```
hackthorne/   →  hackthorne.db
ranui/        →  ranui.db
samsgully/    →  samsgully.db
```

Local bird photos (PNG, named `<Common_Name_With_Underscores>.png`) live in `bird_photos/` and are used by `plot_detections.py` when plotting a single species.

---

D. Q. McDonald — August 2025
