#!/usr/bin/env python3
"""Normalize supplied per-turn evidence without inferring a backend from prose.

This is an offline JSONL recorder, not a model client or a backend detector.
Only Python's standard library is required (Python 3.10+).
"""

import argparse
import copy
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unicodedata


RULE_VERSION = "2.0"
OPTIONAL_TEXT = (
    "timestamp_utc", "client_version", "provider", "endpoint",
    "conversation_kind", "history_hash", "requested_model", "requested_effort",
    "effective_effort", "request_id", "response_id", "response_model",
    "model_evidence_source",
)
MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)


def text_field(data, name, required=False):
    value = data.get(name)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def observe_reply(reply):
    """Report mentions, including quotations/negation; never claim a cutoff."""
    normalized = unicodedata.normalize("NFKC", reply)
    mentions = set()
    for year, month in re.findall(
        r"(?<!\d)(20\d{2})\s*年\s*(1[0-2]|0?[1-9])\s*月", normalized
    ):
        mentions.add(f"{year}-{int(month):02d}")
    for year, month in re.findall(
        r"(?<!\d)(20\d{2})[-/](0[1-9]|1[0-2])(?!\d)", normalized
    ):
        mentions.add(f"{year}-{month}")
    for month, year in re.findall(
        r"\b(" + "|".join(MONTHS) + r")\s+(20\d{2})\b",
        normalized, re.IGNORECASE,
    ):
        mentions.add(f"{year}-{MONTHS.index(month.lower()) + 1:02d}")
    return {
        "date_mentions": sorted(mentions),
        "unavailable_phrase_mentioned": any(
            phrase in normalized.casefold()
            for phrase in (
                "无法可靠确认", "无可供核实", "无知识训练截止日期",
                "cannot reliably confirm", "cannot verify",
            )
        ),
    }


def build_record(data):
    if not isinstance(data, dict):
        raise ValueError("each input record must be a JSON object")
    record = {key: text_field(data, key, required=True)
              for key in ("run_id", "case_id", "turn_id")}
    reply = data.get("reply")
    if not isinstance(reply, str):
        raise ValueError("reply must be a string (use an empty string for an error)")
    record.update({key: text_field(data, key) for key in OPTIONAL_TEXT})
    attempts = data.get("attempts", [])
    if not isinstance(attempts, list):
        raise ValueError("attempts must be an array")
    ids = set()
    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise ValueError("each attempt must be a JSON object")
        attempt_id = text_field(attempt, "attempt_id", required=True)
        if attempt_id in ids:
            raise ValueError("attempt_id values must be unique")
        ids.add(attempt_id)
        if attempt.get("status") not in ("success", "error"):
            raise ValueError("attempt status must be success or error")
        for key in OPTIONAL_TEXT:
            text_field(attempt, key)
    final_id = text_field(data, "final_attempt_id")
    final = None
    if attempts:
        if final_id not in ids:
            raise ValueError("final_attempt_id must identify a recorded attempt")
        final = next(a for a in attempts if a["attempt_id"] == final_id)
        # Do not silently attach the chosen model/ID from another attempt.
        for key in ("response_model", "request_id", "response_id"):
            top, chosen = record[key], final.get(key)
            if top is not None and chosen is not None and top != chosen:
                raise ValueError(f"{key} disagrees with final_attempt_id")
            record[key] = chosen if chosen is not None else top
        record["model_evidence_source"] = (
            final.get("model_evidence_source") or record["model_evidence_source"]
        )
    elif final_id is not None:
        raise ValueError("final_attempt_id requires attempts")
    for key in ("metadata", "capability_result"):
        if data.get(key) is not None and not isinstance(data[key], dict):
            raise ValueError(f"{key} must be an object or null")
    requested, reported = record["requested_model"], record["response_model"]
    record.update({
        "rule_version": RULE_VERSION,
        "record_status": final["status"] if final else "observed",
        "reply": reply,
        "reply_observation": observe_reply(reply),
        "model_evidence": "reported" if reported else "unknown",
        "identity_status": "unknown",
        "route_status": "unverified",
        "model_label_mismatch": (
            requested != reported if requested is not None and reported is not None
            else None
        ),
        "attempts": copy.deepcopy(attempts),
        "final_attempt_id": final_id,
        "raw_response": copy.deepcopy(data.get("raw_response")),
        "metadata": copy.deepcopy(data.get("metadata")),
        "capability_result": copy.deepcopy(data.get("capability_result")),
    })
    return record


def load_records(path):
    records, seen = [], set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = build_record(json.loads(line))
            key = tuple(record[name] for name in ("run_id", "case_id", "turn_id"))
            if key in seen:
                raise ValueError("duplicate run_id/case_id/turn_id")
            seen.add(key)
            records.append(record)
        except ValueError as exc:
            raise ValueError(f"line {line_number}: {exc}") from exc
    if not records:
        raise ValueError("input contains no records")
    return records


def write_records(path, content):
    """Replace output only after the entire input has validated."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="per-turn evidence JSONL")
    parser.add_argument("--output", type=Path, help="output JSONL; defaults to stdout")
    args = parser.parse_args(argv)
    try:
        if args.output and args.input.resolve() == args.output.resolve():
            raise ValueError("input and output must be different files")
        records = load_records(args.input)
        content = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
        if args.output:
            write_records(args.output, content)
        else:
            sys.stdout.write(content)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
