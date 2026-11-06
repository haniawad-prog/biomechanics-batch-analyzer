# Biomechanics Batch Analyzer: User Manual

[App overview](README.md) | [Quick-start guide](QUICK_START.md) | [Open the app](https://awad-lab-biomechanics.streamlit.app/)

This manual describes the public app checked on **6 November 2026**. It documents the current software, not a universal experimental protocol. Record the repository commit used for each analysis because later versions may change behavior.

## Contents

- [Purpose and scope](#purpose-and-scope)
- [Input files and units](#input-files-and-units)
- [Specimen identification and metadata filtering](#specimen-identification-and-metadata-filtering)
- [Choosing test geometry](#choosing-test-geometry)
- [Correction and elastic fitting](#correction-and-elastic-fitting)
- [Stress, strain, and material properties](#stress-strain-and-material-properties)
- [Yield estimation](#yield-estimation)
- [Group plots and descriptive summaries](#group-plots-and-descriptive-summaries)
- [Statistical analysis](#statistical-analysis)
- [Downloads and provenance](#downloads-and-provenance)
- [Troubleshooting](#troubleshooting)
- [Reproducibility and responsible use](#reproducibility-and-responsible-use)
- [Local operation and implementation](#local-operation-and-implementation)

## Purpose and scope

The app processes batches of mechanical testing files for bone bending and tendon tension. It provides raw and corrected curves, structural properties, geometry-based material curves and properties, group visualizations, statistical comparisons, and downloadable outputs.

Structural properties describe the specimen as tested. Material properties normalize the response using geometry and a mechanical model. For irregular bone, these are **apparent bending properties**, not a direct measurement of a uniform material's intrinsic constants.

The app does not control the testing instrument. It does not perform microCT segmentation, determine the anatomical bending axis from an image, measure tendon area, or automatically correct machine compliance, fixture deformation, grip slip, or contact indentation.

The current interface does not implement MANOVA, mixed-effects models, repeated-measures analysis, or a user-selected one-sided test. Analyses performed separately from this app are not part of its built-in statistical workflow.

## Input files and units

### Testing files

Accepted file types are `.csv`, `.xlsx`, and `.xls`. One testing file should represent one specimen or an intentionally selected run. Excel imports read the first worksheet only.

The importer searches the first 100 rows for unambiguous displacement/extension and force/load column headings. Recognized examples include `Displacement (mm)`, `Extension`, `Force (N)`, and `Load`, without regard to capitalization. If no suitable heading pair is found, the legacy layout reads displacement from column B and force from column C, starting at row 11.

The current importer requires at least three columns, even for heading-based imports, and at least five usable numeric point pairs. A practical format is `Time,Displacement (mm),Force (N)`. Numeric conversion excludes invalid or nonfinite pairs. Fewer than the selected minimum elastic-fit points can prevent a stiffness or modulus estimate.

Use force in **newtons (N)** and displacement in **millimeters (mm)**. There is no automatic conversion from kN, micrometers, inches, or percent strain, and no automatic correction of a reversed force/displacement sign convention. Check the numeric values as well as the headings. Preserve acquisition order and investigate unloading or backward displacement within the loading branch.

### Metadata

Metadata use a header row and one row per specimen. Avoid merged headings, title rows above the headers, duplicate IDs, mixed units, and multiple unrelated tables on the first worksheet. Blank rows are dropped. CSV metadata are comma-delimited; supported text encodings include UTF-8 and common Western encodings.

Select the ID column explicitly. Select up to three **Biological variables** for grouping and models. The app suggests likely columns, but users must verify them. Original selected column names are displayed; grouping is not restricted to genotype, age, and sex. Categories such as `F` and `Female`, or `6M` and `6 months`, should be standardized before upload if they mean the same thing.

For bending, supply separate positive numeric columns for `Ixx` in mm^4 and `Ixx/Cy` in mm^3. They must describe the same specimen, anatomical region, and bending axis. For tendon tension, supply positive initial cross-sectional area in mm^2 and initial gauge length in mm.

If metadata load successfully, they control specimen inclusion even when geometry is absent. If metadata cannot be loaded, the app warns and has no usable metadata filter. Resolve that warning before running a metadata-restricted analysis; do not assume a failed upload is filtering the batch.

## Specimen identification and metadata filtering

The app searches filenames, explicitly labeled cells, and recognized instrument results tables for specimen identity. It rejects ordinary measurement headings as specimen labels and records the selected source.

Matching proceeds conservatively:

1. Match full labels after basic case/spacing normalization.
2. Match normalized alphanumeric labels, allowing punctuation and formatting differences.
3. Use a unique numeric specimen identifier, with up to four significant digits, if no full-label match is found.

Leading zeros and integer-like spreadsheet labels are normalized. Common date, time, run, age, and gene annotations are screened out of numeric candidates. When several numbers remain in a name, the longest numeric tokens are prioritized. This is a heuristic, not a substitute for checking the audit table. Longer IDs can match by full label; the numeric fallback does not truncate them into four-digit suffixes.

Explicit alternate-ID columns can help link names that share no useful number. Recognized headings include `Specimen alias`, `Sample alias`, `Alternate ID`, `Alternate specimen ID`, `Alternate sample ID`, and `microCT sample name`. Arbitrary notes and source-row numbers are not treated as aliases.

Examples:

| Testing label | Metadata ID | Interpretation |
| --- | --- | --- |
| `101R.csv` | `101` | May match by unique numeric ID |
| `Specimen-0101` | `Specimen101` | May match after alphanumeric normalization |
| `101R.csv` | Rows `101R` and `101L` | Full label can identify `101R`; a numbers-only label would be ambiguous |
| `Specimen-A.csv` | `9001` | Requires an explicit alias or corrected identity record; the relationship is not inferred from unrelated names |

Repeated full labels may be disambiguated with a metadata `Instron Run #` column and a recognized run suffix in the testing filename. A run number is only a secondary key, not a replacement for specimen identity. Do not upload repeated tests as independent biological replicates unless the design justifies that treatment.

**With successfully loaded metadata:** unmatched or ambiguous specimens are skipped. They do not enter the analyzed-results summary or group averages. Review **Specimen label matching** or **Tendon specimen label matching** to see exclusions and conflicts.

**Without metadata:** valid uploaded files are considered for structural analysis. No biological grouping or geometry-based material analysis is available.

A successful match does not guarantee valid material geometry. A matched specimen can retain structural results while material results are missing.

## Choosing test geometry

The initial bone mode is **3-point bending**. Initial span values are `S = 9.5 mm` and, for 4-point bending, `L = 3.5 mm`. These are editable defaults, not recommendations for every experiment.

Definitions:

| Symbol | Meaning | Unit |
| --- | --- | --- |
| `F` | Total measured applied force | N |
| `delta` | Corrected displacement at the selected measurement location | mm |
| `S` | Lower support span | mm |
| `L` | Distance between the two upper loading points in 4-point bending | mm |
| `M` | Bending moment used for analysis | N.mm |
| `Ixx` | Second moment of area about the relevant neutral bending axis | mm^4 |
| `Z = Ixx/Cy` | Section modulus for that axis and surface | mm^3 |
| `Cy` | Distance from neutral axis to the relevant surface | mm |

For symmetric, simply supported loading, the app uses:

```text
3-point bending: M = F*S/4
4-point bending: M = F*(S-L)/4
```

In 4-point bending, `F` is the total applied force; each upper loading point carries `F/2`. Enter `0 < L < S`. In 3-point mode the upper loading span is not an independent input.

### Displacement measurement location

For 4-point bending, select either **Specimen midpoint** or **Upper loading points / crosshead**. The default is midpoint. This choice changes the conversion from displacement to strain and therefore modulus, strain-based yield criteria, strain outcomes, and energy density.

When using crosshead travel, select the upper-loading-point option, but recognize that instrument motion may include fixture compliance or contact deformation. The app does not remove those contributions. For 3-point bending the idealized loading point is at midspan; crosshead travel still requires the same experimental caution.

## Correction and elastic fitting

### Loading onset and zero reference

The app smooths force with a centered rolling median for onset detection, estimates an early baseline/noise level, and looks for a sustained rise in force with positive slope. A maximum-onset-force setting can move the selected onset earlier. If no onset is detected, the first valid point is used with a warning.

After choosing onset, it discards earlier points and subtracts both the displacement and the force at that point:

```text
corrected displacement = measured displacement - displacement at onset
corrected force        = measured force - force at onset
```

Thus, the first retained point is `(0, 0)`. Original force and displacement are retained alongside corrected values for the retained rows. The original input files remain necessary to inspect any removed leading or trailing data.

This is an analytical correction. Subtracting preload changes maximum force, derived stress, yield, and areas under curves. The fit slope can also change if the retained or selected fitting region changes. Do not assume that zeroing leaves all final properties unaffected.

### Post-peak trimming

By default, **Delete data after post-peak force drop** is enabled with a **15%** drop. The app finds the measured maximum and retains data through the first subsequent point at or below 85% of that maximum. Later data are removed. If no such drop occurs, the tail is retained and a warning is issued.

Trimming follows the maximum and does not intentionally remove the peak. It does affect the final retained displacement/strain. The reported **Strain at failure** is the last retained strain, not a separately verified fast-fracture measurement.

### Elastic fit

Automatic fitting searches pre-peak regions for a positive-slope linear regression with an intercept. Candidate selection prioritizes fit R^2, then point count and span. The search is bounded for performance; it does not exhaustively test every possible interval in long files.

Initial settings:

| Setting | Initial value |
| --- | --- |
| Force threshold multiplier | 0.1 |
| Consecutive positive-slope points | 15 |
| Smoothing window size | 5 points |
| Minimum force rise | 0.5% of specimen force range |
| Maximum detected onset force | 1.0 N |
| Elastic fit R^2 threshold | 0.950 |
| Minimum points in stiffness fit | 25 |
| Max stiffness search points | 250 |

If no acceptable region reaches the threshold but a positive fit exists, the best available fit may be used with a warning. A high R^2 alone does not establish that the chosen segment is physically elastic.

**Manually set stiffness region** applies a common corrected-displacement window to the batch. The initial bounds are 0 to 0.2 mm; inspect their suitability for every specimen. For direct material analysis, the displacement bounds are converted to each specimen's strain coordinates. An insufficient manual interval can trigger an automatic-fit fallback with a warning.

Bending stiffness is the slope of moment versus displacement, in **N**. Tendon tensile stiffness is the slope of force versus displacement, in **N/mm**. These are different quantities despite sharing the word stiffness.

## Stress, strain, and material properties

### Bending conversion

The interface requests `Ixx` and `Ixx/Cy`, not a separately entered `Cy`:

```text
Z     = Ixx/Cy                         [metadata input, mm^3]
Cy    = Ixx/Z                          [derived, mm]
stress = M/Z                          [N/mm^2 = MPa]
```

The strain equations are:

```text
3-point:
strain = 12*Cy*delta / S^2

4-point, specimen midpoint deflection:
strain = 24*Cy*delta / (3*S^2 - (S-L)^2)

4-point, upper-loading-point deflection:
strain = 12*Cy*delta / ((S-L)*(S+2*L))
```

Strain is dimensionless (`mm/mm`). These equations assume symmetric loading and idealized small-deflection beam behavior. Verify the bending direction and the surface used for `Cy` against the microCT measurement convention.

`CMx` and `CMy` are centroid-coordinate fields, not the surface distance required here, and are excluded from the bending geometry selector. Do not replace `Ixx/Cy` with `Imin/Cmin` without establishing equivalence for the actual axis. If `Ixx` and `Ixx/Cy` are slice averages, their quotient is an effective distance and need not equal the mean of slice-by-slice distances.

Some legacy result headings use **I/c (mm^3)** and **c (mm)**. In this workflow they represent the selected `Ixx/Cy` and derived `Cy`, respectively. Corrected-data columns named `tensile_stress_mpa` and `tensile_strain` are also historical names: in the bone workflow they contain *bending* stress and strain.

### Tendon conversion

```text
engineering stress = corrected force / initial area
engineering strain = corrected displacement / initial gauge length
```

Stress is MPa when force is N and area is mm^2. These are engineering measures based on initial geometry, not true stress and strain based on evolving area and length. Crosshead motion, grip compliance, or slippage can bias the inferred strain and modulus.

### Direct material measurements

When a complete stress-strain curve is available, the app fits **elastic modulus directly to numeric stress-strain data** using the elastic-region search. It also determines yield in stress-strain coordinates, measures the maximum stress and its strain coordinate, and integrates stress with respect to strain through the maximum. It does not estimate these values from the pixels of a displayed image.

The direct material yield estimate is mapped back to a corresponding force, moment where applicable, and displacement for structural displays. Consequently, adding valid material geometry can change the reported structural yield: the automatic policy then starts with a strain-offset criterion instead of a structural proportional-limit criterion.

### Peak and area definitions

| Output | Definition and interpretation |
| --- | --- |
| Maximum force | Largest retained corrected force |
| Maximum moment | Largest retained corrected bending moment |
| Displacement at maximum | Displacement at the first occurrence of the measured maximum, not the largest displacement in the file |
| Apparent/elastic modulus | Direct stress-strain regression slope, in MPa |
| Ultimate stress | Largest retained stress; not the maximum of a group-average curve |
| Strain at yield | Strain coordinate of the detected yield estimate |
| Strain at ultimate stress | Strain coordinate at the measured stress maximum |
| Post-yield displacement | Displacement at maximum minus displacement at yield |
| Bending work to maximum moment | Trapezoidal area under moment versus displacement through maximum moment, in N.mm^2 |
| Tendon work to maximum force | Trapezoidal area under force versus displacement through maximum force, in N.mm = mJ |
| Energy to maximum stress | Trapezoidal area under stress versus strain through maximum stress; MPa is numerically equivalent to MJ/m^3 |
| Strain at failure | Last retained strain; depends on acquisition endpoint and trimming |

**Bending moment-displacement area is not physical work in joules.** Do not relabel N.mm^2 as mJ. Likewise, stress-strain area is energy per volume, not total specimen energy. The app's energy-to-maximum endpoint excludes post-peak energy and should not be described as total work to fracture.

Integration follows acquisition order. Backward motion or loops can affect the signed trapezoidal area; review such traces rather than treating them as a monotonic loading test automatically.

## Yield estimation

Yield is a criterion-based estimate of departure from elastic behavior. The current default is **Automatic**, shared by 3-point bending, 4-point bending, and tendon tension.

### Automatic sequence

| Available data for a specimen | Criteria attempted in order |
| --- | --- |
| Complete material stress-strain curve | 0.1% strain offset; 0.05% strain offset; proportional limit at the configured departure |
| Structural results only | Proportional limit at the configured departure; 0.01 mm displacement offset; 0.005 mm displacement offset |

The initial proportional departure is **10%**, with **5 consecutive confirmation points**. If enabled, **Try 5% then 2.5% proportional-limit fallbacks** adds those smaller departure thresholds after the initial sequence fails, but only if they are below the configured threshold. A successful earlier estimate is not replaced by a later one.

Percentages have different meanings: `0.1% strain = 0.001 mm/mm`, whereas a `5% proportional departure` means a response 5% below the fitted elastic prediction. Neither is a 5% strain offset.

### Offset criterion

For an elastic fit `response = K*x + b`, the parallel reference is:

```text
offset response = K*(x - offset) + b
```

Here, `x` is strain in the direct material analysis or displacement in structural analysis. The app looks for the first valid intersection with the smoothed response **after the elastic fitting region and before the maximum**. It retains the regression intercept; an offset line is not expected to pass through `(0, 0)`.

### Proportional-limit criterion

The app detects a sustained crossing below `(1 - departure fraction)` times the elastic prediction after the fitted region and before the peak. The default yield smoothing is a 5-point rolling median. The confirmation rule helps avoid declaring a one-point fluctuation to be yield.

If no criterion succeeds, yield remains missing. The app does not substitute maximum force/stress for an undetected yield point. Detected yield responses are constrained not to exceed the measured maximum.

### Manual choices and interpretation

Select **Proportional limit** or **Offset** to override the automatic policy. Manual controls allow the other method as a fallback and a half-offset retry. The fixed-displacement offset defaults to 0.01 mm; it is not the same as a 0.1% strain offset.

Inspect **Individual stress-strain fits** and preserve the corrected-data provenance fields: requested method, successful method, criterion, attempts, fallback flags, offset basis and value, and proportional departure where applicable. Do not treat estimates based on different offsets or departure thresholds as interchangeable without a justified analysis plan or sensitivity analysis.

## Group plots and descriptive summaries

### Group selection and layout

Each selected biological variable has its own value menu. The bending bar-graph section also offers **Specific combinations**. **X-axis variable** and **Side-by-side bars** control arrangement; a remaining variable produces separate panels instead of being pooled away. Tendon layouts use **Group bars by** and **Side-by-side bars**.

Bending average curves and bars have independently adjustable filters. **Match average-curve filters** copies the average selections to the bar controls. Tendon property plots use the tendon average-curve selections.

Bars show the arithmetic mean, sample SD, and individual finite observations for each property. Missing outcomes are omitted per property, so the count can differ across panels. A marker represents a testing specimen/run; it is not automatically an independent animal.

### Average curves

The app interpolates each eligible curve to a common grid and calculates a pointwise mean. At least 20 distinct usable coordinates are needed for a specimen to contribute to the grouped curve. That requirement does not apply to every scalar summary in the same way, so a curve legend and a property table can have different counts.

**Bending average stress-strain curves:** individual curves are display-trimmed at the first major peak, interpolated only within each specimen's measured range, and averaged where data are available. The displayed mean and SEM are smoothed, and the line is truncated near the mean strain at the retained individual peaks. The number contributing can decrease along the curve; the legend gives the number of eligible curves, not a fixed pointwise count. The displayed endpoint is not guaranteed to equal mean ultimate stress.

**Tendon average curves:** each specimen is cut at its measured peak before interpolation. Averaging uses the shared pre-peak range so every point has the same contributing cohort. The force-displacement plot also shows mean individual peak coordinates with horizontal and vertical SEM bars; its dashed connector is a visual guide, not measured data. The tendon average stress-strain curve stops at the shared-range endpoint without that peak extension.

Average-curve shading is **mean +/- standard error of the mean (SEM)**, not a 95% confidence interval. At a coordinate with `n` observations, `SEM = sample SD / sqrt(n)`. With one observation there is no estimated uncertainty band. The group-average curve and the mean of individual maximum values answer different questions; use the specimen-level peak summary for ultimate-stress comparisons.

### Group averages CSV

Group averages cover every observed combination among **all successfully analyzed metadata-matched specimens**, irrespective of plot filters. They do not create rows for unobserved combinations or specimens with no analyzed testing file.

Each property is exported as text in the form `mean +/- SD`, with two digits after the decimal and no exponent notation. This is **two decimal places**, not two significant figures. Small strains and SDs can round to `0.00`; use the unrounded specimen table for further calculations.

SD uses `n - 1` when at least two values are available. For a single available value, the current formatter writes `0.00` as SD; this is a placeholder, not evidence of zero biological variability. A wholly missing property is blank. **Analyzed specimens (n)** counts the group's analyzed specimens, not the nonmissing count for each property.

The bending table includes `Ixx`, `I/c`, and `c` averages as well as structural and material properties. The tendon group table includes its structural and material outcomes.

## Statistical analysis

### Analysis scope

Statistics follow the current selected specimens and properties. The app treats varying biological variables as categorical factors, even when their labels look numeric. It uses up to three selected factors and considers interactions when a complete factorial model can be estimated.

**Experimental design** must reflect the study. Selecting **Paired / repeated specimens** disables independent-specimen inference and annotations because the app does not fit repeated-measures or mixed-effects models. Independence cannot be established by a normality test: bilateral specimens, repeated runs, litter effects, and batches require design-level review.

**Simple effects** compares observed groups differing in one biological variable. **All group pairs** includes every observed pair. Comparisons are two-sided with alpha 0.05. Numeric metadata can be selected as scientifically justified **Continuous covariates**; do not use specimen IDs as covariates.

Each property uses its own complete cases for outcome and required predictors. Missing-value details identify excluded specimens. At least two observed groups, at least two usable observations per observed group, and sufficient model rank/residual degrees of freedom are required for the relevant inference. When inference is not estimable, the app returns a diagnostic rather than a significance claim.

### Assumptions and automatic test choice

Residual normality is screened with Shapiro-Wilk when applicable (3 to 5,000 residuals). Variance equality is screened with median-centered Levene testing across observed groups. The decision threshold is 0.05. An unavailable normality result can prevent inference. A nonsignificant diagnostic does not prove an assumption, especially in small samples.

| Data/model situation | Current analysis |
| --- | --- |
| One factor, two groups, approximately normal residuals, no covariates | Independent Student t-test when variance screening is acceptable; Welch t-test when variances are unequal or not established |
| One factor, more than two groups, normal residuals and acceptable variances, no covariates | One-way ANOVA with Tukey HSD pairwise comparisons |
| One factor, more than two groups, normal residuals but unequal variances, no covariates | Welch one-way ANOVA with pairwise Welch tests and Holm adjustment |
| Complete multifactor design with normal residuals | OLS factorial ANOVA with interactions, Type III tests, and sum contrasts; HC3 robust covariance when variance screening requires it |
| Normal-residual model with selected continuous covariates | ANCOVA with common linear covariate slopes; model-based comparisons at mean covariate values, with Holm adjustment |
| Incomplete factorial design | Observed-cell model when estimable, rather than unsupported separate factorial effects |
| Nonnormal residuals, no covariates | Kruskal-Wallis for more than two observed groups, plus pairwise Mann-Whitney U tests with Holm adjustment; two groups use Mann-Whitney U |
| Nonnormal residuals with covariates | Inference withheld for review, rather than silently dropping the covariates |

Nonnormal multifactor data are analyzed as **observed groups**, not with a rank-based factorial interaction test. This route does not establish genotype-by-sex or other interactions. Mann-Whitney and Kruskal-Wallis concern distributions/ranks; interpreting them strictly as median differences needs additional distributional assumptions.

Covariate models assume common linear slopes, which require scientific and diagnostic review. Bar heights remain **unadjusted means**, even when the comparisons are covariate-adjusted.

### Multiple comparisons and annotations

Tukey HSD is used for the ordinary one-factor, equal-variance case. Other applicable pairwise families use Holm correction. The family includes selected comparisons for that property, including comparisons not visible in a particular panel.

The app adjusts pairwise p-values **within each property**, not across all measured properties. Omnibus p-values are not adjusted across outcomes. Model contrast confidence intervals are not generally simultaneous multiplicity-adjusted intervals; Tukey intervals are a separate case. Plan outcome families and any study-wide correction before making confirmatory claims.

Significant pairwise brackets use adjusted p-values:

```text
*     p < 0.05
**    p < 0.01
***   p < 0.001
****  p < 0.0001
```

Brackets appear only when the tested groups correspond to the displayed groups and counts within a panel. Missing model predictors can make a bar's cohort differ from the inferential cohort, in which case a bracket is omitted. No star does not necessarily mean an adequately powered null result; consult the downloadable statistics and diagnostics.

## Downloads and provenance

| Download | Scope and important details |
| --- | --- |
| Corrected data CSV | All successfully processed specimens in the batch; retained data points, original/corrected coordinates, available metadata, specimen-match information, geometry, fit indicators, and yield provenance |
| Bending Summary CSV / Summary Excel | Selected structural/material result columns for successfully analyzed specimens; selected biological columns follow specimen ID; not every original metadata column is included |
| Tendon Results CSV / Results Excel | Successfully analyzed specimens with outcomes, diagnostics, and available metadata fields |
| Group averages CSV | All analyzed metadata groups, not just plot selections; values are formatted text |
| Stats results CSV / Statistics CSV | Current selected statistical scope, diagnostic/model/pairwise rows, and available raw/adjusted p-values and counts |
| Download PNG | The displayed figure, generated at its configured resolution; not a universal 600-dpi publication export |
| Bending results report PDF | Only individual stress-strain plots, four per landscape page, with specimen labels, elastic/yield overlays, and y-axis upper limit at 110% of each specimen's ultimate stress |
| Tendon results report PDF | Individual force-displacement plots with stiffness/yield overlays, four per landscape page |
| Methods DOC | Bending workflow with metadata; a generated draft methods narrative, not a Results narrative or a certified account of the experimental protocol |

The bending PDF excludes specimens without valid material curves and lists their IDs in the interface. A missing yield estimate alone does not require excluding an otherwise valid material curve. Neither report PDF is a complete substitute for the summary and corrected-data exports.

The Methods DOC download is Word-compatible HTML with a `.doc` extension, not a native `.docx` package. Review it in Word and verify all experimental and statistical statements before manuscript use. Experimental details not recorded in the app, such as instrument model, loading rate, storage, hydration, and loading direction, must come from your actual protocol.

Bending corrected-data columns prefixed `metadata_` preserve matched metadata values. This is the more complete traceability export; the compact Summary CSV intentionally omits many audit fields. Keep the source metadata as well. The corrected-data preview shows only the first 500 rows: repeated IDs there can simply be many points from the first specimen, not evidence that all specimens were renamed.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| All files were skipped by metadata filtering | Verify the metadata first worksheet, header row, selected ID column, discovered labels, filename numbers, and alias columns in the matching audit. A file count is not a match count. |
| Only some specimens were skipped | Look for ambiguous numeric IDs, conflicting labels, unmatched names, or duplicate metadata rows. Add explicit aliases where justified; do not guess an identity from biology. |
| Material properties are missing but force/moment results exist | Check positive, correctly mapped `Ixx` and `Ixx/Cy`, or tendon area and gauge length. Check units, specimen matching, and elastic-fit warnings. |
| Yield is missing | Inspect the individual curve and elastic region. A valid post-fit, pre-peak crossing may not exist even after all fallbacks. Review the attempt sequence; do not replace missing values with zero or maximum stress. |
| No elastic fit is available | Check data length, positive loading direction, pre-peak points, fit minimum, and manual-window bounds. Select settings for mechanical validity, not to force a desired result. |
| A fit or offset line does not start at zero | The measured corrected curve is zeroed upstream; regression and offset reference lines include intercepts and need not pass through the origin. |
| Average-curve peaks disagree with a maximum-stress bar | Confirm identical filters and counts. Pointwise means and mean individual maxima are different; bending curve support can also vary along the x-axis. |
| Bars have different counts | A property can be missing independently of others. Inspect per-property exclusions and geometry/yield warnings. |
| No significant bracket is shown | Check adjusted p-values, comparison family, independent design, estimability, missing predictors, and whether the comparison spans different panels. |
| Group CSV strains look like zero | The summary uses two decimal places. Consult the specimen-level numeric export for small values. |
| A structural-only bending bar graph is empty | Material outcomes are the initial defaults. Select available structural outcomes under **Properties to plot**. |
| Bending PDF is unavailable or incomplete | It requires valid stress-strain curves. Use structural CSV/Excel and PNG exports for structural-only specimens. |
| A download or session is lost | Reopen or rerun from the original files and saved settings. Export before resetting; the app is not a permanent results archive. Large batches may exceed hosting resources; try smaller batches or an approved local run. |
| A local server will not start | Use Python 3.12, install the pinned requirements in the same virtual environment, and choose a free port. |

After changing any analysis input or setting, explicitly run processing again before using new results. Some changes invalidate results automatically, but a displayed previous result should never be assumed to reflect an unprocessed input change.

## Reproducibility and responsible use

Keep the following with an analysis:

- Original instrument files and metadata, including the exact run chosen for repeated tests.
- App repository commit and analysis date.
- Test mode, spans, displacement measurement location, units, anatomical loading direction, and geometry measurement definitions.
- Onset, trimming, elastic-fit, and yield settings, including fallback choices.
- A reviewed matching/inclusion record and the reasons for specimen/property exclusions.
- Corrected-data, specimen-results, group-averages, and statistics exports.
- Selected factors, factor levels, covariates, comparison family, experimental unit, and any additional multiplicity plan.
- Any manual checks, sensitivity analyses, and deviations from a prespecified protocol.

A public hosted upload leaves your computer and is processed on Streamlit infrastructure. Use only data approved for external hosting. The app does not intentionally write uploaded study data or generated results to shared static files; session state and downloads are held in memory. Reset clears the current session's application state, not a verified platform-wide deletion or retention record. Local operation changes where analysis runs but does not by itself establish institutional compliance or eliminate all network requests, such as loading a remote logo.

The software does not call an LLM to interpret uploaded datasets in the current analysis code. Its calculations and draft methods text are generated by the Python implementation. Any manuscript describing LLM-assisted software development should distinguish that development assistance from the actual deterministic analysis and independent scientific validation.

## Local operation and implementation

See the [README installation steps](README.md#run-locally) for macOS/Linux and Windows. Use an isolated Python 3.12 environment and the pinned requirements. The app can run locally without connecting it to Streamlit Community Cloud.

The public deployment uses `app.py` on the `main` branch with Python 3.12. Its configuration disables shared static serving, keeps CORS/XSRF protections enabled, and disables Streamlit usage-stat collection. Do not enable shared static result storage as a download workaround on a multi-user deployment.

Key source files:

| File | Responsibility |
| --- | --- |
| [app.py](app.py) | Interface, parsing, correction, geometry, fits, plots, summaries, and exports |
| [specimen_labels.py](specimen_labels.py) | Label discovery and conservative metadata matching |
| [statistics_analysis.py](statistics_analysis.py) | Current statistical decision rules, diagnostics, models, and comparisons |
| [test_public_app.py](test_public_app.py) | Included public-deployment regression checks |
| [requirements.txt](requirements.txt) | Pinned runtime dependencies |
| [.streamlit/config.toml](.streamlit/config.toml) | Deployment and presentation settings |

The included checks can be run with `python -m unittest test_public_app -v`. They test important deployment behaviors but are not a complete scientific validation suite for every input format or experimental design. Before adopting the tool for a new protocol, verify representative files against independently checked calculations and document any limits of agreement.

For problems, use the [GitHub issue tracker](https://github.com/haniawad-prog/biomechanics-batch-analyzer/issues) with a de-identified or synthetic reproducible example, settings, commit, and expected result. Do not post confidential files or credentials.
