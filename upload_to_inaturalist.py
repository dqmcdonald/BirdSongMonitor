#!/usr/bin/env python3
# Upload BirdNET detections to iNaturalist as audio observations.
# One observation is created per date per species (using the best-confidence
# detection of the day for the timestamp and optional audio clip).
#
# Get your API token from: https://www.inaturalist.org/users/api_token
# Store it in the INATURALIST_TOKEN environment variable or pass --token.
#
# Location per database is read from locations.json (if present) keyed by the
# db stem name, e.g. {"samsgully": {"lat": -43.627, "lon": 172.726, "name": "Sam's Gully"}}.
# Falls back to the default Christchurch coordinates if not found.
#
# D. Q. McDonald  June 2026

import argparse
import json
import os
import sys
import sqlite3
import tempfile
import wave
from datetime import datetime

import requests

INATURALIST_API = "https://api.inaturalist.org/v1"
DEFAULT_LAT = -43.62674558206582
DEFAULT_LON = 172.72602916819974
LOCATIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locations.json")


def load_location(db_name: str, lat_arg: float, lon_arg: float) -> tuple[float, float, str]:
    """Return (lat, lon, place_name) from args, locations.json, or project default."""
    if lat_arg is not None and lon_arg is not None:
        return lat_arg, lon_arg, ""
    db_stem = os.path.splitext(os.path.basename(db_name))[0]
    if os.path.exists(LOCATIONS_FILE):
        with open(LOCATIONS_FILE) as f:
            locs = json.load(f)
        if db_stem in locs:
            entry = locs[db_stem]
            return entry["lat"], entry["lon"], entry.get("name", db_stem)
    return DEFAULT_LAT, DEFAULT_LON, "Christchurch, New Zealand"


def _parse_date(date_str: str) -> str:
    """Accept DD/MM/YYYY or YYYY-MM-DD and return YYYY-MM-DD."""
    if date_str and '/' in date_str:
        parts = date_str.split('/')
        if len(parts) == 3:
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return date_str


def query_detections(db_name: str, species: str, date: str,
                     confidence: float) -> dict[str, list]:
    """Return detections grouped by date: {YYYY-MM-DD: [row, ...]}."""
    conn = sqlite3.connect(db_name)
    cur = conn.cursor()

    params: tuple = (confidence, species)
    date_clause = ""
    if date:
        date_clause = " AND DATE(date) = ?"
        params += (date,)

    rows = cur.execute(f"""
        SELECT file_name, date, start_time, end_time, confidence, scientific_name, event
        FROM detection
        WHERE confidence > ? AND common_name = ? AND common_name != 'DUMMY' {date_clause}
        ORDER BY date, confidence DESC
    """, params).fetchall()
    conn.close()

    by_date: dict[str, list] = {}
    for row in rows:
        day = str(row[1])[:10]
        by_date.setdefault(day, []).append(row)
    return by_date


def extract_clip(recordings_dir: str, file_name: str,
                 start_time: float, end_time: float) -> str | None:
    """Extract a WAV segment to a temp file; returns path or None on error."""
    wav_path = os.path.join(recordings_dir, file_name)
    if not os.path.exists(wav_path):
        print(f"  Audio not found: {wav_path}", file=sys.stderr)
        return None
    try:
        with wave.open(wav_path, 'r') as wf:
            wav_params = wf.getparams()
            rate = wf.getframerate()
            wf.setpos(int(start_time * rate))
            frames = wf.readframes(int(end_time * rate) - int(start_time * rate))
        tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        tmp.close()
        with wave.open(tmp.name, 'w') as wf_out:
            wf_out.setparams(wav_params)
            wf_out.writeframes(frames)
        return tmp.name
    except Exception as e:
        print(f"  Clip extraction error: {e}", file=sys.stderr)
        return None


