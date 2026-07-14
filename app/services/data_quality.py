"""Data-quality validation for imported/synced run data.

validate_samples() is a pure function (no I/O, no Qt) so it's cheap to
call on every import and easy to unit test: give it the parsed sample
rows (the same list[dict] shape data_service.read_samples()/csv_dicts()
produce -- string values, exactly as read from CSV) plus the run's
already-computed numeric_columns list, get back a flat list of issues.

Each issue is {"severity": "error"|"warning", "code": str, "message": str}.
"error" means the data is likely unusable for analysis (e.g. no numeric
columns at all); "warning" means analysis can proceed but the result
should be treated with some suspicion (a few dropped-out samples, an
implausible outlier, ...).

Several checks here are necessarily heuristic (there's no schema telling
this code what units or plausible ranges a given column *should* have) --
each says so in its own message rather than pretending to certainty.
"""

import math
import statistics

# Deliberately not imported from data_service: data_service will import
# *this* module (to validate on ingest), so importing back from it here
# would be circular. to_float()'s logic is tiny and stable enough that a
# local copy is simpler than restructuring either module around a shared
# utility just to avoid it.


def to_float(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


# Wide but not unbounded: a thermal chamber plausibly spans deep-cryo to
# high-temperature process ranges. This exists to catch obviously broken
# sensor readings (a stuck 9999, a NaN that slipped through as a literal
# string, a sign error), not to model a specific chamber's real limits.
_TEMP_PLAUSIBLE_RANGE = (-273.15, 2000.0)
_GAP_RATIO_THRESHOLD = 5.0  # a sample gap this many times the median dt is flagged
_SAMPLING_RATE_CV_THRESHOLD = 0.5  # coefficient of variation above this = "irregular"
_UNIT_SHIFT_RATIO_THRESHOLD = 10.0  # median-magnitude ratio between halves of a column
_OUTLIER_Z_SCORE = 5.0


def _issue(severity, code, message):
    return {"severity": severity, "code": code, "message": message}


def _check_missing_columns(samples, numeric_columns):
    issues = []
    if not samples:
        issues.append(_issue("error", "no_samples", "The run has no sample rows at all."))
        return issues
    if "timestamp" not in samples[0]:
        issues.append(
            _issue(
                "warning",
                "missing_timestamp_column",
                "No 'timestamp' column -- charts and rate-of-change/gap checks will use "
                "row index instead of real elapsed time.",
            )
        )
    if not numeric_columns:
        issues.append(
            _issue(
                "error",
                "no_numeric_columns",
                "No column in this run has any parseable numeric values -- there is "
                "nothing to chart.",
            )
        )
    return issues


def _check_timestamps(samples):
    issues: list[dict[str, str]] = []
    if not samples or "timestamp" not in samples[0]:
        return issues, []

    raw = [row.get("timestamp") for row in samples]
    parsed = [to_float(v) for v in raw]
    invalid_count = sum(
        1 for v, p in zip(raw, parsed, strict=False) if v not in (None, "") and p is None
    )
    if invalid_count:
        issues.append(
            _issue(
                "warning",
                "invalid_timestamps",
                f"{invalid_count} row(s) have a timestamp that doesn't parse as a number.",
            )
        )

    known = [p for p in parsed if p is not None]
    non_monotonic = sum(1 for a, b in zip(known, known[1:], strict=False) if b < a)
    if non_monotonic:
        issues.append(
            _issue(
                "warning",
                "non_monotonic_timestamps",
                f"{non_monotonic} row(s) have a timestamp earlier than the previous row "
                "(out-of-order samples, a clock reset, or a merged/concatenated file).",
            )
        )
    return issues, known


def _check_duplicates(samples):
    issues: list[dict[str, str]] = []
    if not samples:
        return issues

    seen_rows = set()
    duplicate_rows = 0
    for row in samples:
        key = tuple(sorted(row.items()))
        if key in seen_rows:
            duplicate_rows += 1
        seen_rows.add(key)
    if duplicate_rows:
        issues.append(
            _issue(
                "warning",
                "duplicate_rows",
                f"{duplicate_rows} row(s) are exact duplicates of an earlier row.",
            )
        )

    if "timestamp" in samples[0]:
        timestamps = [to_float(row.get("timestamp")) for row in samples]
        known = [t for t in timestamps if t is not None]
        duplicate_ts = len(known) - len(set(known))
        if duplicate_ts:
            issues.append(
                _issue(
                    "warning",
                    "duplicate_timestamps",
                    f"{duplicate_ts} row(s) share a timestamp with another row (but aren't "
                    "otherwise identical) -- the sampling clock or the export step may have "
                    "produced repeated stamps.",
                )
            )
    return issues


def _check_gaps_and_sampling_rate(known_timestamps):
    issues: list[dict[str, str]] = []
    if len(known_timestamps) < 3:
        return issues

    deltas = [b - a for a, b in zip(known_timestamps, known_timestamps[1:], strict=False)]
    positive_deltas = [d for d in deltas if d > 0]
    if not positive_deltas:
        return issues

    median_dt = statistics.median(positive_deltas)
    if median_dt <= 0:
        return issues

    gap_count = sum(1 for d in deltas if d > median_dt * _GAP_RATIO_THRESHOLD)
    if gap_count:
        issues.append(
            _issue(
                "warning",
                "sample_gaps",
                f"{gap_count} gap(s) in the timestamp sequence are at least "
                f"{_GAP_RATIO_THRESHOLD:g}x the typical sampling interval "
                f"(~{median_dt:.3g}s) -- likely a dropped connection or paused recording.",
            )
        )

    if len(positive_deltas) >= 5:
        mean_dt = statistics.mean(positive_deltas)
        stdev_dt = statistics.stdev(positive_deltas)
        cv = (stdev_dt / mean_dt) if mean_dt else 0.0
        if cv > _SAMPLING_RATE_CV_THRESHOLD:
            issues.append(
                _issue(
                    "warning",
                    "irregular_sampling_rate",
                    f"Sampling interval is irregular (coefficient of variation {cv:.2f} -- "
                    f"typical interval ~{median_dt:.3g}s, but it varies a lot), which will "
                    "distort rate-of-change and rolling-window derived variables.",
                )
            )
    return issues


def _check_nonnumeric_and_implausible_values(samples, numeric_columns):
    issues = []
    for column in numeric_columns:
        raw = [row.get(column) for row in samples]
        parsed = [to_float(v) for v in raw]
        nonnumeric_count = sum(
            1 for v, p in zip(raw, parsed, strict=False) if v not in (None, "") and p is None
        )
        if nonnumeric_count:
            issues.append(
                _issue(
                    "warning",
                    "nonnumeric_values",
                    f"Column '{column}' is mostly numeric but has {nonnumeric_count} "
                    "value(s) that don't parse as a number.",
                )
            )

        known = [p for p in parsed if p is not None]
        if len(known) < 4:
            continue

        # Implausible values.
        if "temp" in column.lower():
            lo, hi = _TEMP_PLAUSIBLE_RANGE
            out_of_range = sum(1 for v in known if v < lo or v > hi)
            if out_of_range:
                issues.append(
                    _issue(
                        "warning",
                        "implausible_sensor_value",
                        f"Column '{column}' has {out_of_range} value(s) outside a plausible "
                        f"temperature range ({lo:g}..{hi:g}) -- possible sensor fault, unit "
                        "mixup, or corrupted data.",
                    )
                )
        else:
            # Median + MAD (median absolute deviation) rather than mean/
            # stdev: a plain stdev-based z-score has a well-known masking
            # problem -- a single extreme outlier inflates the stdev enough
            # to hide itself (e.g. ten 1.0 readings and one 5000.0 spike:
            # the spike drags the stdev up so far that 5000 no longer looks
            # like 5 stdevs away). Median/MAD are robust to exactly this.
            median = statistics.median(known)
            mad = statistics.median(abs(v - median) for v in known)
            if mad > 0:
                # 0.6745 makes the modified z-score comparable in scale to
                # a normal-distribution z-score (standard MAD convention).
                outliers = sum(
                    1 for v in known if 0.6745 * abs(v - median) / mad > _OUTLIER_Z_SCORE
                )
            else:
                # MAD itself is 0 when more than half the values are
                # identical (a very plausible case for a mostly-constant
                # sensor reading) -- the modified z-score is undefined
                # there, so fall back to a plain "way outside a generous
                # band around the constant value" check instead of skipping
                # the column entirely.
                band = max(abs(median) * 3, 1.0)
                outliers = sum(1 for v in known if abs(v - median) > band)
            if outliers:
                issues.append(
                    _issue(
                        "warning",
                        "implausible_sensor_value",
                        f"Column '{column}' has {outliers} value(s) far from the column's "
                        "typical value (robust outlier check) -- worth a manual look "
                        "before trusting downstream statistics.",
                    )
                )

        # Possible unit inconsistency: a large, sustained shift in typical
        # magnitude partway through the column (heuristic: compare median
        # magnitude of the first half against the second half).
        if len(known) >= 10:
            mid = len(known) // 2
            first_half, second_half = known[:mid], known[mid:]
            med_a = statistics.median(abs(v) for v in first_half) or 1e-9
            med_b = statistics.median(abs(v) for v in second_half) or 1e-9
            ratio = max(med_a, med_b) / max(min(med_a, med_b), 1e-9)
            if ratio > _UNIT_SHIFT_RATIO_THRESHOLD:
                issues.append(
                    _issue(
                        "warning",
                        "possible_unit_inconsistency",
                        f"Column '{column}' shifts by roughly {ratio:.0f}x in typical "
                        "magnitude partway through the run -- possibly a unit change "
                        "mid-recording (e.g. Celsius/Kelvin, or a scale-factor change), "
                        "not necessarily a real reading.",
                    )
                )
    return issues


def validate_samples(samples, numeric_columns):
    """Runs every check and returns the combined, flat issue list. Never
    raises on malformed input (empty samples, samples missing expected
    keys) -- a validation pass that itself crashes on bad data would be
    worse than useless."""
    issues = []
    issues.extend(_check_missing_columns(samples, numeric_columns))

    ts_issues, known_timestamps = _check_timestamps(samples)
    issues.extend(ts_issues)
    issues.extend(_check_gaps_and_sampling_rate(known_timestamps))

    issues.extend(_check_duplicates(samples))
    issues.extend(_check_nonnumeric_and_implausible_values(samples, numeric_columns))
    return issues


def summarize(issues):
    """(#errors, #warnings) -- convenience for a one-line UI badge."""
    errors = sum(1 for i in issues if i["severity"] == "error")
    warnings = sum(1 for i in issues if i["severity"] == "warning")
    return errors, warnings
