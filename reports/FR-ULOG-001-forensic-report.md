# Drone Forensic Report — FR-ULOG-001

> **Training / research report.** Prepared to demonstrate PX4 ULog forensic analysis on a public sample log. Not a real criminal investigation.

| | |
|---|---|
| **Report ID** | FR-ULOG-001 |
| **Case reference** | UAV telemetry examination (training) |
| **Evidence item** | E-01 — `12127aab-02aa-4e98-890a-f17523ebba0c.ulg` |
| **Examiner** | Akshit, Digital Forensics |
| **Date of examination** | 2026-10-07 |
| **Classification** | Educational |

---

## 1. Evidence Received

| Item | Description | Hash (SHA-256) |
|---|---|---|
| E-01 | PX4 ULog flight log, 921,631 bytes, recovered as `/fs/microsd/log/2021-04-21/06_30_58.ulg` | `68d1020f688109f027dba08d2950247cc0ae34aaefdcf37e4a7d60838f3e1aa3` |
| E-02 | Parameter dump, `vehicle.params` (980 parameters) | `b9f5b825a94aa37bdd97e36a28422e0a13b4b6d5096415c7bf43856d1f1ec119` |
| E-03 | Non-default parameters, `non-default.params` (584 parameters) | `f9ff8e8e3a67b829fb42f89920d191f7d9f0f2b43b463bb45387d2264ba5ec5e` |
| E-04 | PX4 Flight Review main report (PDF) | `e15506dcef077ece6a2eb1d58a7d646ac3c0f959cfa250b97a1d78635a1cd3db` |
| E-05 | PX4 Flight Review PID analysis (PDF) | `d7fcaff891ab4d544548f77c7baaf69f2fc84e54721696a455b55020d5e9d5cc` |

Integrity was verified before and after analysis. The extractor recorded `hash_verified_after_processing: true`.

---

## 2. Forensic Tools & Methodology

| Tool | Use |
|---|---|
| `ulog_forensic_extractor.py` (this repo, Python stdlib only) | Hashing, binary decode, timeline, GNSS/KML/CSV export, parameter dump |
| PX4 Flight Review | Independent plots, 3-D replay, PID analysis |
| `plot_flight_profile.py` + matplotlib | Flight-reconstruction figure |

**Methodology:** analysis performed on copies only; evidence hashed before and after; every quantitative finding pinned by an automated regression test (`tests/`) and cross-checked between two independent tools. Boot-relative timestamps anchored to GNSS UTC.

---

## 3. Analysis & Findings

### 3.1 Device identification
PX4 **1.11.2** (git `8583f1da…`, branch **`v1.11.2_w_rc_sysid`**, self-built) on a **CubePilot Cube Orange** (STM32H7), airframe `SYS_AUTOSTART = 13014` (Standard VTOL, `babyshark.main.mix`). Flight-controller **UUID `000600000000383638393239510d0035002d`** uniquely identifies the board. Lifetime flight time stored in the FC is **6 h 07 min 15 s**, so this was not a new unit.

### 3.2 Time and place
Log window **2021-04-21 06:30:57.630 – 06:31:04.954 UTC** (7.324 s), anchored by GNSS. Position **63.41706° N, 10.40822° E** (Trondheim, Norway), on a rooftop. Horizontal footprint 1.84 m × 0.62 m, 14–15 satellites, HDOP 0.70–0.75. The on-card filename (UTC 06:30:58) corroborates the GNSS-derived start to within 0.4 s.

### 3.3 Operator control
**MANUAL** mode throughout. RC receiver healthy: 18 channels, `rc_lost = false`, 0 lost frames, no failsafe. **No stored mission (0 waypoints).** The vehicle was under direct human control; it was not flying an autonomous route.