def upload_observation(token: str, species: str, sci_name: str,
                       observed_on: str, time_str: str,
                       lat: float, lon: float, place_name: str,
                       confidence: float, n_detections: int, event: str,
                       audio_path: str | None, dry_run: bool) -> str | None:
    """POST an observation to iNaturalist; returns observation ID or None."""
    description = (
        f"Detected by BirdNET during {event} recording "
        f"(best confidence {confidence:.2f}, {n_detections} detection(s) that day)."
    )
    payload = {
        "observation": {
            "taxon_name": sci_name,
            "observed_on_string": f"{observed_on} {time_str}",
            "time_zone": "Pacific/Auckland",
            "latitude": lat,
            "longitude": lon,
            "place_guess": place_name,
            "description": description,
            "tag_list": "BirdNET,bioacoustics,automated",
            "captive_flag": False,
        }
    }

    if dry_run:
        print(f"  [DRY RUN] {species} ({sci_name})")
        print(f"            {observed_on} {time_str}, {event}, conf={confidence:.3f}, "
              f"{n_detections} detection(s)")
        print(f"            lat={lat:.5f}, lon={lon:.5f}, place='{place_name}'")
        if audio_path:
            print(f"            + audio: {audio_path}")
        return "DRY_RUN"

    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.post(f"{INATURALIST_API}/observations",
                         json=payload, headers=headers, timeout=30)
    if resp.status_code not in (200, 201):
        print(f"  Upload failed ({resp.status_code}): {resp.text[:300]}", file=sys.stderr)
        return None

    obs_id = str(resp.json()["id"])
    print(f"  Created: https://www.inaturalist.org/observations/{obs_id}")

    if audio_path:
        with open(audio_path, 'rb') as f:
            sound_resp = requests.post(
                f"{INATURALIST_API}/observation_sounds",
                headers=headers,
                data={"observation_sound[observation_id]": obs_id},
                files={"file": ("detection.wav", f, "audio/wav")},
                timeout=60,
            )
        if sound_resp.status_code in (200, 201):
            print(f"  Audio attached.")
        else:
            print(f"  Audio attach failed ({sound_resp.status_code}): "
                  f"{sound_resp.text[:200]}", file=sys.stderr)

    return obs_id


def main():
    parser = argparse.ArgumentParser(
        prog="upload_to_inaturalist",
        description="Upload BirdNET detections to iNaturalist (one observation per date per species)",
    )
    parser.add_argument("db_name", help="SQLite detection database")
    parser.add_argument("-s", "--species", required=True,
                        help="Common name of species to upload")
    parser.add_argument("-d", "--date", default=None, metavar="DATE",
                        help="Restrict to a single date (DD/MM/YYYY or YYYY-MM-DD)")
    parser.add_argument("-c", "--confidence", type=float, default=0.75,
                        help="Minimum confidence threshold (default: 0.75)")
    parser.add_argument("--lat", type=float, default=None, help="Latitude override")
    parser.add_argument("--lon", type=float, default=None, help="Longitude override")
    parser.add_argument("--token", default=None,
                        help="iNaturalist API token (or set INATURALIST_TOKEN env var)")
    parser.add_argument("--recordings-dir", dest="recordings_dir", default=None,
                        metavar="DIR",
                        help="Directory with source WAV files (default: <db_stem>/)")
    parser.add_argument("--attach-audio", dest="attach_audio", action="store_true",
                        help="Attach the best-confidence detection as an audio clip")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="Show what would be uploaded without making API calls")
    args = parser.parse_args()

    token = args.token or os.environ.get("INATURALIST_TOKEN")
    if not token and not args.dry_run:
        sys.exit("Error: provide --token or set INATURALIST_TOKEN env var.\n"
                 "Get your token from: https://www.inaturalist.org/users/api_token")

    if not os.path.exists(args.db_name):
        sys.exit(f"Error: database not found: {args.db_name}")

    lat, lon, place_name = load_location(args.db_name, args.lat, args.lon)

    recordings_dir = args.recordings_dir or os.path.splitext(args.db_name)[0]
    if args.attach_audio and not os.path.isdir(recordings_dir):
        sys.exit(f"Error: recordings directory not found: {recordings_dir}\n"
                 f"Use --recordings-dir to specify the WAV file location.")

    date = _parse_date(args.date) if args.date else None
    by_date = query_detections(args.db_name, args.species, date, args.confidence)

    if not by_date:
        sys.exit(f"No detections found for '{args.species}' "
                 f"with confidence > {args.confidence:.2f}")

    print(f"\nUploading {len(by_date)} observation(s) for '{args.species}' "
          f"from {os.path.basename(args.db_name)}")
    print(f"Location: {place_name} (lat={lat:.5f}, lon={lon:.5f})\n")

    uploaded = failed = 0
    for day, rows in sorted(by_date.items()):
        file_name, det_date, start_time, end_time, conf, sci_name, event = rows[0]
        dt = datetime.strptime(str(det_date), "%Y-%m-%d %H:%M:%S")
        time_str = dt.strftime("%H:%M:%S")

        print(f"  {day}  {len(rows)} detection(s), best conf={conf:.3f}, event={event}")

        audio_path = None
        if args.attach_audio:
            audio_path = extract_clip(recordings_dir, file_name, start_time, end_time)

        obs_id = upload_observation(
            token=token or "",
            species=args.species,
            sci_name=sci_name,
            observed_on=day,
            time_str=time_str,
            lat=lat,
            lon=lon,
            place_name=place_name,
            confidence=conf,
            n_detections=len(rows),
            event=event,
            audio_path=audio_path,
            dry_run=args.dry_run,
        )

        if audio_path and os.path.exists(audio_path):
            os.unlink(audio_path)

        if obs_id:
            uploaded += 1
        else:
            failed += 1

    print(f"\n{uploaded} observation(s) uploaded" +
          (f", {failed} failed" if failed else "") + ".")


if __name__ == "__main__":
    main()
