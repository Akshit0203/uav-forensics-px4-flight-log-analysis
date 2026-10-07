# 05: UAV Attack Surface, Advanced Acquisition & Challenges

This document covers the material at a **conceptual, forensic-awareness level**: what an examiner needs to understand about a UAV's exposure and about hard-to-reach evidence, not operational instructions for attacking a system.

---

## 1. Why Drone Forensics Is Needed

| Threat | Examples |
|---|---|
| Cross-border smuggling | Narcotics and weapons drops across the Punjab, Rajasthan and Jammu borders |
| Prison contraband | Drugs, phones and weapons delivered over walls |
| Espionage / reconnaissance | Overflights of defence installations and critical infrastructure. Deleted SD-card video recovered forensically has proven intent |
| Privacy violation | Photographing private property, resorts, individuals |
| Airspace violation | Flights near aerodromes and over crowds, interference with manned aircraft |
| Conflict use | Low-cost FPV / loitering munitions (Ukraine–Russia, Middle East) |

Roughly 20,000 DJI units are sold per month, and DIY builds are easy to assemble, so the volume of potential evidence keeps growing.

---

## 2. Artifact Map: The Whole System, Not Just the Aircraft

The correct term is **sUAS (small Unmanned Aircraft System)**: aircraft, payload, data links and ground station. Analyse the whole integrated system.

| Category | Artifacts |
|---|---|
| **Aircraft** | Flight controller (logs, parameters, UUID), MicroSD, internal flash/EEPROM, GNSS module, compass, collision-avoidance sensors, batteries (capacity → range), camera/payload |
| **Ground** | RC transmitter (often a smartphone/tablet app), FPV goggles, Wi-Fi extender, laptop running Mission Planner/QGC (`.tlog`, waypoint files) |
| **Cloud / back office** | Vendor cloud sync, image-processing servers, purchase and billing records |
| **Other** | Fingerprints/DNA on the airframe, OSINT (social-media posts of footage), purchase trail (serial → reseller → buyer) |

> **The 80 % rule:** the **GCS and sensor/payload data** usually provide about 80 % of the evidence: commands sent, actions taken and imagery captured.

Payload type shows purpose. A thermal or NIR camera on a "hobby" drone raises legitimate questions about intent.

---

## 3. Communication Attack Surface (Awareness)

Many consumer UAVs expose a wireless command-and-control and data-transfer link. An examiner should understand these exposures because they explain both how a drone could be interfered with and where live-acquisition opportunities exist. These are described here as **risk categories**, not as a how-to.

| Link / interface | Exposure (why it matters forensically) |
|---|---|
| **Wi-Fi C2** (e.g. some Parrot and DJI Wi-Fi models) | An unauthenticated or weakly-authenticated control link can be disrupted or taken over by a third party. Forensically: a "someone else flew it" claim can be tested against RC/link-state logs, and counter-UAS teams may lawfully capture a live link under authority |
| **Dedicated 2.4/5.8 GHz RC** | RF fingerprinting can attribute a transmitter; jamming leaves a signature (RC-loss events, failsafe triggers) in the log |
| **USB / debug interfaces** | Primary **lawful acquisition** path for an embedded Linux drone (see §4) |
| **Cellular (LTE/4G) C2** | See §6. Changes the whole investigative approach |

> **Lawful-use boundary:** live interception, de-authentication or takeover of a radio link is only appropriate for **authorised counter-UAS operations or sanctioned research**, under the relevant legal authority. In a courtroom-bound investigation, prefer **passive acquisition** of seized media so the evidence is not altered. Tools such as *Skyjack* exist and target Wi-Fi-controlled drones, but using them is an operational activity governed by law, not a forensic procedure.

---

## 4. Advanced Acquisition from Embedded-Linux Drones

Many drones (e.g. the DJI Phantom family) run Linux internally and expose network endpoints over USB. **With the device lawfully seized and documented**, an examiner can acquire data over that interface.

