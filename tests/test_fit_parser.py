import struct
import unittest
from fit_analyzer.fit.parser import FitParser, FitParseError


def minimal_fit():
    # Header (12 bytes), one definition (global record message), two record data messages.
    header=bytes([14,0])+b"\x00\x00"+struct.pack("<I",0)+b".FIT"+b"\x00\x00"
    definition=bytes([0x40,0,0,20,0,3,
                      253,4,0x86, 3,1,0x02, 7,2,0x84])
    # timestamp, HR, power
    data1=bytes([0x00])+struct.pack("<I",100)+bytes([120])+struct.pack("<H",180)
    data2=bytes([0x00])+struct.pack("<I",101)+bytes([125])+struct.pack("<H",200)
    payload=definition+data1+data2
    header=bytes([14,0])+b"\x00\x00"+struct.pack("<I",len(payload))+b".FIT"+b"\x00\x00"
    return header+payload+b"\x00\x00"


class FitParserTests(unittest.TestCase):
    def test_decode_common_record_fields(self):
        messages=FitParser().parse(minimal_fit())
        records=[m for m in messages if m["global_message"]==20]
        self.assertEqual(len(records),2)
        self.assertEqual(records[0]["heart_rate_bpm"],120)
        self.assertEqual(records[1]["power_w"],200)
        self.assertEqual(records[0]["timestamp"],631065700)

    def test_lap_end_timestamp_uses_start_plus_elapsed_when_fit_end_repeats(self):
        # Garmin export regression: field_253 can repeat the first lap timestamp.
        msg = {
            "field_2": 1_162_335_955,
            "field_253": 1_162_331_673,
            "field_7": 802_456,
        }
        lap = FitParser._decorate(19, msg)
        self.assertEqual(lap["start_timestamp"], 631065600 + 1_162_335_955)
        self.assertAlmostEqual(
            lap["end_timestamp"],
            631065600 + 1_162_335_955 + 802.456,
        )
        self.assertEqual(lap["end_timestamp_source"], "start_plus_elapsed")

    def test_invalid_signature(self):
        with self.assertRaises(FitParseError):
            FitParser().parse(b"not a fit file")


if __name__ == "__main__":
    unittest.main()
