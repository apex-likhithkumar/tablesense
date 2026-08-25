"""Score the golden set. Prints a per-question table and an overall pass rate.

Truth comes from hand-written oracle SQL in golden.yaml, never from the app,
so a wrong model query cannot quietly become the expected answer.

Usage:  python evals/run_evals.py
"""

import io
import sys
from pathlib import Path

import duckdb
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.answer import answer_question  # noqa: E402
from core.config import settings  # noqa: E402
from core.ingest import load_files  # noqa: E402
from core.profile import find_join_candidates, profile_table, schema_context  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"
GOLDEN = Path(__file__).parent / "golden.yaml"
TOLERANCE = 0.01
PASS_THRESHOLD = 85.0


class _Upload:
    """Minimal stand-in for a Streamlit UploadedFile."""

    def __init__(self, path: Path) -> None:
        self.name = path.name
        self._buffer = io.BytesIO(path.read_bytes())

    def __getattr__(self, item):
        return getattr(self._buffer, item)


def build_session():
    con = duckdb.connect(":memory:")
    loaded, failed = load_files(con, [_Upload(p) for p in sorted(SAMPLES.iterdir())])
    if failed:
        raise SystemExit(f"Sample data failed to load: {failed}")
    profiles = [profile_table(con, t.name, settings.sample_values_per_column) for t in loaded]
    joins = find_join_candidates(
        con, profiles, settings.min_join_overlap, settings.max_join_candidates
    )
    return con, schema_context(profiles, joins), {t.name for t in loaded}


def values_match(expected, actual) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    try:
        return abs(float(expected) - float(actual)) <= TOLERANCE
    except (TypeError, ValueError):
        return str(expected).strip().lower() == str(actual).strip().lower()


def frames_match(con, oracle_sql, frame) -> tuple[bool, str]:
    truth = con.execute(oracle_sql).fetch_df()

    if frame is None or frame.empty:
        return truth.empty, "app returned no rows"

    if len(truth) != len(frame):
        return False, f"expected {len(truth)} row(s), got {len(frame)}"

    # Compare the measure column (last) of every row. Column naming is the
    # model's choice, so position is compared rather than name.
    for i in range(len(truth)):
        if not values_match(truth.iloc[i, -1], frame.iloc[i, -1]):
            return False, f"row {i}: expected {truth.iloc[i, -1]!r}, got {frame.iloc[i, -1]!r}"

    return True, ""


def main() -> int:
    con, schema_text, tables = build_session()
    cases = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))

    rows = []
    passed = 0

    for index, case in enumerate(cases, start=1):
        answer = answer_question(con, case["question"], schema_text, tables)
        record = answer.record

        if case.get("expect", {}).get("type") == "refusal":
            ok = record.status == "refused"
            detail = "refused" if ok else f"did not refuse ({record.status})"
        elif record.status != "answered":
            ok = False
            detail = f"{record.status}: {(record.message or '')[:40]}"
        else:
            ok, why = frames_match(con, case["oracle_sql"], answer.frame)
            detail = "match" if ok else why
            if ok and case.get("chart"):
                got = answer.chart.kind if answer.chart else "none"
                if got != case["chart"]:
                    ok = False
                    detail = f"chart expected {case['chart']}, got {got}"

        passed += ok
        rows.append((case["id"], ok, detail, record.total_ms, len(record.attempts)))
        print(
            f"  {index:>2}/{len(cases)}  {'PASS' if ok else 'FAIL'}  {case['id']}",
            flush=True,
        )

    width = max(len(r[0]) for r in rows) + 2
    print(f"\n{'id'.ljust(width)}{'result'.ljust(8)}{'detail'.ljust(46)}{'ms'.rjust(7)}  tries")
    print("-" * (width + 63))
    for case_id, ok, detail, ms, tries in rows:
        print(
            f"{case_id.ljust(width)}{('PASS' if ok else 'FAIL').ljust(8)}"
            f"{detail[:44].ljust(46)}{str(ms).rjust(7)}  {tries}"
        )

    rate = passed / len(rows) * 100
    failures = [r[0] for r in rows if not r[1]]
    print(f"\n{passed}/{len(rows)} passed  ({rate:.1f}%)")
    if failures:
        print("failed: " + ", ".join(failures))
    print()
    return 0 if rate >= PASS_THRESHOLD else 1


if __name__ == "__main__":
    raise SystemExit(main())