* Typical endpoints on older DJI Phantoms: a general CPU, a Wi-Fi-extender/GCS node running OpenWRT, and a camera node, each on the `192.168.1.x` subnet with vendor default credentials.
* Acquisition goal: a **bit-level image** of the storage partitions and a copy of the filesystem, taken to a working copy and hashed. Capture volatile state first if the device is powered.
* Use Brian Moran's **Live Response Collection** (or equivalent) for volatile data when the system is live.

### JFFS2 byte-swap gotcha

The general-purpose CPU often uses **JFFS2 over an MTD device**, and on DJI systems it is **byte-swapped**, so it will not mount directly on an analysis workstation.

* Dump every MTD partition, then **byte-swap** the image (e.g. `dd ... conv=swab`, or `jffs2dump` from `mtd-utils`) before mounting the working copy.
* JFFS2 is often layered on another filesystem, so a complete image means **dumping all pieces and reconstructing** before examination.

### SDK / API reality

Most flight data lives in **RAM**, and most FC software runs from flash, so little useful data persists after power loss — only sensor data on removable media reliably survives. Vendor apps and commercial tools frequently **will not extract everything**, so be prepared to build acquisition tooling from the SDK.

---

## 5. Chip-Level Recovery: JTAG & Chip-Off

For a crashed, burned or heavily damaged board where normal interfaces are dead:

| Technique | When | Notes |
|---|---|---|
| **JTAG** | Board intact but interfaces broken | Connect to the chip's test-access pins with a jig and read **raw binary** from memory |
| **Chip-off** | Connectors destroyed | Desolder the memory chip and read it in a dedicated reader |
| **Transistor/VLSI-level reads** | National-security-grade cases | Reconstruct state from a partially destroyed die. Used in high-profile recoveries |

| Limitation | Detail |
|---|---|
| Sealed / secured chips | Security fuses can block access |
| Volatile data | Does not survive power loss regardless of technique |
| Success not guaranteed | Reserved for high-priority cases due to cost and expertise |

---

## 6. Challenges & the Systems Approach

### Evolving C2 protocols

```
Wi-Fi  →  Bluetooth  →  dedicated RF  →  LTE / 4G
```

**Cellular-controlled drones** route control through commercial towers: harder to intercept by RF, but **easier to locate through carrier records** (subscriber, cell-site, timing). Standard RF-triangulation tooling does not help; the investigation shifts to lawful requests to the carrier.

### Vendor and system diversity

Many manufacturers, each with customised embedded systems, countless log formats and bespoke payloads. This is why the **80 % rule** (focus on GCS and sensor data) is practical.

### Regulatory framing

When building the legal case, look at the **capabilities of the onboard sensors and services**, not just the airframe:

* **Why** was a thermal / NIR camera mounted? A farmer or blogger has no legitimate need for it.
* **Where** was it flown? Restricted airspace?
* Were **clearances and a flight plan** obtained?
* Over ~2 kg the operator needs a **valid remote-pilot licence**.

> Raw data corroborates inferences; it is not the whole case. Regulatory violations, licensing gaps and flight-plan analysis carry equal weight. Correlate findings with the applicable statute (e.g. the relevant Bharatiya Nyaya Sanhita provisions) with a cyber-law professional.

---

## 7. Anti-Drone / Counter-UAS Measures (Reference)

Context for how a drone might have been brought down, which an examiner may need to explain:

| Category | Method |
|---|---|
| Detection / ID | RF fingerprinting, radar, acoustic, EO/IR |
| Soft kill | Signal / GPS disruption, geofencing, protocol takeover (authorised operations only) |
| Hard kill | Net / "tangle" interceptor drones, projectiles, directed energy |

Evidence of a counter-UAS takedown (sudden RC-loss, jamming indicators, abrupt failsafe) will appear in the logs and should be distinguished from pilot action or malfunction.
