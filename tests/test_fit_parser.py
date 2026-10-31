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

    def test_invalid_signature(self):
        with self.assertRaises(FitParseError):
            FitParser().parse(b"not a fit file")


if __name__ == "__main__":
    unittest.main()
