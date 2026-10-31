"""Dependency-free decoder for common Garmin FIT activity data."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class FitParseError(ValueError):
    pass


# FIT base type number -> (struct format, byte width, invalid sentinel)
BASE_TYPES = {
    0: ("B", 1, 0xFF), 1: ("b", 1, 0x7F), 2: ("B", 1, 0xFF),
    3: ("h", 2, 0x7FFF), 4: ("H", 2, 0xFFFF),
    5: ("i", 4, 0x7FFFFFFF), 6: ("I", 4, 0xFFFFFFFF),
    7: ("f", 4, None), 8: ("d", 8, None),
    9: ("q", 8, 0x7FFFFFFFFFFFFFFF), 10: ("Q", 8, 0xFFFFFFFFFFFFFFFF),
    11: ("B", 1, 0xFF), 12: ("?", 1, None),
}
FIT_EPOCH = 631065600  # seconds from 1989-12-31 to Unix epoch


@dataclass
class FieldDef:
    number: int
    size: int
    base_type: int


@dataclass
class MessageDef:
    global_number: int
    architecture: str
    fields: List[FieldDef] = field(default_factory=list)
    developer_fields: List[Tuple[int, int, int]] = field(default_factory=list)

    @property
    def endian(self) -> str:
        return ">" if self.architecture == 1 else "<"


class FitParser:
    """Parse a FIT file into decoded message dictionaries.

    `strict_crc=True` validates the FIT header and file CRCs when present.
    Unknown fields are retained by field number (e.g. `field_123`).
    """

    def __init__(self, strict_crc: bool = False):
        self.strict_crc = strict_crc
        self.definitions: Dict[int, MessageDef] = {}
        self.messages: List[Dict[str, Any]] = []
        self._last_timestamp: Optional[int] = None

    @staticmethod
    def _crc(data: bytes) -> int:
        # FIT CRC-16 lookup table generated from the FIT polynomial.
        table = (
            0x0000,0xCC01,0xD801,0x1400,0xF001,0x3C00,0x2800,0xE401,
            0xA001,0x6C00,0x7800,0xB401,0x5000,0x9C01,0x8801,0x4400,
        )
        crc = 0
        for byte in data:
            tmp = table[crc & 0xF]
            crc = (crc >> 4) & 0x0FFF
            crc ^= tmp ^ table[byte & 0xF]
            tmp = table[crc & 0xF]
            crc = (crc >> 4) & 0x0FFF
            crc ^= tmp ^ table[(byte >> 4) & 0xF]
        return crc

    def parse(self, source: str | Path | bytes) -> List[Dict[str, Any]]:
        if isinstance(source, (str, Path)):
            raw = Path(source).read_bytes()
        else:
            raw = source
        if len(raw) < 12:
            raise FitParseError("File is too short to be a FIT file.")

        header_size = raw[0]
        if header_size not in (12, 14) or len(raw) < header_size:
            raise FitParseError(f"Unsupported FIT header size: {header_size}")
        if raw[8:12] != b".FIT":
            raise FitParseError("Missing .FIT signature.")

        data_size = struct.unpack("<I", raw[4:8])[0]
        data_start = header_size
        data_end = data_start + data_size
        if data_end > len(raw):
            raise FitParseError("FIT data section is truncated.")

        if self.strict_crc:
            expected_header_crc = struct.unpack("<H", raw[header_size-2:header_size])[0]
            actual_header_crc = self._crc(raw[:header_size-2])
            if expected_header_crc and expected_header_crc != actual_header_crc:
                raise FitParseError("FIT header CRC mismatch.")
            if len(raw) >= data_end + 2:
                expected_file_crc = struct.unpack("<H", raw[data_end:data_end+2])[0]
                actual_file_crc = self._crc(raw[:data_end])
                if expected_file_crc and expected_file_crc != actual_file_crc:
                    raise FitParseError("FIT file CRC mismatch.")

        self.definitions.clear()
        self.messages.clear()
        self._last_timestamp = None
        pos = data_start

        while pos < data_end:
            header = raw[pos]
            pos += 1
            if header & 0x80:
                local = (header >> 5) & 0x03
                time_offset = header & 0x1F
                definition = self.definitions.get(local)
                if definition is None:
                    raise FitParseError(f"Compressed timestamp references undefined local message {local}.")
                msg = self._read_data_message(raw, pos, definition)
                pos += sum(f.size for f in definition.fields) + sum(x[1] for x in definition.developer_fields)
                if self._last_timestamp is not None:
                    base = self._last_timestamp & ~0x1F
                    timestamp = base + time_offset
                    if timestamp < self._last_timestamp:
                        timestamp += 0x20
                    msg["timestamp"] = timestamp
                    self._last_timestamp = timestamp
                self.messages.append(self._decorate(definition.global_number, msg))
                continue

            local = header & 0x0F
            is_definition = bool(header & 0x40)
            has_dev = bool(header & 0x20)
            if is_definition:
                if pos + 5 > data_end:
                    raise FitParseError("Truncated FIT message definition.")
                reserved = raw[pos]
                architecture = raw[pos+1]
                endian = ">" if architecture == 1 else "<"
                global_number = struct.unpack(endian + "H", raw[pos+2:pos+4])[0]
                field_count = raw[pos+4]
                pos += 5
                fields = []
                for _ in range(field_count):
                    if pos + 3 > data_end:
                        raise FitParseError("Truncated FIT field definition.")
                    number, size, base_type = raw[pos:pos+3]
                    fields.append(FieldDef(number, size, base_type & 0x1F))
                    pos += 3
                dev_fields = []
                if has_dev:
                    if pos >= data_end:
                        raise FitParseError("Truncated developer field count.")
                    dev_count = raw[pos]
                    pos += 1
                    for _ in range(dev_count):
                        if pos + 3 > data_end:
                            raise FitParseError("Truncated developer field definition.")
                        number, size, dev_index = raw[pos:pos+3]
                        dev_fields.append((number, size, dev_index))
                        pos += 3
                self.definitions[local] = MessageDef(global_number, architecture, fields, dev_fields)
            else:
                definition = self.definitions.get(local)
                if definition is None:
                    raise FitParseError(f"Data message references undefined local message {local}.")
                msg = self._read_data_message(raw, pos, definition)
                pos += sum(f.size for f in definition.fields) + sum(x[1] for x in definition.developer_fields)
                if "timestamp" in msg:
                    self._last_timestamp = int(msg["timestamp"])
                self.messages.append(self._decorate(definition.global_number, msg))

        return self.messages

    def _read_data_message(self, raw: bytes, pos: int, definition: MessageDef) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for field_def in definition.fields:
            end = pos + field_def.size
            if end > len(raw):
                raise FitParseError("Truncated FIT data field.")
            chunk = raw[pos:end]
            pos = end
            result[f"field_{field_def.number}"] = self._decode_value(
                chunk, field_def.base_type, definition.endian
            )
        # Developer fields are skipped but their bytes are included in the message length.
        return result

    @staticmethod
    def _decode_value(chunk: bytes, base_type: int, endian: str) -> Any:
        spec = BASE_TYPES.get(base_type)
        if spec is None:
            return chunk.hex()
        fmt, width, invalid = spec
        if len(chunk) == 0:
            return None
        if len(chunk) % width:
            return chunk.hex()
        values = []
        for offset in range(0, len(chunk), width):
            value = struct.unpack(endian + fmt, chunk[offset:offset+width])[0]
            if invalid is not None and value == invalid:
                values.append(None)
            else:
                values.append(value)
        return values[0] if len(values) == 1 else values

    @staticmethod
    def _decorate(global_number: int, msg: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {"global_message": global_number}
        out.update(msg)
        # Global message 20 = record.
        if global_number == 20:
            def get(n: int) -> Any:
                return msg.get(f"field_{n}")
            timestamp = get(253)
            if timestamp is not None:
                out["timestamp"] = FIT_EPOCH + timestamp
            if get(0) is not None and get(1) is not None:
                out["position_lat"] = get(0) * (180.0 / 2**31)
                out["position_long"] = get(1) * (180.0 / 2**31)
            if get(2) is not None:
                out["altitude_m"] = get(2) / 5.0 - 500.0
            if get(78) is not None:
                out["enhanced_altitude_m"] = get(78) / 5.0 - 500.0
            if get(3) is not None: out["heart_rate_bpm"] = get(3)
            if get(4) is not None: out["cadence_rpm"] = get(4)
            if get(5) is not None: out["distance_m"] = get(5) / 100.0
            if get(6) is not None: out["speed_mps"] = get(6) / 1000.0
            if get(73) is not None: out["enhanced_speed_mps"] = get(73) / 1000.0
            if get(7) is not None: out["power_w"] = get(7)
            if get(13) is not None: out["temperature_c"] = get(13)
            if get(53) is not None: out["fractional_cadence"] = get(53) / 128.0
        elif global_number == 19:  # lap
            # FIT lap messages summarize manually marked laps. FIT timestamps
            # are seconds since 1989-12-31; elapsed/timer values are ms.
            start = msg.get("field_2")
            raw_end = msg.get("field_253")
            elapsed_ms = msg.get("field_7")
            elapsed_s = elapsed_ms / 1000.0 if elapsed_ms is not None else None
            out["start_timestamp"] = FIT_EPOCH + start if start is not None else None
            # Some Garmin FIT exports repeat the first lap timestamp in field 253
            # on subsequent lap messages. Prefer the lap's start_time + elapsed
            # duration when it is available; retain the raw end only as fallback.
            if start is not None and elapsed_s is not None:
                out["end_timestamp"] = FIT_EPOCH + start + elapsed_s
                out["end_timestamp_source"] = "start_plus_elapsed"
            else:
                out["end_timestamp"] = FIT_EPOCH + raw_end if raw_end is not None else None
                out["end_timestamp_source"] = "fit_timestamp" if raw_end is not None else None
            out["total_elapsed_time_s"] = elapsed_s
            out["total_timer_time_s"] = msg.get("field_8") / 1000.0 if msg.get("field_8") is not None else None
            out["total_distance_m"] = msg.get("field_9") / 100.0 if msg.get("field_9") is not None else None
            out["avg_heart_rate_bpm"] = msg.get("field_15")
            out["max_heart_rate_bpm"] = msg.get("field_16")
            out["avg_cadence_rpm"] = msg.get("field_17")
            out["max_cadence_rpm"] = msg.get("field_18")
            out["avg_power_w"] = msg.get("field_19")
            out["max_power_w"] = msg.get("field_20")
        elif global_number == 18:  # session
            out["session_start_timestamp"] = msg.get("field_2")
            out["total_elapsed_time_s"] = (
                msg.get("field_7") / 1000.0 if msg.get("field_7") is not None else None
            )
            out["total_timer_time_s"] = (
                msg.get("field_8") / 1000.0 if msg.get("field_8") is not None else None
            )
            out["total_distance_m"] = (
                msg.get("field_9") / 100.0 if msg.get("field_9") is not None else None
            )
            out["avg_heart_rate_bpm"] = msg.get("field_16")
            out["max_heart_rate_bpm"] = msg.get("field_17")
            out["avg_cadence_rpm"] = msg.get("field_18")
            out["avg_power_w"] = msg.get("field_20")
            out["max_power_w"] = msg.get("field_21")
        return out
