"""Specimen-level inference for the exact selection shown in grouped charts.

Categorical factors are retained together, including interactions. Rank tests
compare observed cells, not factorial main effects or interactions. No test here
can establish independence of specimens; paired designs require a different model.
"""
from __future__ import annotations

from hashlib import sha256
from itertools import combinations
import json
import warnings

import numpy as np
import pandas as pd

try:
    from scipy import stats
    import statsmodels.api as sm
    from statsmodels.formula.api import ols
    from statsmodels.stats.multicomp import pairwise_tukeyhsd
    from statsmodels.stats.multitest import multipletests
    from statsmodels.stats.oneway import anova_oneway
    from patsy import build_design_matrices
    STATISTICS_AVAILABLE = True
except ImportError:
    STATISTICS_AVAILABLE = False

BIOLOGICAL_FACTORS = ("Genotype", "Age", "Sex")
MISSING_LABELS = {"", "nan", "none", "unspecified", "<na>"}


def biological_value(value):
    return "Unspecified" if pd.isna(value) or str(value).strip().lower() in MISSING_LABELS else str(value).strip()


def biological_key(row):
    """Lossless group identity even when a metadata label contains a separator."""
    return json.dumps([biological_value(row.get(name)) for name in BIOLOGICAL_FACTORS])


def stats_factor_options(summary):
    return [name for name in BIOLOGICAL_FACTORS if name in summary and
            summary[name].map(biological_value).loc[lambda values: values != "Unspecified"].nunique() > 1]


def statistics_scope_id(summary, metric):
    """Prevent annotation of stale results after values or selected rows change."""
    records = []
    for _, row in summary.iterrows():
        value = pd.to_numeric(row.get(metric), errors="coerce")
        if np.isfinite(value):
            records.append((str(row.get("Specimen ID", "")), str(row.get("File name", "")),
                            biological_key(row), float(value)))
    return sha256(json.dumps(sorted(records)).encode()).hexdigest()


def significance_stars(p_value):
    if not np.isfinite(p_value):
        return ""
    for threshold, stars in ((0.0001, "****"), (0.001, "***"), (0.01, "**"), (0.05, "*")):
        if p_value < threshold:
            return stars
    return ""


def format_p_value(value):
    if not np.isfinite(value):
        return ""
    return "<0.0001" if value < 0.0001 else f"{value:.4f}"


def holm_adjust_pvalues(values):
    values = np.asarray(values, dtype=float)
    result = np.full(len(values), np.nan)
    valid = np.isfinite(values)
    if valid.any():
        # Undefined planned tests still count toward the comparison family.
        result[:] = multipletests(np.where(valid, values, 1.0), method="holm")[1]
        result[~valid] = np.nan
    return result.tolist()


def _prepare(summary, metric, covariates):
    data = summary.reset_index(drop=True).copy()
    excluded = []

    def retain(mask, category, reason):
        nonlocal data
        for _, row in data.loc[~mask].iterrows():
            excluded.append({
                "Metric": metric, "Specimen ID": str(row.get("Specimen ID", "")),
                "File name": str(row.get("File name", "")),
                "Category": category, "Reason": reason,
                "Processing warning": "" if pd.isna(row.get("Warning")) else str(row.get("Warning", "")),
            })
        data = data.loc[mask].copy()

    data["value"] = pd.to_numeric(data[metric], errors="coerce")
    retain(np.isfinite(data["value"]), "Missing outcome", f"No finite value for {metric}.")
    for name in BIOLOGICAL_FACTORS:
        data[name] = data[name].map(biological_value) if name in data else "Unspecified"
        if (data[name] != "Unspecified").any():
            retain(data[name] != "Unspecified", "Missing biological label", f"Missing {name} label.")
    for index, name in enumerate(covariates):
        data[f"cov_{index}"] = pd.to_numeric(data[name], errors="coerce")
        retain(np.isfinite(data[f"cov_{index}"]), "Missing covariate", f"No finite value for {name}.")
    factors = stats_factor_options(data)
    data["Group"] = data.apply(biological_key, axis=1) if len(data) else pd.Series(dtype=str)
    return data, factors, excluded


