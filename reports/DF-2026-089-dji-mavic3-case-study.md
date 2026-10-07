# Drone Forensic Report — DF-2026-089 (Case Study)

> **Training exercise.** A constructed unauthorised-overflight scenario used to practise the full report format end-to-end. Identifying details are redacted; this is **not** a real investigation and must not be read as one. Scanned pages: [`assets/sample-report/`](../assets/sample-report/).

| | |
|---|---|
| **Report ID** | DF-2026-089 (23/26) |
| **Target device** | DJI Mavic 3 Classic |
| **Firmware** | v01.00.1200 |
| **Case reference** | Unauthorised overflight / security breach |
| **Examiner** | *[redacted]*, Digital Forensics Unit |
| **Date of examination** | *[redacted]*, 2026 |

---

## 1. Evidence Received

| Item | Description |
|---|---|
| Item 01 | DJI Mavic 3 Classic (S/N `1581F3PBB2000X`) — recovered with structural damage to the front-right propeller and gimbal |
| Item 02 | DJI RC-N1 remote controller (S/N `3W5CK1CXXXXX`) |
| Item 03 | SanDisk Extreme 64 GB MicroSD recovered from the drone's onboard storage slot |

---

## 2. Forensic Tools & Methodology

| Aspect | Detail |
|---|---|
| Extraction tools | Oxygen Forensic Detective v16.2, Cellebrite UFED v7.62, DatCon v3 & R2 (DAT decryption) |
| Environment | Isolated Linux forensic workstation running open-source parser scripts |
| Methodology | Physical imaging of the MicroSD; logical extraction of the mobile GCS app; decryption of embedded `.DAT` internal logs and `.TXT` flight records |

---

## 3. Analysis & Findings

### A. Device identification & serial numbers
The Master Controller ID (MCID) from the internal configuration files matches the physical serial on the mainboard and on the remote controller, confirming **unity of the evidence** (all three items belong together).

### B. Flight path & telemetry reconstruction
| Field | Value |
|---|---|
| Launch date/time | 2026-*[redacted]* 17:41:02 UTC |
| Home point | 28°27′ N, 77°02′ E |
| Coordinates of interest | Secured perimeter |
| Max altitude | 122 m AGL |
| Waypoint anomaly | Telemetry shows a **direct deviation** from the pre-planned agricultural-survey route over a restricted industrial zone (28°28′ N, 77°03′ E) |
| Velocity profile | Accelerated to **19.2 m/s in Sport Mode** during the unauthorised descent phase |

### C. Payload & media recovery
| Field | Value |
|---|---|
| Deleted media | Carving unallocated space on the 64 GB card recovered **14 high-resolution JPEGs** |
| EXIF metadata | Recovered photos carry exact GPS latitude, longitude and absolute altitude tags matching the time the drone hovered above the restricted facility |

### D. System status & errors
| Field | Value |
|---|---|
| Battery | Normal state of health, **42 % remaining** at motor stoppage |
| Flight termination | **No** critical hardware failure (no ESC or compass error) logged. Motor stop triggered by a **manual RC stick-command combination** at 17:52:14 UTC → controlled or crash landing in the restricted zone |

---

## 4. Conclusion

Digital evidence from the UAV and MicroSD confirms that **Item 01 flew over the restricted zone at 17:48 UTC and captured high-resolution imagery**. The flight logs show **deliberate manual pilot intervention**, not a technical malfunction:

* a manual deviation from the programmed agricultural route into restricted airspace;
* Sport-Mode acceleration during the descent;
* 14 deleted-but-recovered geotagged photos of the facility;
* a manual stick-command motor stop with no logged hardware fault.

---

## 5. Methodology Notes (what this case study demonstrates)

| Technique shown | Where it is covered generally |
|---|---|
| Serial/MCID correlation for evidence unity | [doc 01 §2](../docs/01-forensic-methodology.md), [doc 02 §1](../docs/02-physical-artifacts-and-sd-card-acquisition.md) |
| DJI `.DAT` / `.TXT` decryption with DatCon | [doc 04 §1](../docs/04-log-formats-and-toolchain.md) |
| Deleted-media carving + EXIF geolocation | [doc 02 §3](../docs/02-physical-artifacts-and-sd-card-acquisition.md) |
| Distinguishing manual intent from malfunction | [doc 01 §6](../docs/01-forensic-methodology.md), [doc 03 §5–§7](../docs/03-ulog-telemetry-analysis.md) |

*Redacted training report — DF-2026-089.*
