import unittest

from creditdelta_mcp.finance import compare_latest_periods, latest_periods


def fixture():
    return {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {
                                "start": "2025-04-01",
                                "end": "2025-06-30",
                                "val": 100,
                                "form": "10-Q",
                                "filed": "2025-07-20",
                                "accn": "old",
                                "fy": 2025,
                                "fp": "Q3",
                            },
                            {
                                "end": "2025-09-30",
                                "val": 120,
                                "form": "10-Q",
                                "filed": "2025-10-20",
                                "accn": "new",
                                "fy": 2025,
                                "fp": "Q4",
                            },
                            {
                                "end": "2025-09-30",
                                "val": 121,
                                "form": "10-Q",
                                "filed": "2025-10-21",
                                "accn": "amended",
                                "fy": 2025,
                                "fp": "Q4",
                            },
                            {
                                "start": "2025-01-01",
                                "end": "2025-09-30",
                                "val": 350,
                                "form": "10-Q",
                                "filed": "2025-10-22",
                                "accn": "ytd",
                                "fy": 2025,
                                "fp": "Q4",
                            },
                            {
                                "start": "2025-07-01",
                                "end": "2025-09-30",
                                "val": 121,
                                "form": "10-Q",
                                "filed": "2025-10-21",
                                "accn": "quarter",
                                "frame": "CY2025Q3",
                                "fy": 2025,
                                "fp": "Q4",
                            },
                        ]
                    }
                }
            }
        },
    }


class FinanceTests(unittest.TestCase):
    def test_latest_periods_deduplicates_amended_fact(self):
        result = latest_periods(fixture(), "revenue")
        self.assertEqual(result["periods"][0]["value"], 121)
        self.assertEqual(result["periods"][0]["accession"], "quarter")

    def test_compare_latest_periods(self):
        result = compare_latest_periods(fixture(), "revenue")
        self.assertEqual(result["absolute_change"], 21)
        self.assertEqual(result["percent_change"], 21.0)
        self.assertEqual(result["direction"], "increased")
        self.assertEqual(result["evidence"]["current_accession"], "quarter")

    def test_rejects_unknown_metric(self):
        with self.assertRaises(ValueError):
            latest_periods(fixture(), "profit_magic")


if __name__ == "__main__":
    unittest.main()
