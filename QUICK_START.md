# Quick-Start Guide

[App overview](README.md) | [Open the app](https://awad-lab-biomechanics.streamlit.app/) | [Detailed manual](USER_MANUAL.md)

This guide takes you from testing files to reviewed results. Begin with a small, representative batch before processing an entire study.

## 1. Prepare your files

Use one testing file per specimen or intended run. CSV, XLSX, and XLS are accepted; Excel imports use the **first worksheet**.

For a straightforward import, include at least three columns with recognizable displacement and force headings. For example:

```csv
Time,Displacement (mm),Force (N)
0.00,0.000,0.00
0.10,0.002,0.04
0.20,0.004,0.09
```

This is a format illustration, not a usable test dataset. At least five valid numeric data points are required, and the default elastic fit requires 25 points. Use the complete measured curve. A two-column file is not supported by the current importer. Legacy exports without recognized headings use columns B and C, beginning at row 11.

Check that force is in **N**, displacement is in **mm**, and loading has the intended positive sign. Keep untouched copies of the original instrument exports.

## 2. Choose the test and geometry

Open the [app](https://awad-lab-biomechanics.streamlit.app/).

| Test | What to select or enter |
| --- | --- |
| 3-point bending | **Bone bending**, then **3-point bending**; enter the lower support span `S` |
| 4-point bending | **Bone bending**, then **4-point bending**; enter `S`, upper loading span `L`, and displacement measurement location |
| Tendon tensile test | **Tendon tensile test** |

The bone interface starts in 3-point mode. Its initial spans are `S = 9.5 mm` and, in 4-point mode, `L = 3.5 mm`. Replace them with your measured setup values.

**For 4-point testing:** choose **Upper loading points / crosshead** when the displacement is crosshead travel at the upper loading points. Choose **Specimen midpoint** only for displacement measured at the specimen midpoint. The initial selection is midpoint; do not accept it without checking. Crosshead travel can also contain machine, fixture, or contact deformation that the app does not separately correct.

## 3. Add metadata when available

Upload one metadata CSV or Excel file with headers and one row per specimen. Map the **Specimen ID column**, then choose up to three **Biological variables**, such as genotype, age, and sex. Check the preview and inferred selections.

For bending material properties, select two different numeric columns:

- **Ixx column (mm^4)**: second moment of area about the relevant bending axis.
- **Ixx/Cy column (mm^3)**: section modulus for that same axis and anatomical region.

The app calculates `Cy = Ixx / (Ixx/Cy)`. Do not choose `CMy`, `CMx`, or `Imin/Cmin` as substitutes.

Illustrative bending metadata:

| Specimen ID | Genotype | Age | Sex | Ixx (mm^4) | Ixx/Cy (mm^3) |
| --- | --- | --- | --- | --- | --- |
| 101 | Control | 6M | F | 0.12 | 0.20 |
| 102 | Treatment | 6M | F | 0.15 | 0.25 |

These invented values demonstrate the format only. Replace them with measured specimen values.

For tendon material properties, map **Cross-sectional area column (mm^2)** and **Initial gauge length column (mm)** instead. Both must contain positive values.

**With successfully loaded metadata, only matching specimens are analyzed. Without metadata, all valid testing files are considered, but material properties are unavailable.** Metadata can also be used only for specimen selection and grouping; geometry is not required for structural analysis.

## 4. Upload testing files and run

Add files under **Upload CSV files** in the bending workflow, or **Upload tendon test files (CSV or Excel)** in the tensile workflow. Despite the bending uploader's label, it also accepts Excel.

Review the sidebar settings. For an initial inspection, leave **Yield method** on **Automatic**. The [manual explains its fallback sequence](USER_MANUAL.md#yield-estimation); automatic results may use different yield definitions across specimens.

Select **Run batch processing** or **Run tendon batch processing**. After changing input files, mappings, geometry, onset, stiffness, trimming, or yield settings, run processing again before downloading results.

## 5. Review before interpreting

1. Check **Processed specimens**, warnings, and errors against the files you intended to include.
2. Open **Specimen label matching** or **Tendon specimen label matching**. Verify filenames, discovered labels, metadata IDs, and matching methods. Unique numeric matches can connect `101R.csv` to metadata ID `101`; ambiguous numbers are not accepted automatically.
3. Compare raw and corrected curves. Correction removes leading data and subtracts the force and displacement at loading onset. It should not conceal a poor onset choice.
4. Inspect stiffness and yield overlays. Open **Individual stress-strain fits** to check the actual material fit, peak, yield estimate, and area under the curve.
5. Investigate missing values. Missing geometry, an unavailable elastic region, or no valid pre-peak yield point can reduce the number of specimens for one property without removing other valid results.

Do not interpret a warning as evidence that a specimen is biologically different. Resolve input and fitting problems first.

## 6. Choose groups and comparisons

Use the separate biological-variable menus to choose the values to display.

In bending **Bar graphs for selected properties**:

- Choose each variable's values and, when needed, use **Specific combinations** to retain only selected combinations.
- Choose **Properties to plot**. Initial choices are available material properties; structural-only analyses may require selecting structural outcomes yourself.
- Choose **X-axis variable** and **Side-by-side bars**. A remaining variable is separated into panels, not averaged away.
- Use **Match average-curve filters** when you want the bar-graph selections to match the average curves. Their filters can otherwise differ.

Tendon plots use the average-curve filters, **Tendon properties to plot**, **Group bars by**, and **Side-by-side bars**.

Under **Statistical model and comparisons**, confirm the experimental design and select **Simple effects** or **All group pairs**. The current app uses two-sided tests. Paired or repeated specimens require another analysis method; selecting that design disables the app's independent tests.

Bars show means with sample SD and individual observations. Average-curve bands show **SEM**, not SD or a 95% confidence interval. The peak of an average curve need not equal the mean of individual peak values.

## 7. Download and keep a record

Download the corrected data, specimen summary/results, group averages, statistics, and the PNG beside each figure you need. Bending PDFs contain individual stress-strain plots; tendon PDFs contain individual force-displacement plots, four per page.

Group averages include **all successfully analyzed metadata groups**, not only the current plot selection. Statistical downloads follow the selected analysis groups and properties. Keep this difference in mind when comparing files.

Save the original data and metadata, app commit/date, settings, mappings, and an inclusion/exclusion record alongside the downloads. Use **Reset and start new batch** only after downloading; it clears the current browser session's app state.

## Need help?

See [Troubleshooting](USER_MANUAL.md#troubleshooting) for skipped specimens, missing material properties, missing yield values, different group counts, and downloads. For installation, see [Run locally](README.md#run-locally).
