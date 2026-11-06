# Biomechanics Batch Analyzer

**Turn mechanical testing files into specimen-level results, comparison plots, and downloadable reports.**

[Open the app](https://awad-lab-biomechanics.streamlit.app/) | [Quick-start guide](QUICK_START.md) | [Detailed user manual](USER_MANUAL.md)

## What does this app do?

Biomechanics Batch Analyzer helps researchers analyze how bone and tendon specimens respond to loading. Upload force-displacement files from a testing instrument, check the detected specimen labels, and process a batch using the same settings. The app displays the original and corrected curves, estimates stiffness and yield, and extracts maximum loads and areas under the curves.

It supports **3-point bending, 4-point bending, and tendon tensile testing**. With suitable specimen measurements, it also calculates stress-strain curves and material properties. Optional metadata lets you compare groups such as genotype, age, sex, or treatment, and download results for further review.

No coding is required to use the hosted app.

## Choose the analysis you need

| Test | What you supply | Additional inputs for material properties |
| --- | --- | --- |
| 3-point bending | Force-displacement files and lower support span | Matched metadata containing `Ixx` and `Ixx/Cy` |
| 4-point bending | Force-displacement files, lower support span, upper loading span, and displacement measurement location | Matched metadata containing `Ixx` and `Ixx/Cy` |
| Tendon tensile test | Force-displacement files | Matched metadata containing initial cross-sectional area and gauge length |

**Structural properties** describe the whole specimen, such as maximum force or bending stiffness. **Material properties** account for specimen geometry, such as stress and elastic modulus. Bone values are described as *apparent* material properties because the calculation uses an idealized beam model.

## Start here

1. Open the [hosted app](https://awad-lab-biomechanics.streamlit.app/) and choose **Bone bending** or **Tendon tensile test**.
2. For bone, select 3-point or 4-point bending and enter your actual test geometry.
3. Optionally upload metadata and map the specimen ID, biological variables, and geometry columns.
4. Upload one CSV or Excel testing file per specimen or intended run.
5. Select **Run batch processing** or **Run tendon batch processing**.
6. Review matching, warnings, raw and corrected curves, and individual stress-strain fits before interpreting the results.
7. Choose groups and properties, then download the tables and figures you need.

The [quick-start guide](QUICK_START.md) walks through a complete first analysis. The [manual](USER_MANUAL.md) explains calculations, settings, statistical tests, and limitations.

## Important checks before analysis

- **Use the correct units:** force in N and displacement in mm. The app does not automatically convert instrument units.
- **Check the displacement location in 4-point bending.** Upper-loading-point crosshead travel and specimen-midpoint deflection require different strain equations. Choose the measurement your instrument actually recorded.
- **Check the specimen matches.** A successfully loaded metadata file acts as an inclusion list: unmatched specimens are skipped. Without metadata, all valid uploaded files are considered.
- **Use the right geometry.** Bending stress uses `Ixx/Cy`; strain uses `Cy = Ixx / (Ixx/Cy)`. Do not substitute a centroid coordinate such as `CMy`.
- **Review the correction.** The app subtracts both force and displacement at the detected loading onset. This changes calculated results, not just the appearance of the plot.
- **Check the number of observations for each property.** A specimen may have structural results but lack material or yield results.

## What can I download?

| Resource | Contents |
| --- | --- |
| Corrected data CSV | Retained point-by-point data, specimen identity, available metadata, and analysis provenance |
| Summary/results CSV and Excel | Specimen-level results for successfully analyzed specimens |
| Group averages CSV | Means and sample standard deviations, grouped by the selected biological variables |
| Statistics CSV | Available diagnostic tests, model results, and adjusted pairwise comparisons for the selected analysis |
| PNG figures | A **Download PNG** control beside each displayed plot |
| Results report PDF | Four labeled specimen plots per page; bending reports use stress-strain curves, tendon reports use force-displacement curves |
| Methods DOC | A draft analysis-methods description in the bending workflow when metadata are loaded |

The bending summary is a selected-results table, not a complete metadata archive. Keep the original metadata and corrected-data export for traceability. See [export details](USER_MANUAL.md#downloads-and-provenance) for differences between workflows.

## Research use and data handling

This is a **research analysis tool, not a clinical diagnostic device**. Automatic fits, yield definitions, specimen matching, and statistical choices require scientific review. Defaults are starting values, not a validated protocol for every tissue or instrument.

The hosted app processes uploads on a remote Streamlit server. Upload only data approved for external hosting; do not upload patient identifiers or confidential study data without appropriate authorization. The app code keeps analysis state in the current session and creates downloads in memory rather than writing shared static result files. This does **not** establish a hosting-provider retention policy or guarantee secure deletion. Download your results before resetting or leaving a session.

For data that must remain under your control, run the app in an approved local environment. The source repository contains the app and schematic assets, not study datasets.

## Run locally

The published deployment uses **Python 3.12**. Install Python 3.12 and Git, then:

```sh
git clone https://github.com/haniawad-prog/biomechanics-batch-analyzer.git
cd biomechanics-batch-analyzer
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

On Windows PowerShell, replace the environment creation, activation, and run steps with:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open the local URL printed by Streamlit, normally `http://localhost:8501`. If that port is occupied, add `--server.port 8502`. Stop the server with `Ctrl+C` in its terminal.

Run the included public-deployment regression checks with:

```sh
python -m unittest test_public_app -v
```

These checks do not replace validation against your instrument, specimen geometry, or study design. Dependencies are pinned in [requirements.txt](requirements.txt); deployment settings are in [.streamlit/config.toml](.streamlit/config.toml).

## Documentation and support

- [Quick-start guide](QUICK_START.md): preparing files and completing a first run.
- [Detailed manual](USER_MANUAL.md): inputs, matching, correction, equations, yield rules, grouping, statistics, exports, and troubleshooting.
- [Report an issue](https://github.com/haniawad-prog/biomechanics-batch-analyzer/issues): include the test mode, settings, expected behavior, and a de-identified or synthetic example. GitHub issues are public; do not attach confidential files.

For reproducibility, record the repository commit, analysis date, test geometry, metadata mappings, correction and yield settings, included specimens, and statistical comparison family. No software license is currently specified in this repository; public visibility alone is not an unrestricted reuse license.

Documentation checked against the public application on **6 November 2026**.
