import unittest
from fit_analyzer.analytics.cycling import rolling_best_power, analyze_records, detect_power_intervals


class CyclingAnalyticsTests(unittest.TestCase):
    def test_rolling_best(self):
        self.assertEqual(rolling_best_power([100]*5+[200]*5,5),200)

    def test_basic_summary(self):
        records=[]
        for i in range(120):
            records.append({"global_message":20,"timestamp":i,"power_w":150,"heart_rate_bpm":130,"cadence_rpm":90,"distance_m":i*5})
        result=analyze_records(records,ftp=210,weight_kg=78)
        self.assertEqual(result["record_count"],120)
        self.assertEqual(result["avg_power_w"],150)
        self.assertEqual(result["distance_km"],0.595)

    def test_interval_detection(self):
        records=[{"timestamp":i,"power_w":200} for i in range(200)]
        result=detect_power_intervals(records,ftp=210,threshold_fraction=.9,min_duration_s=180)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["duration_s"],200)


if __name__ == "__main__":
    unittest.main()