def _diagnostics(model, groups):
    residuals = np.asarray(model.resid, dtype=float)
    normality = np.nan
    variance = np.nan
    if 3 <= len(residuals) <= 5000 and np.ptp(residuals) > 0:
        normality = float(stats.shapiro(residuals).pvalue)
    if all(len(values) >= 2 for values in groups.values()):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            variance = float(stats.levene(*groups.values(), center="median").pvalue)
    normality_note = ("Residual normality: not assessed" if not np.isfinite(normality) else
                      "Residual normality: evidence of departure" if normality < .05 else
                      "Residual normality: no departure detected")
    variance_note = ("Equal variance: not assessed" if not np.isfinite(variance) else
                     "Equal variance: evidence of unequal variance" if variance < .05 else
                     "Equal variance: no difference detected")
    return normality, variance, normality_note + "; " + variance_note


def analyze_metric(summary, metric, factors=None, *, covariates=(), comparison_family="simple", independent=True):
    """Automatic OLS/ANCOVA, Welch, or rank inference, without pooling strata.

    ``factors`` is accepted for older callers. All varying biological variables
    in the selected data are always retained; layout choices cannot omit them.
    Holm families include every planned pair for this metric, not just stars.
    """
    rows = []
    common = {"Metric": metric, "Scope ID": statistics_scope_id(summary, metric),
              "Selected specimens (n)": len(summary), "Covariates": " + ".join(covariates),
              "Experimental design": "Independent specimens" if independent else "Paired/repeated specimens",
              "Comparison family": "All observed-cell pairs" if comparison_family == "all" else "Simple effects (one factor differs)",
              "Multiplicity scope": "Within each property; not across properties", "Alpha": .05}

    def add(method, effect, *, p=np.nan, adjusted=np.nan, statistic=np.nan, kind="omnibus", note="", **extra):
        rows.append(dict(common, **{
            "Method": method, "Test/effect": effect, "Result type": kind,
            "Statistic": statistic, "P value": format_p_value(p), "Adjusted P value": format_p_value(adjusted),
            "P value (numeric)": p, "Adjusted P value (numeric)": adjusted,
            "Significant (unadjusted omnibus P < 0.05)": bool(np.isfinite(p) and p < .05) if kind == "omnibus" else np.nan,
            "Significant (adjusted P < 0.05)": bool(significance_stars(adjusted)),
            "Stars": significance_stars(adjusted) if kind == "pairwise" else "",
            "Note": note, **extra}))

    def unavailable(note):
        add("Not run", "Inference unavailable", kind="diagnostic", note=note)
        return rows

    if not independent:
        return unavailable("Paired/repeated observations require animal IDs and a repeated-measures or mixed-effects model; independent tests and stars are disabled.")
    if not STATISTICS_AVAILABLE:
        return unavailable("Install scipy and statsmodels to run statistics.")
    if metric not in summary:
        return unavailable("Property is unavailable in the selected data.")
    if any(name not in summary for name in covariates):
        return unavailable("A selected covariate is unavailable.")
    data, factors, excluded = _prepare(summary, metric, covariates)
    groups = {key: group["value"].to_numpy(float) for key, group in data.groupby("Group", sort=True)}
    common.update({"Factors": " + ".join(factors), "Analyzed specimens (n)": len(data),
                   "Excluded specimens (n)": len(summary) - len(data),
                   "Excluded specimen IDs": json.dumps([item["Specimen ID"] for item in excluded]),
                   "Exclusion details (JSON)": json.dumps(excluded),
                   "Specimen IDs": json.dumps(data.get("Specimen ID", pd.Series(dtype=str)).astype(str).tolist())})
    if "yield" in metric.casefold() and "Yield method" in data:
        common["Yield methods (JSON)"] = json.dumps(data["Yield method"].value_counts().to_dict())
        common["Yield criteria (JSON)"] = json.dumps(data.get("Yield criterion", pd.Series(dtype=str)).dropna().unique().tolist())
        common["Yield offsets (JSON)"] = data.reindex(columns=[
            "Specimen ID", "Yield method", "Yield analysis basis", "Yield offset basis",
            "Yield offset used (%)", "Yield offset used (mm)",
            "Yield proportional departure used (%)", "Yield reduced proportional limit used",
        ]).to_json(orient="records")
    if len(groups) < 2 or not factors:
        return unavailable("At least two biological groups with valid values are required; constant/missing variables are not model factors.")
    if any(len(values) < 2 for values in groups.values()):
        return unavailable("At least two independent specimens per observed group are required; one or more groups have n=1.")
    if any(data[f"cov_{index}"].nunique() < 2 for index in range(len(covariates))):
        return unavailable("A selected covariate is constant in these complete cases.")

    complete = len(groups) == int(np.prod([data[name].nunique() for name in factors]))
    model_data = data.copy()
    names = {}
    for index, name in enumerate(factors):
        model_data[f"factor_{index}"] = data[name]
        names[f"C(factor_{index}, Sum)"] = name
    for index, name in enumerate(covariates):
        names[f"cov_{index}"] = name
        model_data[f"cov_{index}"] -= model_data[f"cov_{index}"].mean()
    terms = " * ".join(list(names)[:len(factors)]) if complete else "C(Group, Sum)"
    terms += "".join(f" + cov_{index}" for index in range(len(covariates)))
    try:
        model = ols("value ~ " + terms, data=model_data).fit()
    except (ValueError, np.linalg.LinAlgError) as exc:
        return unavailable(f"Model could not be fitted: {exc}")
    if model.df_resid < 2 or np.linalg.matrix_rank(model.model.exog) < model.model.exog.shape[1]:
        return unavailable("The model is not estimable: insufficient residual degrees of freedom or confounded predictors.")
    if model.ssr <= np.finfo(float).eps * max(1.0, float(np.sum(data["value"] ** 2))):
        return unavailable("There is no measurable residual variability; inferential p-values and stars are not reported.")
    normality, variance, diagnostic = _diagnostics(model, groups)
    common.update({"Residual normality P": format_p_value(normality), "Equal variance P": format_p_value(variance),
                   "Residual normality P (numeric)": normality, "Equal variance P (numeric)": variance,
                   "Assumption result": diagnostic, "Residual DF": float(model.df_resid)})
    base_note = "Independent specimens assumed. Missing outcome/covariate or partially missing biological labels excluded per property. "
    if not complete:
        base_note += "Incomplete factorial design: observed combinations compared; separate factorial effects are not estimable. "
    if covariates:
        base_note += "ANCOVA assumes common linear covariate slopes; pairwise estimates are at mean covariates. "
    common["Analysis note"] = base_note

    nonnormal = np.isfinite(normality) and normality < .05
    unequal = not np.isfinite(variance) or variance < .05
    if not np.isfinite(normality):
        return unavailable("Residual normality could not be assessed; automatic inference withheld for review.")
    if nonnormal and covariates:
        return unavailable("Residual normality check failed for ANCOVA. A rank test would discard covariate adjustment; review the model or a justified outcome transformation.")
    labels = list(groups)
    pairs = [(a, b) for a, b in combinations(labels, 2)
             if comparison_family == "all" or sum(x != y for x, y in zip(json.loads(a), json.loads(b))) == 1]
    common["Planned pairwise comparisons (n)"] = len(pairs)
    if not pairs:
        add("Not run", "No simple-effect comparisons", kind="diagnostic",
            note="No observed groups differ in only one biological variable. Select all group pairs to compare observed combinations; confounded factor effects cannot be separated.")
    raw_pvalues, pair_results = [], []

    def pair_record(a, b, statistic, p, method, **extra):
        raw_pvalues.append(p)
        pair_results.append((a, b, statistic, p, method, extra))

    if nonnormal:
        common["Analysis note"] += "Rank tests compare distributions across observed combinations; they do not test factorial interactions or covariate-adjusted means."
        if len(groups) > 2:
            result = stats.kruskal(*groups.values())
            add("Kruskal-Wallis across observed combinations", "Observed groups", p=float(result.pvalue),
                statistic=float(result.statistic), DF1=len(groups) - 1)
        for a, b in pairs:
            result = stats.mannwhitneyu(groups[a], groups[b], alternative="two-sided", method="auto")
            pair_record(a, b, float(result.statistic), float(result.pvalue), "Mann-Whitney U + Holm")
    elif len(factors) == 1 and not covariates and len(groups) == 2:
        a, b = labels
        result = stats.ttest_ind(groups[a], groups[b], equal_var=not unequal)
        method = "Welch t-test" if unequal else "Student t-test"
        pair_record(a, b, float(result.statistic), float(result.pvalue), method, DF2=float(result.df))
    elif len(factors) == 1 and not covariates and unequal:
        result = anova_oneway(list(groups.values()), use_var="unequal")
        add("Welch one-way ANOVA", factors[0], p=float(result.pvalue), statistic=float(result.statistic),
            DF1=float(result.df_num), DF2=float(result.df_denom))
        for a, b in pairs:
            result = stats.ttest_ind(groups[a], groups[b], equal_var=False)
            pair_record(a, b, float(result.statistic), float(result.pvalue), "Pairwise Welch t-tests + Holm", DF2=float(result.df))
    else:
        robust = "hc3" if unequal else None
        fitted = model.get_robustcov_results(cov_type="HC3", use_t=True) if robust else model
        method = ("ANCOVA" if covariates else
                  "One-way ANOVA across observed combinations" if not complete else
                  {1: "One-way ANOVA", 2: "Two-way ANOVA", 3: "Three-way ANOVA"}[len(factors)])
        method += " (HC3 robust)" if robust else " (Type III, sum contrasts)"
        table = sm.stats.anova_lm(model, typ=3, robust=robust)
        for effect, row in table.iterrows():
            if effect in ("Intercept", "Residual"):
                continue
            effect_label = " x ".join(
                names.get(term, "Observed groups" if term == "C(Group, Sum)" else term)
                for term in effect.split(":")
            )
            add(method, effect_label, p=float(row["PR(>F)"]), statistic=float(row["F"]),
                DF1=float(row["df"]), DF2=float(model.df_resid),
                note="Omnibus p-value is unadjusted; inspect interaction terms before interpreting marginal main effects.")
        if len(factors) == 1 and not covariates and not robust:
            tukey = pairwise_tukeyhsd(data["value"], data["Group"])
            # Use full-precision arrays, never rounded values from summary().
            for index, (a, b) in enumerate(combinations(tukey.groupsunique, 2)):
                pair_record(a, b, float(tukey.meandiffs[index]), np.nan, "Tukey HSD",
                            tukey_p=float(tukey.pvalues[index]), **{"CI lower": float(tukey.confint[index, 0]),
                            "CI upper": float(tukey.confint[index, 1]), "Estimate direction": "Group 2 - Group 1"})
        else:
            designs = {}
            for label in labels:
                prediction = model_data[model_data["Group"] == label].iloc[[0]].copy()
                for index in range(len(covariates)):
                    prediction[f"cov_{index}"] = 0.0
                designs[label] = np.asarray(build_design_matrices([model.model.data.design_info], prediction)[0])[0]
            for a, b in pairs:
                result = fitted.t_test(designs[b] - designs[a])
                interval = np.asarray(result.conf_int()).ravel()
                pair_record(a, b, float(np.asarray(result.tvalue).item()), float(np.asarray(result.pvalue).item()),
                            "Model contrasts + Holm" + (" (HC3 robust)" if robust else ""),
                            **{"DF2": float(model.df_resid), "Adjusted mean difference": float(np.asarray(result.effect).item()),
                               "CI lower": float(interval[0]), "CI upper": float(interval[1]),
                               "Estimate direction": "Group 2 - Group 1", "CI adjustment": "Unadjusted 95%"})
    adjusted_values = holm_adjust_pvalues(raw_pvalues)
    for (a, b, statistic, p, method, extra), adjusted in zip(pair_results, adjusted_values):
        if "tukey_p" in extra:
            adjusted = extra.pop("tukey_p")
            adjustment = "Tukey HSD (all pairs within property)"
        else:
            adjustment = "Holm (planned pairs within property)" if len(pairs) > 1 else "Single comparison"
        label = lambda key: " | ".join(f"{factor}: {value}" for factor, value in zip(BIOLOGICAL_FACTORS, json.loads(key)) if value != "Unspecified")
        add(method, "Pairwise comparison", statistic=statistic, p=p, adjusted=adjusted, kind="pairwise",
            **{"Group 1": label(a), "Group 2": label(b), "Group 1 key": a, "Group 2 key": b,
               "Group 1 n": len(groups[a]), "Group 2 n": len(groups[b]),
               "Group 1 mean": float(groups[a].mean()), "Group 2 mean": float(groups[b].mean()),
               "P adjustment": adjustment, **extra})
    return rows


def generate_statistics_results_table(summary, metrics, factors=None, **options):
    data = summary.copy()
    if "Error" in data:
        data = data[~data["Error"].fillna(False).astype(bool)]
    if "Retained data points" in data:
        data = data[pd.to_numeric(data["Retained data points"], errors="coerce") > 0]
    rows = []
    for metric in metrics:
        try:
            rows.extend(analyze_metric(data, metric, factors, **options))
        except (ValueError, np.linalg.LinAlgError, FloatingPointError) as exc:
            rows.append({"Metric": metric, "Method": "Not run", "Result type": "diagnostic",
                         "Test/effect": "Inference unavailable", "Note": f"Statistical model failed; no stars reported: {exc}"})
    return pd.DataFrame(rows)
