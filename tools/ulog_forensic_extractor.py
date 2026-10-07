#!/usr/bin/env python3
"""
ulog_forensic_extractor.py
==========================

Zero-dependency forensic triage tool for PX4 ULog (.ulg) flight logs.

The tool parses the ULog binary format directly (no pyulog / numpy needed), so
an independent examiner can reproduce every number in the report with nothing
more than a stock Python 3.8+ interpreter.

What it produces (in the chosen output directory):

    summary.json          Machine-readable evidence summary
    report.md             Human-readable triage report (annex-ready)
    timeline.csv          Unified event timeline (log messages, arming,
                          nav-state changes, land detector, dropouts)
    gps_track.csv         GNSS track (UTC, lat, lon, alt, fix, sats, eph)
    flight_path.kml       Google Earth overlay of the GNSS track
    parameters.csv        Full parameter dump (name, type, value)
    topics.csv            Logged uORB topics with sample counts and rates

Evidence integrity:
    The input file is opened read-only and hashed (MD5 / SHA-1 / SHA-256)
    before parsing. Re-run the tool against the master copy and compare the
    hashes in summary.json to prove the working copy was not altered.

ULog format reference:
    https://docs.px4.io/main/en/dev_log/ulog_file_format.html

Usage:
    python ulog_forensic_extractor.py <log.ulg> [-o OUTPUT_DIR]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import struct
import sys
from collections import OrderedDict, defaultdict

__version__ = "1.0.0"

ULOG_MAGIC = b"ULog\x01\x12\x35"

# ULog primitive types -> (struct code, size in bytes)
PRIMITIVES = {
    "int8_t": ("b", 1),
    "uint8_t": ("B", 1),
    "int16_t": ("h", 2),
    "uint16_t": ("H", 2),
    "int32_t": ("i", 4),
    "uint32_t": ("I", 4),
    "int64_t": ("q", 8),
    "uint64_t": ("Q", 8),
    "float": ("f", 4),
    "double": ("d", 8),
    "bool": ("?", 1),
    "char": ("c", 1),
}

LOG_LEVELS = {
    0: "EMERG", 1: "ALERT", 2: "CRIT", 3: "ERROR",
    4: "WARNING", 5: "NOTICE", 6: "INFO", 7: "DEBUG",
}

# PX4 vehicle_status.nav_state enumeration (v1.11 – v1.14)
NAV_STATES = {
    0: "MANUAL", 1: "ALTCTL", 2: "POSCTL", 3: "AUTO_MISSION", 4: "AUTO_LOITER",
    5: "AUTO_RTL", 6: "AUTO_RCRECOVER", 7: "AUTO_RTGS", 8: "AUTO_LANDENGFAIL",
    9: "AUTO_LANDGPSFAIL", 10: "ACRO", 11: "UNUSED", 12: "DESCEND",
    13: "TERMINATION", 14: "OFFBOARD", 15: "STAB", 16: "UNUSED2",
    17: "AUTO_TAKEOFF", 18: "AUTO_LAND", 19: "AUTO_FOLLOW_TARGET",
    20: "AUTO_PRECLAND", 21: "ORBIT", 22: "AUTO_VTOL_TAKEOFF",
}

ARMING_STATES = {
    0: "INIT", 1: "STANDBY", 2: "ARMED", 3: "STANDBY_ERROR",
    4: "SHUTDOWN", 5: "IN_AIR_RESTORE",
}

VEHICLE_TYPES = {0: "UNKNOWN", 1: "ROTARY_WING", 2: "FIXED_WING", 3: "ROVER", 4: "AIRSHIP"}

# estimator_status.gps_check_fail_flags bit positions (PX4 v1.11 – v1.13)
GPS_CHECK_BITS = {
    0: "GPS_FIX", 1: "MIN_SAT_COUNT", 2: "MIN_PDOP", 3: "MAX_HORZ_ERR (eph > EKF2_REQ_EPH)",
    4: "MAX_VERT_ERR (epv > EKF2_REQ_EPV)", 5: "MAX_SPD_ERR (sacc > EKF2_REQ_SACC)",
    6: "MAX_HORZ_DRIFT", 7: "MAX_VERT_DRIFT", 8: "MAX_HORZ_SPD_ERR", 9: "MAX_VERT_SPD_ERR",
}

GPS_FIX = {0: "NONE", 1: "NONE", 2: "2D", 3: "3D", 4: "DGPS", 5: "RTK_FLOAT", 6: "RTK_FIXED"}


# --------------------------------------------------------------------------- #
#  ULog parser
# --------------------------------------------------------------------------- #
class ULogFormat:
    """A message format definition ('F' message)."""

    def __init__(self, name: str, fields: list[tuple[str, str, int]]):
        self.name = name
        self.fields = fields  # (type, field_name, array_len or 0)


class ULog:
    """Minimal, read-only ULog parser focused on forensic extraction."""

    def __init__(self, path: str):
        self.path = path
        self.version = None
        self.start_timestamp_us = None
        self.compat_flags = b""
        self.incompat_flags = b""
        self.formats: dict[str, ULogFormat] = {}
        self.info: "OrderedDict[str, object]" = OrderedDict()
        self.info_multi: dict[str, list] = defaultdict(list)
        self.params: "OrderedDict[str, tuple[str, object]]" = OrderedDict()
        self.param_changes: list[tuple[int, str, object]] = []
        self.default_params: dict[str, object] = {}
        self.subscriptions: dict[int, tuple[str, int]] = {}  # msg_id -> (name, multi_id)
        self.data: dict[tuple[str, int], list[dict]] = defaultdict(list)
        self.logged_messages: list[tuple[int, str, str]] = []  # (ts, level, text)
        self.dropouts: list[tuple[int, int]] = []  # (ts_before, duration_ms)
        self.sync_count = 0
        self.message_type_counts: dict[str, int] = defaultdict(int)
        self.corrupt_bytes = 0
        self._last_ts = 0
        self._data_ts: list[int] = []  # timestamps of 'D' messages in file order
        self._dropout_idx: list[tuple[int, int]] = []  # (index into _data_ts, duration_ms)
        self._parse()

    # -- format handling ---------------------------------------------------- #
    @staticmethod
    def _parse_type(type_str: str) -> tuple[str, int]:
        if "[" in type_str:
            base, n = type_str.split("[", 1)
            return base, int(n.rstrip("]"))
        return type_str, 0

    def _add_format(self, payload: bytes) -> None:
        text = payload.decode("ascii", errors="replace")
        name, body = text.split(":", 1)
        fields = []
        for item in body.split(";"):
            item = item.strip()
            if not item:
                continue
            type_str, field_name = item.rsplit(" ", 1)
            base, n = self._parse_type(type_str)
            fields.append((base, field_name, n))
        self.formats[name] = ULogFormat(name, fields)

    def _decode(self, fmt_name: str, buf: bytes, off: int) -> tuple[dict, int]:
        """Decode a struct of type fmt_name starting at buf[off]. Returns (dict, new_off)."""
        out = {}
        fmt = self.formats[fmt_name]
        for base, fname, n in fmt.fields:
            count = n if n else 1
            if base in PRIMITIVES:
                code, size = PRIMITIVES[base]
                need = size * count
                if off + need > len(buf):
                    # Trailing padding is allowed to be truncated in ULog.
                    break
                if fname.startswith("_padding"):
                    off += need
                    continue
                if base == "char":
                    raw = buf[off:off + count]
                    out[fname] = raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
                else:
                    vals = struct.unpack_from("<%d%s" % (count, code), buf, off)
                    out[fname] = list(vals) if n else vals[0]
                off += need
            else:
                # Nested message type
                if n:
                    items = []
                    for _ in range(count):
                        val, off = self._decode(base, buf, off)
                        items.append(val)
                    out[fname] = items
                else:
                    out[fname], off = self._decode(base, buf, off)
        return out, off

    @staticmethod
    def _decode_value(type_str: str, raw: bytes):
        base, n = ULog._parse_type(type_str)
        if base == "char":
            return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        code, size = PRIMITIVES[base]
        count = n if n else 1
        vals = struct.unpack_from("<%d%s" % (count, code), raw, 0)
        return list(vals) if n else vals[0]

    def _parse_kv(self, payload: bytes, offset: int = 0):
        key_len = payload[offset]
        key = payload[offset + 1: offset + 1 + key_len].decode("ascii", errors="replace")
        raw = payload[offset + 1 + key_len:]
        type_str, name = key.rsplit(" ", 1)
        return type_str, name, self._decode_value(type_str, raw)

    # -- main loop ---------------------------------------------------------- #
    def _parse(self) -> None:
        with open(self.path, "rb") as fh:
            buf = fh.read()

        if buf[:7] != ULOG_MAGIC:
            raise ValueError("Not a ULog file (bad magic): %r" % buf[:8])
        self.version = buf[7]
        self.start_timestamp_us = struct.unpack_from("<Q", buf, 8)[0]

        p = 16
        end = len(buf)
        in_header = True
        while p + 3 <= end:
            size, mtype = struct.unpack_from("<HB", buf, p)
            if p + 3 + size > end:
                self.corrupt_bytes += end - p
                break
            payload = buf[p + 3: p + 3 + size]
            t = chr(mtype)
            self.message_type_counts[t] += 1
            p += 3 + size

            if t == "B":
                self.compat_flags = payload[0:8]
                self.incompat_flags = payload[8:16]
            elif t == "F":
                self._add_format(payload)
            elif t == "I":
                _, name, val = self._parse_kv(payload)
                self.info[name] = val
            elif t == "M":
                is_cont = payload[0]
                _, name, val = self._parse_kv(payload, 1)
                if is_cont and self.info_multi[name]:
                    self.info_multi[name][-1].append(val)
                else:
                    self.info_multi[name].append([val])
            elif t == "P":
                type_str, name, val = self._parse_kv(payload)
                if in_header or name not in self.params:
                    self.params[name] = (type_str, val)
                else:
                    self.param_changes.append((self._last_ts, name, val))
                    self.params[name] = (type_str, val)
            elif t == "Q":
                _, name, val = self._parse_kv(payload, 1)
                self.default_params[name] = val
            elif t == "A":
                in_header = False
                multi_id, msg_id = struct.unpack_from("<BH", payload, 0)
                name = payload[3:].decode("ascii", errors="replace")
                self.subscriptions[msg_id] = (name, multi_id)
            elif t == "D":
                msg_id = struct.unpack_from("<H", payload, 0)[0]
                if msg_id not in self.subscriptions:
                    continue
                name, multi_id = self.subscriptions[msg_id]
                if name not in self.formats:
                    continue
                rec, _ = self._decode(name, payload, 2)
                ts = rec.get("timestamp")
                if isinstance(ts, int):
                    self._last_ts = max(self._last_ts, ts)
                    self._data_ts.append(ts)
                self.data[(name, multi_id)].append(rec)
            elif t == "L":
                level = payload[0]
                ts = struct.unpack_from("<Q", payload, 1)[0]
                msg = payload[9:].decode("utf-8", errors="replace")
                self.logged_messages.append((ts, LOG_LEVELS.get(level & 0x7, str(level)), msg))
            elif t == "C":
                level = payload[0]
                ts = struct.unpack_from("<Q", payload, 3)[0]
                msg = payload[11:].decode("utf-8", errors="replace")
                self.logged_messages.append((ts, LOG_LEVELS.get(level & 0x7, str(level)), msg))
            elif t == "O":
                self._dropout_idx.append((len(self._data_ts), struct.unpack_from("<H", payload, 0)[0]))
            elif t == "S":
                self.sync_count += 1

        # Resolve each dropout to the last in-window data timestamp preceding it
        # (latched topics with foreign time bases must not shift the dropout).
        lo, hi = self.time_bounds()
        for idx, dur in self._dropout_idx:
            ts = next((t for t in reversed(self._data_ts[:idx]) if lo <= t <= hi), lo)
            self.dropouts.append((ts, dur))

    # -- helpers ------------------------------------------------------------ #
    def topic(self, name: str, multi_id: int = 0) -> list[dict]:
        return self.data.get((name, multi_id), [])

    def time_bounds(self) -> tuple[int, int]:
        """Logging window derived from periodic topics (>= 10 samples).

        One-shot / latched topics (e.g. `mission`, `vehicle_command`) can carry
        timestamps from before logging started or from a different time base,
        so they are excluded here and reported separately as anomalies.
        """
        lo, hi = None, None
        for recs in self.data.values():
            if len(recs) < 10:
                continue
            for r in (recs[0], recs[-1]):
                ts = r.get("timestamp")
                if not isinstance(ts, int) or ts == 0:
                    continue
                lo = ts if lo is None else min(lo, ts)
                hi = ts if hi is None else max(hi, ts)
        return lo or 0, hi or 0

    def timestamp_anomalies(self) -> list[dict]:
        """Samples whose timestamp falls outside the periodic logging window."""
        lo, hi = self.time_bounds()
        out = []
        for (name, mid), recs in sorted(self.data.items()):
            for r in recs:
                ts = r.get("timestamp")
                if isinstance(ts, int) and (ts < lo or ts > hi):
                    out.append({"topic": name, "multi_id": mid, "timestamp_us": ts,
                                "offset_s": round((ts - (lo if ts < lo else hi)) / 1e6, 3)})
        return out


# --------------------------------------------------------------------------- #
#  Forensic analysis
# --------------------------------------------------------------------------- #
def file_hashes(path: str) -> dict:
    h = {"md5": hashlib.md5(), "sha1": hashlib.sha1(), "sha256": hashlib.sha256()}
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            for algo in h.values():
                algo.update(chunk)
    return {k: v.hexdigest() for k, v in h.items()}


def fmt_t(us: int, t0: int) -> str:
    """Format a boot-relative microsecond timestamp as H:MM:SS.mmm since boot."""
    s = max(us, 0) / 1e6
    return "%d:%02d:%06.3f" % (s // 3600, (s % 3600) // 60, s % 60)


def utc(us: int) -> str:
    if not us:
        return ""
    return dt.datetime.fromtimestamp(us / 1e6, tz=dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " UTC"


def stats(values):
    vals = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
    if not vals:
        return None
    return {"min": min(vals), "max": max(vals), "mean": sum(vals) / len(vals), "n": len(vals)}


def transitions(records, key, mapping=None):
    """Return [(timestamp, value)] whenever records[key] changes."""
    out, last = [], object()
    for r in records:
        if key not in r:
            continue
        v = r[key]
        if v != last:
            out.append((r["timestamp"], mapping.get(v, v) if mapping else v))
            last = v
    return out


def analyse(log: ULog) -> dict:
    t_start, t_end = log.time_bounds()
    res: dict = OrderedDict()

    # ---- System identification ------------------------------------------- #
    info = log.info
    ver_sw_release = info.get("ver_sw_release")
    if isinstance(ver_sw_release, int):
        ver = "%d.%d.%d" % ((ver_sw_release >> 24) & 0xFF, (ver_sw_release >> 16) & 0xFF,
                            (ver_sw_release >> 8) & 0xFF)
    else:
        ver = None
    res["system"] = OrderedDict(
        hardware=info.get("ver_hw"),
        hardware_subtype=info.get("ver_hw_subtype"),
        system_name=info.get("sys_name"),
        firmware_git_hash=info.get("ver_sw"),
        firmware_branch=info.get("ver_sw_branch"),
        firmware_release=ver,
        os_name=info.get("sys_os_name"),
        os_git_hash=info.get("sys_os_ver"),
        toolchain=info.get("sys_toolchain"),
        toolchain_version=info.get("sys_toolchain_ver"),
        mcu=info.get("sys_mcu"),
        vehicle_uuid=info.get("sys_uuid"),
        airframe_id=log.params.get("SYS_AUTOSTART", (None, None))[1],
        estimator={0: "?", 1: "LPE", 2: "EKF2"}.get(log.params.get("SYS_MC_EST_GROUP", (None, -1))[1], "EKF2"),
        utc_offset_min=info.get("time_ref_utc"),
    )

    # Total vehicle flight time stored in parameters (LND_FLIGHT_T_HI/LO, microseconds)
    hi = log.params.get("LND_FLIGHT_T_HI", (None, 0))[1] or 0
    lo = log.params.get("LND_FLIGHT_T_LO", (None, 0))[1] or 0
    life_us = (hi << 32) | (lo & 0xFFFFFFFF)
    res["system"]["vehicle_life_flight_time_s"] = round(life_us / 1e6, 1) if life_us else None

    # ---- Log container metadata ------------------------------------------ #
    res["log"] = OrderedDict(
        ulog_version=log.version,
        header_timestamp_us=log.start_timestamp_us,
        first_data_timestamp_us=t_start,
        last_data_timestamp_us=t_end,
        logging_duration_s=round((t_end - t_start) / 1e6, 3),
        message_type_counts=dict(sorted(log.message_type_counts.items())),
        topics_logged=len(log.data),
        formats_defined=len(log.formats),
        parameters=len(log.params),
        parameter_changes_in_flight=len(log.param_changes),
        sync_markers=log.sync_count,
        dropouts=[{"after_us": a, "after": fmt_t(a, t_start), "duration_ms": d} for a, d in log.dropouts],
        total_dropout_ms=sum(d for _, d in log.dropouts),
        truncated_bytes=log.corrupt_bytes,
        timestamps_outside_window=log.timestamp_anomalies(),
        boot_console_lines=sum(len(v) for k, v in log.info_multi.items() if k == "boot_console_output"),
    )

    # ---- Wall-clock anchoring (GNSS UTC) --------------------------------- #
    gps = log.topic("vehicle_gps_position")
    utc_anchor = None
    for r in gps:
        if r.get("time_utc_usec"):
            utc_anchor = (r["timestamp"], r["time_utc_usec"])
            break
    res["time_reference"] = OrderedDict(
        gnss_utc_available=bool(utc_anchor),
        log_start_utc=utc(utc_anchor[1] - (utc_anchor[0] - t_start)) if utc_anchor else None,
        log_end_utc=utc(utc_anchor[1] + (t_end - utc_anchor[0])) if utc_anchor else None,
    )

    def to_utc(ts):
        return utc(utc_anchor[1] + (ts - utc_anchor[0])) if utc_anchor else ""

    # ---- GNSS ------------------------------------------------------------ #
    if gps:
        lat = [r["lat"] / 1e7 for r in gps if r.get("fix_type", 0) >= 2]
        lon = [r["lon"] / 1e7 for r in gps if r.get("fix_type", 0) >= 2]
        res["gnss"] = OrderedDict(
            samples=len(gps),
            first_fix=OrderedDict(lat=lat[0], lon=lon[0]) if lat else None,
            last_fix=OrderedDict(lat=lat[-1], lon=lon[-1]) if lat else None,
            lat_span_m=round((max(lat) - min(lat)) * 111_320, 2) if lat else None,
            lon_span_m=round((max(lon) - min(lon)) * 111_320 * math.cos(math.radians(lat[0])), 2) if lat else None,
            alt_msl_m=stats([r["alt"] / 1e3 for r in gps]),
            satellites_used=stats([r.get("satellites_used") for r in gps]),
            eph_m=stats([r.get("eph") for r in gps]),
            epv_m=stats([r.get("epv") for r in gps]),
            hdop=stats([r.get("hdop") for r in gps]),
            fix_types=sorted({GPS_FIX.get(r.get("fix_type"), r.get("fix_type")) for r in gps}),
            jamming_indicator=stats([r.get("jamming_indicator") for r in gps]),
            noise_per_ms=stats([r.get("noise_per_ms") for r in gps]),
        )

    # ---- Home position --------------------------------------------------- #
    home = log.topic("home_position")
    if home:
        h = home[-1]
        res["home_position"] = OrderedDict(lat=h.get("lat"), lon=h.get("lon"), alt_msl_m=h.get("alt"),
                                           set_at=fmt_t(h["timestamp"], t_start))

    # ---- Vehicle status / arming / flight modes -------------------------- #
    vs = log.topic("vehicle_status")
    if vs:
        res["vehicle_status"] = OrderedDict(
            vehicle_type=[VEHICLE_TYPES.get(v, v) for _, v in transitions(vs, "vehicle_type")],
            is_vtol=bool(vs[0].get("is_vtol")),
            arming_transitions=[(fmt_t(t, t_start), s) for t, s in transitions(vs, "arming_state", ARMING_STATES)],
            nav_state_transitions=[(fmt_t(t, t_start), s) for t, s in transitions(vs, "nav_state", NAV_STATES)],
            rc_signal_lost_transitions=[(fmt_t(t, t_start), bool(s)) for t, s in transitions(vs, "rc_signal_lost")],
            data_link_lost_transitions=[(fmt_t(t, t_start), bool(s)) for t, s in transitions(vs, "data_link_lost")],
            failsafe_transitions=[(fmt_t(t, t_start), bool(s)) for t, s in transitions(vs, "failsafe")],
        )

    land = log.topic("vehicle_land_detected")
    if land:
        res["land_detector"] = [(fmt_t(t, t_start), "LANDED" if v else "IN_AIR")
                                for t, v in transitions(land, "landed")]

    # ---- RC input (proof of operator-in-the-loop) ------------------------ #
    rc = log.topic("input_rc")
    if rc:
        res["rc_input"] = OrderedDict(
            samples=len(rc),
            channel_count=stats([r.get("channel_count") for r in rc]),
            rssi=stats([r.get("rssi") for r in rc]),
            rc_lost_any=any(r.get("rc_lost") for r in rc),
            rc_failsafe_any=any(r.get("rc_failsafe") for r in rc),
            lost_frame_count_max=max((r.get("rc_lost_frame_count") or 0) for r in rc),
        )
    mc = log.topic("manual_control_setpoint")
    if mc:
        res["manual_control"] = OrderedDict(
            samples=len(mc),
            throttle=stats([r.get("z") for r in mc]),
            roll=stats([r.get("y") for r in mc]),
            pitch=stats([r.get("x") for r in mc]),
            yaw=stats([r.get("r") for r in mc]),
        )

    # ---- Kinematics ------------------------------------------------------ #
    lp = log.topic("vehicle_local_position")
    if lp:
        z = [r.get("z") for r in lp]
        speeds = [math.hypot(r.get("vx", 0.0), r.get("vy", 0.0)) for r in lp]
        vz = [r.get("vz") for r in lp]
        zs = stats(z)
        res["kinematics"] = OrderedDict(
            altitude_change_m=round(zs["max"] - zs["min"], 3) if zs else None,
            max_height_above_origin_m=round(-zs["min"], 3) if zs else None,
            max_horizontal_speed_ms=round(max(speeds), 3) if speeds else None,
            max_climb_rate_ms=round(-min(vz), 3) if vz else None,
            max_descent_rate_ms=round(max(vz), 3) if vz else None,
            max_distance_from_origin_m=round(max(math.hypot(r.get("x", 0), r.get("y", 0)) for r in lp), 3),
            # If False, EKF2 had no horizontal position solution: x/y and horizontal
            # speed are NOT meaningful and GNSS must be used for the ground track.
            horizontal_position_valid_any=any(r.get("xy_valid") for r in lp),
            vertical_position_valid_any=any(r.get("z_valid") for r in lp),
        )

    att = log.topic("vehicle_attitude")
    if att:
        tilts = []
        for r in att:
            q = r.get("q")
            if not q:
                continue
            w, x, y, zq = q
            # tilt = angle between body z and earth z
            c = 1.0 - 2.0 * (x * x + y * y)
            tilts.append(math.degrees(math.acos(max(-1.0, min(1.0, c)))))
        res.setdefault("kinematics", OrderedDict())["max_tilt_deg"] = round(max(tilts), 2) if tilts else None

    # ---- Power ----------------------------------------------------------- #
    bat = log.topic("battery_status")
    if bat:
        res["battery"] = OrderedDict(
            voltage_v=stats([r.get("voltage_v") for r in bat]),
            voltage_filtered_v=stats([r.get("voltage_filtered_v") for r in bat]),
            current_a=stats([r.get("current_a") for r in bat]),
            discharged_mah=stats([r.get("discharged_mah") for r in bat]),
            remaining_fraction=stats([r.get("remaining") for r in bat]),
            temperature_c=stats([r.get("temperature") for r in bat]),
            warnings=sorted({r.get("warning") for r in bat if r.get("warning") is not None}),
        )

    # ---- Vibration / sensor health -------------------------------------- #
    imu = []
    for mid in range(4):
        recs = log.topic("vehicle_imu_status", mid)
        if recs:
            imu.append(OrderedDict(
                instance=mid,
                accel_device_id=recs[0].get("accel_device_id"),
                gyro_device_id=recs[0].get("gyro_device_id"),
                accel_vibration_metric=stats([r.get("accel_vibration_metric") for r in recs]),
                gyro_vibration_metric=stats([r.get("gyro_vibration_metric") for r in recs]),
                accel_clipping_total=max(sum(r.get("accel_clipping") or [0]) for r in recs),
            ))
    if imu:
        res["imu_health"] = imu

    for name in ("cpuload",):
        recs = log.topic(name)
        if recs:
            res["cpu"] = OrderedDict(load=stats([r.get("load") for r in recs]),
                                     ram_usage=stats([r.get("ram_usage") for r in recs]))

    mag = log.topic("vehicle_magnetometer")
    if mag:
        norms = [math.sqrt(sum(v * v for v in r["magnetometer_ga"])) for r in mag if r.get("magnetometer_ga")]
        res["magnetometer"] = OrderedDict(field_norm_gauss=stats(norms))

    mission = log.topic("mission")
    if mission:
        m = mission[-1]
        res["mission"] = OrderedDict(waypoint_count=m.get("count"), current_seq=m.get("current_seq"),
                                     dataman_id=m.get("dataman_id"))

    estim = log.topic("estimator_status")
    if estim:
        res["estimator"] = OrderedDict(
            samples=len(estim),
            gps_check_fail_flags=sorted({r.get("gps_check_fail_flags") for r in estim}),
            gps_checks_failed=sorted({GPS_CHECK_BITS[bit] for r in estim for bit in GPS_CHECK_BITS
                                      if (r.get("gps_check_fail_flags") or 0) >> bit & 1}),
            filter_fault_flags=sorted({r.get("filter_fault_flags") for r in estim}),
            innovation_check_flags=sorted({r.get("innovation_check_flags") for r in estim}),
        )

    # ---- Messages / timeline -------------------------------------------- #
    res["logged_messages"] = [
        OrderedDict(t=fmt_t(ts, t_start), utc=to_utc(ts), level=lvl, message=msg)
        for ts, lvl, msg in log.logged_messages
    ]

    # ---- Non-default parameters (where defaults are embedded) ------------ #
    if log.default_params:
        nd = {k: v[1] for k, v in log.params.items()
              if k in log.default_params and log.default_params[k] != v[1]}
        res["non_default_parameter_count"] = len(nd)

    res["parameters_of_interest"] = OrderedDict(
        (k, log.params[k][1]) for k in (
            "SYS_AUTOSTART", "MAV_TYPE", "MAV_SYS_ID", "COM_RC_LOSS_T", "NAV_RCL_ACT", "NAV_DLL_ACT",
            "COM_LOW_BAT_ACT", "GF_ACTION", "GF_MAX_HOR_DIST", "GF_MAX_VER_DIST", "RTL_RETURN_ALT",
            "BAT1_N_CELLS", "BAT1_CAPACITY", "BAT_N_CELLS", "BAT_CAPACITY", "SDLOG_MODE", "SDLOG_PROFILE",
            "EKF2_AID_MASK", "EKF2_HGT_MODE", "CBRK_SUPPLY_CHK", "CBRK_USB_CHK", "CBRK_IO_SAFETY",
            "CBRK_AIRSPD_CHK", "COM_ARM_WO_GPS", "LND_FLIGHT_T_HI", "LND_FLIGHT_T_LO",
        ) if k in log.params
    )

    return res


def build_timeline(log: ULog) -> list[tuple[int, str, str]]:
    t0, _ = log.time_bounds()
    ev: list[tuple[int, str, str]] = []
    for ts, lvl, msg in log.logged_messages:
        ev.append((ts, "log/" + lvl, msg))
    vs = log.topic("vehicle_status")
    for ts, s in transitions(vs, "arming_state", ARMING_STATES):
        ev.append((ts, "arming_state", s))
    for ts, s in transitions(vs, "nav_state", NAV_STATES):
        ev.append((ts, "flight_mode", s))
    for ts, s in transitions(vs, "vehicle_type", VEHICLE_TYPES):
        ev.append((ts, "vehicle_type", s))
    for ts, s in transitions(vs, "rc_signal_lost"):
        ev.append((ts, "rc_signal_lost", str(bool(s))))
    for ts, s in transitions(vs, "failsafe"):
        ev.append((ts, "failsafe", str(bool(s))))
    for ts, s in transitions(log.topic("vehicle_land_detected"), "landed"):
        ev.append((ts, "land_detector", "LANDED" if s else "IN_AIR"))
    for ts, s in transitions(log.topic("actuator_armed"), "armed"):
        ev.append((ts, "actuator_armed", str(bool(s))))
    for ts, d in log.dropouts:
        ev.append((ts, "logger_dropout", "%d ms" % d))
    for ts, name, val in log.param_changes:
        ev.append((ts, "param_change", "%s=%s" % (name, val)))
    ev.sort(key=lambda e: e[0])
    return ev


# --------------------------------------------------------------------------- #
#  Writers
# --------------------------------------------------------------------------- #
def write_outputs(log: ULog, result: dict, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    t0, _ = log.time_bounds()

    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, default=str)

    # Timeline
    tl = build_timeline(log)
    with open(os.path.join(out_dir, "timeline.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp_us", "time_since_boot", "source", "event"])
        for ts, src, evt in tl:
            w.writerow([ts, fmt_t(ts, t0), src, evt])

    # GNSS track + KML
    gps = log.topic("vehicle_gps_position")
    with open(os.path.join(out_dir, "gps_track.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp_us", "time_since_boot", "utc", "lat", "lon", "alt_msl_m",
                    "fix_type", "satellites_used", "eph_m", "epv_m", "vel_m_s"])
        for r in gps:
            w.writerow([r["timestamp"], fmt_t(r["timestamp"], t0), utc(r.get("time_utc_usec", 0)),
                        "%.7f" % (r["lat"] / 1e7), "%.7f" % (r["lon"] / 1e7), "%.3f" % (r["alt"] / 1e3),
                        GPS_FIX.get(r.get("fix_type"), r.get("fix_type")), r.get("satellites_used"),
                        "%.2f" % r.get("eph", float("nan")), "%.2f" % r.get("epv", float("nan")),
                        "%.3f" % r.get("vel_m_s", float("nan"))])

    coords = " ".join("%.7f,%.7f,%.2f" % (r["lon"] / 1e7, r["lat"] / 1e7, r["alt"] / 1e3)
                      for r in gps if r.get("fix_type", 0) >= 2)
    kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{name}</name>
    <description>GNSS track extracted from {name} by ulog_forensic_extractor v{ver}. SHA-256: {sha}</description>
    <Style id="track"><LineStyle><color>ff0000ff</color><width>4</width></LineStyle></Style>
    <Placemark>
      <name>Flight path</name>
      <styleUrl>#track</styleUrl>
      <LineString><extrude>1</extrude><tessellate>1</tessellate><altitudeMode>absolute</altitudeMode>
        <coordinates>{coords}</coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>
""".format(name=os.path.basename(log.path), ver=__version__, sha=result["evidence"]["sha256"], coords=coords)
    with open(os.path.join(out_dir, "flight_path.kml"), "w", encoding="utf-8") as fh:
        fh.write(kml)

    # Parameters
    with open(os.path.join(out_dir, "parameters.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "type", "value", "default", "non_default"])
        for k, (typ, val) in log.params.items():
            d = log.default_params.get(k, "")
            w.writerow([k, typ, val, d, "" if d == "" else str(d != val)])

    # Topics
    with open(os.path.join(out_dir, "topics.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["topic", "multi_id", "samples", "first_us", "last_us", "approx_rate_hz"])
        for (name, mid), recs in sorted(log.data.items()):
            first, last = recs[0].get("timestamp", 0), recs[-1].get("timestamp", 0)
            rate = (len(recs) - 1) / ((last - first) / 1e6) if last > first and len(recs) > 1 else 0
            w.writerow([name, mid, len(recs), first, last, "%.1f" % rate])

    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(render_markdown(log, result, tl))


def _s(d, key="max", fmt="%.2f"):
    if not d:
        return "n/a"
    return fmt % d[key]


def render_markdown(log: ULog, r: dict, timeline) -> str:
    t0, _ = log.time_bounds()
    ev = r["evidence"]
    sysi = r["system"]
    L = []
    L.append("# ULog Forensic Triage Report\n")
    L.append("_Generated by `ulog_forensic_extractor.py` v%s on %s_\n" % (__version__, ev["examined_utc"]))
    L.append("## 1. Evidence Item\n")
    L.append("| Field | Value |\n|---|---|")
    L.append("| File name | `%s` |" % ev["file_name"])
    L.append("| Size | %s bytes |" % format(ev["size_bytes"], ","))
    L.append("| MD5 | `%s` |" % ev["md5"])
    L.append("| SHA-1 | `%s` |" % ev["sha1"])
    L.append("| SHA-256 | `%s` |" % ev["sha256"])
    L.append("| ULog version | %s |" % r["log"]["ulog_version"])
    L.append("")
    L.append("## 2. System Identification\n")
    L.append("| Field | Value |\n|---|---|")
    for k, v in sysi.items():
        if v not in (None, ""):
            L.append("| %s | `%s` |" % (k.replace("_", " ").title(), v))
    L.append("")
    L.append("## 3. Log Container Integrity\n")
    lg = r["log"]
    L.append("| Field | Value |\n|---|---|")
    L.append("| Logging duration | %.3f s |" % lg["logging_duration_s"])
    L.append("| Topics logged | %d |" % lg["topics_logged"])
    L.append("| Message formats | %d |" % lg["formats_defined"])
    L.append("| Parameters | %d |" % lg["parameters"])
    L.append("| In-flight parameter changes | %d |" % lg["parameter_changes_in_flight"])
    L.append("| Logger dropouts | %d (%d ms total) |" % (len(lg["dropouts"]), lg["total_dropout_ms"]))
    L.append("| Sync markers | %d |" % lg["sync_markers"])
    L.append("| Truncated / unparsable bytes | %d |" % lg["truncated_bytes"])
    L.append("| Message type counts | `%s` |" % json.dumps(lg["message_type_counts"]))
    L.append("")
    if lg["timestamps_outside_window"]:
        L.append("**Samples outside the periodic logging window** (latched / one-shot topics - "
                 "verify before relying on them for timeline reconstruction):\n")
        L.append("| Topic | Timestamp (us) | Offset from window |\n|---|---|---|")
        for a in lg["timestamps_outside_window"]:
            L.append("| `%s` | %d | %+.3f s |" % (a["topic"], a["timestamp_us"], a["offset_s"]))
        L.append("")
    tr = r["time_reference"]
    L.append("## 4. Time Reference\n")
    if tr["gnss_utc_available"]:
        L.append("GNSS UTC available - log anchored to wall-clock time.\n")
        L.append("* Log start: **%s**\n* Log end: **%s**\n" % (tr["log_start_utc"], tr["log_end_utc"]))
    else:
        L.append("No GNSS UTC time in log - timestamps are relative to boot only.\n")

    if "gnss" in r:
        g = r["gnss"]
        L.append("## 5. GNSS / Position\n")
        L.append("| Metric | Value |\n|---|---|")
        if g["first_fix"]:
            L.append("| First fix | %.7f, %.7f |" % (g["first_fix"]["lat"], g["first_fix"]["lon"]))
            L.append("| Last fix | %.7f, %.7f |" % (g["last_fix"]["lat"], g["last_fix"]["lon"]))
            L.append("| Horizontal footprint | %.2f m (N-S) x %.2f m (E-W) |" % (g["lat_span_m"], g["lon_span_m"]))
        L.append("| Altitude MSL (min / max) | %s / %s m |" % (_s(g["alt_msl_m"], "min"), _s(g["alt_msl_m"])))
        L.append("| Satellites used (min / max) | %s / %s |" % (_s(g["satellites_used"], "min", "%d"),
                                                             _s(g["satellites_used"], "max", "%d")))
        L.append("| EPH (min / max) | %s / %s m |" % (_s(g["eph_m"], "min"), _s(g["eph_m"])))
        L.append("| HDOP (min / max) | %s / %s |" % (_s(g["hdop"], "min"), _s(g["hdop"])))
        L.append("| Fix types observed | %s |" % ", ".join(map(str, g["fix_types"])))
        L.append("| Jamming indicator (max) | %s |" % _s(g["jamming_indicator"], "max", "%d"))
        L.append("")

    if "kinematics" in r:
        k = r["kinematics"]
        L.append("## 6. Kinematics\n")
        L.append("| Metric | Value |\n|---|---|")
        for key, val in k.items():
            L.append("| %s | %s |" % (key.replace("_", " "), val))
        L.append("")

    L.append("## 7. Flight State & Operator Control\n")
    if "vehicle_status" in r:
        v = r["vehicle_status"]
        L.append("* Vehicle type sequence: %s" % " -> ".join(v["vehicle_type"]))
        L.append("* VTOL airframe: %s" % v["is_vtol"])
        L.append("* Arming: %s" % ", ".join("%s @ %s" % (s, t) for t, s in v["arming_transitions"]))
        L.append("* Flight modes: %s" % ", ".join("%s @ %s" % (s, t) for t, s in v["nav_state_transitions"]))
        L.append("* RC signal lost: %s" % ", ".join("%s @ %s" % (s, t) for t, s in v["rc_signal_lost_transitions"]))
        L.append("* Failsafe: %s" % ", ".join("%s @ %s" % (s, t) for t, s in v["failsafe_transitions"]))
    if "land_detector" in r:
        L.append("* Land detector: %s" % ", ".join("%s @ %s" % (s, t) for t, s in r["land_detector"]))
    if "rc_input" in r:
        rc = r["rc_input"]
        L.append("* RC receiver: %d samples, %s channels, rc_lost=%s, rc_failsafe=%s, max lost frames=%s" % (
            rc["samples"], _s(rc["channel_count"], "max", "%d"), rc["rc_lost_any"], rc["rc_failsafe_any"],
            rc["lost_frame_count_max"]))
    L.append("")

    if "estimator" in r and r["estimator"]["gps_checks_failed"]:
        L.append("* EKF2 GPS quality checks failed during log: %s" % ", ".join(r["estimator"]["gps_checks_failed"]))
    if "mission" in r:
        L.append("* Stored mission: %s waypoint(s) (dataman slot %s)" % (r["mission"]["waypoint_count"],
                                                                     r["mission"]["dataman_id"]))
        L.append("")

    if "battery" in r:
        b = r["battery"]
        L.append("## 8. Power System\n")
        L.append("| Metric | Min | Max |\n|---|---|---|")
        for key in ("voltage_v", "voltage_filtered_v", "current_a", "discharged_mah", "remaining_fraction",
                    "temperature_c"):
            if b.get(key):
                L.append("| %s | %.3f | %.3f |" % (key, b[key]["min"], b[key]["max"]))
        L.append("")

    if "imu_health" in r:
        L.append("## 9. IMU / Vibration Health\n")
        L.append("| IMU | Accel vib (max) | Gyro vib (max) | Accel clipping |\n|---|---|---|---|")
        for i in r["imu_health"]:
            L.append("| %d | %s | %s | %s |" % (i["instance"], _s(i["accel_vibration_metric"], "max", "%.3f"),
                                               _s(i["gyro_vibration_metric"], "max", "%.4f"),
                                               i["accel_clipping_total"]))
        L.append("")

    L.append("## 10. Logged Messages\n")
    L.append("| Time since boot | Level | Message |\n|---|---|---|")
    for m in r["logged_messages"]:
        L.append("| %s | %s | %s |" % (m["t"], m["level"], m["message"]))
    L.append("")

    L.append("## 11. Unified Event Timeline\n")
    L.append("| Time since boot | Source | Event |\n|---|---|---|")
    for ts, src, evt in timeline:
        L.append("| %s | %s | %s |" % (fmt_t(ts, t0), src, evt))
    L.append("")

    L.append("## 12. Parameters of Forensic Interest\n")
    L.append("| Parameter | Value |\n|---|---|")
    for k2, v2 in r["parameters_of_interest"].items():
        L.append("| `%s` | %s |" % (k2, v2))
    L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Forensic triage of PX4 ULog (.ulg) flight logs.")
    ap.add_argument("ulog", help="Path to the .ulg evidence file (opened read-only)")
    ap.add_argument("-o", "--output", default="output", help="Output directory (default: ./output)")
    args = ap.parse_args(argv)

    path = os.path.abspath(args.ulog)
    print("[*] Hashing evidence: %s" % path)
    hashes = file_hashes(path)
    print("    SHA-256: %s" % hashes["sha256"])

    print("[*] Parsing ULog ...")
    log = ULog(path)
    result = OrderedDict()
    result["evidence"] = OrderedDict(
        file_name=os.path.basename(path),
        size_bytes=os.path.getsize(path),
        examined_utc=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        tool="ulog_forensic_extractor.py v%s" % __version__,
        **hashes,
    )
    result.update(analyse(log))

    # Verify the evidence file was not modified during processing
    after = file_hashes(path)
    result["evidence"]["hash_verified_after_processing"] = after == hashes
    if after != hashes:
        print("[!] WARNING: evidence hash changed during processing!", file=sys.stderr)

    write_outputs(log, result, args.output)
    print("[+] %d topics, %d parameters, %d logged messages, duration %.3f s"
          % (len(log.data), len(log.params), len(log.logged_messages), result["log"]["logging_duration_s"]))
    print("[+] Outputs written to %s" % os.path.abspath(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
