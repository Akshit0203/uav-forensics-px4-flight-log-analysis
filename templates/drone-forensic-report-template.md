# Drone Forensic Report — Template

> Standard five-section format. Keep the language clear enough for a non-technical bench; attach raw logs and graphs as technical annexures.

| | |
|---|---|
| **Report ID** | e.g. `25/2025-26` (case number / fiscal year) |
| **Case reference** | |
| **Examiner / unit** | |
| **Date of examination** | |

---

## 1. Report ID
Case identifier for indexing.

## 2. Evidence Received
| Item | Description | Received from / by | Date | Condition | Serial(s) | Hash (SHA-256) |
|---|---|---|---|---|---|---|
| | | | | | | |

Attach photographs of the physical artifact and the chain-of-custody reference.

## 3. Forensic Tools & Methodology
- Imaging tool(s) and verification method (write-blocker, hashing)
- Decryption / parsing tools and versions
- Analysis environment (isolated workstation)
- Visualisation tools (3-D flight path, KML, plots)

> Prefer open-source tools so findings can be independently reproduced. Document everything to withstand cross-examination.

## 4. Analysis & Findings
For each finding record: **observation → source (topic/parameter/artifact) → inference**.

- **A. Device identification & serial numbers** — FC serial/UUID as the unique identifier; correlate with controller and media
- **B. Flight path & telemetry** — launch time, home point, altitude, waypoints vs actual, velocity; was there deviation into restricted airspace?
- **C. Payload & media recovery** — recovered/carved media, EXIF GPS + timestamp
- **D. System status & errors** — battery, vibration, GPS integrity, failsafe, flight-termination cause
- **E. Operator control** — flight mode, RC link state, stick inputs 5–10 s before the event; stored mission (premeditation)
- **F. Configuration review** — geofence, failsafe actions, circuit breakers, tamper indicators

## 5. Conclusion
Professional opinion: **intentional act vs genuine accident** (wind, mechanical failure). State what the evidence does **and does not** support, and the limits of the analysis.

---

## Annexures
- Machine-readable summary (JSON)
- Event timeline (CSV)
- GNSS track + KML
- Parameter dump (CSV)
- Flight-reconstruction figures
- Raw tool reports (Flight Review / Mission Planner / DatCon)
