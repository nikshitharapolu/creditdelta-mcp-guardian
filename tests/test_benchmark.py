import tempfile
import unittest

from creditdelta_mcp.benchmark import run_benchmark


class BenchmarkTests(unittest.TestCase):
    def test_reference_benchmark_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_benchmark(directory)
        self.assertEqual(result["total_cases"], 14)
        self.assertEqual(result["passed"], 14)
        self.assertEqual(result["attack_block_rate_percent"], 100.0)
        self.assertEqual(result["safe_false_positive_rate_percent"], 0.0)


if __name__ == "__main__":
    unittest.main()
