import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EMITTERS = {
    "pine/signal_engine.pine": "nz(tE)",
    "pine/signal_engine_strategy.pine": "time",
}


class PineAlertContractTests(unittest.TestCase):
    def test_json_emitters_use_canonical_v2_contract_identity_and_time(self):
        for relative_path, timestamp_expression in EMITTERS.items():
            source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
            json_line = source[source.index("f_json(") :].splitlines()[1]
            expected_time = (
                f'str.format_time({timestamp_expression}, '
                '"yyyy-MM-dd\'T\'HH:mm:ss\'Z\'", "UTC")'
            )

            with self.subTest(emitter=relative_path):
                self.assertIn('"version":"2.0.0"', json_line)
                self.assertIn('"symbol":"NEAR-USDT"', json_line)
                self.assertNotIn("syminfo.ticker", json_line)
                self.assertIn(expected_time, json_line)


if __name__ == "__main__":
    unittest.main()