### 3.4 Flight envelope
Land detector reports **1.148 s airborne** (takeoff 06:31:00.803, landing 06:31:01.951). Peak thrust demand 0.27, max tilt **1.1°**. The EKF2 "height" decays near-monotonically from 1.18 m to 0.15 m across the whole window with no slope change at takeoff/landing, which identifies it as **estimator convergence after alignment, not a climb**. Flight Review's "Max Altitude Difference 1 m" is the same artefact.

### 3.5 Navigation integrity
`vehicle_local_position.xy_valid` is **false** for the entire log. EKF2 **never fused GPS** because the quality gates `MAX_HORZ_ERR` (EPH 2.5–3.3 m vs the 3.0 m gate) and `MAX_SPD_ERR` failed, and never passed for the 10 s that `EKF2_REQ_GPS_H` requires. Arming was permitted only because `COM_ARM_WO_GPS = 1`. The vehicle had **no horizontal position solution** and could not have navigated autonomously.

### 3.6 System health
No hardware fault: IMU vibration ≤ 0.001, zero accelerometer clipping, stable magnetometer, no filter or innovation faults. Battery 6S at 23.34–23.46 V (~3.9 V/cell), ~74 % remaining, no sag under the thrust pulse. Current never exceeds ~1 A, which is implausible for VTOL lift, so **current sensing is treated as unreliable** and `discharged_mah` is excluded from conclusions.

### 3.7 Control-surface activity
Four fixed-wing pitch-surface deflections to 0.72 (with matching roll) between 06:31:01.5 and 06:31:04.3, mostly **after landing**, with zero forward thrust and repeated 60 °/s pitch-rate setpoints the grounded airframe could not follow. On **system-identification firmware** this matches a **deliberate, pilot-commanded control-surface check**.

### 3.8 Configuration review
No safety circuit breakers set (`CBRK_* = 0`). However **geofence is disabled** (`GF_MAX_HOR_DIST = GF_MAX_VER_DIST = 0`), **RC-loss failsafe action is disabled** (`NAV_RCL_ACT = 0`) and airspeed checks are off (`ASPD_DO_CHECKS = 0`). No in-flight parameter changes.

### 3.9 Log integrity
0 truncated bytes, 1 × 30 ms dropout, 12 sync markers, steady 200 Hz sampling. Flight Review and the independent parser agree on every shared metric.

---

## 4. Conclusion

The evidence records a **short, manually piloted ground-effect hop or run-up test** of a self-built Cube Orange VTOL on a rooftop in Trondheim on 2021-04-21, lasting about one second airborne within a 7.3 s log. The data shows:

* **a human in direct control** (MANUAL, healthy RC, no mission);
* **no autonomous navigation capability** during the session (no GPS fusion);
* **no climb or horizontal translation** of forensic significance;
* **no hardware, sensor or battery malfunction** and **no failsafe**;
* deliberate **control-surface checks** consistent with system-ID testing;
* safety features (**geofence, RC-loss action**) deliberately disabled.

A claim that this vehicle *"flew away autonomously"* or *"malfunctioned"* during this log is **not supported** by the evidence. These findings are limited to the 7.3 s window; prior flights would require the older logs retained on the SD card.

---

## 5. Annexures

| Annexure | File |
|---|---|
| A — Machine-readable summary | [`analysis/output/summary.json`](../analysis/output/summary.json) |
| B — Triage report | [`analysis/output/report.md`](../analysis/output/report.md) |
| C — Event timeline | [`analysis/output/timeline.csv`](../analysis/output/timeline.csv) |
| D — GNSS track + KML | [`analysis/output/gps_track.csv`](../analysis/output/gps_track.csv), [`flight_path.kml`](../analysis/output/flight_path.kml) |
| E — Parameters | [`analysis/output/parameters.csv`](../analysis/output/parameters.csv) |
| F — Flight reconstruction figure | [`analysis/figures/flight_profile.png`](../analysis/figures/flight_profile.png) |
| G — Flight Review PDFs | [`evidence/flight-review/`](../evidence/flight-review/) |

*Examiner: Akshit — 2026-10-07*
