# Analysis Output

Every file here is **regenerated** from the evidence log by:

```bash
python tools/ulog_forensic_extractor.py evidence/ulog/12127aab-02aa-4e98-890a-f17523ebba0c.ulg -o analysis/output
```

| File | Contents |
|---|---|
| `summary.json` | Full machine-readable evidence summary (incl. hashes and post-processing hash verification) |
| `report.md` | Human-readable triage report |
| `timeline.csv` | Unified event timeline (messages, arming, flight modes, land detector, dropouts) |
| `gps_track.csv` | GNSS track (UTC, lat/lon/alt, fix, satellites, EPH/EPV) |
| `flight_path.kml` | Google Earth overlay of the GNSS track |
| `parameters.csv` | All 980 parameters (name, type, value, default, non-default flag) |
| `topics.csv` | Logged uORB topics with sample counts and approximate rates |

These are committed so the repository is reviewable without running anything; the CI job and `tests/` prove they stay reproducible.
