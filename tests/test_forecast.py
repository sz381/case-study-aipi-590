import unittest

from src.southwest_forecast import run_analysis


class ForecastTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_analysis()

    def test_point_forecasts_match_documented_model(self):
        forecast = self.result["forecast"]
        self.assertAlmostEqual(forecast.loc["Revenue passengers", "point"], 33.5157942542)
        self.assertAlmostEqual(forecast.loc["Average passenger fare", "point"], 223.3205852190)

    def test_conformal_calibration_is_finite_and_reported(self):
        forecast = self.result["forecast"]
        self.assertEqual(int(forecast.loc["Revenue passengers", "calibration_n"]), 12)
        self.assertEqual(int(forecast.loc["Average passenger fare", "calibration_n"]), 12)
        self.assertGreater(forecast.loc["Revenue passengers", "upper_80"], forecast.loc["Revenue passengers", "point"])
        self.assertLess(forecast.loc["Average passenger fare", "lower_80"], forecast.loc["Average passenger fare", "point"])

    def test_point_passenger_revenue_is_inside_guidance_band(self):
        reconciliation = self.result["reconciliation"]
        point = reconciliation.loc["Model passenger revenue", "point_usd_b"]
        lower = reconciliation.loc["Guidance-implied passenger revenue", "lower_usd_b"]
        upper = reconciliation.loc["Guidance-implied passenger revenue", "upper_usd_b"]
        self.assertAlmostEqual(point, 7.4847667869)
        self.assertLessEqual(lower, point)
        self.assertGreaterEqual(upper, point)

    def test_t100_is_a_cross_check_not_a_model_input(self):
        check = self.result["t100_cross_check"].set_index("metric")
        self.assertAlmostEqual(check.loc["segment_passengers", "yoy_change_pct"], -0.4554432833)

    def test_known_tsa_disruptions_are_flagged(self):
        data = self.result["data"]
        self.assertEqual(int(data.loc["2025Q4", "tsa_disruption_days"]), 43)
        self.assertEqual(int(data.loc["2026Q1", "tsa_disruption_days"]), 46)
        self.assertEqual(int(data.loc["2026Q2", "tsa_disruption_days"]), 30)


if __name__ == "__main__":
    unittest.main()
