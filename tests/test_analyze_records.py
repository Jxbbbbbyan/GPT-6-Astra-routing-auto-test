import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/gpt6-routing-test/scripts/analyze_records.py"
SPEC = importlib.util.spec_from_file_location("analyze_records", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def sample(**overrides):
    return {"run_id": "r", "case_id": "c", "turn_id": "t",
            "reply": "2024 年 6 月", **overrides}


def attempts():
    return [
        {"attempt_id": "a1", "status": "error", "request_id": "req1",
         "requested_model": "target", "error": "timeout"},
        {"attempt_id": "a2", "status": "error", "request_id": "req2",
         "requested_model": "target", "error": "retry failed"},
        {"attempt_id": "a3", "status": "success", "request_id": "req3",
         "response_id": "resp3", "requested_model": "fallback",
         "response_model": "fallback", "model_evidence_source": "fixture",
         "fallback_reason": "upstream errors"},
    ]


class EvidenceTests(unittest.TestCase):
    def test_reply_variations_never_identify_backend(self):
        for reply in ("2024 年 6 月", "2024 年 8 月", "无法可靠确认",
                      "不是 2024 年 6 月", "引用：2024年6月；实际无法核实",
                      "June 2024", "2024-08", "2025年9月", ""):
            for model in (None, "gpt-4o", "fixture-target", "auto"):
                with self.subTest(reply=reply, model=model):
                    record = MODULE.build_record(sample(reply=reply, response_model=model))
                    self.assertEqual(record["identity_status"], "unknown")
                    self.assertEqual(record["route_status"], "unverified")
                    self.assertEqual(record["response_model"], model)

    def test_no_metadata_stays_unknown(self):
        record = MODULE.build_record(sample(reply="无法可靠确认"))
        self.assertIsNone(record["response_model"])
        self.assertEqual(record["model_evidence"], "unknown")
        self.assertIsNone(record["model_label_mismatch"])

    def test_reported_alias_is_preserved_without_resolution(self):
        record = MODULE.build_record(sample(requested_model="target", response_model="auto"))
        self.assertEqual(record["response_model"], "auto")
        self.assertEqual(record["model_evidence"], "reported")
        self.assertIsNone(record["model_evidence_source"])
        self.assertTrue(record["model_label_mismatch"])
        self.assertEqual(record["route_status"], "unverified")

    def test_dates_are_mentions_even_in_negation_or_quotes(self):
        record = MODULE.build_record(sample(
            reply="并非 2024年6月；引用 August 2024，另有 2024-06 和 ２０２５年９月。"
        ))
        self.assertEqual(record["reply_observation"]["date_mentions"],
                         ["2024-06", "2024-08", "2025-09"])

    def test_unavailable_phrase_is_only_a_mention(self):
        record = MODULE.build_record(sample(reply="并不是‘无法可靠确认’"))
        self.assertTrue(record["reply_observation"]["unavailable_phrase_mentioned"])
        self.assertEqual(record["identity_status"], "unknown")

    def test_capability_result_cannot_change_identity(self):
        for passed in (True, False):
            record = MODULE.build_record(sample(capability_result={"passed": passed}))
            self.assertEqual(record["capability_result"], {"passed": passed})
            self.assertEqual(record["identity_status"], "unknown")

    def test_two_retries_and_fallback_keep_final_attempt_evidence(self):
        chain = attempts()
        record = MODULE.build_record(sample(
            requested_model="target", attempts=chain, final_attempt_id="a3"
        ))
        self.assertEqual(record["attempts"], chain)
        self.assertEqual(record["request_id"], "req3")
        self.assertEqual(record["response_id"], "resp3")
        self.assertEqual(record["response_model"], "fallback")
        self.assertEqual(record["requested_model"], "target")
        self.assertEqual(record["model_evidence_source"], "fixture")
        self.assertTrue(record["model_label_mismatch"])
        self.assertEqual(record["route_status"], "unverified")

    def test_attempt_identity_conflicts_are_rejected(self):
        for field, value in (("response_model", "wrong"), ("request_id", "req1"),
                             ("response_id", "resp1")):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                MODULE.build_record(sample(attempts=attempts(), final_attempt_id="a3",
                                           **{field: value}))

    def test_missing_or_invalid_final_attempt_is_rejected(self):
        for final_id in (None, "missing"):
            with self.subTest(final_id=final_id), self.assertRaises(ValueError):
                MODULE.build_record(sample(attempts=attempts(), final_attempt_id=final_id))
        with self.assertRaises(ValueError):
            MODULE.build_record(sample(final_attempt_id="a1"))

    def test_duplicate_attempts_and_invalid_status_are_rejected(self):
        for chain in ([attempts()[0], attempts()[0]],
                      [{"attempt_id": "a", "status": "unknown"}]):
            with self.subTest(chain=chain), self.assertRaises(ValueError):
                MODULE.build_record(sample(attempts=chain, final_attempt_id="a"))

    def test_error_is_not_a_successful_model_detection(self):
        record = MODULE.build_record(sample(
            reply="", attempts=[attempts()[0]], final_attempt_id="a1"
        ))
        self.assertEqual(record["record_status"], "error")
        self.assertEqual(record["model_evidence"], "unknown")
        self.assertEqual(record["identity_status"], "unknown")

    def test_input_and_raw_evidence_are_not_mutated(self):
        raw = sample(attempts=attempts(), final_attempt_id="a3",
                     raw_response={"model": "unparsed-alias"},
                     metadata={"upstream_claim": "unverified"})
        before = copy.deepcopy(raw)
        result = MODULE.build_record(raw)
        self.assertEqual(raw, before)
        self.assertEqual(result["raw_response"], raw["raw_response"])
        result["attempts"][0]["error"] = "changed"
        self.assertEqual(raw, before)
        self.assertEqual(result["response_model"], "fallback")

    def test_required_fields_and_types(self):
        for value in ([], sample(run_id=""), sample(case_id=3), sample(reply=None),
                      sample(response_model=False), sample(attempts={}),
                      sample(metadata=[]), sample(capability_result=False)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MODULE.build_record(value)


class CommandTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              capture_output=True, text=True)

    def test_documented_example_runs_and_records_final_attempt(self):
        result = self.run_cli(ROOT / "examples/observations.jsonl")
        self.assertEqual(result.returncode, 0, result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(records), 4)
        self.assertTrue(all(r["identity_status"] == "unknown" for r in records))
        self.assertEqual(records[-1]["request_id"], "req-a3")
        self.assertEqual(records[-1]["response_model"], "fixture-fallback")

    def test_invalid_later_line_does_not_clobber_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "in.jsonl", Path(directory) / "out.jsonl"
            source.write_text(json.dumps(sample()) + "\n{\n", encoding="utf-8")
            output.write_text("keep me", encoding="utf-8")
            result = self.run_cli(source, "--output", output)
            self.assertEqual(result.returncode, 2)
            self.assertIn("line 2", result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(output.read_text(encoding="utf-8"), "keep me")

    def test_duplicate_turns_are_rejected_with_line_number(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "in.jsonl"
            source.write_text((json.dumps(sample()) + "\n") * 2, encoding="utf-8")
            result = self.run_cli(source)
            self.assertEqual(result.returncode, 2)
            self.assertIn("line 2: duplicate", result.stderr)

    def test_same_input_output_is_rejected_without_damage(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "in.jsonl"
            original = json.dumps(sample()) + "\n"
            source.write_text(original, encoding="utf-8")
            result = self.run_cli(source, "--output", source)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(source.read_text(encoding="utf-8"), original)

    def test_empty_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "in.jsonl"
            source.write_text("\n", encoding="utf-8")
            result = self.run_cli(source)
            self.assertEqual(result.returncode, 2)
            self.assertIn("no records", result.stderr)

    def test_file_output_is_valid_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out.jsonl"
            result = self.run_cli(ROOT / "examples/observations.jsonl", "--output", output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(len(output.read_text(encoding="utf-8").splitlines()), 4)


if __name__ == "__main__":
    unittest.main()
