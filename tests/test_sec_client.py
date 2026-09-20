import unittest

from creditdelta_mcp.sec_client import SECClient, SEC_TICKERS_URL


class SECClientTests(unittest.TestCase):
    def test_search_company_prioritizes_exact_ticker(self):
        payload = {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": 1, "ticker": "AAP", "title": "Advance Auto Parts"},
        }

        def fetch(url):
            self.assertEqual(url, SEC_TICKERS_URL)
            return payload

        results = SECClient(fetch).search_company("AAPL")
        self.assertEqual(results[0]["name"], "Apple Inc.")
        self.assertEqual(results[0]["cik"], "0000320193")

    def test_rejects_invalid_cik(self):
        with self.assertRaises(ValueError):
            SECClient(lambda _: {}).company_facts("not-a-cik")


if __name__ == "__main__":
    unittest.main()

