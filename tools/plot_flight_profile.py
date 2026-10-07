#!/usr/bin/env python3
"""
plot_flight_profile.py
======================

Renders a single annex-ready figure that reconstructs the flight from a PX4
ULog: height, operator/controller demand, power and GNSS quality on a shared
time axis, with the arming window and airborne window shaded.

Uses the zero-dependency parser from ulog_forensic_extractor.py; only this
plotting step needs matplotlib (pip install matplotlib).

Usage:
    python plot_flight_profile.py <log.ulg> [-o figure.png]
"""

from __future__ import annotations

import argparse
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ulog_forensic_extractor import ULog, transitions  # noqa: E402


def secs(recs):
    return [r["timestamp"] / 1e6 for r in recs]


def windows(recs, key, active):
    """[(start_s, end_s)] where recs[key] == active."""
    out, start = [], None
    for r in recs:
        on = r.get(key) == active
        t = r["timestamp"] / 1e6
        if on and start is None:
            start = t
        elif not on and start is not None:
            out.append((start, t))
            start = None
    if start is not None:
        out.append((start, recs[-1]["timestamp"] / 1e6))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("ulog")
    ap.add_argument("-o", "--output", default="flight_profile.png")
    args = ap.parse_args(argv)

    log = ULog(args.ulog)
    lp = log.topic("vehicle_local_position")
    ac0 = log.topic("actuator_controls_0")
    ac1 = log.topic("actuator_controls_1")
    bat = log.topic("battery_status")
    gps = log.topic("vehicle_gps_position")
    vs = log.topic("vehicle_status")
    land = log.topic("vehicle_land_detected")

    armed = windows(vs, "arming_state", 2)
    airborne = windows(land, "landed", False)

    fig, ax = plt.subplots(4, 1, figsize=(12, 11), sharex=True,
                           gridspec_kw={"height_ratios": [1.2, 1.2, 1, 1]})
    fig.suptitle("Flight reconstruction - %s" % os.path.basename(args.ulog), fontsize=13, fontweight="bold")

    def shade(a):
        for s, e in armed:
            a.axvspan(s, e, color="#f4c7c3", alpha=0.35, lw=0)
        for s, e in airborne:
            a.axvspan(s, e, color="#9fc5e8", alpha=0.55, lw=0)
        a.grid(alpha=0.3)

    # 1. Height
    shade(ax[0])
    ax[0].plot(secs(lp), [-r["z"] for r in lp], color="#1f4e79", lw=1.6, label="EKF2 height above origin")
    ax[0].set_ylabel("Height [m]")
    ax[0].legend(loc="upper left", fontsize=8)

    # 2. Controller demand
    shade(ax[1])
    ax[1].plot(secs(ac0), [r["control"][3] for r in ac0], color="black", lw=1.4, label="MC thrust (up)")
    ax[1].plot(secs(ac0), [r["control"][0] for r in ac0], color="#c55a11", lw=1, label="MC roll")
    ax[1].plot(secs(ac0), [r["control"][1] for r in ac0], color="#2e7d32", lw=1, label="MC pitch")
    if ac1:
        ax[1].plot(secs(ac1), [r["control"][1] for r in ac1], color="#2e7d32", lw=1, ls="--",
                   label="FW pitch surface")
    ax[1].set_ylabel("Normalised demand")
    ax[1].legend(loc="upper left", fontsize=8, ncol=4)

    # 3. Power
    shade(ax[2])
    ax[2].plot(secs(bat), [r["voltage_v"] for r in bat], color="#7030a0", lw=1.4, label="Battery voltage")
    ax[2].set_ylabel("Voltage [V]")
    ax2b = ax[2].twinx()
    ax2b.plot(secs(bat), [r["remaining"] * 100 for r in bat], color="#999999", lw=1, ls=":", label="Remaining %")
    ax2b.set_ylabel("Remaining [%]")
    ax[2].legend(loc="upper left", fontsize=8)

    # 4. GNSS quality
    shade(ax[3])
    ax[3].plot(secs(gps), [r["eph"] for r in gps], color="#bf9000", lw=1.4, label="EPH [m]")
    ax[3].axhline(log.params.get("EKF2_REQ_EPH", (None, 3.0))[1], color="#bf9000", ls="--", lw=1,
                  label="EKF2_REQ_EPH gate")
    ax3b = ax[3].twinx()
    ax3b.step(secs(gps), [r["satellites_used"] for r in gps], color="#0b5394", lw=1, where="post")
    ax3b.set_ylabel("Satellites")
    ax[3].set_ylabel("EPH [m]")
    ax[3].set_xlabel("Time since boot [s]   (red = ARMED, blue = AIRBORNE per land detector)")
    ax[3].legend(loc="upper left", fontsize=8)

    for ts, _, msg in log.logged_messages:
        for a in ax:
            a.axvline(ts / 1e6, color="#666666", lw=0.8, ls="-.")
        ax[0].annotate(msg.replace("[commander] ", ""), (ts / 1e6, ax[0].get_ylim()[1]), rotation=90,
                       fontsize=7, va="top", ha="right", color="#444444")

    fig.tight_layout(rect=(0, 0, 1, 0.97))
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    fig.savefig(args.output, dpi=130)
    print("[+] Figure written to %s" % os.path.abspath(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
