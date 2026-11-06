"""Deterministic specimen-label discovery and conservative metadata matching."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

import numpy as np
import pandas as pd


MetadataLookup = dict[str, dict[str, list[dict[str, str]]]]
LABEL_MATCHING_VERSION = "instron-table-and-filename-v5"
DATE_PATTERN = re.compile(r"(?<!\d)(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4})(?!\d)")
NON_LABELS = {
    "", "nan", "none", "null", "n/a", "na", "unknown", "not specified", "-",
    "force", "load", "displacement", "extension", "time", "date", "age", "sex",
    "genotype", "operator", "test", "test name", "test method", "method", "results",
    "export", "data", "raw data", "mm", "n", "s", "id", "name", "identifier",
}


def clean_identifier(value) -> str:
    if value is None or pd.isna(value):
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip().strip("\"'").strip()


def normalize_identifier(value) -> str:
    return " ".join(clean_identifier(value).casefold().split())


def alphanumeric_identifier(value) -> str:
    text = normalize_identifier(value)
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".")[0]
    text = "".join(char for char in text if char.isalnum())
    return re.sub(r"\d+", lambda match: str(int(match.group())), text)


def extract_numeric_identifiers(value, max_digits: int = 4) -> list[str]:
    """Find complete ID numbers, never a truncated suffix of a longer number."""
    text = normalize_identifier(value)
    if re.fullmatch(r"\d+\.0+", text):
        text = text.split(".")[0]
    text = DATE_PATTERN.sub(" ", text)
    text = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", " ", text)
    # Full age units and acquisition annotations are not specimen identifiers.
    without_genes = re.sub(r"(?<![a-z])(?:rosa|runx|il)\s*\d+", " ", text)
    has_gene_annotation = without_genes != text
    text = without_genes
    text = re.sub(r"(?<![a-z])(?:age|trial|run|replicate)\s*[-_:#]?\s*\d+(?!\d)", " ", text)
    text = re.sub(r"(?<![a-z0-9])\d+\s*(?:months?|mo|weeks?|wk|days?)(?![a-z0-9])", " ", text)
    # A leading 718M is an ID with a letter suffix, not 718 months. Interpret
    # compact age suffixes only after another number or a genotype annotation.
    text = re.sub(
        r"(?<![a-z0-9])\d+\s*[mwd](?![a-z0-9])",
        lambda match: " " if has_gene_annotation or re.search(r"\d", text[:match.start()]) else match.group(),
        text,
    )
    text = re.sub(r"\d+\.\d+", " ", text)
    tokens = {str(int(match.group())) for match in re.finditer(r"\d+", text)
              if len(str(int(match.group()))) <= max_digits}
    # A long specimen number has priority over residual short tokens (e.g. 585_18M6).
    return sorted(tokens, key=lambda token: (-len(token), token))


def extract_numeric_identifier(value, max_digits: int = 4) -> str:
    tokens = extract_numeric_identifiers(value, max_digits)
    return tokens[0] if tokens else ""


def _primary_numbers(value) -> list[str]:
    tokens = extract_numeric_identifiers(value)
    return [token for token in tokens if len(token) == len(tokens[0])] if tokens else []


def build_metadata_lookup(metadata_df: pd.DataFrame | None, id_column: str | None) -> MetadataLookup:
    lookup: MetadataLookup = {"exact": {}, "alphanumeric": {}, "numeric": {}}
    if metadata_df is None or not id_column or id_column not in metadata_df.columns:
        return lookup
    # Only explicitly named alternate specimen identifiers are aliases. Notes,
    # run numbers, biological variables, and source row numbers are never IDs.
    alias_names = {"specimenalias", "samplealias", "alternateid", "alternatespecimenid",
                   "alternatesampleid", "microctsamplename"}
    alias_columns = [column for column in metadata_df.columns if column != id_column
                     and re.sub(r"[^a-z0-9]", "", normalize_identifier(column)) in alias_names]
    for _, row in metadata_df.iterrows():
        identifier = clean_identifier(row.get(id_column))
        if normalize_identifier(identifier) in NON_LABELS:
            continue
        record = {str(column): clean_identifier(value) for column, value in row.items()}
        identifiers = [identifier] + [record[str(column)] for column in alias_columns
                                       if normalize_identifier(record[str(column)]) not in NON_LABELS]
        keys = {
            "exact": {normalize_identifier(value) for value in identifiers},
            "alphanumeric": {alphanumeric_identifier(value) for value in identifiers},
            "numeric": {number for value in identifiers for number in _primary_numbers(value)},
        }
        for kind, values in keys.items():
            for value in values:
                if value:
                    lookup[kind].setdefault(value, []).append(record)
    return lookup


def _match_duplicate_run(records: list[dict[str, str]], run_number: str) -> dict[str, str] | None:
    """Disambiguate an already matched full ID with the instrument run number."""
    aliases = {"instronrun", "instronrunnumber", "testrun", "runnumber", "runno", "runid"}
    matches = []
    for record in records:
        columns = [column for column in record if re.sub(r"[^a-z]", "", column.casefold()) in aliases]
        if len(columns) == 1 and alphanumeric_identifier(record[columns[0]]) == run_number:
            matches.append(record)
    return matches[0] if len(matches) == 1 else None


def find_metadata_row(
    lookup: MetadataLookup | None, *candidate_ids: str, run_number: str = "",
) -> tuple[dict[str, str] | None, str]:
    """Prefer full labels, then use a unique specimen number as a fallback."""
    if not lookup:
        return None, ""

    for kind, key_function in (
        ("exact", lambda value: [normalize_identifier(value)]),
        ("alphanumeric", lambda value: [alphanumeric_identifier(value)]),
    ):
        matches = {}
        used_keys = set()
        for candidate in candidate_ids:
            for key in key_function(candidate):
                for record in lookup.get(kind, {}).get(key, []):
                    matches[id(record)] = record
                    used_keys.add(key)
        if len(matches) == 1:
            return next(iter(matches.values())), f"{kind} label {', '.join(sorted(used_keys))}"
        if len(matches) > 1:
            # A filename sequence is only a secondary key after a full label
            # match; it must never substitute for the specimen identity.
            if run_number:
                record = _match_duplicate_run(list(matches.values()), run_number)
                if record is not None:
                    return record, f"{kind} label {', '.join(sorted(used_keys))}; Instron run {run_number}"
            return None, f"ambiguous duplicate {kind} labels: {', '.join(sorted(used_keys))}"

    numeric_matches = {}
    numeric_keys = set()
    for candidate in candidate_ids:
        for key in _primary_numbers(candidate):
            for record in lookup.get("numeric", {}).get(key, []):
                numeric_matches[id(record)] = record
                numeric_keys.add(key)
    if len(numeric_matches) == 1:
        return next(iter(numeric_matches.values())), f"unique numeric ID {', '.join(sorted(numeric_keys))}"
    if len(numeric_matches) > 1:
        return None, f"ambiguous repeated numeric ID: {', '.join(sorted(numeric_keys))}"
    return None, ""


@dataclass(frozen=True)
class LabelCandidate:
    label: str
    source: str
    priority: int


@dataclass
class SpecimenIdentity:
    specimen_id: str
    display_label: str
    source: str
    metadata_row: dict[str, str] | None = None
    metadata_id: str = ""
    match_method: str = ""
    warning: str = ""
    error: str = ""


def _label_priority(text: str) -> int:
    key = normalize_identifier(text).replace("_", " ").replace("#", " number").strip(" :.=;")
    key = re.sub(r"^(?:unique|test)\s+", "", key)
    # Instron/Bluehill's default custom label field. Notes and numbered
    # secondary text inputs are not interchangeable with this ID field.
    if re.fullmatch(r"(?:specimen|sample)\s+text\s+input\s+1", key):
        return 100
    match = re.fullmatch(r"(?:specimen|sample|animal|mouse|bone|femur|tendon|tissue|subject)\s*(id|identifier|name|label|number|no)?", key)
    if not match:
        return 0
    return 100 if match.group(1) in ("id", "identifier", "name", "label") else 90


def _is_measurement_heading(value) -> bool:
    text = normalize_identifier(value).replace("_", " ")
    return bool(re.match(
        r"^(?:(?:maximum|minimum|max|min|peak|ultimate|yield|mean|average)\s+)?"
        r"(?:force|load|displacement|extension|strain|stress|modulus|stiffness|"
        r"energy|work|time|length|width|thickness|area)(?:$|[\s(\[])", text,
    ))


def _is_unit(value) -> bool:
    text = normalize_identifier(value).strip("()[] ")
    return text in {"n", "kn", "mn", "mm", "cm", "m", "s", "sec", "hz", "pa", "kpa", "mpa", "gpa",
                    "%", "mm/mm", "mm/min", "mm/s", "n/mm", "mm^2", "mm2", "j", "mj"}


def _plausible_label(value) -> bool:
    text = clean_identifier(value)
    normalized = normalize_identifier(text)
    if (normalized in NON_LABELS or _label_priority(text) or len(text) > 180
            or _is_measurement_heading(text) or _is_unit(text)):
        return False
    if not any(char.isalnum() for char in text):
        return False
    if DATE_PATTERN.fullmatch(text) or re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", text):
        return False
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?\s*(?:mm|cm|n|kg|s|sec|hz|mpa)", normalized):
        return False
    if re.fullmatch(r"[-+]?\d*\.\d+", text) and not re.fullmatch(r"\d+\.0+", text):
        return False
    return True


def _cell_name(row: int, column: int) -> str:
    letters = ""
    index = column + 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row + 1}"


def scan_specimen_labels(df: pd.DataFrame, file_name: str = "", lookup: MetadataLookup | None = None) -> list[LabelCandidate]:
    """Scan labeled header/footer fields, B4, filename, then metadata-backed header cells.

    Numeric measurement rows are excluded before scanning so force and displacement
    values cannot become labels. Unlabeled scanning stops at the measurement table.
    """
    if df.empty:
        return []
    measurement_rows = np.zeros(len(df), dtype=bool)
    data_start = len(df)
    if df.shape[1] >= 3:
        numeric = (pd.to_numeric(df.iloc[:, 1], errors="coerce").notna()
                   & pd.to_numeric(df.iloc[:, 2], errors="coerce").notna()).to_numpy()
        runs = np.flatnonzero(np.convolve(numeric.astype(int), np.ones(3, dtype=int), mode="valid") == 3) if len(df) >= 3 else []
        if len(runs):
            data_start = int(runs[0])
            measurement_rows[data_start:] = numeric[data_start:]
    candidates = []
    occupied_cells = set()

    def add(value, source, priority):
        if _plausible_label(value):
            candidate = LabelCandidate(clean_identifier(value), source, priority)
            if candidate not in candidates:
                candidates.append(candidate)

    for row in np.flatnonzero(~measurement_rows):
        for column in range(df.shape[1]):
            text = clean_identifier(df.iat[row, column])
            if not text:
                continue
            inline = re.split(r"\s*[:=]\s*", text, maxsplit=1)
            priority = _label_priority(inline[0])
            if not priority:
                continue
            source = f"{inline[0].strip()}: {_cell_name(row, column)}"
            if len(inline) == 2 and inline[1]:
                add(inline[1], source, priority)
                occupied_cells.add((row, column))
                continue
            value_found = False
            for offset in range(1, min(4, df.shape[1] - column)):
                value = clean_identifier(df.iat[row, column + offset])
                if not value:
                    continue
                if _plausible_label(value):
                    add(value, f"{text}: {_cell_name(row, column + offset)}", priority)
                    occupied_cells.add((row, column + offset))
                    value_found = True
                break
            if not value_found:
                # Results tables put the specimen under its column heading,
                # often after a blank/unit row, not beside it like key/value metadata.
                for below in range(row + 1, min(row + 5, data_start)):
                    value = clean_identifier(df.iat[below, column])
                    if not value or _is_unit(value):
                        continue
                    if _plausible_label(value):
                        add(value, f"{text}: {_cell_name(below, column)} (below)", priority)
                        occupied_cells.add((below, column))
                    break

    if df.shape[0] > 3 and df.shape[1] > 1 and 3 < data_start and (3, 1) not in occupied_cells:
        # B4 is a fallback, not an override of explicitly labeled fields.
        row_key = clean_identifier(df.iat[3, 0])
        excluded_keys = {"date", "time", "age", "sex", "genotype", "operator", "test name", "method", "test method", "force", "load", "displacement"}
        if normalize_identifier(row_key).strip(" :") not in excluded_keys:
            add(df.iat[3, 1], "B4 (legacy layout)", 60)
    if file_name:
        add(Path(file_name).stem, "File name", 40)
        if not any(candidate.source == "File name" for candidate in candidates):
            candidates.append(LabelCandidate(Path(file_name).stem, "File name", 10))
    if lookup:
        # Metadata-backed scanning lets the app find an ID in an unlabeled or
        # shifted header cell. Exact/alphanumeric matches rank above a unique
        # numeric fallback; dates, ages, measurement rows, and ambiguous
        # duplicate specimen numbers remain excluded.
        for row in range(min(data_start, 100)):
            populated = [(column, clean_identifier(df.iat[row, column])) for column in range(df.shape[1]) if clean_identifier(df.iat[row, column])]
            # Key/value rows describing dates, operators, age, etc. are not fallback IDs.
            if len(populated) > 1 and populated[0][1] and not _label_priority(populated[0][1]):
                continue
            for column, value in populated:
                if (row, column) in occupied_cells or not _plausible_label(value):
                    continue
                record, method = find_metadata_row(lookup, value)
                if record is not None:
                    priority = 75 if method.startswith(("exact", "alphanumeric")) else 70
                    add(value, f"Auto-detected header {_cell_name(row, column)} ({method})", priority)
    return sorted(candidates, key=lambda candidate: -candidate.priority)


def resolve_specimen_identity(df: pd.DataFrame, file_name: str = "", lookup: MetadataLookup | None = None,
                              id_column: str | None = None) -> SpecimenIdentity:
    candidates = scan_specimen_labels(df, file_name, lookup)
    if not candidates:
        return SpecimenIdentity("", "", "", error="No specimen label could be identified in the CSV or file name.")
    primary = candidates[0]
    top = [candidate for candidate in candidates if candidate.priority == primary.priority]
    run_suffix = re.search(r"_(\d+)$", Path(file_name).stem)
    run_number = str(int(run_suffix.group(1))) if run_suffix else ""
    matches = [(candidate, *find_metadata_row(lookup, candidate.label, run_number=run_number)) for candidate in candidates]
    matched = [(candidate, row, method) for candidate, row, method in matches if row is not None]
    authoritative = primary.priority >= 90
    warning = ""

    # A labeled CSV identity must not be replaced by an unrelated filename match.
    eligible = [(candidate, row, method) for candidate, row, method in matched
                if not authoritative or candidate.priority == primary.priority]
    if not authoritative and any(candidate.priority >= 40 for candidate, _, _ in eligible):
        eligible = [(candidate, row, method) for candidate, row, method in eligible if candidate.priority >= 40]
    rows = {id(row): row for _, row, _ in eligible}
    conflict = len(rows) > 1
    if authoritative and len(top) > 1:
        unmatched_top = [candidate for candidate, row, _ in matches if candidate in top and row is None]
        conflict |= len({alphanumeric_identifier(candidate.label) for candidate in top}) > 1 and bool(unmatched_top or not rows)
    if len(rows) == 1:
        chosen = next(iter(rows.values()))
        # B4 and filenames are independent evidence; disagreement needs review.
        conflict |= any(row is not chosen and (candidate.priority == primary.priority or candidate.source in ("File name", "B4 (legacy layout)"))
                        for candidate, row, _ in matched)
    if conflict:
        details = "; ".join(f"{candidate.source} = {candidate.label}" for candidate in candidates if candidate.priority >= 40)
        fallback = Path(file_name).stem or primary.label
        return SpecimenIdentity(primary.label, fallback, primary.source, match_method="ambiguous label evidence",
                                warning=f"Conflicting specimen labels: {details}. Using file name until resolved.")

    if eligible:
        candidate, row, method = eligible[0]
        detected = primary if authoritative else candidate
        metadata_id = clean_identifier(row.get(id_column)) if id_column else ""
        if detected.source == "File name":
            warning = "Specimen label was recovered from the file name."
        return SpecimenIdentity(detected.label, metadata_id or detected.label, detected.source,
                                row, metadata_id, method, warning)

    ambiguous = [method for candidate, _, method in matches if method.startswith("ambiguous") and candidate.priority >= primary.priority]
    if ambiguous:
        warning = "; ".join(ambiguous)
    elif primary.source == "File name":
        warning = "No labeled specimen field was found; using the file name as the specimen label."
    return SpecimenIdentity(primary.label, primary.label, primary.source, match_method=warning if ambiguous else "",
                            warning=warning)
