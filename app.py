from __future__ import annotations

import csv
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from io import BytesIO, StringIO
import os
from pathlib import Path
import re
import textwrap
from typing import BinaryIO, Optional
from xml.sax.saxutils import escape
import zipfile

from specimen_labels import (
    LABEL_MATCHING_VERSION,
    build_metadata_lookup,
    extract_numeric_identifier,
    extract_numeric_identifiers,
    find_metadata_row,
    normalize_identifier,
    resolve_specimen_identity,
)

MPL_CONFIG_DIR = Path(__file__).resolve().with_name(".matplotlib")
MPL_CONFIG_DIR.mkdir(exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(MPL_CONFIG_DIR))

import matplotlib
from matplotlib.patches import Patch

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import pandas as pd
import streamlit as st

from statistics_analysis import (
    STATISTICS_AVAILABLE,
    biological_key,
    generate_statistics_results_table,
    significance_stars,
    statistics_scope_id,
    stats_factor_options,
)


def _install_download_button_no_rerun() -> None:
    """Prevent download clicks from rerunning all plot/PDF generation."""
    if getattr(st.download_button, "_app_no_rerun_download", False):
        return

    original_st_download_button = st.download_button
    original_delta_download_button = st.delta_generator.DeltaGenerator.download_button

    def st_download_button_no_rerun(*args, **kwargs):
        kwargs.setdefault("on_click", "ignore")
        return original_st_download_button(*args, **kwargs)

    def delta_download_button_no_rerun(self, *args, **kwargs):
        kwargs.setdefault("on_click", "ignore")
        return original_delta_download_button(self, *args, **kwargs)

    st_download_button_no_rerun._app_no_rerun_download = True
    delta_download_button_no_rerun._app_no_rerun_download = True
    st.download_button = st_download_button_no_rerun
    st.delta_generator.DeltaGenerator.download_button = delta_download_button_no_rerun


_install_download_button_no_rerun()


CSV_ENCODINGS = ("utf-8", "utf-8-sig", "latin-1", "cp1252")
MIN_VALID_POINTS = 5
APP_STATE_VERSION = "smart-id-dynamic-biological-variables-v86"
MATERIAL_INPUT_VERSION = "ixx-section-modulus-derived-cy-v2"
CORRECTION_VERSION = "specimen-origin-displacement-force-v1"
THREE_POINT = "3-point bending"
FOUR_POINT = "4-point bending"
TENDON_TENSILE = "tendon tensile"
MIDSPAN = "Specimen midpoint"
LOADING_POINTS = "Upper loading points / crosshead"
SCHEMATIC_IMAGE_PATH = Path(__file__).resolve().with_name("four_point_bending_ap_schematic.png")
THREE_POINT_SCHEMATIC_IMAGE_PATH = Path(__file__).resolve().with_name("three_point_bending_ap_schematic.png")
TENDON_TENSILE_SCHEMATIC_IMAGE_PATH = Path(__file__).resolve().with_name("tendon_tensile_schematic_user.png")
UR_PRIMARY_KNOCKOUT_LOGO_URL = "https://brand.rochester.edu/wp-content/uploads/2025/09/primary_horizontal_knockout.png"

UR_NAVY = "#001E5F"
UR_DANDELION = "#FFD82B"
UR_MELIORA_BLUE = "#021BC3"
UR_QUANTUM_COBALT = "#003EFF"
UR_ARPEGGIO_AZURE = "#0066FD"
UR_CONNECTIVE_CORNFLOWER = "#66A2FF"
UR_WONDROUS_SKY = "#B7D3FF"
UR_YELLOWJACKET_GOLD = "#FFC200"
UR_BRIGHT_LEMON = "#FFE95F"
UR_EVER_BUTTER = "#FFF3B1"
UR_CHARCOAL = "#707070"
UR_MERIDIAN_SILVER = "#E8E8E8"
UR_WHITE_COAT = "#FFFFFF"

UR_CHART_COLORS = [
    UR_NAVY,
    UR_ARPEGGIO_AZURE,
    UR_YELLOWJACKET_GOLD,
    UR_CONNECTIVE_CORNFLOWER,
    UR_MELIORA_BLUE,
    UR_CHARCOAL,
    UR_WONDROUS_SKY,
    UR_DANDELION,
    UR_QUANTUM_COBALT,
    UR_EVER_BUTTER,
]
UR_LINE_STYLES = ["-", "--", "-.", ":"]


def configure_ur_matplotlib() -> None:
    """Apply URochester color and type defaults to generated figures."""
    plt.rcParams.update(
        {
            "figure.facecolor": UR_WHITE_COAT,
            "axes.facecolor": UR_WHITE_COAT,
            "axes.edgecolor": UR_CHARCOAL,
            "axes.labelcolor": UR_NAVY,
            "axes.titlecolor": UR_NAVY,
            "axes.titleweight": "bold",
            "xtick.color": UR_CHARCOAL,
            "ytick.color": UR_CHARCOAL,
            "grid.color": UR_MERIDIAN_SILVER,
            "grid.alpha": 0.8,
            "font.family": "sans-serif",
            "font.sans-serif": ["Inter Variable", "Inter", "Aptos", "Arial", "DejaVu Sans"],
            "axes.prop_cycle": plt.cycler(color=UR_CHART_COLORS),
        }
    )


def apply_ur_brand_theme() -> None:
    """Apply a University of Rochester-inspired Streamlit theme layer."""
    configure_ur_matplotlib()
    st.markdown(
        f"""
        <style>
        :root {{
            --ur-navy: {UR_NAVY};
            --ur-dandelion: {UR_DANDELION};
            --ur-meliora-blue: {UR_MELIORA_BLUE};
            --ur-arpeggio-azure: {UR_ARPEGGIO_AZURE};
            --ur-connective-cornflower: {UR_CONNECTIVE_CORNFLOWER};
            --ur-wondrous-sky: {UR_WONDROUS_SKY};
            --ur-yellowjacket-gold: {UR_YELLOWJACKET_GOLD};
            --ur-ever-butter: {UR_EVER_BUTTER};
            --ur-charcoal: {UR_CHARCOAL};
            --ur-meridian-silver: {UR_MERIDIAN_SILVER};
            --ur-white-coat: {UR_WHITE_COAT};
            --ur-font-sans: "Inter Variable", Inter, Aptos, Arial, sans-serif;
            --ur-font-serif: "Ivy Presto Text", "Ivy Presto", Georgia, serif;
        }}

        html, body, [class*="css"], .stApp {{
            font-family: var(--ur-font-sans);
        }}

        .stApp {{
            background:
                linear-gradient(135deg, rgba(255,216,43,0.20) 0 18rem, transparent 18rem),
                linear-gradient(180deg, #ffffff 0%, #f7f9ff 36rem, #ffffff 100%);
            color: #1f2937;
        }}

        .block-container {{
            padding-top: 4.75rem;
            max-width: 1320px;
        }}

        div[data-baseweb="tab-list"] {{
            min-height: 3.65rem;
            padding-top: 0.45rem;
            overflow: visible;
        }}

        button[data-baseweb="tab"] {{
            min-height: 3.25rem;
            padding-top: 0.7rem;
            padding-bottom: 0.7rem;
            overflow: visible;
        }}

        button[data-baseweb="tab"] p {{
            line-height: 1.35;
            overflow: visible;
        }}

        @media (max-width: 640px) {{
            .block-container {{
                padding-top: 4.25rem;
            }}

            div[data-baseweb="tab-list"] {{
                min-height: 3.4rem;
            }}
        }}

        .ur-app-header {{
            border-left: 0.55rem solid var(--ur-dandelion);
            background: linear-gradient(120deg, var(--ur-navy), var(--ur-meliora-blue));
            color: var(--ur-white-coat);
            padding: 1.45rem 1.65rem 1.55rem;
            margin: 0 0 1.35rem;
            box-shadow: 0 18px 38px rgba(0, 30, 95, 0.18);
        }}

        .ur-app-header__logo {{
            display: block;
            width: min(20rem, 72vw);
            height: auto;
            margin: 0 0 1.25rem;
        }}

        .ur-app-header__overline {{
            color: var(--ur-dandelion);
            font-size: 0.83rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin-bottom: 0.28rem;
        }}

        .ur-app-header h1 {{
            color: var(--ur-white-coat);
            font-family: var(--ur-font-sans);
            font-size: 2.25rem;
            font-weight: 900;
            line-height: 1.05;
            margin: 0 0 0.5rem;
            letter-spacing: 0;
        }}

        .ur-app-header p {{
            color: var(--ur-wondrous-sky);
            max-width: 62rem;
            margin: 0;
            font-size: 1rem;
            line-height: 1.45;
        }}

        .ur-brand-note {{
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            margin-top: 0.9rem;
            padding: 0.42rem 0.62rem;
            background: rgba(255,216,43,0.14);
            border: 1px solid rgba(255,216,43,0.45);
            color: var(--ur-ever-butter);
            font-size: 0.9rem;
            font-weight: 700;
        }}

        [data-testid="stBaseButton-segmented_controlActive"] {{
            background: var(--ur-dandelion);
            border-color: var(--ur-navy);
            color: var(--ur-navy);
        }}

        [data-testid="stBaseButton-segmented_control"] {{
            background: var(--ur-white-coat);
            border-color: var(--ur-charcoal);
            color: var(--ur-navy);
        }}

        [data-testid="stBaseButton-segmented_controlActive"] p,
        [data-testid="stBaseButton-segmented_control"] p {{
            color: inherit;
        }}

        h1, h2, h3, h4, h5, h6 {{
            color: var(--ur-navy);
            letter-spacing: 0;
        }}

        h2, h3 {{
            font-weight: 800;
        }}

        [data-testid="stSidebar"] {{
            background: var(--ur-navy);
            border-right: 0.35rem solid var(--ur-dandelion);
        }}

        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] .stMarkdown {{
            color: var(--ur-white-coat);
        }}

        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {{
            color: var(--ur-wondrous-sky);
        }}

        [data-testid="stSidebar"] input,
        [data-testid="stSidebar"] textarea,
        [data-testid="stSidebar"] [data-baseweb="select"] {{
            color: #111827;
        }}

        .stButton > button,
        .stDownloadButton > button {{
            border-radius: 0.35rem;
            border: 2px solid var(--ur-navy);
            color: var(--ur-navy);
            background: var(--ur-white-coat);
            font-weight: 800;
            transition: border-color 120ms ease, background 120ms ease, transform 120ms ease;
        }}

        .stButton > button:hover,
        .stDownloadButton > button:hover {{
            border-color: var(--ur-dandelion);
            background: var(--ur-ever-butter);
            color: var(--ur-navy);
            transform: translateY(-1px);
        }}

        .stButton > button[kind="primary"] {{
            background: var(--ur-dandelion);
            color: var(--ur-navy);
            border-color: var(--ur-dandelion);
        }}

        .stButton > button[kind="primary"]:hover {{
            background: var(--ur-yellowjacket-gold);
            border-color: var(--ur-yellowjacket-gold);
        }}

        button:focus-visible,
        a:focus-visible,
        input:focus,
        textarea:focus {{
            outline: 3px solid var(--ur-dandelion) !important;
            outline-offset: 2px !important;
        }}

        div[data-testid="stMetric"] {{
            background: var(--ur-white-coat);
            border-top: 0.28rem solid var(--ur-dandelion);
            border-left: 1px solid var(--ur-meridian-silver);
            border-right: 1px solid var(--ur-meridian-silver);
            border-bottom: 1px solid var(--ur-meridian-silver);
            padding: 0.75rem 0.9rem;
            box-shadow: 0 8px 22px rgba(0, 30, 95, 0.08);
        }}

        [data-testid="stMetricLabel"] p {{
            color: var(--ur-charcoal);
            font-weight: 700;
        }}

        [data-testid="stMetricValue"] {{
            color: var(--ur-navy);
            font-weight: 900;
        }}

        [data-testid="stExpander"] {{
            border: 1px solid var(--ur-meridian-silver);
            border-radius: 0.35rem;
            background: rgba(255,255,255,0.82);
        }}

        [data-testid="stSidebar"] [data-testid="stExpander"] {{
            background: transparent;
            color: var(--ur-white-coat);
        }}

        [data-testid="stDataFrame"] {{
            border: 1px solid var(--ur-meridian-silver);
            border-radius: 0.35rem;
            overflow: hidden;
            box-shadow: 0 10px 28px rgba(0, 30, 95, 0.07);
        }}

        div[data-testid="stAlert"] {{
            border-radius: 0.35rem;
            border-left-width: 0.45rem;
        }}

        .ur-download-link {{
            display: inline-block;
            padding: 0.48rem 0.76rem;
            border: 2px solid var(--ur-navy);
            border-radius: 0.35rem;
            text-decoration: none !important;
            color: var(--ur-navy) !important;
            background: var(--ur-white-coat);
            font-weight: 800;
        }}

        .ur-download-link:hover {{
            background: var(--ur-ever-butter);
            border-color: var(--ur-dandelion);
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_ur_brand_header(test_type: str = FOUR_POINT) -> None:
    st.markdown(
        f"""
        <section class="ur-app-header" aria-label="Application heading">
            <img
                class="ur-app-header__logo"
                src="{UR_PRIMARY_KNOCKOUT_LOGO_URL}"
                alt="University of Rochester logo"
            />
            <div class="ur-app-header__overline">University of Rochester</div>
            <h1>{escape(test_type.replace('bending', 'Bend').title())} Batch Analyzer</h1>
            <p>Mouse femur biomechanical analysis</p>
            <div class="ur-brand-note">Ever wonder. Ever better.</div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_tendon_header() -> None:
    st.markdown(
        f"""
        <section class="ur-app-header" aria-label="Application heading">
            <img class="ur-app-header__logo" src="{UR_PRIMARY_KNOCKOUT_LOGO_URL}"
                alt="University of Rochester logo" />
            <div class="ur-app-header__overline">University of Rochester</div>
            <h1>Tendon Tensile Test Batch Analyzer</h1>
            <p>Mouse tendon structural and material-property analysis</p>
            <div class="ur-brand-note">Ever wonder. Ever better.</div>
        </section>
        """,
        unsafe_allow_html=True,
    )


@dataclass(frozen=True)
class BendingGeometry:
    """Symmetric, simply supported bending with a specified deflection location.

    F is total applied force. From Euler-Bernoulli beam theory, M=FS/4
    and delta=FS^3/(48EI) for a central load, hence epsilon=12c*delta/S^2.
    For four points, a=(S-L)/2 and M=Fa/2. Midspan delta is
    Fa(3S^2-4a^2)/(48EI); loading-point delta is Fa^2(3S-4a)/(12EI).
    Dividing M*c/EI by the appropriate delta gives the strain factors below.
    Reference: SCI/BCSA Handbook, simply supported beam/two symmetric loads.
    https://www.steelconstruction.info/images/6/65/Handbook_of_Structural_Steelwork_EE_55-13.pdf
    """

    test_type: str = FOUR_POINT
    support_span_mm: float = 9.5
    loading_span_mm: float = 3.5
    displacement_location: str = MIDSPAN

    def validate(self) -> None:
        if self.test_type not in (THREE_POINT, FOUR_POINT):
            raise ValueError("Select 3-point bending or 4-point bending.")
        if not np.isfinite(self.support_span_mm) or self.support_span_mm <= 0:
            raise ValueError("Support span S must be finite and greater than 0.")
        if self.test_type == FOUR_POINT and (
            not np.isfinite(self.loading_span_mm)
            or not 0 < self.loading_span_mm < self.support_span_mm
        ):
            raise ValueError("Loading span L must be greater than 0 and smaller than support span S.")
        if self.test_type == FOUR_POINT and self.displacement_location not in (MIDSPAN, LOADING_POINTS):
            raise ValueError("Select the displacement measurement location.")

    @property
    def effective_displacement_location(self) -> str:
        return MIDSPAN if self.test_type == THREE_POINT else self.displacement_location

    @property
    def effective_loading_span_mm(self) -> float:
        return 0.0 if self.test_type == THREE_POINT else self.loading_span_mm

    @property
    def moment_per_force_mm(self) -> float:
        self.validate()
        return (self.support_span_mm - self.effective_loading_span_mm) / 4.0

    def strain_per_displacement(self, c_mm: float) -> float:
        self.validate()
        if not np.isfinite(c_mm) or c_mm <= 0:
            raise ValueError("c must be finite and greater than 0.")
        if self.test_type == THREE_POINT:
            return 12.0 * c_mm / self.support_span_mm**2
        if self.displacement_location == LOADING_POINTS:
            return 12.0 * c_mm / (
                (self.support_span_mm - self.loading_span_mm)
                * (self.support_span_mm + 2.0 * self.loading_span_mm)
            )
        return 24.0 * c_mm / (
            3.0 * self.support_span_mm**2
            - (self.support_span_mm - self.loading_span_mm)**2
        )

    @property
    def description(self) -> str:
        spans = f"S = {self.support_span_mm:g} mm"
        if self.test_type == FOUR_POINT:
            spans += f", L = {self.loading_span_mm:g} mm"
            spans += " | " + ("Loading-point deflection" if self.displacement_location == LOADING_POINTS else "Midspan deflection")
        return f"{self.test_type.capitalize()} | {spans}"


@dataclass
class OnsetParameters:
    threshold_multiplier: float
    consecutive_points: int
    smoothing_window: int
    min_force_rise_fraction: float
    max_onset_force: float
    baseline_fraction: float = 0.10


@dataclass
class StiffnessParameters:
    r2_threshold: float
    minimum_points: int
    max_search_points: int
    manual_region_enabled: bool
    manual_start_displacement: float
    manual_end_displacement: float


@dataclass
class YieldParameters:
    use_fixed_offset: bool
    fixed_offset_mm: float
    smoothing_window: int
    method: str = "Automatic"
    proportional_departure_fraction: float = 0.10
    proportional_consecutive_points: int = 5
    fallback_other_method: bool = True
    fallback_half_offset: bool = True
    fallback_lower_proportional_limits: bool = True


@dataclass
class ProcessedSpecimen:
    specimen_id: str
    display_id: str
    file_name: str
    original_points: int
    retained_points: int
    removed_points: int
    onset_index: int
    onset_displacement: float
    onset_force: float
    maximum_force: float
    displacement_at_maximum_force: float
    maximum_moment: float
    displacement_at_maximum_moment: float
    work_to_maximum_force: float
    elastic_stiffness_n_per_mm: float
    stiffness_r2: float
    stiffness_region_start_displacement: float
    stiffness_region_end_displacement: float
    stiffness_region_points: int
    stiffness_region_source: str
    yield_displacement: float
    yield_force: float
    yield_moment: float
    yield_offset_mm: float
    post_yield_displacement: float
    metadata_matched: bool
    metadata_id: str
    genotype: str
    age: str
    sex: str
    section_modulus_mm3: float
    c_mm: float
    elastic_modulus_mpa: float
    elastic_modulus_r2: float
    yield_stress_mpa: float
    ultimate_stress_mpa: float
    strain_energy_density_to_max_stress_mpa: float
    strain_at_yield: float
    strain_at_ultimate_stress: float
    strain_at_failure: float
    post_peak_drop_percent: float
    post_peak_points_removed: int
    geometry: BendingGeometry
    subtract_baseline: bool
    metadata: dict[str, str]
    raw_data: pd.DataFrame
    corrected_data: pd.DataFrame
    ixx_mm4: float = np.nan
    material_geometry_source: str = ""
    label_source: str = ""
    metadata_match_method: str = ""
    yield_method: str = "Not detected"
    yield_requested_method: str = "Automatic"
    yield_criterion: str = ""
    yield_fallback_used: bool = False
    yield_reduced_offset_used: bool = False
    yield_attempted_methods: str = ""
    yield_analysis_basis: str = ""
    yield_offset_basis: str = ""
    yield_offset_strain: float = np.nan
    yield_proportional_departure_percent: float = np.nan
    yield_reduced_proportional_used: bool = False
    warning: str = ""
    error: str = ""


@dataclass
class TendonProcessedSpecimen:
    specimen_id: str
    display_id: str
    file_name: str
    original_points: int
    retained_points: int
    onset_index: int
    onset_displacement: float
    onset_force: float
    maximum_force: float
    displacement_at_maximum_force: float
    work_to_maximum_force_mj: float
    tensile_stiffness_n_per_mm: float
    stiffness_r2: float
    stiffness_region_start_displacement: float
    stiffness_region_end_displacement: float
    stiffness_region_points: int
    stiffness_region_source: str
    yield_displacement: float
    yield_force: float
    yield_offset_mm: float
    post_yield_displacement: float
    cross_sectional_area_mm2: float
    gauge_length_mm: float
    elastic_modulus_mpa: float
    elastic_modulus_r2: float
    yield_stress_mpa: float
    ultimate_stress_mpa: float
    strain_energy_density_mj_m3: float
    strain_at_yield: float
    strain_at_ultimate_stress: float
    strain_at_failure: float
    metadata_matched: bool
    metadata_id: str
    genotype: str
    age: str
    sex: str
    metadata: dict[str, str]
    raw_data: pd.DataFrame
    corrected_data: pd.DataFrame
    post_peak_points_removed: int = 0
    label_source: str = ""
    metadata_match_method: str = ""
    yield_method: str = "Not detected"
    yield_requested_method: str = "Automatic"
    yield_criterion: str = ""
    yield_fallback_used: bool = False
    yield_reduced_offset_used: bool = False
    yield_attempted_methods: str = ""
    yield_analysis_basis: str = ""
    yield_offset_basis: str = ""
    yield_offset_strain: float = np.nan
    yield_proportional_departure_percent: float = np.nan
    yield_reduced_proportional_used: bool = False
    warning: str = ""
    error: str = ""


def load_csv_file(file: BinaryIO | bytes | str | Path) -> pd.DataFrame:
    """Load a CSV as a spreadsheet-like table with no inferred header.

    Many instrument exports have ragged metadata rows before the numeric data.
    Pandas' CSV parser rejects those by default, so this uses Python's csv
    module and pads shorter rows to the widest row.
    """
    if isinstance(file, (str, Path)):
        raw_bytes = Path(file).read_bytes()
    elif isinstance(file, bytes):
        raw_bytes = file
    else:
        raw_bytes = file.read()

    last_error: Exception | None = None
    for encoding in CSV_ENCODINGS:
        try:
            decoded = raw_bytes.decode(encoding)
            if not decoded.strip():
                raise ValueError("The CSV file is empty.")

            sample = decoded[:4096]
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
            except csv.Error:
                dialect = csv.excel

            rows = list(csv.reader(StringIO(decoded), dialect))
            if not rows:
                raise ValueError("The CSV file is empty.")

            width = max(len(row) for row in rows)
            if width == 0:
                raise ValueError("The CSV file is empty.")

            padded_rows = [row + [""] * (width - len(row)) for row in rows]
            return pd.DataFrame(padded_rows, dtype=str)
        except UnicodeDecodeError as exc:
            last_error = exc
        except ValueError:
            raise
        except Exception as exc:
            last_error = exc

    raise ValueError(f"Could not read CSV with supported encodings: {last_error}")


def read_uploaded_bytes(file: BinaryIO | bytes | str | Path) -> tuple[bytes, str]:
    if isinstance(file, (str, Path)):
        path = Path(file)
        return path.read_bytes(), path.name
    if isinstance(file, bytes):
        return file, ""
    if hasattr(file, "seek"):
        file.seek(0)
    raw_bytes = file.read()
    if hasattr(file, "seek"):
        file.seek(0)
    return raw_bytes, str(getattr(file, "name", ""))


def load_test_data_file(file: BinaryIO | bytes | str | Path) -> pd.DataFrame:
    """Load a headerless test table from CSV or the first Excel worksheet."""
    raw_bytes, file_name = read_uploaded_bytes(file)
    suffix = Path(file_name).suffix.casefold()
    is_excel = suffix in {".xlsx", ".xls"} or (
        not suffix
        and (
            raw_bytes.startswith(b"PK\x03\x04")
            or raw_bytes.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
        )
    )
    if not is_excel:
        return load_csv_file(raw_bytes)
    if not raw_bytes:
        raise ValueError("The test data file is empty.")
    try:
        data = pd.read_excel(
            BytesIO(raw_bytes), sheet_name=0, header=None, dtype=str,
            keep_default_na=False,
        )
    except Exception as exc:
        raise ValueError(f"Could not read Excel test data: {exc}") from exc
    if data.empty or data.shape[1] == 0:
        raise ValueError("The first Excel worksheet is empty.")
    return data


def load_metadata_file(file: BinaryIO | bytes | str | Path) -> pd.DataFrame:
    """Load optional specimen metadata from CSV or the first Excel worksheet."""
    if isinstance(file, (str, Path)):
        raw_bytes = Path(file).read_bytes()
    elif isinstance(file, bytes):
        raw_bytes = file
    else:
        raw_bytes = file.read()

    if raw_bytes.startswith(b"PK\x03\x04") or raw_bytes.startswith(
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    ):
        try:
            metadata = pd.read_excel(BytesIO(raw_bytes), sheet_name=0, dtype=str)
        except Exception as exc:
            raise ValueError(f"Could not read Excel metadata: {exc}") from exc
        metadata = metadata.dropna(how="all")
        metadata.columns = [str(column).strip() for column in metadata.columns]
        if metadata.empty or not len(metadata.columns):
            raise ValueError("The first Excel metadata worksheet is empty.")
        return metadata

    last_error: Exception | None = None
    for encoding in CSV_ENCODINGS:
        try:
            metadata = pd.read_csv(BytesIO(raw_bytes), dtype=str, encoding=encoding)
            metadata = metadata.dropna(how="all")
            metadata.columns = [str(column).strip() for column in metadata.columns]
            if metadata.empty or not len(metadata.columns):
                raise ValueError("The metadata CSV is empty.")
            return metadata
        except UnicodeDecodeError as exc:
            last_error = exc
        except ValueError:
            raise
        except Exception as exc:
            last_error = exc

    raise ValueError(f"Could not read metadata CSV with supported encodings: {last_error}")


def load_metadata_data_file(file: BinaryIO | bytes | str | Path) -> pd.DataFrame:
    """Load metadata from CSV or the first Excel worksheet."""
    raw_bytes, file_name = read_uploaded_bytes(file)
    suffix = Path(file_name).suffix.casefold()
    is_excel = suffix in {".xlsx", ".xls"} or (
        not suffix
        and (
            raw_bytes.startswith(b"PK\x03\x04")
            or raw_bytes.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
        )
    )
    if not is_excel:
        return load_metadata_file(raw_bytes)
    if not raw_bytes:
        raise ValueError("The metadata file is empty.")
    try:
        metadata = pd.read_excel(BytesIO(raw_bytes), sheet_name=0, dtype=str)
    except Exception as exc:
        raise ValueError(f"Could not read Excel metadata: {exc}") from exc
    metadata = metadata.dropna(how="all")
    metadata.columns = [str(column).strip() for column in metadata.columns]
    if metadata.empty or not len(metadata.columns):
        raise ValueError("The first Excel metadata worksheet is empty.")
    return metadata


def parse_metadata_numeric(value) -> float:
    """Parse numeric metadata values that may include units, commas, or spaces."""
    numeric = pd.to_numeric(value, errors="coerce")
    if np.isfinite(numeric):
        return float(numeric)
    if pd.isna(value):
        return np.nan

    text = str(value).strip().replace(",", "")
    if not text:
        return np.nan
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", text)
    if not match:
        return np.nan
    numeric = pd.to_numeric(match.group(0), errors="coerce")
    return float(numeric) if np.isfinite(numeric) else np.nan


def infer_column_index(columns: list[str], keywords: list[str]) -> int:
    normalized_columns = [column.casefold().strip() for column in columns]
    for keyword in keywords:
        keyword_normalized = keyword.casefold().strip()
        for index, column in enumerate(normalized_columns):
            if column == keyword_normalized:
                return index
    for keyword in keywords:
        keyword_normalized = keyword.casefold().strip()
        for index, column in enumerate(columns):
            if keyword_normalized in column.casefold():
                return index
    return 0


def infer_optional_column_index(columns: list[str], keywords: list[str]) -> int | None:
    normalized_columns = [column.casefold().strip() for column in columns]
    for keyword in keywords:
        keyword_normalized = keyword.casefold().strip()
        for index, column in enumerate(normalized_columns):
            if column == keyword_normalized:
                return index
    for keyword in keywords:
        keyword_normalized = keyword.casefold().strip()
        for index, column in enumerate(columns):
            if keyword_normalized in column.casefold():
                return index
    return None


BIOLOGICAL_COLUMN_KEYWORDS = (
    "genotype", "strain", "sex", "gender", "age", "cohort", "group",
    "treatment", "condition", "diet", "injury", "timepoint", "time point",
    "phenotype", "site", "laterality", "batch",
)


def infer_biological_metadata_columns(
    metadata_df: pd.DataFrame,
    excluded_columns: set[str | None],
    maximum: int = 3,
) -> list[str]:
    """Select likely grouping variables from metadata headers and cardinality."""
    excluded = {str(column) for column in excluded_columns if column is not None}
    available = [str(column) for column in metadata_df.columns if str(column) not in excluded]
    selected = []
    for keyword in BIOLOGICAL_COLUMN_KEYWORDS:
        for column in available:
            normalized = column.casefold().strip()
            if column not in selected and (normalized == keyword or keyword in normalized):
                selected.append(column)
                if len(selected) >= maximum:
                    return selected

    # When familiar names are absent, prefer non-unique categorical columns.
    row_count = max(1, len(metadata_df))
    for column in available:
        values = metadata_df[column].dropna().astype(str).str.strip()
        values = values[values.astype(bool)]
        unique_count = int(values.nunique())
        if column not in selected and 2 <= unique_count <= min(20, max(2, row_count // 2)):
            selected.append(column)
            if len(selected) >= maximum:
                break
    return selected


def biological_role_columns(selected_columns: list[str]) -> tuple[str | None, str | None, str | None]:
    padded = list(selected_columns[:3]) + [None, None, None]
    return padded[0], padded[1], padded[2]


def biological_factor_label_map(
    first_column: str | None,
    second_column: str | None,
    third_column: str | None,
) -> dict[str, str]:
    selected = (first_column, second_column, third_column)
    return {
        internal: external or f"Biological variable {index}"
        for index, (internal, external) in enumerate(zip(("Genotype", "Age", "Sex"), selected), start=1)
    }


def _replace_factor_labels(text: str, factor_labels: dict[str, str]) -> str:
    return re.sub(
        r"\b(?:Genotype|Age|Sex)\b",
        lambda match: factor_labels.get(match.group(), match.group()),
        text,
    )


def public_summary_with_biological_headers(
    summary: pd.DataFrame,
    factor_labels: dict[str, str],
) -> pd.DataFrame:
    """Remove internal grouping aliases when their metadata headers are available."""
    # Copy all roles before renaming: e.g. Genotype -> Sex and Sex -> Timepoint
    # must not read or discard a column that has already been renamed.
    values = {
        external: summary[internal].copy()
        for internal, external in factor_labels.items()
        if internal in summary and not external.startswith("Biological variable")
    }
    result = summary.drop(columns=list(factor_labels), errors="ignore").copy()
    for column, data in values.items():
        result[column] = data
    leading = (["Specimen ID"] if "Specimen ID" in result else []) + list(values)
    return result[leading + [column for column in result if column not in leading]]


def infer_geometry_column(columns: list[str], quantity: str) -> str | None:
    """Only preselect an unambiguous axis-specific header, never a substring.

    In particular, Imin/Cmin, Iyy, and specimen-ID columns are not substitutes
    for Ixx or Cy. Ignore common unit suffixes when identifying the header.
    """
    aliases = {
        "ixx": {"ixx", "ix", "secondmomentofareaxx", "momentofinertiaxx"},
        "cy": {"cy"},
        "ic": {"ixxcy"},
        "c": {"c", "cy", "neutralaxisdistance", "nadistance"},
    }
    matches = []
    for column in columns:
        header = str(column).casefold().replace("\u2074", "4").replace("\u00b3", "3").replace("\u00b2", "2")
        normalized = re.sub(r"[^a-z0-9]", "", header)
        unit_suffix = {"ixx": r"mm4$", "ic": r"mm3$", "cy": r"mm$", "c": r"mm$"}[quantity]
        normalized = re.sub(unit_suffix, "", normalized)
        if normalized in aliases[quantity]:
            matches.append(column)
    return matches[0] if len(matches) == 1 else None


def is_centroid_column(column: str | None) -> bool:
    """Centroid coordinates must never stand in for bending geometry inputs."""
    header = re.sub(r"[^a-z]", "", str(column).casefold())
    header = re.sub(r"(?:mm|cm|um)$", "", header)
    return header in {
        "cmx", "cmy", "cmz", "centroidx", "centroidy", "centroidz",
        "xcentroid", "ycentroid", "zcentroid", "centerofmassx",
        "centerofmassy", "centerofmassz", "centreofmassx",
        "centreofmassy", "centreofmassz",
    }


def metadata_value_from_selected_or_keywords(
    metadata_row: dict[str, str],
    selected_column: str | None,
    keywords: list[str],
) -> str:
    if selected_column and selected_column in metadata_row:
        return str(metadata_row.get(selected_column, "")).strip()

    columns = list(metadata_row.keys())
    inferred_index = infer_optional_column_index(columns, keywords)
    if inferred_index is None:
        return ""
    return str(metadata_row.get(columns[inferred_index], "")).strip()


def extract_specimen_id(df: pd.DataFrame, file_name: str = "") -> str:
    """Discover labeled specimen fields, with B4 and filename fallbacks."""
    identity = resolve_specimen_identity(df, file_name)
    if identity.error:
        raise ValueError(identity.error)
    return identity.specimen_id


def extract_force_displacement_data(df: pd.DataFrame) -> pd.DataFrame:
    """Read the labeled measurement table, with row 11 as a legacy fallback."""
    if df.shape[1] <= 2:
        raise ValueError("Missing displacement and/or force columns B and C.")

    header_row = None
    displacement_column, force_column = 1, 2
    for row in range(min(len(df), 100)):
        labels = [str(value).strip().casefold() for value in df.iloc[row]]
        displacements = [i for i, label in enumerate(labels) if re.fullmatch(r"(?:displacement|extension)(?:\s*\(mm\))?", label)]
        forces = [i for i, label in enumerate(labels) if re.fullmatch(r"(?:force|load)(?:\s*\(n\))?", label)]
        if len(displacements) == 1 and len(forces) == 1:
            header_row = row
            displacement_column, force_column = displacements[0], forces[0]
            break
    start_row = header_row + 1 if header_row is not None else 10
    if len(df) <= start_row:
        raise ValueError("No measurement rows found after the force-displacement header or legacy row 11.")
    data = df.iloc[start_row:, [displacement_column, force_column]].copy()
    data.columns = ["displacement_mm", "force_n"]
    data["displacement_mm"] = pd.to_numeric(data["displacement_mm"], errors="coerce")
    data["force_n"] = pd.to_numeric(data["force_n"], errors="coerce")
    data = data.replace([np.inf, -np.inf], np.nan).dropna(subset=["displacement_mm", "force_n"]).reset_index(drop=True)

    if len(data) < MIN_VALID_POINTS:
        raise ValueError(f"Too few valid data points after cleanup; found {len(data)}.")

    return data


def _odd_window(window: int, n_points: int) -> int:
    window = max(1, int(window))
    window = min(window, n_points)
    if window % 2 == 0:
        window -= 1
    return max(1, window)


def smooth_force_signal(force: np.ndarray, window: int) -> np.ndarray:
    """Apply a centered rolling median while preserving signal length."""
    window = _odd_window(window, len(force))
    if window <= 1:
        return force.astype(float)

    return (
        pd.Series(force)
        .rolling(window=window, center=True, min_periods=1)
        .median()
        .to_numpy(dtype=float)
    )


def detect_loading_onset(
    displacement: np.ndarray,
    force: np.ndarray,
    parameters: OnsetParameters,
) -> tuple[int, str]:
    """
    Detect the loading onset using a noise threshold plus sustained positive slope.

    The early part of each curve is treated as baseline noise. The onset is the
    first point where smoothed force rises above baseline median + multiplier*MAD
    and the following local force-displacement steps keep a positive slope for
    the requested consecutive-point window.
    """
    if len(displacement) != len(force):
        raise ValueError("Displacement and force arrays must have the same length.")
    if len(force) < MIN_VALID_POINTS:
        raise ValueError(f"At least {MIN_VALID_POINTS} valid points are required.")

    smoothed_force = smooth_force_signal(force, parameters.smoothing_window)
    baseline_n = max(3, int(np.ceil(len(force) * parameters.baseline_fraction)))
    baseline_n = min(baseline_n, len(force))
    baseline = smoothed_force[:baseline_n]
    baseline_median = float(np.median(baseline))
    mad = float(np.median(np.abs(baseline - baseline_median)))
    std = float(np.std(baseline, ddof=1)) if baseline_n > 1 else 0.0
    noise = mad if mad > 0 else std
    if noise <= 0:
        noise = max(abs(baseline_median) * 1e-9, 1e-12)

    force_range = float(np.nanmax(smoothed_force) - np.nanmin(smoothed_force))
    min_force_rise = max(0.0, parameters.min_force_rise_fraction) * force_range
    force_threshold = baseline_median + max(
        parameters.threshold_multiplier * noise,
        min_force_rise,
    )
    window = max(1, int(parameters.consecutive_points))

    delta_displacement = np.diff(displacement)
    delta_force = np.diff(smoothed_force)
    slopes = np.full_like(delta_force, np.nan, dtype=float)
    valid_steps = delta_displacement > 0
    slopes[valid_steps] = delta_force[valid_steps] / delta_displacement[valid_steps]
    positive_slopes = slopes[np.isfinite(slopes) & (slopes > 0)]
    if len(positive_slopes):
        slope_threshold = max(float(np.percentile(positive_slopes, 75)) * 0.05, 1e-12)
    else:
        slope_threshold = 1e-12

    loading_slope = np.isfinite(slopes) & (slopes >= slope_threshold)
    slope_only_index = detect_sustained_slope_onset(loading_slope, window)
    force_threshold_index = None

    for idx in range(len(force)):
        if smoothed_force[idx] <= force_threshold:
            continue

        end = min(idx + window, len(force) - 1)
        if end <= idx:
            return idx, ""

        if np.all(loading_slope[idx:end]):
            force_threshold_index = idx
            break

    if slope_only_index is not None and force_threshold_index is not None:
        if slope_only_index == 0:
            return enforce_max_onset_force(0, force, parameters.max_onset_force)
        return enforce_max_onset_force(
            force_threshold_index,
            force,
            parameters.max_onset_force,
        )

    if slope_only_index == 0:
        return enforce_max_onset_force(0, force, parameters.max_onset_force)

    if force_threshold_index is not None:
        return enforce_max_onset_force(
            force_threshold_index,
            force,
            parameters.max_onset_force,
        )

    warning = "Loading onset was not detected; first valid data point was used."
    onset_index, force_warning = enforce_max_onset_force(
        0,
        force,
        parameters.max_onset_force,
    )
    return onset_index, combine_warnings(warning, force_warning)


def enforce_max_onset_force(
    onset_index: int,
    force: np.ndarray,
    max_onset_force: float,
) -> tuple[int, str]:
    """Move onset back so the selected raw force does not exceed the cap."""
    if max_onset_force <= 0 or not np.isfinite(max_onset_force):
        return onset_index, ""

    if force[onset_index] <= max_onset_force:
        return onset_index, ""

    eligible_indices = np.flatnonzero(force[: onset_index + 1] <= max_onset_force)
    if len(eligible_indices):
        adjusted_index = int(eligible_indices[-1])
        warning = (
            f"Onset was moved from point {onset_index} to point {adjusted_index} "
            f"to keep onset force <= {max_onset_force:g} N."
        )
        return adjusted_index, warning

    warning = (
        f"No point at or before detected onset had force <= {max_onset_force:g} N; "
        "detected onset was kept."
    )
    return onset_index, warning


def combine_warnings(*warnings: str) -> str:
    return " ".join(warning for warning in warnings if warning)


def detect_sustained_slope_onset(
    loading_slope: np.ndarray,
    consecutive_points: int,
) -> Optional[int]:
    """Return the first point followed by a sustained run of loading slopes."""
    window = max(1, int(consecutive_points))
    if len(loading_slope) < window:
        return None

    for idx in range(len(loading_slope) - window + 1):
        if np.all(loading_slope[idx : idx + window]):
            return 0 if idx == 0 else idx + 1

    return None


def correct_curve(
    displacement: np.ndarray,
    force: np.ndarray,
    onset_index: int,
) -> pd.DataFrame:
    """Trim before onset and zero BOTH axes independently for this specimen.

    This is the common input to trimming, moment/stress conversion, fits,
    yield, peaks, and integrals. Original instrument values remain unchanged.
    """
    trimmed_displacement = displacement[onset_index:].astype(float)
    trimmed_force = force[onset_index:].astype(float)
    onset_displacement = float(displacement[onset_index])
    onset_force = float(force[onset_index])

    corrected_force = trimmed_force - onset_force

    return pd.DataFrame(
        {
            "data_point_index_after_correction": np.arange(len(trimmed_displacement)),
            "corrected_displacement_mm": trimmed_displacement - onset_displacement,
            "force_n": corrected_force,
            "original_displacement_mm": trimmed_displacement,
            "original_force_n": trimmed_force,
            "displacement_origin_mm": onset_displacement,
            "force_offset_subtracted_n": onset_force,
            "correction_version": CORRECTION_VERSION,
        }
    )


def trim_after_force_drop(
    corrected_data: pd.DataFrame,
    drop_fraction: float,
) -> tuple[pd.DataFrame, int, float, float, str]:
    """Trim post-peak data after force drops by a chosen fraction from max force."""
    if corrected_data.empty:
        return corrected_data, 0, np.nan, np.nan, ""

    force = corrected_data["force_n"].to_numpy(dtype=float)
    max_index = int(np.nanargmax(force))
    max_force = float(force[max_index])
    cutoff_force = max_force * (1.0 - drop_fraction)

    if max_force <= 0:
        return corrected_data, 0, max_force, cutoff_force, "Post-peak trimming skipped because maximum force is not positive."

    post_peak_force = force[max_index + 1 :]
    crossing_positions = np.flatnonzero(post_peak_force <= cutoff_force)
    if not len(crossing_positions):
        warning = (
            f"Post-peak force never dropped by {drop_fraction * 100:g}% from maximum force; "
            "no post-peak data were removed."
        )
        return corrected_data, 0, max_force, cutoff_force, warning

    cutoff_index = max_index + 1 + int(crossing_positions[0])
    trimmed_data = corrected_data.iloc[: cutoff_index + 1].copy().reset_index(drop=True)
    trimmed_data["data_point_index_after_correction"] = np.arange(len(trimmed_data))
    removed_points = len(corrected_data) - len(trimmed_data)
    return trimmed_data, removed_points, max_force, cutoff_force, ""


def add_bending_moment(
    corrected_data: pd.DataFrame,
    geometry: BendingGeometry,
) -> pd.DataFrame:
    """Convert corrected force using the selected fixture's moment factor."""
    corrected_data = corrected_data.copy()
    corrected_data["bending_test"] = geometry.test_type
    corrected_data["support_span_s_mm"] = geometry.support_span_mm
    corrected_data["loading_span_l_mm"] = geometry.effective_loading_span_mm
    corrected_data["moment_per_force_mm"] = geometry.moment_per_force_mm
    corrected_data["displacement_measurement_location"] = geometry.effective_displacement_location
    corrected_data["bending_moment_n_mm"] = corrected_data["force_n"].astype(float) * geometry.moment_per_force_mm
    return corrected_data


def extract_peak_metrics(corrected_data: pd.DataFrame) -> dict[str, float]:
    """Extract peak force and moment metrics from final corrected data."""
    if corrected_data.empty:
        return {
            "maximum_force": np.nan,
            "displacement_at_maximum_force": np.nan,
            "maximum_moment": np.nan,
            "displacement_at_maximum_moment": np.nan,
            "work_to_maximum_force": np.nan,
        }

    force_index = int(corrected_data["force_n"].astype(float).idxmax())
    moment_index = int(corrected_data["bending_moment_n_mm"].astype(float).idxmax())
    force_row = corrected_data.loc[force_index]
    moment_row = corrected_data.loc[moment_index]
    moment_to_peak = corrected_data.loc[:moment_index, "bending_moment_n_mm"].to_numpy(dtype=float)
    displacement_to_peak = corrected_data.loc[:moment_index, "corrected_displacement_mm"].to_numpy(dtype=float)
    work_to_maximum_force = (
        float(np.trapezoid(moment_to_peak, displacement_to_peak))
        if len(moment_to_peak) > 1
        else 0.0
    )

    return {
        "maximum_force": float(force_row["force_n"]),
        "displacement_at_maximum_force": float(force_row["corrected_displacement_mm"]),
        "maximum_moment": float(moment_row["bending_moment_n_mm"]),
        "displacement_at_maximum_moment": float(moment_row["corrected_displacement_mm"]),
        "work_to_maximum_force": work_to_maximum_force,
    }


def empty_material_metrics() -> dict[str, float | bool | str]:
    return {
        "metadata_matched": False,
        "metadata_id": "",
        "ixx_mm4": np.nan,
        "material_geometry_source": "",
        "section_modulus_mm3": np.nan,
        "c_mm": np.nan,
        "elastic_modulus_mpa": np.nan,
        "elastic_modulus_r2": np.nan,
        "yield_stress_mpa": np.nan,
        "ultimate_stress_mpa": np.nan,
        "strain_energy_density_to_max_stress_mpa": np.nan,
        "strain_at_yield": np.nan,
        "strain_at_ultimate_stress": np.nan,
        "strain_at_failure": np.nan,
    }


def calculate_bending_strain(
    displacement_mm: np.ndarray,
    c_mm: float,
    geometry: BendingGeometry,
) -> np.ndarray:
    """Convert the selected specimen deflection to apparent outer-fiber strain."""
    return np.asarray(displacement_mm, dtype=float) * geometry.strain_per_displacement(c_mm)


def apply_material_properties(
    corrected_data: pd.DataFrame,
    metadata_row: dict[str, str] | None,
    metadata_id_column: str | None,
    section_modulus_column: str | None,
    stiffness_metrics: dict[str, float],
    yield_metrics: dict[str, float],
    geometry: BendingGeometry,
    inertia_column: str | None = None,
    conversion_only: bool = False,
) -> tuple[pd.DataFrame, dict[str, float | bool | str], str]:
    """Use Z = supplied Ixx/Cy for stress and derive Cy = supplied Ixx / Z.

    Both inputs come from the same specimen's matched metadata row and bending
    axis. Cy is an effective surface distance when the inputs are slice averages.
    CMx/CMy centroid coordinates are never used for either calculation.
    """
    corrected_data = corrected_data.copy()
    corrected_data["metadata_matched"] = False
    corrected_data["ixx_mm4"] = np.nan
    corrected_data["material_geometry_source"] = ""
    corrected_data["section_modulus_mm3"] = np.nan
    corrected_data["c_mm"] = np.nan
    corrected_data["tensile_stress_mpa"] = np.nan
    corrected_data["tensile_strain"] = np.nan
    corrected_data["elastic_modulus_fit_stress_mpa"] = np.nan

    metrics = empty_material_metrics()
    if metadata_row is None:
        return corrected_data, metrics, ""
    # A valid metadata match is independent of whether its geometry is usable.
    metrics["metadata_matched"] = True
    metrics["metadata_id"] = str(metadata_row.get(metadata_id_column, "")).strip() if metadata_id_column else ""
    corrected_data["metadata_matched"] = True
    source = f"Supplied Ixx/Cy: {section_modulus_column}; derived Cy = {inertia_column} / ({section_modulus_column})"
    metrics["material_geometry_source"] = source
    corrected_data["material_geometry_source"] = source
    if any(is_centroid_column(column) for column in (inertia_column, section_modulus_column)):
        return corrected_data, metrics, "Material properties skipped: CMx/CMy are centroid coordinates, not Ixx or Ixx/Cy."
    if inertia_column and inertia_column == section_modulus_column:
        return corrected_data, metrics, "Material properties skipped: Ixx and Ixx/Cy must use separate metadata columns."
    ixx_value = parse_metadata_numeric(metadata_row.get(inertia_column)) if inertia_column else np.nan
    ixx_valid = bool(np.isfinite(ixx_value) and ixx_value > 0)
    ixx_value = float(ixx_value) if ixx_valid else np.nan
    metrics["ixx_mm4"] = ixx_value
    corrected_data["ixx_mm4"] = ixx_value
    ic_value = parse_metadata_numeric(metadata_row.get(section_modulus_column)) if section_modulus_column else np.nan
    if not np.isfinite(ic_value) or ic_value <= 0:
        return corrected_data, metrics, f"Material properties skipped: Ixx/Cy in '{section_modulus_column}' must be finite and > 0 (mm^3)."
    ic_value = float(ic_value)
    # Divide Ixx by the supplied section modulus, never by the centroid CMy.
    c_value = ixx_value / ic_value if ixx_valid else np.nan
    c_valid = bool(np.isfinite(c_value) and c_value > 0)
    c_value = float(c_value) if c_valid else np.nan
    displacement = corrected_data["corrected_displacement_mm"].to_numpy(dtype=float)
    moment = corrected_data["bending_moment_n_mm"].to_numpy(dtype=float)
    stress = moment / ic_value
    strain = (
        calculate_bending_strain(
            displacement,
            c_value,
            geometry,
        )
        if c_valid
        else np.full_like(displacement, np.nan, dtype=float)
    )

    corrected_data["metadata_matched"] = True
    corrected_data["section_modulus_mm3"] = ic_value
    corrected_data["c_mm"] = c_value
    corrected_data["tensile_stress_mpa"] = stress
    corrected_data["tensile_strain"] = strain

    fit_result = {"slope": np.nan, "intercept": np.nan, "r2": np.nan}
    if not conversion_only and "stiffness_region" in corrected_data.columns and corrected_data["stiffness_region"].any():
        region = corrected_data["stiffness_region"].to_numpy(dtype=bool)
        valid_region = region & np.isfinite(strain) & np.isfinite(stress)
        if int(valid_region.sum()) >= 2 and np.ptp(strain[valid_region]) > 0:
            fit_result = fit_linear_region(strain[valid_region], stress[valid_region])
            corrected_data.loc[valid_region, "elastic_modulus_fit_stress_mpa"] = (
                fit_result["slope"] * strain[valid_region] + fit_result["intercept"]
            )

    peak_index = int(np.nanargmax(stress)) if len(stress) else 0
    stress_to_peak = stress[: peak_index + 1]
    strain_to_peak = strain[: peak_index + 1]
    energy_to_max_stress = np.nan
    if c_valid and len(stress_to_peak) > 1 and np.isfinite(strain_to_peak).all():
        energy_to_max_stress = float(np.trapezoid(stress_to_peak, strain_to_peak))
    yield_displacement = float(yield_metrics.get("yield_displacement", np.nan))
    yield_moment = float(yield_metrics.get("yield_moment", np.nan))
    yield_stress = yield_moment / ic_value if np.isfinite(yield_moment) else np.nan
    yield_strain = (
        float(calculate_bending_strain(np.array([yield_displacement]), c_value, geometry)[0])
        if c_valid and np.isfinite(yield_displacement)
        else np.nan
    )

    metadata_id = str(metadata_row.get(metadata_id_column, "")).strip() if metadata_id_column else ""
    metrics = {
        "metadata_matched": True,
        "metadata_id": metadata_id,
        "ixx_mm4": float(ixx_value),
        "material_geometry_source": source,
        "section_modulus_mm3": ic_value,
        "c_mm": c_value,
        "elastic_modulus_mpa": float(fit_result["slope"]),
        "elastic_modulus_r2": float(fit_result["r2"]),
        "yield_stress_mpa": float(yield_stress),
        "ultimate_stress_mpa": float(np.nanmax(stress)),
        "strain_energy_density_to_max_stress_mpa": energy_to_max_stress,
        "strain_at_yield": yield_strain,
        "strain_at_ultimate_stress": float(strain[peak_index]),
        "strain_at_failure": float(strain[-1]) if len(strain) else np.nan,
    }
    warning = ""
    if not c_valid:
        warning = (
            f"Stress metrics were computed from Ixx/Cy, but strain-dependent metrics were skipped: "
            f"Cy = Ixx / (Ixx/Cy) must be finite and > 0. Check Ixx in '{inertia_column}' (mm^4). "
            "Direct material yield also requires valid strain; structural yield remains available."
        )
    return corrected_data, metrics, warning


def fit_linear_region(displacement: np.ndarray, moment: np.ndarray) -> dict[str, float]:
    """Fit M = K*delta + b and return stiffness K plus R^2."""
    if len(displacement) < 2 or np.ptp(displacement) <= 0:
        return {
            "slope": np.nan,
            "intercept": np.nan,
            "r2": np.nan,
        }

    slope, intercept = np.polyfit(displacement, moment, 1)
    fitted = slope * displacement + intercept
    residual_sum_squares = float(np.sum((moment - fitted) ** 2))
    total_sum_squares = float(np.sum((moment - np.mean(moment)) ** 2))
    r2 = 1.0 if total_sum_squares == 0 else 1.0 - residual_sum_squares / total_sum_squares
    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "r2": float(r2),
    }


def select_elastic_stiffness_region(
    corrected_data: pd.DataFrame,
    parameters: StiffnessParameters,
    response_column: str = "bending_moment_n_mm",
    coordinate_column: str = "corrected_displacement_mm",
) -> tuple[pd.DataFrame, dict[str, float], str]:
    """Select a linear pre-peak region in the supplied measurement coordinates."""
    corrected_data = corrected_data.copy()
    corrected_data["stiffness_region"] = False
    corrected_data["stiffness_fit_force_n"] = np.nan

    empty_result = {
        "elastic_stiffness_n_per_mm": np.nan,
        "stiffness_r2": np.nan,
        "stiffness_region_start_displacement": np.nan,
        "stiffness_region_end_displacement": np.nan,
        "stiffness_region_points": 0,
        "stiffness_intercept": np.nan,
        "stiffness_region_source": "",
    }
    if corrected_data.empty:
        return corrected_data, empty_result, "Stiffness fit skipped because corrected data are empty."

    if response_column not in corrected_data:
        return corrected_data, empty_result, f"Stiffness fit skipped because '{response_column}' was unavailable."

    peak_index = int(corrected_data[response_column].astype(float).idxmax())
    pre_peak = corrected_data.loc[:peak_index].copy()
    min_points = max(2, int(parameters.minimum_points))
    if len(pre_peak) < min_points:
        return (
            corrected_data,
            empty_result,
            f"Stiffness fit skipped because fewer than {min_points} pre-peak points were available.",
        )

    x_all = pre_peak[coordinate_column].to_numpy(dtype=float)
    y_all = pre_peak[response_column].to_numpy(dtype=float)

    selected_positions: np.ndarray | None = None
    fit_result: dict[str, float] | None = None
    source = "automatic"
    warning = ""

    if parameters.manual_region_enabled:
        source = "manual"
        lower = min(parameters.manual_start_displacement, parameters.manual_end_displacement)
        upper = max(parameters.manual_start_displacement, parameters.manual_end_displacement)
        selected_positions = np.flatnonzero((x_all >= lower) & (x_all <= upper))
        if len(selected_positions) >= min_points:
            fit_result = fit_linear_region(x_all[selected_positions], y_all[selected_positions])
        else:
            warning = (
                f"Manual stiffness region had fewer than {min_points} pre-peak points; "
                "automatic region selection was used instead."
            )
            selected_positions = None
            source = "automatic"

    if selected_positions is None:
        best_score = None
        best_positions = None
        best_fit = None
        fallback_score = None
        fallback_positions = None
        fallback_fit = None

        max_search_points = max(min_points, int(parameters.max_search_points))
        if len(pre_peak) > max_search_points:
            search_positions = np.unique(
                np.linspace(0, len(pre_peak) - 1, max_search_points).astype(int)
            )
        else:
            search_positions = np.arange(len(pre_peak))

        search_min_points = min(min_points, len(search_positions))
        for start in range(0, len(search_positions) - search_min_points + 1):
            max_end = len(search_positions) - 1
            candidate_ends = np.unique(
                np.linspace(start + search_min_points - 1, max_end, 24).astype(int)
            )
            for end in candidate_ends:
                coarse_positions = search_positions[start : end + 1]
                lower = x_all[coarse_positions[0]]
                upper = x_all[coarse_positions[-1]]
                positions = np.flatnonzero((x_all >= lower) & (x_all <= upper))
                if len(positions) < min_points:
                    continue

                x = x_all[positions]
                y = y_all[positions]
                fit = fit_linear_region(x, y)
                if not np.isfinite(fit["r2"]) or not np.isfinite(fit["slope"]):
                    continue
                if fit["slope"] <= 0:
                    continue

                span = float(x[-1] - x[0])
                score = (fit["r2"], len(positions), span)
                if fallback_score is None or score > fallback_score:
                    fallback_score = score
                    fallback_positions = positions
                    fallback_fit = fit
                if fit["r2"] >= parameters.r2_threshold:
                    if best_score is None or score > best_score:
                        best_score = score
                        best_positions = positions
                        best_fit = fit

        if best_positions is not None:
            selected_positions = best_positions
            fit_result = best_fit
        elif fallback_positions is not None:
            selected_positions = fallback_positions
            fit_result = fallback_fit
            warning = combine_warnings(
                warning,
                (
                    f"No stiffness region met R^2 >= {parameters.r2_threshold:.3f}; "
                    f"best positive-slope region was used with R^2 = {fit_result['r2']:.3f}."
                ),
            )
        else:
            return (
                corrected_data,
                empty_result,
                combine_warnings(warning, "Stiffness fit failed because no positive-slope pre-peak region was found."),
            )

    selected_index = pre_peak.index[selected_positions]
    x_selected = corrected_data.loc[selected_index, coordinate_column].to_numpy(dtype=float)
    fitted_selected = fit_result["slope"] * x_selected + fit_result["intercept"]
    corrected_data.loc[selected_index, "stiffness_region"] = True
    corrected_data.loc[selected_index, "stiffness_fit_force_n"] = fitted_selected

    metrics = {
        "elastic_stiffness_n_per_mm": float(fit_result["slope"]),
        "stiffness_r2": float(fit_result["r2"]),
        "stiffness_region_start_displacement": float(x_selected[0]),
        "stiffness_region_end_displacement": float(x_selected[-1]),
        "stiffness_region_points": int(len(selected_index)),
        "stiffness_intercept": float(fit_result["intercept"]),
        "stiffness_region_source": source,
    }
    return corrected_data, metrics, warning


def smooth_yield_response(response: np.ndarray, window: int) -> np.ndarray:
    """Median-filter the pre-peak segment without flattening its endpoints."""
    smoothed = smooth_force_signal(response, window)
    edge = _odd_window(window, len(response)) // 2
    if edge:
        # Partial median windows bias even a perfectly straight rising curve.
        smoothed[:edge] = response[:edge]
        smoothed[-edge:] = response[-edge:]
    return smoothed


def calculate_offset_yield(
    corrected_data: pd.DataFrame,
    stiffness_metrics: dict[str, float],
    geometry: BendingGeometry,
    parameters: YieldParameters,
) -> tuple[pd.DataFrame, dict[str, float], str]:
    """Find offset yield point from corrected moment-displacement data."""
    corrected_data = corrected_data.copy()
    corrected_data["offset_yield_line_force_n"] = np.nan
    corrected_data["yield_point"] = False

    offset_mm = (
        float(parameters.fixed_offset_mm)
        if parameters.use_fixed_offset
        else 0.01
    )
    empty_metrics = {
        "yield_displacement": np.nan,
        "yield_force": np.nan,
        "yield_moment": np.nan,
        "yield_offset_mm": offset_mm,
        "post_yield_displacement": np.nan,
    }

    slope = float(stiffness_metrics.get("elastic_stiffness_n_per_mm", np.nan))
    intercept = float(stiffness_metrics.get("stiffness_intercept", np.nan))
    stiffness_end = float(stiffness_metrics.get("stiffness_region_end_displacement", np.nan))
    if corrected_data.empty or not np.isfinite(slope) or slope <= 0 or not np.isfinite(intercept) or not np.isfinite(stiffness_end):
        return corrected_data, empty_metrics, "Yield calculation skipped because elastic stiffness fit was unavailable."

    displacement = corrected_data["corrected_displacement_mm"].to_numpy(dtype=float)
    force = corrected_data["force_n"].to_numpy(dtype=float)
    moment = corrected_data["bending_moment_n_mm"].to_numpy(dtype=float)
    if not np.isfinite(displacement).all() or not np.isfinite(moment).all():
        return corrected_data, empty_metrics, "Offset yield requires finite displacement and response values."
    moment_per_force_mm = geometry.moment_per_force_mm
    offset_line = slope * (displacement - offset_mm) + intercept
    corrected_data["offset_yield_line_force_n"] = offset_line

    peak_index = int(np.nanargmax(moment))
    if peak_index <= 0:
        return corrected_data, empty_metrics, "Yield calculation skipped because maximum moment occurred at the first point."

    # Post-peak fracture points must not create a pre-peak intersection through smoothing.
    smoothed_moment = smooth_yield_response(moment[:peak_index + 1], parameters.smoothing_window)
    difference = smoothed_moment - offset_line[:peak_index + 1]
    crossing_index = None
    # Preserve acquisition order; instrument displacement may contain small backsteps.
    for idx in range(1, peak_index + 1):
        if (displacement[idx] > stiffness_end and displacement[idx] > displacement[idx - 1]
                and difference[idx - 1] > 0 and difference[idx] <= 0):
            fraction = difference[idx - 1] / (difference[idx - 1] - difference[idx])
            crossing_displacement = displacement[idx - 1] + fraction * (displacement[idx] - displacement[idx - 1])
            if stiffness_end < crossing_displacement < displacement[peak_index]:
                crossing_index = idx
                break

    if crossing_index is None:
        return (
            corrected_data,
            empty_metrics,
            "Yield point was not found before maximum moment using the offset-yield method.",
        )

    previous_index = max(crossing_index - 1, 0)
    x0 = displacement[previous_index]
    x1 = displacement[crossing_index]
    d0 = difference[previous_index]
    d1 = difference[crossing_index]
    if x1 == x0 or d1 == d0:
        yield_displacement = float(x1)
    else:
        fraction = float(-d0 / (d1 - d0))
        fraction = min(max(fraction, 0.0), 1.0)
        yield_displacement = float(x0 + fraction * (x1 - x0))

    if not stiffness_end < yield_displacement < displacement[peak_index]:
        return corrected_data, empty_metrics, "No offset-yield intersection occurred after the elastic fit and before maximum moment."

    maximum_force = float(np.nanmax(force))
    maximum_moment = float(np.nanmax(moment))
    yield_moment = float(slope * (yield_displacement - offset_mm) + intercept)
    yield_force = (
        float(yield_moment / moment_per_force_mm)
        if moment_per_force_mm > 0 and np.isfinite(yield_moment)
        else np.nan
    )
    cap_warning = ""
    capped_values = []
    if np.isfinite(yield_moment) and np.isfinite(maximum_moment) and yield_moment > maximum_moment:
        yield_moment = maximum_moment
        capped_values.append("yield moment")
    if np.isfinite(yield_force) and np.isfinite(maximum_force) and yield_force > maximum_force:
        yield_force = maximum_force
        capped_values.append("yield force")
    if capped_values:
        verb = "were" if len(capped_values) > 1 else "was"
        noun = "values" if len(capped_values) > 1 else "value"
        cap_warning = (
            f"{' and '.join(capped_values).capitalize()} exceeded the maximum {noun} "
            f"and {verb} capped at the specimen maximum."
        )

    post_yield_displacement = float(
        corrected_data["corrected_displacement_mm"].iloc[peak_index] - yield_displacement
    )

    corrected_data.loc[corrected_data.index[crossing_index], "yield_point"] = True
    metrics = {
        "yield_displacement": yield_displacement,
        "yield_force": yield_force,
        "yield_moment": yield_moment,
        "yield_offset_mm": offset_mm,
        "post_yield_displacement": post_yield_displacement,
    }
    return corrected_data, metrics, cap_warning


def find_proportional_limit(
    displacement: np.ndarray,
    response: np.ndarray,
    stiffness_metrics: dict[str, float],
    parameters: YieldParameters,
) -> tuple[np.ndarray, dict, str]:
    """Operational proportional limit, not a measurement of permanent deformation.

    Response can be force or moment. For prediction P = K*delta + b and r, find
    the first downward crossing of (1-r)*P sustained for the requested number
    of points. Search only after the elastic fit and before the measured peak.
    Multiplicative conversion to stress preserves this fractional criterion.
    """
    reference = np.full(len(displacement), np.nan)
    fraction = parameters.proportional_departure_fraction
    consecutive = parameters.proportional_consecutive_points
    if not np.isfinite(fraction) or not 0 < fraction < 1 or consecutive < 1:
        raise ValueError("Proportional departure must be between 0 and 100%, with at least one confirmation point.")
    slope = float(stiffness_metrics.get("elastic_stiffness_n_per_mm", np.nan))
    intercept = float(stiffness_metrics.get("stiffness_intercept", np.nan))
    fit_end = float(stiffness_metrics.get("stiffness_region_end_displacement", np.nan))
    if not len(displacement) or not np.isfinite([slope, intercept, fit_end]).all() or slope <= 0:
        return reference, {}, "Proportional limit unavailable because a positive elastic stiffness fit was unavailable."
    x = np.asarray(displacement, dtype=float)
    response = np.asarray(response, dtype=float)
    if len(x) != len(response) or not np.isfinite(x).all() or not np.isfinite(response).all():
        return reference, {}, "Proportional limit requires finite displacement and response values."
    peak = int(np.argmax(response))
    prediction = slope * x + intercept
    reference = (1 - fraction) * prediction
    smoothed = smooth_yield_response(response[:peak + 1], parameters.smoothing_window)
    difference = smoothed - reference[:peak + 1]
    for index in range(1, peak - consecutive + 2):
        end = index + consecutive
        if not (x[index] > x[index - 1] and np.all(x[index:end] > fit_end)
                and difference[index - 1] > 0 and np.all(difference[index:end] <= 0)
                and np.all(prediction[index - 1:end] > 0)):
            continue
        weight = difference[index - 1] / (difference[index - 1] - difference[index])
        displacement = float(x[index - 1] + weight * (x[index] - x[index - 1]))
        if not fit_end < displacement < x[peak]:
            continue
        value = float(reference[index - 1] + weight * (reference[index] - reference[index - 1]))
        return reference, {
            "index": index, "displacement": displacement, "response": value,
            "post_yield_displacement": float(x[peak] - displacement),
        }, ""
    return reference, {}, (
        f"Proportional limit not found: no sustained {fraction * 100:g}% departure "
        f"for {consecutive} points after the elastic fit and before the measured peak."
    )


def calculate_proportional_limit(
    corrected_data: pd.DataFrame,
    stiffness_metrics: dict[str, float],
    geometry: BendingGeometry,
    parameters: YieldParameters,
) -> tuple[pd.DataFrame, dict[str, float], str]:
    data = corrected_data.copy()
    data["yield_point"] = False
    reference, point, warning = find_proportional_limit(
        data["corrected_displacement_mm"].to_numpy(dtype=float),
        data["bending_moment_n_mm"].to_numpy(dtype=float), stiffness_metrics, parameters,
    )
    data["yield_reference_moment_n_mm"] = reference
    metrics = {key: np.nan for key in (
        "yield_displacement", "yield_force", "yield_moment", "yield_offset_mm", "post_yield_displacement",
    )}
    if point:
        metrics.update(
            yield_displacement=point["displacement"], yield_moment=point["response"],
            yield_force=point["response"] / geometry.moment_per_force_mm,
            post_yield_displacement=point["post_yield_displacement"],
        )
        data.loc[data.index[point["index"]], "yield_point"] = True
    return data, metrics, warning


def yield_criterion_description(parameters: YieldParameters, offset_mm: float) -> str:
    if parameters.method == "Offset":
        criterion = f"Offset {offset_mm:g} mm"
    else:
        criterion = (
            f"{parameters.proportional_departure_fraction * 100:g}% below elastic prediction; "
            f"{parameters.proportional_consecutive_points} consecutive points"
        )
    return f"{criterion}; rolling median {parameters.smoothing_window} points"


def yield_strain_scale(data: pd.DataFrame, stress_column: str, strain_column: str) -> float:
    """Return strain/mm only when this specimen has a complete material curve."""
    columns = ["corrected_displacement_mm", stress_column, strain_column]
    if not all(column in data for column in columns) or len(data) < 2:
        return np.nan
    values = data[columns].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        return np.nan
    displacement, stress, strain = values.T
    index = int(np.argmax(np.abs(displacement)))
    if displacement[index] == 0 or np.ptp(strain) <= 0 or np.max(stress) <= 0:
        return np.nan
    scale = strain[index] / displacement[index]
    return float(scale) if scale > 0 and np.allclose(strain, displacement * scale) else np.nan


def yield_offset_definitions(summary: pd.DataFrame) -> set[tuple[str, float]]:
    """Compare offset definitions in their selected units, not converted mm."""
    definitions = set()
    for _, row in summary.loc[summary["Yield method"].eq("Offset")].iterrows():
        strain_based = row.get("Yield offset basis") == "strain"
        value = pd.to_numeric(row.get("Yield offset used (%)" if strain_based else "Yield offset used (mm)"), errors="coerce")
        if np.isfinite(value):
            definitions.add(("strain (%)" if strain_based else "displacement (mm)", round(float(value), 12)))
    return definitions


def run_yield_methods(parameters: YieldParameters, offset_mm: float, evaluate, value_key: str,
                      strain_scale: float = np.nan):
    """Try the requested definition first; never replace a successful primary result."""
    if parameters.method not in ("Automatic", "Offset", "Proportional limit"):
        raise ValueError("Unknown yield method.")
    automatic = parameters.method == "Automatic"
    material = np.isfinite(strain_scale) and strain_scale > 0
    if automatic and material:
        # A strain offset is a fraction (0.1% = 0.001), not millimeters.
        # Dividing by strain/mm gives the equivalent structural offset line.
        attempts = [("Offset", .001 / strain_scale, False),
                    ("Offset", .0005 / strain_scale, True),
                    ("Proportional limit", .01, False)]
    elif automatic:
        attempts = [("Proportional limit", .01, False),
                    ("Offset", .01, False), ("Offset", .005, True)]
    else:
        attempts = [(parameters.method, offset_mm, False)]
    if not automatic and parameters.fallback_other_method:
        attempts.append(("Offset" if parameters.method == "Proportional limit" else "Proportional limit", offset_mm, False))
        if parameters.fallback_half_offset and np.isfinite(offset_mm) and offset_mm > 0:
            attempts.append(("Offset", offset_mm / 2, True))
    attempts = [(method, offset, reduced, parameters.proportional_departure_fraction)
                for method, offset, reduced in attempts]
    if automatic and parameters.fallback_lower_proportional_limits:
        # Only relax the selected departure; never retry it or increase it.
        attempts.extend(("Proportional limit", .01, False, departure)
                        for departure in (.05, .025)
                        if departure < parameters.proportional_departure_fraction)
    attempted, warnings = [], []
    for method, attempt_offset, reduced_offset, departure in attempts:
        # Resolve displacement offsets here, including per-specimen strain offsets
        # in tensile tests. Retry exactly once at half the original offset.
        attempt_parameters = replace(parameters, method=method, use_fixed_offset=True,
                                     fixed_offset_mm=attempt_offset, proportional_departure_fraction=departure)
        data, metrics, warning = evaluate(attempt_parameters)
        if automatic and method == "Offset":
            label = (f"Offset ({attempt_offset * strain_scale * 100:g}% strain)" if material
                     else f"Offset ({attempt_offset:g} mm)")
        elif automatic and method == "Proportional limit":
            label = f"Proportional limit ({departure * 100:g}%)"
        else:
            label = f"Offset (half: {attempt_offset:g} mm)" if reduced_offset else method
        attempted.append(label)
        if warning:
            warnings.append(warning)
        if np.isfinite(metrics[value_key]):
            break
    detected = bool(np.isfinite(metrics[value_key]))
    used = method if detected else "Not detected"
    fallback = detected and len(attempted) > 1
    criterion = yield_criterion_description(attempt_parameters, attempt_offset)
    if automatic and material and method == "Offset":
        criterion = (f"Offset {attempt_offset * strain_scale * 100:g}% strain; "
                     f"rolling median {parameters.smoothing_window} points")
    elif reduced_offset and not automatic:
        criterion += f"; half of configured {offset_mm:g} mm offset"
    offset_basis = ("strain" if automatic and material else "displacement") if detected and method == "Offset" else ""
    provenance = dict(
        yield_method=used, yield_requested_method=parameters.method,
        yield_criterion=criterion, yield_fallback_used=fallback,
        yield_reduced_offset_used=detected and reduced_offset,
        yield_attempted_methods=" -> ".join(attempted),
        yield_analysis_basis="Stress-strain" if material else "Structural only",
        yield_offset_basis=offset_basis,
        yield_offset_strain=attempt_offset * strain_scale if offset_basis == "strain" else np.nan,
        yield_proportional_departure_percent=departure * 100 if detected and method == "Proportional limit" else np.nan,
        yield_reduced_proportional_used=detected and method == "Proportional limit" and departure < parameters.proportional_departure_fraction,
    )
    metrics.update(provenance)
    for key, value in provenance.items():
        data[key] = value
    data["yield_reference_method"] = method
    if automatic:
        if not detected:
            metrics["yield_offset_mm"] = np.nan
            warning = combine_warnings(*warnings, "No valid pre-peak yield point met the automatic criteria; yield remains missing.")
        elif fallback:
            warning = combine_warnings(f"Automatic yield fallback: {' -> '.join(attempted)}. Used {label}.", warning)
    elif fallback:
        warning = combine_warnings(
            (f"Neither initial criterion detected yield; Offset at {attempt_offset:g} mm "
             f"(half of {offset_mm:g} mm) supplied the fallback estimate."
             if reduced_offset else f"{parameters.method} did not detect yield; {method} supplied the fallback estimate."), warning,
        )
    elif not detected:
        warning = combine_warnings(*warnings)
        if reduced_offset:
            warning = combine_warnings(warning, f"The half-offset retry ({attempt_offset:g} mm) also did not detect a valid yield point.")
    data["yield_offset_mm"] = metrics.get("yield_offset_mm", np.nan)
    return data, metrics, warning


def calculate_bending_yield(
    corrected_data: pd.DataFrame,
    stiffness_metrics: dict[str, float],
    geometry: BendingGeometry,
    parameters: YieldParameters,
) -> tuple[pd.DataFrame, dict, str]:
    """Select a criterion and retain explicit provenance for alternative estimates."""
    offset = parameters.fixed_offset_mm if parameters.use_fixed_offset else 0.01

    def evaluate(attempt):
        if attempt.method == "Offset":
            data, metrics, warning = calculate_offset_yield(corrected_data, stiffness_metrics, geometry, attempt)
            data["yield_reference_moment_n_mm"] = data["offset_yield_line_force_n"]
            return data, metrics, warning
        return calculate_proportional_limit(corrected_data, stiffness_metrics, geometry, attempt)

    return run_yield_methods(parameters, offset, evaluate, "yield_moment",
                             yield_strain_scale(corrected_data, "tensile_stress_mpa", "tensile_strain"))


def find_material_offset_yield(strain, stress, fit, offset_strain, smoothing_window):
    """Intersect a native stress-strain offset line after the fit and before peak."""
    slope = fit["elastic_stiffness_n_per_mm"]
    intercept = fit["stiffness_intercept"]
    fit_end = fit["stiffness_region_end_displacement"]
    reference = slope * (strain - offset_strain) + intercept
    if not np.isfinite([slope, intercept, fit_end]).all() or slope <= 0:
        return reference, {}, "Stress-strain yield requires a positive elastic modulus fit."
    peak = int(np.argmax(stress))
    smoothed = smooth_yield_response(stress[:peak + 1], smoothing_window)
    difference = smoothed - reference[:peak + 1]
    for index in range(1, peak + 1):
        if not (strain[index] > strain[index - 1] and strain[index] > fit_end
                and difference[index - 1] > 0 and difference[index] <= 0):
            continue
        weight = difference[index - 1] / (difference[index - 1] - difference[index])
        crossing = float(strain[index - 1] + weight * (strain[index] - strain[index - 1]))
        if fit_end < crossing < strain[peak]:
            return reference, {
                "index": index, "displacement": crossing,
                "response": min(float(slope * (crossing - offset_strain) + intercept), float(stress[peak])),
            }, ""
    return reference, {}, "No stress-strain offset intersection occurred after the elastic fit and before maximum stress."


def analyze_stress_strain(
    data: pd.DataFrame,
    stiffness_parameters: StiffnessParameters,
    yield_parameters: YieldParameters,
    stress_column: str,
    strain_column: str,
    offset_mm: float,
) -> tuple[pd.DataFrame, dict, dict, str]:
    """Fit and measure material properties directly, independently of structural fits.

    The shared region search operates on stress and strain here. Its legacy
    metric names are internal only; native material coordinates are exported
    explicitly. Displacement conversion is used only for manual bounds/offsets
    and for mapping the resulting yield point back to the structural display.
    """
    data = data.copy()
    scale = yield_strain_scale(data, stress_column, strain_column)
    if not np.isfinite(scale):
        raise ValueError("Direct material analysis requires a complete finite stress-strain curve.")
    strain = data[strain_column].to_numpy(dtype=float)
    stress = data[stress_column].to_numpy(dtype=float)
    native_parameters = replace(
        stiffness_parameters,
        manual_start_displacement=stiffness_parameters.manual_start_displacement * scale,
        manual_end_displacement=stiffness_parameters.manual_end_displacement * scale,
    )
    native_fit, fit, fit_warning = select_elastic_stiffness_region(
        data, native_parameters, response_column=stress_column, coordinate_column=strain_column,
    )
    data["modulus_region"] = native_fit["stiffness_region"]
    data["elastic_modulus_fit_stress_mpa"] = native_fit["stiffness_fit_force_n"]
    if stress_column == "engineering_stress_mpa":
        data["elastic_modulus_fit_mpa"] = data["elastic_modulus_fit_stress_mpa"]
    data["material_analysis_basis"] = "Direct stress-strain"
    data["modulus_fit_start_strain"] = fit["stiffness_region_start_displacement"]
    data["modulus_fit_end_strain"] = fit["stiffness_region_end_displacement"]
    data["modulus_fit_intercept_mpa"] = fit["stiffness_intercept"]
    data["modulus_fit_r2"] = fit["stiffness_r2"]
    data["modulus_fit_region_source"] = fit["stiffness_region_source"]
    peak = int(np.argmax(stress))
    data["material_peak_point"] = np.arange(len(data)) == peak
    data["material_smoothed_stress_mpa"] = np.nan
    data.loc[data.index[:peak + 1], "material_smoothed_stress_mpa"] = smooth_yield_response(
        stress[:peak + 1], yield_parameters.smoothing_window,
    )

    def evaluate(attempt):
        output = data.copy()
        if attempt.method == "Offset":
            reference, point, warning = find_material_offset_yield(
                strain, stress, fit, attempt.fixed_offset_mm * scale, attempt.smoothing_window,
            )
        else:
            reference, point, warning = find_proportional_limit(strain, stress, fit, attempt)
        output["yield_reference_stress_mpa"] = reference
        output["yield_point"] = False
        result = {
            "yield_stress_mpa": np.nan, "strain_at_yield": np.nan,
            "yield_displacement": np.nan, "post_yield_displacement": np.nan,
            "yield_offset_mm": attempt.fixed_offset_mm if attempt.method == "Offset" else np.nan,
        }
        if point:
            output.loc[output.index[point["index"]], "yield_point"] = True
            result.update(
                yield_stress_mpa=point["response"], strain_at_yield=point["displacement"],
                yield_displacement=point["displacement"] / scale,
                post_yield_displacement=(strain[peak] - point["displacement"]) / scale,
            )
        return output, result, warning

    data, yielded, yield_warning = run_yield_methods(
        yield_parameters, offset_mm, evaluate, "yield_stress_mpa", scale,
    )
    energy = float(np.trapezoid(stress[:peak + 1], strain[:peak + 1])) if peak else 0.0
    material = {
        "elastic_modulus_mpa": fit["elastic_stiffness_n_per_mm"],
        "elastic_modulus_r2": fit["stiffness_r2"],
        "yield_stress_mpa": yielded["yield_stress_mpa"],
        "ultimate_stress_mpa": float(stress[peak]),
        "strain_energy_density_to_max_stress_mpa": energy,
        "strain_energy_density_mj_m3": energy,
        "strain_at_yield": yielded["strain_at_yield"],
        "strain_at_ultimate_stress": float(strain[peak]),
        "strain_at_failure": float(strain[-1]),
    }
    return data, material, yielded, combine_warnings(
        fit_warning.replace("Stiffness", "Modulus").replace("stiffness", "modulus"), yield_warning,
    )


def correct_single_specimen(
    raw_data: pd.DataFrame,
    parameters: OnsetParameters,
    trim_post_peak: bool = False,
    post_peak_drop_fraction: float = 0.20,
) -> tuple[pd.DataFrame, int, float, float, float, int, str]:
    """Detect onset, zero both axes, then optionally trim one specimen's tail."""
    displacement = raw_data["displacement_mm"].to_numpy(dtype=float)
    force = raw_data["force_n"].to_numpy(dtype=float)
    onset_index, warning = detect_loading_onset(displacement, force, parameters)
    corrected_data = correct_curve(displacement, force, onset_index)
    onset_displacement = float(displacement[onset_index])
    onset_force = float(force[onset_index])
    maximum_force = float(corrected_data["force_n"].max()) if not corrected_data.empty else np.nan
    post_peak_points_removed = 0

    if trim_post_peak:
        corrected_data, post_peak_points_removed, maximum_force, _, trim_warning = (
            trim_after_force_drop(corrected_data, post_peak_drop_fraction)
        )
        warning = combine_warnings(warning, trim_warning)

    return (
        corrected_data,
        onset_index,
        onset_displacement,
        onset_force,
        maximum_force,
        post_peak_points_removed,
        warning,
    )


def make_unique_display_id(specimen_id: str, file_name: str, used_ids: set[str]) -> str:
    base = specimen_id or Path(file_name).stem or "Unknown specimen"
    if base not in used_ids:
        used_ids.add(base)
        return base

    file_stem = Path(file_name).stem
    candidate = f"{base} ({file_stem})"
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base} ({file_stem} {suffix})"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def empty_processed_specimen(
    file_name: str,
    specimen_id: str,
    display_id: str,
    geometry: BendingGeometry,
    trim_post_peak: bool,
    post_peak_drop_fraction: float,
    yield_parameters: YieldParameters,
    warning: str = "",
    error: str = "",
    label_source: str = "",
    metadata_match_method: str = "",
    metadata_id: str = "",
) -> ProcessedSpecimen:
    return ProcessedSpecimen(
        specimen_id=specimen_id,
        display_id=display_id,
        file_name=file_name,
        original_points=0,
        retained_points=0,
        removed_points=0,
        onset_index=0,
        onset_displacement=np.nan,
        onset_force=np.nan,
        maximum_force=np.nan,
        displacement_at_maximum_force=np.nan,
        maximum_moment=np.nan,
        displacement_at_maximum_moment=np.nan,
        work_to_maximum_force=np.nan,
        elastic_stiffness_n_per_mm=np.nan,
        stiffness_r2=np.nan,
        stiffness_region_start_displacement=np.nan,
        stiffness_region_end_displacement=np.nan,
        stiffness_region_points=0,
        stiffness_region_source="",
        yield_displacement=np.nan,
        yield_force=np.nan,
        yield_moment=np.nan,
        yield_offset_mm=np.nan,
        yield_requested_method=yield_parameters.method,
        post_yield_displacement=np.nan,
        metadata_matched=False,
        metadata_id=metadata_id,
        genotype="",
        age="",
        sex="",
        elastic_modulus_mpa=np.nan,
        elastic_modulus_r2=np.nan,
        yield_stress_mpa=np.nan,
        ultimate_stress_mpa=np.nan,
        strain_energy_density_to_max_stress_mpa=np.nan,
        strain_at_yield=np.nan,
        strain_at_ultimate_stress=np.nan,
        strain_at_failure=np.nan,
        post_peak_drop_percent=(post_peak_drop_fraction * 100.0 if trim_post_peak else 0.0),
        post_peak_points_removed=0,
        section_modulus_mm3=np.nan,
        c_mm=np.nan,
        geometry=geometry,
        subtract_baseline=False,
        metadata={},
        raw_data=pd.DataFrame(),
        corrected_data=pd.DataFrame(),
        label_source=label_source,
        metadata_match_method=metadata_match_method,
        warning=warning,
        error=error,
    )


def process_file(
    uploaded_file,
    parameters: OnsetParameters,
    stiffness_parameters: StiffnessParameters,
    yield_parameters: YieldParameters,
    trim_post_peak: bool,
    post_peak_drop_fraction: float,
    geometry: BendingGeometry,
    used_ids: set[str],
    metadata_lookup: dict[str, dict[str, list[dict[str, str]]]] | None = None,
    metadata_filter_required: bool = False,
    metadata_id_column: str | None = None,
    genotype_column: str | None = None,
    age_column: str | None = None,
    sex_column: str | None = None,
    section_modulus_column: str | None = None,
    inertia_column: str | None = None,
) -> ProcessedSpecimen:
    file_name = getattr(uploaded_file, "name", "uploaded_file.csv")
    identity = None
    display_id = ""
    try:
        geometry.validate()
        df = load_test_data_file(uploaded_file)
        identity = resolve_specimen_identity(df, file_name, metadata_lookup, metadata_id_column)
        if identity.error:
            raise ValueError(identity.error)
        specimen_id = identity.specimen_id
        display_id = make_unique_display_id(identity.display_label, file_name, used_ids)
        metadata_row = identity.metadata_row
        metadata_match_method = identity.match_method
        if metadata_filter_required and metadata_row is None:
            skip_message = (
                f"Skipped because metadata match was ambiguous ({metadata_match_method})."
                if metadata_match_method.startswith("ambiguous")
                else "Skipped because this specimen was not found in the uploaded metadata file."
            )
            return empty_processed_specimen(
                file_name,
                specimen_id,
                display_id,
                geometry,
                trim_post_peak,
                post_peak_drop_fraction,
                yield_parameters,
                error=skip_message,
                warning=identity.warning,
                label_source=identity.source,
                metadata_match_method=metadata_match_method,
            )

        raw_data = extract_force_displacement_data(df)
        (
            corrected_data,
            onset_index,
            onset_displacement,
            onset_force,
            maximum_force,
            post_peak_points_removed,
            warning,
        ) = (
            correct_single_specimen(
                raw_data,
                parameters,
                trim_post_peak,
                post_peak_drop_fraction,
            )
        )
        corrected_data = add_bending_moment(
            corrected_data,
            geometry,
        )
        peak_metrics = extract_peak_metrics(corrected_data)
        corrected_data, stiffness_metrics, stiffness_warning = select_elastic_stiffness_region(
            corrected_data,
            stiffness_parameters,
        )
        warning = combine_warnings(warning, stiffness_warning)
        corrected_data, material_metrics, material_warning = apply_material_properties(
            corrected_data,
            metadata_row,
            metadata_id_column,
            section_modulus_column,
            stiffness_metrics,
            {},
            geometry,
            inertia_column,
            conversion_only=True,
        )
        section_modulus = material_metrics["section_modulus_mm3"]
        if np.isfinite(yield_strain_scale(corrected_data, "tensile_stress_mpa", "tensile_strain")):
            corrected_data, direct_material, yield_metrics, yield_warning = analyze_stress_strain(
                corrected_data, stiffness_parameters, yield_parameters,
                "tensile_stress_mpa", "tensile_strain",
                yield_parameters.fixed_offset_mm if yield_parameters.use_fixed_offset else .01,
            )
            material_metrics.update(direct_material)
            # Material yield is authoritative; transform it back for structural displays.
            yield_metrics["yield_moment"] = yield_metrics["yield_stress_mpa"] * section_modulus
            yield_metrics["yield_force"] = yield_metrics["yield_moment"] / geometry.moment_per_force_mm
            corrected_data["yield_reference_moment_n_mm"] = corrected_data["yield_reference_stress_mpa"] * section_modulus
            corrected_data["offset_yield_line_force_n"] = corrected_data["yield_reference_moment_n_mm"]
        else:
            corrected_data, yield_metrics, yield_warning = calculate_bending_yield(
                corrected_data, stiffness_metrics, geometry, yield_parameters,
            )
        warning = combine_warnings(warning, yield_warning)
        if metadata_lookup and metadata_row is None:
            material_warning = combine_warnings(
                material_warning,
                (
                    f"Metadata match was ambiguous ({metadata_match_method}); material properties were skipped."
                    if metadata_match_method.startswith("ambiguous")
                    else "No matching metadata row was found for this specimen; material properties were skipped."
                ),
            )
        elif metadata_match_method.startswith("unique numeric"):
            material_warning = combine_warnings(
                material_warning,
                f"Metadata matched by {metadata_match_method}.",
            )
        warning = combine_warnings(warning, material_warning, identity.warning)
        corrected_data.insert(0, "file_name", file_name)
        corrected_data.insert(0, "specimen_id", display_id)
        corrected_data["original_specimen_id"] = specimen_id
        corrected_data["specimen_label_source"] = identity.source
        corrected_data["metadata_id"] = identity.metadata_id
        corrected_data["metadata_match_method"] = metadata_match_method
        metadata_export = metadata_row or {}
        genotype_value = metadata_value_from_selected_or_keywords(
            metadata_export,
            genotype_column,
            ["genotype", "strain", "group"],
        )
        age_value = metadata_value_from_selected_or_keywords(
            metadata_export,
            age_column,
            ["age", "weeks", "month"],
        )
        sex_value = metadata_value_from_selected_or_keywords(
            metadata_export,
            sex_column,
            ["sex", "gender"],
        )
        corrected_data["genotype"] = genotype_value
        corrected_data["age"] = age_value
        corrected_data["sex"] = sex_value
        for column, value in metadata_export.items():
            corrected_data[f"metadata_{column}"] = value
        raw_output_data = raw_data.copy()
        raw_output_data.insert(0, "file_name", file_name)
        raw_output_data.insert(0, "specimen_id", display_id)
        raw_output_data["original_specimen_id"] = specimen_id
        raw_output_data["bending_test"] = geometry.test_type
        raw_output_data["loading_span_l_mm"] = geometry.effective_loading_span_mm
        raw_output_data["support_span_s_mm"] = geometry.support_span_mm
        raw_output_data["displacement_measurement_location"] = geometry.effective_displacement_location

        return ProcessedSpecimen(
            specimen_id=specimen_id,
            display_id=display_id,
            file_name=file_name,
            original_points=len(raw_data),
            retained_points=len(corrected_data),
            removed_points=onset_index,
            onset_index=onset_index,
            onset_displacement=onset_displacement,
            onset_force=onset_force,
            maximum_force=peak_metrics["maximum_force"],
            displacement_at_maximum_force=peak_metrics["displacement_at_maximum_force"],
            maximum_moment=peak_metrics["maximum_moment"],
            displacement_at_maximum_moment=peak_metrics["displacement_at_maximum_moment"],
            work_to_maximum_force=peak_metrics["work_to_maximum_force"],
            elastic_stiffness_n_per_mm=stiffness_metrics["elastic_stiffness_n_per_mm"],
            stiffness_r2=stiffness_metrics["stiffness_r2"],
            stiffness_region_start_displacement=stiffness_metrics["stiffness_region_start_displacement"],
            stiffness_region_end_displacement=stiffness_metrics["stiffness_region_end_displacement"],
            stiffness_region_points=stiffness_metrics["stiffness_region_points"],
            stiffness_region_source=stiffness_metrics["stiffness_region_source"],
            yield_displacement=yield_metrics["yield_displacement"],
            yield_force=yield_metrics["yield_force"],
            yield_moment=yield_metrics["yield_moment"],
            yield_offset_mm=yield_metrics["yield_offset_mm"],
            yield_method=yield_metrics["yield_method"],
            yield_requested_method=yield_metrics["yield_requested_method"],
            yield_criterion=yield_metrics["yield_criterion"],
            yield_fallback_used=yield_metrics["yield_fallback_used"],
            yield_reduced_offset_used=yield_metrics["yield_reduced_offset_used"],
            yield_attempted_methods=yield_metrics["yield_attempted_methods"],
            yield_analysis_basis=yield_metrics["yield_analysis_basis"],
            yield_offset_basis=yield_metrics["yield_offset_basis"],
            yield_offset_strain=yield_metrics["yield_offset_strain"],
            yield_proportional_departure_percent=yield_metrics["yield_proportional_departure_percent"],
            yield_reduced_proportional_used=yield_metrics["yield_reduced_proportional_used"],
            post_yield_displacement=yield_metrics["post_yield_displacement"],
            metadata_matched=bool(material_metrics["metadata_matched"]),
            metadata_id=identity.metadata_id,
            genotype=genotype_value,
            age=age_value,
            sex=sex_value,
            section_modulus_mm3=float(material_metrics["section_modulus_mm3"]),
            ixx_mm4=float(material_metrics["ixx_mm4"]),
            material_geometry_source=str(material_metrics["material_geometry_source"]),
            c_mm=float(material_metrics["c_mm"]),
            geometry=geometry,
            elastic_modulus_mpa=float(material_metrics["elastic_modulus_mpa"]),
            elastic_modulus_r2=float(material_metrics["elastic_modulus_r2"]),
            yield_stress_mpa=float(material_metrics["yield_stress_mpa"]),
            ultimate_stress_mpa=float(material_metrics["ultimate_stress_mpa"]),
            strain_energy_density_to_max_stress_mpa=float(material_metrics["strain_energy_density_to_max_stress_mpa"]),
            strain_at_yield=float(material_metrics["strain_at_yield"]),
            strain_at_ultimate_stress=float(material_metrics["strain_at_ultimate_stress"]),
            strain_at_failure=float(material_metrics["strain_at_failure"]),
            post_peak_drop_percent=(post_peak_drop_fraction * 100.0 if trim_post_peak else 0.0),
            post_peak_points_removed=post_peak_points_removed,
            subtract_baseline=True,
            metadata=metadata_export,
            raw_data=raw_output_data,
            corrected_data=corrected_data,
            label_source=identity.source,
            metadata_match_method=metadata_match_method,
            warning=warning,
        )
    except Exception as exc:
        fallback_id = display_id or make_unique_display_id(Path(file_name).stem, file_name, used_ids)
        return empty_processed_specimen(
            file_name,
            identity.specimen_id if identity else "",
            fallback_id,
            geometry,
            trim_post_peak,
            post_peak_drop_fraction,
            yield_parameters,
            error=str(exc),
            label_source=identity.source if identity else "",
            metadata_match_method=identity.match_method if identity else "",
            metadata_id=identity.metadata_id if identity else "",
        )


def calculate_tendon_offset_yield(
    corrected_data: pd.DataFrame,
    stiffness_metrics: dict[str, float],
    offset_mm: float,
    smoothing_window: int,
    allow_peak_fallback: bool = True,
) -> tuple[pd.DataFrame, dict[str, float], str]:
    """Find offset yield, using the measured peak if no intersection is found."""
    data = corrected_data.copy()
    data["tendon_offset_yield_line_n"] = np.nan
    data["tendon_yield_point"] = False
    data["tendon_yield_peak_fallback"] = False
    empty = {
        "yield_displacement": np.nan,
        "yield_force": np.nan,
        "yield_offset_mm": float(offset_mm),
        "post_yield_displacement": np.nan,
    }
    slope = float(stiffness_metrics.get("elastic_stiffness_n_per_mm", np.nan))
    intercept = float(stiffness_metrics.get("stiffness_intercept", np.nan))
    stiffness_end = float(stiffness_metrics.get("stiffness_region_end_displacement", np.nan))
    if data.empty or not np.isfinite([slope, intercept, stiffness_end]).all() or slope <= 0:
        return data, empty, "Yield calculation skipped because tensile stiffness was unavailable."

    displacement = data["corrected_displacement_mm"].to_numpy(dtype=float)
    force = data["force_n"].to_numpy(dtype=float)
    if not np.isfinite(displacement).all() or not np.isfinite(force).all():
        return data, empty, "Offset yield requires finite displacement and response values."
    offset_line = slope * (displacement - float(offset_mm)) + intercept
    data["tendon_offset_yield_line_n"] = offset_line
    peak_index = int(np.nanargmax(force))
    if peak_index <= 0:
        return data, empty, "Yield calculation skipped because maximum force occurred at the first point."

    difference = smooth_yield_response(force[:peak_index + 1], smoothing_window) - offset_line[:peak_index + 1]
    crossing_index = None
    for idx in range(1, peak_index + 1):
        if (displacement[idx] > displacement[idx - 1] and difference[idx - 1] > 0
                and difference[idx] <= 0):
            fraction = difference[idx - 1] / (difference[idx - 1] - difference[idx])
            crossing_displacement = displacement[idx - 1] + fraction * (displacement[idx] - displacement[idx - 1])
            if stiffness_end < crossing_displacement < displacement[peak_index]:
                crossing_index = idx
                break
    if crossing_index is None:
        if not allow_peak_fallback:
            return data, empty, "Offset yield was not detected before maximum force."
        data.loc[data.index[peak_index], "tendon_yield_point"] = True
        data.loc[data.index[peak_index], "tendon_yield_peak_fallback"] = True
        return data, {
            "yield_displacement": float(displacement[peak_index]),
            "yield_force": float(force[peak_index]),
            "yield_offset_mm": float(offset_mm),
            "post_yield_displacement": 0.0,
        }, (
            "No offset-yield intersection was found before maximum force. "
            "Yield force and displacement were assigned the maximum force and its "
            "corresponding displacement (peak fallback, not a detected yield point)."
        )

    previous_index = max(0, crossing_index - 1)
    x0, x1 = displacement[previous_index], displacement[crossing_index]
    d0, d1 = difference[previous_index], difference[crossing_index]
    if x1 == x0 or d1 == d0:
        yield_displacement = float(x1)
    else:
        fraction = min(max(float(-d0 / (d1 - d0)), 0.0), 1.0)
        yield_displacement = float(x0 + fraction * (x1 - x0))
    yield_force = float(slope * (yield_displacement - offset_mm) + intercept)
    maximum_force = float(np.nanmax(force))
    warning = ""
    if yield_force > maximum_force:
        yield_force = maximum_force
        warning = "Yield force exceeded maximum force and was capped at the specimen maximum."
    yield_force = max(0.0, yield_force)
    post_yield_displacement = max(
        0.0, float(displacement[peak_index] - yield_displacement)
    )
    data.loc[data.index[crossing_index], "tendon_yield_point"] = True
    return data, {
        "yield_displacement": yield_displacement,
        "yield_force": yield_force,
        "yield_offset_mm": float(offset_mm),
        "post_yield_displacement": post_yield_displacement,
    }, warning


def _calculate_tendon_yield_method(
    corrected_data: pd.DataFrame,
    stiffness_metrics: dict[str, float],
    offset_mm: float,
    parameters: YieldParameters,
) -> tuple[pd.DataFrame, dict, str]:
    if parameters.method == "Offset":
        data, metrics, warning = calculate_tendon_offset_yield(
            corrected_data, stiffness_metrics, offset_mm, parameters.smoothing_window,
            allow_peak_fallback=False,
        )
        data["tendon_yield_reference_n"] = data["tendon_offset_yield_line_n"]
        used = "Peak fallback" if data["tendon_yield_peak_fallback"].any() else "Offset"
    elif parameters.method == "Proportional limit":
        data = corrected_data.copy()
        reference, point, warning = find_proportional_limit(
            data["corrected_displacement_mm"].to_numpy(dtype=float),
            data["force_n"].to_numpy(dtype=float), stiffness_metrics, parameters,
        )
        data["tendon_yield_reference_n"] = reference
        data["tendon_yield_point"] = False
        data["tendon_yield_peak_fallback"] = False
        metrics = {key: np.nan for key in (
            "yield_displacement", "yield_force", "yield_offset_mm", "post_yield_displacement",
        )}
        if point:
            metrics.update(
                yield_displacement=point["displacement"], yield_force=point["response"],
                post_yield_displacement=point["post_yield_displacement"],
            )
            data.loc[data.index[point["index"]], "tendon_yield_point"] = True
        used = "Proportional limit"
    else:
        raise ValueError("Unknown tensile yield method.")
    if not np.isfinite(metrics["yield_force"]):
        used = "Not detected"
    criterion = yield_criterion_description(parameters, offset_mm)
    metrics.update(yield_method=used, yield_requested_method=parameters.method, yield_criterion=criterion)
    data["yield_method"] = used
    data["yield_requested_method"] = parameters.method
    data["yield_criterion"] = criterion
    return data, metrics, warning


def calculate_tendon_yield(
    corrected_data: pd.DataFrame,
    stiffness_metrics: dict[str, float],
    offset_mm: float,
    parameters: YieldParameters,
) -> tuple[pd.DataFrame, dict, str]:
    return run_yield_methods(
        parameters, offset_mm,
        lambda attempt: _calculate_tendon_yield_method(corrected_data, stiffness_metrics, attempt.fixed_offset_mm, attempt),
        "yield_force", yield_strain_scale(corrected_data, "engineering_stress_mpa", "engineering_strain"),
    )


def apply_tendon_material_properties(
    corrected_data: pd.DataFrame,
    stiffness_metrics: dict[str, float],
    yield_metrics: dict[str, float],
    area_mm2: float,
    gauge_length_mm: float,
    conversion_only: bool = False,
) -> tuple[pd.DataFrame, dict[str, float], str]:
    """Convert corrected tensile force and extension to engineering stress-strain."""
    data = corrected_data.copy()
    for column in ("engineering_stress_mpa", "engineering_strain", "elastic_modulus_fit_mpa"):
        data[column] = np.nan
    empty = {
        "elastic_modulus_mpa": np.nan,
        "elastic_modulus_r2": np.nan,
        "yield_stress_mpa": np.nan,
        "ultimate_stress_mpa": np.nan,
        "strain_energy_density_mj_m3": np.nan,
        "strain_at_yield": np.nan,
        "strain_at_ultimate_stress": np.nan,
        "strain_at_failure": np.nan,
    }
    if not np.isfinite(area_mm2) or area_mm2 <= 0 or not np.isfinite(gauge_length_mm) or gauge_length_mm <= 0:
        return data, empty, "Material properties require positive cross-sectional area and initial gauge length."

    force = data["force_n"].to_numpy(dtype=float)
    displacement = data["corrected_displacement_mm"].to_numpy(dtype=float)
    stress = force / area_mm2
    strain = displacement / gauge_length_mm
    data["engineering_stress_mpa"] = stress
    data["engineering_strain"] = strain

    modulus_fit = {"slope": np.nan, "intercept": np.nan, "r2": np.nan}
    if not conversion_only and "stiffness_region" in data and data["stiffness_region"].any():
        region = data["stiffness_region"].to_numpy(dtype=bool)
        if int(region.sum()) >= 2 and np.ptp(strain[region]) > 0:
            modulus_fit = fit_linear_region(strain[region], stress[region])
            data.loc[region, "elastic_modulus_fit_mpa"] = (
                modulus_fit["slope"] * strain[region] + modulus_fit["intercept"]
            )

    peak_index = int(np.nanargmax(stress))
    energy = (
        float(np.trapezoid(stress[: peak_index + 1], strain[: peak_index + 1]))
        if peak_index >= 1 else 0.0
    )
    yield_force = float(yield_metrics.get("yield_force", np.nan))
    yield_displacement = float(yield_metrics.get("yield_displacement", np.nan))
    return data, {
        "elastic_modulus_mpa": float(modulus_fit["slope"]),
        "elastic_modulus_r2": float(modulus_fit["r2"]),
        "yield_stress_mpa": float(yield_force / area_mm2) if np.isfinite(yield_force) else np.nan,
        "ultimate_stress_mpa": float(stress[peak_index]),
        "strain_energy_density_mj_m3": energy,
        "strain_at_yield": float(yield_displacement / gauge_length_mm) if np.isfinite(yield_displacement) else np.nan,
        "strain_at_ultimate_stress": float(strain[peak_index]),
        "strain_at_failure": float(strain[-1]),
    }, ""


def empty_tendon_specimen(
    file_name: str,
    display_id: str,
    error: str,
    warning: str = "",
    identity=None,
) -> TendonProcessedSpecimen:
    nan = np.nan
    return TendonProcessedSpecimen(
        specimen_id=identity.specimen_id if identity else "", display_id=display_id, file_name=file_name,
        original_points=0, retained_points=0, onset_index=0,
        onset_displacement=nan, onset_force=nan, maximum_force=nan,
        displacement_at_maximum_force=nan, work_to_maximum_force_mj=nan,
        tensile_stiffness_n_per_mm=nan, stiffness_r2=nan,
        stiffness_region_start_displacement=nan, stiffness_region_end_displacement=nan,
        stiffness_region_points=0, stiffness_region_source="",
        yield_displacement=nan, yield_force=nan, yield_offset_mm=nan,
        post_yield_displacement=nan, cross_sectional_area_mm2=nan,
        gauge_length_mm=nan, elastic_modulus_mpa=nan, elastic_modulus_r2=nan,
        yield_stress_mpa=nan, ultimate_stress_mpa=nan,
        strain_energy_density_mj_m3=nan, strain_at_yield=nan,
        strain_at_ultimate_stress=nan, strain_at_failure=nan,
        metadata_matched=bool(identity and identity.metadata_row is not None),
        metadata_id=identity.metadata_id if identity else "", genotype="", age="", sex="",
        metadata={}, raw_data=pd.DataFrame(), corrected_data=pd.DataFrame(),
        label_source=identity.source if identity else "",
        metadata_match_method=identity.match_method if identity else "",
        warning=warning, error=error,
    )


def process_tendon_file(
    uploaded_file,
    parameters: OnsetParameters,
    stiffness_parameters: StiffnessParameters,
    yield_parameters: YieldParameters,
    trim_post_peak: bool,
    post_peak_drop_fraction: float,
    used_ids: set[str],
    metadata_lookup=None,
    metadata_filter_required: bool = False,
    metadata_id_column: str | None = None,
    genotype_column: str | None = None,
    age_column: str | None = None,
    sex_column: str | None = None,
    area_column: str | None = None,
    gauge_column: str | None = None,
    use_strain_offset: bool = False,
    strain_offset_fraction: float = 0.001,
) -> TendonProcessedSpecimen:
    file_name = getattr(uploaded_file, "name", "uploaded_file.csv")
    identity = None
    display_id = ""
    try:
        df = load_test_data_file(uploaded_file)
        identity = resolve_specimen_identity(df, file_name, metadata_lookup, metadata_id_column)
        if identity.error:
            raise ValueError(identity.error)
        display_id = make_unique_display_id(identity.display_label, file_name, used_ids)
        metadata_row = identity.metadata_row
        if metadata_filter_required and metadata_row is None:
            reason = identity.match_method or "no matching metadata ID"
            return empty_tendon_specimen(
                file_name, display_id,
                f"Skipped because this specimen was not uniquely matched to metadata ({reason}).",
                identity.warning, identity=identity,
            )

        raw_data = extract_force_displacement_data(df)
        corrected, onset_index, onset_displacement, onset_force, _, removed, warning = correct_single_specimen(
            raw_data, parameters, trim_post_peak, post_peak_drop_fraction,
        )
        force = corrected["force_n"].to_numpy(dtype=float)
        displacement = corrected["corrected_displacement_mm"].to_numpy(dtype=float)
        peak_index = int(np.nanargmax(force))
        maximum_force = float(force[peak_index])
        displacement_at_maximum = float(displacement[peak_index])
        work_to_maximum = (
            float(np.trapezoid(force[: peak_index + 1], displacement[: peak_index + 1]))
            if peak_index >= 1 else 0.0
        )
        corrected, stiffness, stiffness_warning = select_elastic_stiffness_region(
            corrected, stiffness_parameters, response_column="force_n",
        )
        warning = combine_warnings(warning, stiffness_warning)

        metadata_export = metadata_row or {}
        area = parse_metadata_numeric(metadata_export.get(area_column)) if area_column else np.nan
        gauge = parse_metadata_numeric(metadata_export.get(gauge_column)) if gauge_column else np.nan
        offset_mm = (
            float(strain_offset_fraction * gauge)
            if use_strain_offset and np.isfinite(gauge) and gauge > 0
            else float(yield_parameters.fixed_offset_mm)
        )
        corrected, material, material_warning = apply_tendon_material_properties(
            corrected, stiffness, {}, area, gauge, conversion_only=True,
        )
        if np.isfinite(yield_strain_scale(corrected, "engineering_stress_mpa", "engineering_strain")):
            corrected, direct_material, yield_metrics, yield_warning = analyze_stress_strain(
                corrected, stiffness_parameters, yield_parameters,
                "engineering_stress_mpa", "engineering_strain", offset_mm,
            )
            material.update(direct_material)
            yield_metrics["yield_force"] = yield_metrics["yield_stress_mpa"] * area
            corrected["tendon_yield_reference_n"] = corrected["yield_reference_stress_mpa"] * area
            corrected["offset_yield_line_force_n"] = corrected["tendon_yield_reference_n"]
        else:
            corrected, yield_metrics, yield_warning = calculate_tendon_yield(
                corrected, stiffness, offset_mm, yield_parameters,
            )
        if yield_parameters.method != "Automatic" and "Offset" in yield_metrics["yield_attempted_methods"] and use_strain_offset and (not np.isfinite(gauge) or gauge <= 0):
            warning = combine_warnings(warning, "The strain offset required gauge length; the fixed displacement offset was used instead.")
        warning = combine_warnings(warning, yield_warning)
        if metadata_row is None or not area_column or not gauge_column:
            material_warning = ""
        warning = combine_warnings(warning, material_warning, identity.warning)

        genotype = metadata_value_from_selected_or_keywords(metadata_export, genotype_column, ["genotype", "strain", "group"])
        age = metadata_value_from_selected_or_keywords(metadata_export, age_column, ["age", "weeks", "month"])
        sex = metadata_value_from_selected_or_keywords(metadata_export, sex_column, ["sex", "gender"])
        corrected.insert(0, "file_name", file_name)
        corrected.insert(0, "specimen_id", display_id)
        corrected["original_specimen_id"] = identity.specimen_id
        corrected["specimen_label_source"] = identity.source
        corrected["metadata_id"] = identity.metadata_id
        corrected["metadata_match_method"] = identity.match_method
        corrected["genotype"], corrected["age"], corrected["sex"] = genotype, age, sex
        corrected["cross_sectional_area_mm2"] = area
        corrected["initial_gauge_length_mm"] = gauge
        for column, value in metadata_export.items():
            corrected[f"metadata_{column}"] = value
        raw_output = raw_data.copy()
        raw_output.insert(0, "file_name", file_name)
        raw_output.insert(0, "specimen_id", display_id)

        return TendonProcessedSpecimen(
            specimen_id=identity.specimen_id, display_id=display_id, file_name=file_name,
            original_points=len(raw_data), retained_points=len(corrected),
            onset_index=onset_index, onset_displacement=onset_displacement,
            onset_force=onset_force, maximum_force=maximum_force,
            displacement_at_maximum_force=displacement_at_maximum,
            work_to_maximum_force_mj=work_to_maximum,
            tensile_stiffness_n_per_mm=stiffness["elastic_stiffness_n_per_mm"],
            stiffness_r2=stiffness["stiffness_r2"],
            stiffness_region_start_displacement=stiffness["stiffness_region_start_displacement"],
            stiffness_region_end_displacement=stiffness["stiffness_region_end_displacement"],
            stiffness_region_points=stiffness["stiffness_region_points"],
            stiffness_region_source=stiffness["stiffness_region_source"],
            yield_displacement=yield_metrics["yield_displacement"],
            yield_force=yield_metrics["yield_force"], yield_offset_mm=yield_metrics["yield_offset_mm"],
            yield_method=yield_metrics["yield_method"],
            yield_requested_method=yield_metrics["yield_requested_method"],
            yield_criterion=yield_metrics["yield_criterion"],
            yield_fallback_used=yield_metrics["yield_fallback_used"],
            yield_reduced_offset_used=yield_metrics["yield_reduced_offset_used"],
            yield_attempted_methods=yield_metrics["yield_attempted_methods"],
            yield_analysis_basis=yield_metrics["yield_analysis_basis"],
            yield_offset_basis=yield_metrics["yield_offset_basis"],
            yield_offset_strain=yield_metrics["yield_offset_strain"],
            yield_proportional_departure_percent=yield_metrics["yield_proportional_departure_percent"],
            yield_reduced_proportional_used=yield_metrics["yield_reduced_proportional_used"],
            post_yield_displacement=yield_metrics["post_yield_displacement"],
            cross_sectional_area_mm2=float(area), gauge_length_mm=float(gauge),
            elastic_modulus_mpa=material["elastic_modulus_mpa"],
            elastic_modulus_r2=material["elastic_modulus_r2"],
            yield_stress_mpa=material["yield_stress_mpa"],
            ultimate_stress_mpa=material["ultimate_stress_mpa"],
            strain_energy_density_mj_m3=material["strain_energy_density_mj_m3"],
            strain_at_yield=material["strain_at_yield"],
            strain_at_ultimate_stress=material["strain_at_ultimate_stress"],
            strain_at_failure=material["strain_at_failure"],
            metadata_matched=metadata_row is not None,
            metadata_id=identity.metadata_id, genotype=genotype, age=age, sex=sex,
            metadata=metadata_export, raw_data=raw_output, corrected_data=corrected,
            post_peak_points_removed=removed, label_source=identity.source,
            metadata_match_method=identity.match_method, warning=warning,
        )
    except Exception as exc:
        fallback = display_id or make_unique_display_id(Path(file_name).stem, file_name, used_ids)
        return empty_tendon_specimen(file_name, fallback, str(exc), identity=identity)


def generate_tendon_summary(processed: list[TendonProcessedSpecimen]) -> pd.DataFrame:
    rows = []
    for item in processed:
        row = {
            "Specimen ID": item.display_id, "Genotype": item.genotype,
            "Age": item.age, "Sex": item.sex, "File name": item.file_name,
            "Original specimen ID": item.specimen_id,
            "Specimen label source": item.label_source,
            "Metadata match method": item.metadata_match_method,
            "Original data points": item.original_points,
            "Retained data points": item.retained_points,
            "Detected onset displacement (mm)": item.onset_displacement,
            "Detected onset force (N)": item.onset_force,
            "Maximum force (N)": item.maximum_force,
            "Displacement at maximum force (mm)": item.displacement_at_maximum_force,
            "Work to maximum force (mJ)": item.work_to_maximum_force_mj,
            "Tensile stiffness (N/mm)": item.tensile_stiffness_n_per_mm,
            "Stiffness R^2": item.stiffness_r2,
            "Yield displacement (mm)": item.yield_displacement,
            "Yield force (N)": item.yield_force,
            "Yield estimation": (
                "Peak fallback" if item.corrected_data.get("tendon_yield_peak_fallback", pd.Series(dtype=bool)).any()
                else item.yield_method if np.isfinite(item.yield_force) else "Unavailable"
            ),
            "Yield method": item.yield_method,
            "Yield requested method": item.yield_requested_method,
            "Yield criterion": item.yield_criterion,
            "Yield fallback used": item.yield_fallback_used,
            "Yield reduced offset used": item.yield_reduced_offset_used,
            "Yield methods attempted": item.yield_attempted_methods,
            "Yield analysis basis": item.yield_analysis_basis,
            "Yield offset basis": item.yield_offset_basis,
            "Yield offset used (%)": item.yield_offset_strain * 100,
            "Yield proportional departure used (%)": item.yield_proportional_departure_percent,
            "Yield reduced proportional limit used": item.yield_reduced_proportional_used,
            "Yield offset used (mm)": item.yield_offset_mm,
            "Post-yield displacement (mm)": item.post_yield_displacement,
            "Cross-sectional area (mm^2)": item.cross_sectional_area_mm2,
            "Initial gauge length (mm)": item.gauge_length_mm,
            "Elastic modulus (MPa)": item.elastic_modulus_mpa,
            "Yield stress (MPa)": item.yield_stress_mpa,
            "Ultimate tensile stress (MPa)": item.ultimate_stress_mpa,
            "Strain-energy density to maximum stress (MJ/m^3)": item.strain_energy_density_mj_m3,
            "Strain at yield": item.strain_at_yield,
            "Strain at ultimate stress": item.strain_at_ultimate_stress,
            "Strain at failure": item.strain_at_failure,
            "Metadata matched": item.metadata_matched,
            "Metadata ID": item.metadata_id,
            "Warning": item.warning, "Error": item.error,
        }
        for column, value in item.metadata.items():
            row.setdefault(column, value)
        rows.append(row)
    return pd.DataFrame(rows)


def export_tendon_corrected_data(processed: list[TendonProcessedSpecimen]) -> pd.DataFrame:
    frames = [item.corrected_data for item in processed if not item.error and not item.corrected_data.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def plot_tendon_force_curves(
    processed: list[TendonProcessedSpecimen], overlay: str = "none",
) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(9, 6), dpi=150)
    for index, specimen in enumerate(item for item in processed if not item.error and not item.corrected_data.empty):
        data = specimen.corrected_data
        color = UR_CHART_COLORS[index % len(UR_CHART_COLORS)]
        ax.plot(data["corrected_displacement_mm"], data["force_n"], color=color, linewidth=1.8, label=specimen.display_id)
        if overlay == "stiffness" and "stiffness_region" in data:
            region = data[data["stiffness_region"].fillna(False)]
            ax.scatter(region["corrected_displacement_mm"], region["force_n"], color=color, edgecolor="black", s=14, zorder=4)
            ax.plot(region["corrected_displacement_mm"], region["stiffness_fit_force_n"], color=color, linestyle=":", linewidth=2)
        reference_column = "tendon_yield_reference_n" if "tendon_yield_reference_n" in data else "tendon_offset_yield_line_n"
        if overlay == "yield" and reference_column in data:
            ax.plot(data["corrected_displacement_mm"], data[reference_column], color=color, linestyle="--", linewidth=1.4)
            if np.isfinite(specimen.yield_displacement) and np.isfinite(specimen.yield_force):
                ax.scatter([specimen.yield_displacement], [specimen.yield_force], marker="D", color=color, edgecolor="black", s=42, zorder=5)
                ax.annotate(f"{specimen.yield_method} {specimen.display_id}", (specimen.yield_displacement, specimen.yield_force),
                            xytext=(5, 5), textcoords="offset points", fontsize=7, color=color)
    titles = {
        "none": "Corrected Tendon Force-Displacement Curves",
        "stiffness": "Tendon Force-Displacement Curves with Stiffness Fits",
        "yield": "Tendon Force-Displacement Curves with Yield Estimates",
    }
    ax.set(title=titles[overlay], xlabel="Displacement (mm)", ylabel="Force (N)")
    ax.set_xlim(left=0); ax.set_ylim(bottom=0)
    ax.grid(True, linewidth=.5, alpha=.35); ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    return fig


def plot_tendon_stress_strain(processed: list[TendonProcessedSpecimen]) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(9, 6), dpi=150)
    valid = [item for item in processed if not item.error and "engineering_stress_mpa" in item.corrected_data and item.corrected_data["engineering_stress_mpa"].notna().any()]
    for index, specimen in enumerate(valid):
        data = specimen.corrected_data
        ax.plot(data["engineering_strain"], data["engineering_stress_mpa"], color=UR_CHART_COLORS[index % len(UR_CHART_COLORS)], linewidth=1.8, label=specimen.display_id)
    ax.set(title="Engineering Stress-Strain Curves", xlabel="Engineering strain (mm/mm)", ylabel="Engineering stress (MPa)")
    ax.set_xlim(left=0); ax.set_ylim(bottom=0)
    ax.grid(True, linewidth=.5, alpha=.35); ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    return fig


def plot_raw_curves(processed_data: list[ProcessedSpecimen]) -> plt.Figure:
    """Create a composite force-displacement plot before correction."""
    fig, ax = plt.subplots(figsize=(9, 6), dpi=150)
    colors = UR_CHART_COLORS
    line_styles = UR_LINE_STYLES

    valid_specimens = [item for item in processed_data if not item.error and not item.raw_data.empty]
    for index, specimen in enumerate(valid_specimens):
        data = specimen.raw_data
        ax.plot(
            data["displacement_mm"],
            data["force_n"],
            label=specimen.display_id,
            color=colors[index % len(colors)],
            linestyle=line_styles[(index // len(colors)) % len(line_styles)],
            linewidth=1.8,
        )

    ax.set_xlabel("Displacement (mm)")
    ax.set_ylabel("Force (N)")
    ax.set_title("Raw Force-Displacement Curves")
    ax.grid(True, which="major", linewidth=0.5, alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    return fig


def plot_composite_curves(processed_data: list[ProcessedSpecimen]) -> plt.Figure:
    """Create a publication-ready composite force-displacement plot."""
    fig, ax = plt.subplots(figsize=(9, 6), dpi=150)
    colors = UR_CHART_COLORS
    line_styles = UR_LINE_STYLES

    valid_specimens = [item for item in processed_data if not item.error and not item.corrected_data.empty]
    for index, specimen in enumerate(valid_specimens):
        data = specimen.corrected_data
        ax.plot(
            data["corrected_displacement_mm"],
            data["force_n"],
            label=specimen.display_id,
            color=colors[index % len(colors)],
            linestyle=line_styles[(index // len(colors)) % len(line_styles)],
            linewidth=1.8,
        )

    ax.set_xlabel("Displacement (mm)")
    ax.set_ylabel("Force (N)")
    ax.set_title("Corrected Force-Displacement Curves")
    ax.grid(True, which="major", linewidth=0.5, alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    return fig


def plot_moment_displacement_curves(
    processed_data: list[ProcessedSpecimen],
    overlay: str = "none",
) -> plt.Figure:
    """Create a composite moment-displacement plot with optional diagnostic overlay."""
    fig, ax = plt.subplots(figsize=(9, 6), dpi=150)
    colors = UR_CHART_COLORS
    line_styles = UR_LINE_STYLES

    valid_specimens = [item for item in processed_data if not item.error and not item.corrected_data.empty]
    for index, specimen in enumerate(valid_specimens):
        data = specimen.corrected_data
        color = colors[index % len(colors)]
        line_style = line_styles[(index // len(colors)) % len(line_styles)]
        ax.plot(
            data["corrected_displacement_mm"],
            data["bending_moment_n_mm"],
            label=specimen.display_id,
            color=color,
            linestyle=line_style,
            linewidth=1.8,
        )

    clean_y_limits = ax.get_ylim()

    for index, specimen in enumerate(valid_specimens):
        data = specimen.corrected_data
        color = colors[index % len(colors)]
        if overlay == "stiffness" and "stiffness_region" in data.columns and data["stiffness_region"].any():
            stiffness_data = data[data["stiffness_region"]]
            ax.scatter(
                stiffness_data["corrected_displacement_mm"],
                stiffness_data["bending_moment_n_mm"],
                color=color,
                edgecolor="black",
                linewidth=0.4,
                s=24,
                zorder=4,
            )
            ax.plot(
                stiffness_data["corrected_displacement_mm"],
                stiffness_data["stiffness_fit_force_n"],
                color=color,
                linestyle=":",
                linewidth=2.2,
                zorder=5,
            )
            if np.isfinite(specimen.elastic_stiffness_n_per_mm) and np.isfinite(specimen.stiffness_r2):
                text_x = float(stiffness_data["corrected_displacement_mm"].iloc[-1])
                text_y = float(stiffness_data["stiffness_fit_force_n"].iloc[-1])
                ax.annotate(
                    f"{specimen.display_id}: K={specimen.elastic_stiffness_n_per_mm:.2f} N, R^2={specimen.stiffness_r2:.3f}",
                    xy=(text_x, text_y),
                    xytext=(5, 5),
                    textcoords="offset points",
                    color=color,
                    fontsize=7,
                )
        reference_column = "yield_reference_moment_n_mm" if "yield_reference_moment_n_mm" in data else "offset_yield_line_force_n"
        if overlay == "yield" and reference_column in data.columns:
            offset_line_data = data.dropna(subset=[reference_column])
            if not offset_line_data.empty:
                ax.plot(
                    offset_line_data["corrected_displacement_mm"],
                    offset_line_data[reference_column],
                    color=color,
                    linestyle="--",
                    linewidth=1.2,
                    alpha=0.7,
                    zorder=3,
                )
        if overlay == "yield" and "yield_point" in data.columns and data["yield_point"].any() and np.isfinite(specimen.yield_displacement):
            ax.scatter(
                [specimen.yield_displacement],
                [specimen.yield_moment],
                marker="D",
                s=58,
                color=color,
                edgecolor="black",
                linewidth=0.7,
                zorder=6,
            )
            ax.annotate(
                f"{specimen.yield_method} {specimen.display_id}: {specimen.yield_moment:.2f} N.mm",
                xy=(specimen.yield_displacement, specimen.yield_moment),
                xytext=(8, -12),
                textcoords="offset points",
                color=color,
                fontsize=7,
                fontweight="bold",
            )

    if overlay == "yield":
        ax.set_ylim(clean_y_limits)

    ax.set_xlabel("Displacement (mm)")
    ax.set_ylabel("Bending Moment (N.mm)")
    title_by_overlay = {
        "none": "Moment-Displacement Curves",
        "stiffness": "Moment-Displacement Curves with Elastic Stiffness Fits",
        "yield": "Moment-Displacement Curves with Yield Estimates",
    }
    title = title_by_overlay.get(overlay, "Moment-Displacement Curves")
    if valid_specimens:
        title = f"{valid_specimens[0].geometry.description}\n{title}"
    ax.set_title(title)
    ax.grid(True, which="major", linewidth=0.5, alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    return fig


def plot_stiffness_overlay_curves(processed_data: list[ProcessedSpecimen]) -> plt.Figure:
    return plot_moment_displacement_curves(processed_data, overlay="stiffness")


def plot_yield_overlay_curves(processed_data: list[ProcessedSpecimen]) -> plt.Figure:
    return plot_moment_displacement_curves(processed_data, overlay="yield")


def plot_stress_strain_curves(processed_data: list[ProcessedSpecimen]) -> plt.Figure:
    """Create apparent bending stress-strain curves when metadata are available."""
    fig, ax = plt.subplots(figsize=(9, 6), dpi=150)
    colors = UR_CHART_COLORS
    line_styles = UR_LINE_STYLES

    valid_specimens = [
        item
        for item in processed_data
        if not item.error
        and not item.corrected_data.empty
        and "tensile_stress_mpa" in item.corrected_data.columns
        and item.corrected_data["tensile_stress_mpa"].notna().any()
        and item.corrected_data["tensile_strain"].notna().any()
    ]
    for index, specimen in enumerate(valid_specimens):
        data = specimen.corrected_data
        color = colors[index % len(colors)]
        line_style = line_styles[(index // len(colors)) % len(line_styles)]
        ax.plot(
            data["tensile_strain"],
            data["tensile_stress_mpa"],
            label=specimen.display_id,
            color=color,
            linestyle=line_style,
            linewidth=1.8,
        )

    ax.set_xlabel("Bending Strain")
    ax.set_ylabel("Bending Stress (MPa)")
    title = "Apparent Stress-Strain Curves"
    if valid_specimens:
        title = f"{valid_specimens[0].geometry.description}\n{title}"
    ax.set_title(title)
    ax.grid(True, which="major", linewidth=0.5, alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    return fig


def biological_group_label(
    specimen: ProcessedSpecimen,
    factor_labels: dict[str, str] | None = None,
) -> str:
    labels = factor_labels or {"Genotype": "Genotype", "Age": "Age", "Sex": "Sex"}
    values = (specimen.genotype, specimen.age, specimen.sex)
    parts = [
        f"{labels[internal]}: {value.strip()}"
        for internal, value in zip(BAR_GRAPH_VARIABLES, values)
        if value and value.strip()
    ]
    return " | ".join(parts) or "Unspecified"


def selected_biological_value(value: str) -> str:
    return value.strip() if value and value.strip() else "Unspecified"


def specimen_matches_biological_filters(
    specimen: ProcessedSpecimen,
    selected_genotypes: set[str],
    selected_ages: set[str],
    selected_sexes: set[str],
) -> bool:
    return (
        selected_biological_value(specimen.genotype) in selected_genotypes
        and selected_biological_value(specimen.age) in selected_ages
        and selected_biological_value(specimen.sex) in selected_sexes
    )


def biological_filter_options(processed_data: list[ProcessedSpecimen]) -> tuple[list[str], list[str], list[str]]:
    valid_specimens = [
        specimen
        for specimen in processed_data
        if not specimen.error and specimen.genotype.strip()
    ]
    genotypes = sorted({selected_biological_value(specimen.genotype) for specimen in valid_specimens})
    ages = sorted({selected_biological_value(specimen.age) for specimen in valid_specimens})
    sexes = sorted({selected_biological_value(specimen.sex) for specimen in valid_specimens})
    return genotypes, ages, sexes


def smooth_average_curve(
    values: np.ndarray,
    fraction: float = 0.05,
    minimum_window: int = 7,
    preserve_start: bool = False,
) -> np.ndarray:
    """Smooth averaged display curves with a centered rolling mean."""
    values = np.asarray(values, dtype=float)
    if len(values) < minimum_window:
        return values
    window = max(minimum_window, int(round(len(values) * fraction)))
    if window % 2 == 0:
        window += 1
    window = min(window, len(values) if len(values) % 2 == 1 else len(values) - 1)
    if window < 3:
        return values
    smoothed = (
        pd.Series(values)
        .rolling(window=window, center=True, min_periods=1)
        .mean()
        .to_numpy(dtype=float)
    )
    if preserve_start:
        # Shrink the initial windows symmetrically around each sample. A
        # one-sided rolling mean otherwise lifts the origin and biases slope.
        for index in range(window // 2):
            smoothed[index] = np.mean(values[: 2 * index + 1])
    return smoothed


def trim_curve_at_first_major_peak(
    curve: pd.DataFrame,
    y_column: str,
    drop_fraction: float = 0.05,
    minimum_drop: float = 5.0,
) -> pd.DataFrame:
    """Keep a curve only through the first peak followed by a meaningful drop."""
    if curve.empty or y_column not in curve.columns:
        return curve
    y_values = curve[y_column].to_numpy(dtype=float)
    if len(y_values) < 4 or not np.isfinite(y_values).any():
        return curve

    smoothed = smooth_average_curve(y_values, fraction=0.04, minimum_window=5)
    y_range = float(np.nanmax(smoothed) - np.nanmin(smoothed))
    drop_threshold = max(minimum_drop, drop_fraction * y_range)
    running_peak_index = int(np.nanargmax(smoothed[:1]))
    running_peak_value = float(smoothed[running_peak_index])

    for index in range(1, len(smoothed)):
        value = float(smoothed[index])
        if not np.isfinite(value):
            continue
        if value > running_peak_value:
            running_peak_value = value
            running_peak_index = index
            continue
        if index > running_peak_index and running_peak_value - value >= drop_threshold:
            return curve.iloc[: running_peak_index + 1].copy()

    global_peak_index = int(np.nanargmax(smoothed))
    return curve.iloc[: global_peak_index + 1].copy()


def plot_average_grouped_curves(
    processed_data: list[ProcessedSpecimen],
    x_column: str,
    y_column: str,
    x_label: str,
    y_label: str,
    title: str,
    selected_genotypes: set[str] | None = None,
    selected_ages: set[str] | None = None,
    selected_sexes: set[str] | None = None,
    min_points: int = 20,
    grid_points: int = 200,
    factor_labels: dict[str, str] | None = None,
    common_prepeak: bool = False,
    show_mean_peak: bool = False,
) -> plt.Figure:
    """Plot mean curves grouped by genotype and selected biological strata.

    Use the upstream-corrected specimen data without any display-only offsets.
    Smoothing preserves the initial point so a corrected origin stays at zero.
    With common_prepeak, every plotted point uses the same complete cohort on
    its shared measured loading range. No extrapolation or peak alignment.
    """
    fig, ax = plt.subplots(figsize=(9, 6), dpi=150)
    grouped: dict[str, list[pd.DataFrame]] = {}
    grouped_peaks: dict[str, list[tuple[float, float]]] = {}
    is_average_stress_strain = x_column == "tensile_strain" and y_column == "tensile_stress_mpa"
    for specimen in processed_data:
        data = specimen.corrected_data
        if specimen.error or data.empty or not specimen.genotype.strip():
            continue
        if (
            selected_genotypes is not None
            and selected_ages is not None
            and selected_sexes is not None
            and not specimen_matches_biological_filters(specimen, selected_genotypes, selected_ages, selected_sexes)
        ):
            continue
        if x_column not in data.columns or y_column not in data.columns:
            continue
        curve = data[[x_column, y_column]].replace([np.inf, -np.inf], np.nan).dropna()
        if curve.empty:
            continue
        # Preserve each measured peak before duplicate-x averaging or display
        # truncation. X is displacement AT peak, not maximum displacement.
        peak_position = int(np.argmax(curve[y_column].to_numpy(dtype=float)))
        peak_point = tuple(float(value) for value in curve.iloc[peak_position])
        if common_prepeak and not curve.empty:
            # Trim in acquisition order, before sorting/interpolating. Otherwise
            # post-failure readings can be folded into the loading branch.
            curve = curve.iloc[: peak_position + 1]
        curve = curve.sort_values(x_column, kind="stable")
        starts_at_origin = (
            (is_average_stress_strain or common_prepeak) and not curve.empty
            and float(curve[x_column].iloc[0]) == 0.0
            and float(curve[y_column].iloc[0]) == 0.0
        )
        curve = curve.groupby(x_column, as_index=False).mean(numeric_only=True)
        if starts_at_origin:
            # Repeated zero-strain readings must not average away the actual
            # first corrected sample. Keep its measured origin, not an offset.
            curve.loc[curve[x_column] == 0.0, y_column] = 0.0
        if is_average_stress_strain and not common_prepeak and not curve.empty:
            curve = trim_curve_at_first_major_peak(curve, y_column)
        if len(curve) < min_points or curve[x_column].max() <= curve[x_column].min():
            continue
        label = biological_group_label(specimen, factor_labels)
        grouped.setdefault(label, []).append(curve)
        grouped_peaks.setdefault(label, []).append(peak_point)

    colors = UR_CHART_COLORS
    plotted_groups = 0
    for index, (label, curves) in enumerate(sorted(grouped.items())):
        if common_prepeak:
            group_max_x = min(float(curve[x_column].max()) for curve in curves)
            group_min_x = max(float(curve[x_column].min()) for curve in curves)
        else:
            group_max_x = max(float(curve[x_column].max()) for curve in curves)
            group_min_x = min(float(curve[x_column].min()) for curve in curves)
        if group_max_x <= group_min_x:
            continue
        x_grid = np.linspace(group_min_x, group_max_x, grid_points)
        interpolated_curves = []
        for curve in curves:
            x_values = curve[x_column].to_numpy(dtype=float)
            y_values_for_curve = curve[y_column].to_numpy(dtype=float)
            interpolated = np.interp(x_grid, x_values, y_values_for_curve)
            interpolated[(x_grid < x_values.min()) | (x_grid > x_values.max())] = np.nan
            interpolated_curves.append(interpolated)
        y_values = np.vstack(interpolated_curves)
        contributing_counts = np.sum(np.isfinite(y_values), axis=0)
        valid_grid = contributing_counts == len(curves) if common_prepeak else contributing_counts > 0
        if not np.any(valid_grid):
            continue
        x_grid = x_grid[valid_grid]
        y_values = y_values[:, valid_grid]
        contributing_counts = contributing_counts[valid_grid]
        y_mean = np.nanmean(y_values, axis=0)
        y_sem = np.zeros_like(y_mean)
        sem_valid = contributing_counts > 1
        if len(curves) > 1 and np.any(sem_valid):
            y_sem[sem_valid] = (
                np.nanstd(y_values[:, sem_valid], axis=0, ddof=1)
                / np.sqrt(contributing_counts[sem_valid])
            )
        if is_average_stress_strain and not common_prepeak:
            y_mean = smooth_average_curve(y_mean, fraction=0.08, minimum_window=9, preserve_start=True)
            y_sem = smooth_average_curve(y_sem, preserve_start=True)
            average_peak_x = float(
                np.nanmean(
                    [
                        curve.loc[curve[y_column].idxmax(), x_column]
                        for curve in curves
                        if not curve.empty and curve[y_column].notna().any()
                    ]
                )
            )
            peak_index = int(np.searchsorted(x_grid, average_peak_x, side="right") - 1)
            if peak_index < 0:
                peak_index = int(np.nanargmax(y_mean))
            peak_index = min(peak_index, len(x_grid) - 1)
            x_grid = x_grid[: peak_index + 1]
            y_mean = y_mean[: peak_index + 1]
            y_sem = y_sem[: peak_index + 1]
            sem_valid = sem_valid[: peak_index + 1]
        color = colors[index % len(colors)]
        ax.plot(x_grid, y_mean, label=f"{label} (n={len(curves)})", color=color, linewidth=2.2)
        if show_mean_peak:
            mean_peak_x, mean_peak_y = np.mean(grouped_peaks[label], axis=0)
            ax.plot(
                [x_grid[-1], mean_peak_x], [y_mean[-1], mean_peak_y],
                color=color, linestyle="--", linewidth=1.5, marker="D",
                markevery=[1], markersize=6, markeredgecolor="white",
                markeredgewidth=0.8, label="_nolegend_", zorder=4,
            )
        plotted_groups += 1
        if len(curves) > 1:
            ax.fill_between(
                x_grid,
                y_mean - y_sem,
                y_mean + y_sem,
                where=sem_valid,
                color=color,
                alpha=0.18,
                linewidth=0,
            )
            if show_mean_peak:
                peak_sem_x, peak_sem_y = np.std(grouped_peaks[label], axis=0, ddof=1) / np.sqrt(len(curves))
                ax.errorbar(
                    mean_peak_x, mean_peak_y, xerr=peak_sem_x, yerr=peak_sem_y,
                    fmt="none", ecolor=color, elinewidth=1.3, capsize=3,
                    capthick=1.3, label="_nolegend_", zorder=3,
                )

    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title)
    ax.grid(True, which="major", linewidth=0.5, alpha=0.35)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    if plotted_groups:
        ax.legend(frameon=False, fontsize=8, loc="best")
    else:
        ax.text(0.5, 0.5, "No grouped curves available.", ha="center", va="center", transform=ax.transAxes)
    if is_average_stress_strain or common_prepeak or show_mean_peak:
        ax.set_xlim(left=0.0)
        if ax.dataLim.ymin >= 0:
            ax.set_ylim(bottom=0.0)
        caption = (
            "Mean +/- SEM; fixed n over the shared pre-peak range."
            if common_prepeak else "Mean of corrected specimen curves; band: SEM."
        )
        if show_mean_peak:
            caption += (
                "\nDiamond: mean individual peak coordinates; horizontal and vertical bars: +/- SEM (n > 1)."
                "\nDashed line: visual guide, not measured data."
            )
        elif common_prepeak:
            caption += " Endpoints are not group mean maxima."
        fig.text(
            0.5, 0.015, caption,
            ha="center", fontsize=8, color="#555555",
        )
        fig.tight_layout(rect=(0, 0.10 if show_mean_peak else 0.04, 1, 1))
    else:
        fig.tight_layout()
    return fig


BAR_GRAPH_METRICS = [
    "Maximum force (N)",
    "Maximum moment (N.mm)",
    "Displacement at maximum force (mm)",
    "Displacement at maximum moment (mm)",
    "Work to maximum moment (N.mm^2)",
    "Elastic bending stiffness (N)",
    "Yield force (N)",
    "Yield moment (N.mm)",
    "Post-yield displacement (mm)",
    "Apparent modulus (MPa)",
    "Yield stress (MPa)",
    "Ultimate stress (MPa)",
    "Energy to max stress (MPa)",
    "Strain at yield",
    "Strain at ultimate stress",
    "Strain at failure",
]

MATERIAL_BAR_GRAPH_METRICS = {
    "Apparent modulus (MPa)",
    "Yield stress (MPa)",
    "Ultimate stress (MPa)",
    "Energy to max stress (MPa)",
    "Strain at yield",
    "Strain at ultimate stress",
    "Strain at failure",
}

STRUCTURAL_PROPERTY_METRICS = [
    "Maximum force (N)",
    "Displacement at maximum force (mm)",
    "Maximum moment (N.mm)",
    "Displacement at maximum moment (mm)",
    "Work to maximum moment (N.mm^2)",
    "Elastic bending stiffness (N)",
    "Yield force (N)",
    "Yield moment (N.mm)",
    "Post-yield displacement (mm)",
]

MATERIAL_PROPERTY_METRICS = [
    "Apparent modulus (MPa)",
    "Yield stress (MPa)",
    "Ultimate stress (MPa)",
    "Energy to max stress (MPa)",
    "Strain at yield",
    "Strain at ultimate stress",
    "Strain at failure",
]

GROUP_AVERAGE_METADATA_METRICS = [
    "Ixx (mm^4)",
    "I/c (mm^3)",
    "c (mm)",
]

GROUP_AVERAGE_PROPERTY_METRICS = (
    GROUP_AVERAGE_METADATA_METRICS
    + STRUCTURAL_PROPERTY_METRICS
    + MATERIAL_PROPERTY_METRICS
)

PROCESSING_SUMMARY_COLUMNS = [
    "Specimen ID",
    "Genotype",
    "Age",
    "Sex",
    "Original specimen ID",
    "File name",
    "Maximum force (N)",
    "Displacement at maximum force (mm)",
    "Maximum moment (N.mm)",
    "Displacement at maximum moment (mm)",
    "Work to maximum moment (N.mm^2)",
    "Elastic bending stiffness (N)",
    "Yield displacement (mm)",
    "Yield force (N)",
    "Yield moment (N.mm)",
    "Yield offset used (mm)",
    "Yield method",
    "Yield requested method",
    "Yield criterion",
    "Yield fallback used",
    "Yield reduced offset used",
    "Yield methods attempted",
    "Yield analysis basis",
    "Yield offset basis",
    "Yield offset used (%)",
    "Yield proportional departure used (%)",
    "Yield reduced proportional limit used",
    "Post-yield displacement (mm)",
    "Ixx (mm^4)",
    "I/c (mm^3)",
    "c (mm)",
    "Material geometry source",
    "Apparent modulus (MPa)",
    "Yield stress (MPa)",
    "Ultimate stress (MPa)",
    "Energy to max stress (MPa)",
    "Strain at yield",
    "Strain at ultimate stress",
    "Strain at failure",
    "Bending test",
    "Loading span L (mm)",
    "Support span S (mm)",
    "Displacement measurement location",
]


def filtered_summary_for_biological_strata(
    summary: pd.DataFrame,
    selected_genotypes: set[str],
    selected_ages: set[str],
    selected_sexes: set[str],
) -> pd.DataFrame:
    filtered = summary.copy()
    for column, selected in [
        ("Genotype", selected_genotypes),
        ("Age", selected_ages),
        ("Sex", selected_sexes),
    ]:
        values = filtered[column].fillna("").astype(str).map(selected_biological_value)
        filtered = filtered[values.isin(selected)]
    return filtered


def biological_combination_label(
    row: pd.Series,
    factor_labels: dict[str, str] | None = None,
) -> str:
    labels = factor_labels or {"Genotype": "Genotype", "Age": "Age", "Sex": "Sex"}
    genotype = selected_biological_value(str(row.get("Genotype", "")))
    age = selected_biological_value(str(row.get("Age", "")))
    sex = selected_biological_value(str(row.get("Sex", "")))
    return " | ".join(
        f"{labels[column]}: {value}"
        for column, value in zip(BAR_GRAPH_VARIABLES, (genotype, age, sex))
        if value != "Unspecified"
    ) or "Unspecified"


def biological_combination_options(
    summary: pd.DataFrame,
    factor_labels: dict[str, str] | None = None,
) -> list[str]:
    if summary.empty:
        return []
    labels = summary.apply(lambda row: biological_combination_label(row, factor_labels), axis=1)
    return sorted(labels.dropna().astype(str).unique().tolist(), key=str.casefold)


def filtered_summary_for_biological_combinations(
    summary: pd.DataFrame,
    selected_combinations: set[str],
    factor_labels: dict[str, str] | None = None,
) -> pd.DataFrame:
    if summary.empty:
        return summary.copy()
    labels = summary.apply(lambda row: biological_combination_label(row, factor_labels), axis=1)
    return summary[labels.isin(selected_combinations)].copy()


BAR_GRAPH_VARIABLES = ("Genotype", "Age", "Sex")


def biological_category_sort_key(value: str) -> tuple:
    """Keep numbered categories such as 2M, 6M, and 12M in natural order."""
    return tuple(
        (1, float(part)) if re.fullmatch(r"\d+(?:\.\d+)?", part) else (0, part.casefold())
        for part in re.split(r"(\d+(?:\.\d+)?)", str(value))
    )


def normalize_bar_graph_data(summary: pd.DataFrame) -> pd.DataFrame:
    data = summary.copy()
    for column in BAR_GRAPH_VARIABLES:
        if column not in data:
            data[column] = "Unspecified"
        data[column] = data[column].fillna("").astype(str).map(selected_biological_value)
    return data


def summarize_bar_graph_metric(summary: pd.DataFrame, metric: str) -> pd.DataFrame:
    """One mean/sample SD per biological combination, never pooled by layout."""
    data = normalize_bar_graph_data(summary)
    data["value"] = pd.to_numeric(data[metric], errors="coerce")
    data = data[np.isfinite(data["value"])]
    return data.groupby(list(BAR_GRAPH_VARIABLES), observed=True, sort=False)["value"].agg(
        Mean="mean", SD="std", N="size", Values=list,
    ).reset_index()


def default_bar_graph_variables(summary: pd.DataFrame) -> tuple[str, Optional[str]]:
    data = normalize_bar_graph_data(summary)
    varying = [column for column in BAR_GRAPH_VARIABLES if data[column].nunique() > 1]
    x_variable = next((column for column in ("Age", "Sex", "Genotype") if column in varying), "Genotype")
    series_variable = next((column for column in varying if column != x_variable), None)
    return x_variable, series_variable


def build_bar_graph_controls(
    summary: pd.DataFrame,
    average_selections: Optional[dict[str, list[str]]] = None,
    factor_labels: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, list[str], str, Optional[str]]:
    """Independent biological filters and explicit category/series assignments."""
    data = normalize_bar_graph_data(summary)
    options = {
        column: sorted(data[column].unique().tolist(), key=biological_category_sort_key)
        for column in BAR_GRAPH_VARIABLES
    }
    if average_selections is not None and st.button("Match average-curve filters", key="bar_match_average"):
        for column in BAR_GRAPH_VARIABLES:
            st.session_state[f"bar_filter_{column}"] = [
                value for value in average_selections[column] if value in options[column]
            ]
        st.session_state.pop("bar_combinations", None)

    labels = factor_labels or {column: column for column in BAR_GRAPH_VARIABLES}
    selections = {}
    for column, container in zip(BAR_GRAPH_VARIABLES, st.columns(3)):
        key = f"bar_filter_{column}"
        initial = average_selections[column] if average_selections is not None else options[column]
        st.session_state[key] = [value for value in st.session_state.get(key, initial) if value in options[column]]
        selections[column] = container.multiselect(
            f"{labels[column]} values", options[column], key=key,
        )
    filtered = filtered_summary_for_biological_strata(data, *[set(selections[column]) for column in BAR_GRAPH_VARIABLES])
    combinations = biological_combination_options(filtered, labels)
    with st.expander("Specific combinations"):
        chosen = st.multiselect("Combinations to include", combinations, default=combinations, key="bar_combinations")
    filtered = filtered_summary_for_biological_combinations(filtered, set(chosen), labels)

    available_metrics = [
        metric for metric in BAR_GRAPH_METRICS
        if metric in filtered and np.isfinite(pd.to_numeric(filtered[metric], errors="coerce")).any()
    ]
    defaults = [
        metric for metric in (
            "Ultimate stress (MPa)", "Apparent modulus (MPa)", "Yield stress (MPa)",
            "Energy to max stress (MPa)", "Strain at yield", "Strain at ultimate stress", "Strain at failure",
        ) if metric in available_metrics
    ][:4]
    metrics = st.multiselect("Properties to plot", available_metrics, default=defaults, key="bar_metrics")
    variable_options = [column for column in BAR_GRAPH_VARIABLES if (data[column] != "Unspecified").any()] or ["Genotype"]
    default_x, default_series = default_bar_graph_variables(filtered)
    if st.session_state.get("bar_x_variable") not in variable_options:
        st.session_state["bar_x_variable"] = default_x if default_x in variable_options else variable_options[0]
    layout_cols = st.columns(2)
    x_variable = layout_cols[0].selectbox(
        "X-axis variable", variable_options, key="bar_x_variable",
        format_func=lambda value: labels.get(value, value),
    )
    series_options = [None] + [column for column in variable_options if column != x_variable]
    if "bar_series_variable" not in st.session_state or st.session_state["bar_series_variable"] not in series_options:
        st.session_state["bar_series_variable"] = default_series if default_series in series_options else None
    series_variable = layout_cols[1].selectbox(
        "Side-by-side bars", series_options, key="bar_series_variable",
        format_func=lambda value: labels.get(value, value) if value is not None else "None",
    )
    return filtered, metrics, x_variable, series_variable


def annotate_bar_comparisons(ax, results, metric, summary, positions, upper, padding):
    """Bracket only exact displayed groups with current, adjusted pairwise tests."""
    required = {"Metric", "Result type", "Scope ID", "Group 1 key", "Group 2 key", "Adjusted P value (numeric)"}
    if results is None or results.empty or not required.issubset(results):
        return upper + padding, 0
    comparisons = results[
        (results["Metric"] == metric) & (results["Result type"] == "pairwise")
        & (results["Scope ID"] == statistics_scope_id(summary, metric))
    ]
    brackets = []
    for _, row in comparisons.iterrows():
        stars = significance_stars(pd.to_numeric(row["Adjusted P value (numeric)"], errors="coerce"))
        a, b = row["Group 1 key"], row["Group 2 key"]
        if not stars or a not in positions or b not in positions:
            continue
        x1, n1 = positions[a]
        x2, n2 = positions[b]
        if n1 != row.get("Group 1 n") or n2 != row.get("Group 2 n"):
            continue
        brackets.append((*sorted((x1, x2)), stars))
    brackets.sort(key=lambda bracket: (bracket[1] - bracket[0], bracket[0]))
    lanes = []
    ceiling = upper + padding
    for x1, x2, stars in brackets:
        lane = next((index for index, intervals in enumerate(lanes)
                     if all(x2 < left - .05 or x1 > right + .05 for left, right in intervals)), len(lanes))
        if lane == len(lanes):
            lanes.append([])
        lanes[lane].append((x1, x2))
        y = upper + padding * (.7 + lane * 1.2)
        height = padding * .18
        line, = ax.plot([x1, x1, x2, x2], [y, y + height, y + height, y], color="black", linewidth=.9, zorder=5)
        line.set_gid("significance-bracket")
        text = ax.text((x1 + x2) / 2, y + height, stars, ha="center", va="bottom", fontsize=10, color="black", zorder=5)
        text.set_gid("significance-stars")
        ceiling = max(ceiling, y + padding * 1.8)
    return ceiling, len(brackets)


def plot_metric_bar_graphs(
    summary: pd.DataFrame,
    selected_metrics: list[str],
    x_variable: str,
    series_variable: Optional[str] = None,
    statistics_results: Optional[pd.DataFrame] = None,
    factor_labels: dict[str, str] | None = None,
) -> plt.Figure:
    """Cluster bars by two variables and facet remaining varying factors.

    Every bar uses one genotype/age/sex combination. Layout changes cannot
    pool a third factor, and unavailable combinations remain empty slots.
    """
    if x_variable not in BAR_GRAPH_VARIABLES or (
        series_variable is not None and (series_variable not in BAR_GRAPH_VARIABLES or series_variable == x_variable)
    ):
        raise ValueError("Select distinct biological variables for the x-axis and side-by-side bars.")
    labels = factor_labels or {column: column for column in BAR_GRAPH_VARIABLES}
    plot_data = normalize_bar_graph_data(summary)
    available_metrics = [
        metric
        for metric in selected_metrics
        if metric in plot_data and np.isfinite(pd.to_numeric(plot_data[metric], errors="coerce")).any()
    ]
    facet_columns = [
        column for column in BAR_GRAPH_VARIABLES
        if column not in (x_variable, series_variable) and plot_data[column].nunique() > 1
    ]
    if facet_columns:
        facets = list(plot_data[facet_columns].drop_duplicates().itertuples(index=False, name=None))
        facets.sort(key=lambda values: tuple(biological_category_sort_key(value) for value in values))
    else:
        facets = [()]
    x_values = sorted(plot_data[x_variable].unique().tolist(), key=biological_category_sort_key)
    series_values = sorted(plot_data[series_variable].unique().tolist(), key=biological_category_sort_key) if series_variable else [None]
    ncols = min(2, max(1, len(facets)))
    facet_rows = max(1, (len(facets) + ncols - 1) // ncols)
    nrows = max(1, len(available_metrics)) * facet_rows
    panel_height = 4.5 if statistics_results is not None and not statistics_results.empty else 3.5
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(max(9, 5.2 * ncols), panel_height * nrows + 1.2), dpi=150, squeeze=False,
    )
    if not available_metrics:
        for ax in axes.flat:
            ax.axis("off")
        axes.flat[0].text(0.5, 0.5, "No selected specimens have plottable values for these properties.", ha="center", va="center", wrap=True)
        fig.tight_layout()
        return fig
    colors = {value: UR_CHART_COLORS[index % len(UR_CHART_COLORS)] for index, value in enumerate(series_values)}
    bar_width = min(0.6, 0.8 / max(1, len(series_values)))
    singleton_present = False
    bracket_count = 0
    for metric_index, metric in enumerate(available_metrics):
        statistics = summarize_bar_graph_metric(plot_data, metric)
        singleton_present |= bool((statistics["N"] == 1).any())
        raw_values = np.concatenate([np.asarray(values, dtype=float) for values in statistics["Values"]])
        lower = min(0.0, float(raw_values.min()), float((statistics["Mean"] - statistics["SD"].fillna(0)).min()))
        upper = max(0.0, float(raw_values.max()), float((statistics["Mean"] + statistics["SD"].fillna(0)).max()))
        padding = max(upper - lower, 1e-8) * 0.14
        metric_axes = []
        metric_ceiling = upper + padding
        for facet_index in range(facet_rows * ncols):
            ax = axes[metric_index * facet_rows + facet_index // ncols, facet_index % ncols]
            if facet_index >= len(facets):
                ax.axis("off")
                continue
            facet = facets[facet_index]
            positions = {}
            metric_axes.append(ax)
            facet_stats = statistics
            for column, value in zip(facet_columns, facet):
                facet_stats = facet_stats[facet_stats[column] == value]
            for x_index, x_value in enumerate(x_values):
                for series_index, series_value in enumerate(series_values):
                    group = facet_stats[facet_stats[x_variable] == x_value]
                    if series_variable:
                        group = group[group[series_variable] == series_value]
                    if group.empty:
                        continue
                    row = group.iloc[0]
                    position = x_index + (series_index - (len(series_values) - 1) / 2) * bar_width
                    positions[biological_key(row)] = (position, int(row["N"]))
                    values = np.asarray(row["Values"], dtype=float)
                    sd = float(row["SD"])
                    ax.bar(
                        position, row["Mean"], width=bar_width * 0.92,
                        yerr=sd if np.isfinite(sd) else None, capsize=4,
                        color=colors[series_value], edgecolor="black", linewidth=0.7, alpha=0.8, zorder=2,
                    )
                    jitter = np.linspace(-bar_width * 0.18, bar_width * 0.18, len(values)) if len(values) > 1 else np.array([0.0])
                    ax.scatter(position + jitter, values, color="black", edgecolor="white", linewidth=0.4, s=22, zorder=4)
                    top = max(float(values.max()), float(row["Mean"]) + (sd if np.isfinite(sd) else 0.0))
                    ax.text(position, top + padding * 0.12, f"n={int(row['N'])}", ha="center", va="bottom", fontsize=8)
            context = [f"{labels[column]}: {value}" for column, value in zip(facet_columns, facet)]
            for column in BAR_GRAPH_VARIABLES:
                if column not in (x_variable, series_variable) and column not in facet_columns and plot_data[column].nunique() == 1:
                    context.append(f"{labels[column]}: {plot_data[column].iloc[0]}")
            ax.set_title(textwrap.fill(metric, 48) + ("\n" + textwrap.fill(" | ".join(context), 48) if context else ""), fontsize=11)
            ax.set_ylabel(textwrap.fill(metric, 35))
            ax.set_xlabel(labels[x_variable])
            ax.set_xticks(np.arange(len(x_values)))
            ax.set_xticklabels([textwrap.fill(value, 18) for value in x_values], fontsize=9)
            ax.set_xlim(-0.55, max(0, len(x_values) - 1) + 0.55)
            ax.set_ylim(lower - padding * 0.2 if lower < 0 else 0, upper + padding)
            ax.grid(True, axis="y", linewidth=0.5, alpha=0.25, zorder=0)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.tick_params(axis="x", length=0)
            if facet_stats.empty:
                ax.text(0.5, 0.5, "No valid values", transform=ax.transAxes, ha="center", va="center")
            ceiling, count = annotate_bar_comparisons(
                ax, statistics_results, metric, summary, positions, upper, padding,
            )
            metric_ceiling = max(metric_ceiling, ceiling)
            bracket_count += count
        for ax in metric_axes:
            ax.set_ylim(ax.get_ylim()[0], metric_ceiling)
    heading = f"Selected Properties by {labels[x_variable]}" + (f" and {labels[series_variable]}" if series_variable else "")
    fig.suptitle(heading, fontsize=14, fontweight="bold", y=0.99)
    if series_variable:
        fig.legend(
            handles=[Patch(facecolor=colors[value], edgecolor="black", alpha=0.8, label=textwrap.fill(value, 30)) for value in series_values],
            title=labels[series_variable], loc="upper center", bbox_to_anchor=(0.5, 1 - 0.35 / fig.get_figheight()),
            frameon=False, fontsize=9, ncol=min(3, len(series_values)),
        )
    note = "Bars: mean; error bars: sample SD; points: individual specimens."
    if singleton_present:
        note += " SD unavailable for n=1."
    if statistics_results is not None and not statistics_results.empty:
        note += "\nAdjusted pairwise p: * <0.05, ** <0.01, *** <0.001, **** <0.0001 (within each property)."
        note += "\nWithin-panel comparisons only; full tests and adjustment methods in the statistics table."
        if not bracket_count:
            note += " No significant, estimable within-panel comparisons."
    fig.text(0.5, 0.01, note, ha="center", fontsize=8)
    legend_height = (0.85 + 0.28 * ((len(series_values) - 1) // 3)) if series_variable else 0.4
    footer_height = .62 if statistics_results is not None and not statistics_results.empty else .18
    fig.tight_layout(rect=[0, footer_height / fig.get_figheight(), 1, 1 - legend_height / fig.get_figheight()])
    return fig


def format_two_decimal_places(value: float) -> str:
    """Format a finite value with 2 digits after the decimal and no exponent notation."""
    if not np.isfinite(value):
        return ""
    return f"{float(value):.2f}"


def format_mean_sd(values: pd.Series) -> str:
    numeric_values = pd.to_numeric(values, errors="coerce").dropna()
    if numeric_values.empty:
        return ""
    mean_value = float(numeric_values.mean())
    sd_value = float(numeric_values.std(ddof=1)) if len(numeric_values) > 1 else 0.0
    return f"{format_two_decimal_places(mean_value)} +/- {format_two_decimal_places(sd_value)}"


def generate_group_average_results_table(
    summary: pd.DataFrame,
    factor_labels: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Average structural and material properties by metadata biological group."""
    group_columns = ["Genotype", "Age", "Sex"]
    output_columns = group_columns + ["Analyzed specimens (n)"] + GROUP_AVERAGE_PROPERTY_METRICS
    if summary.empty or not all(column in summary.columns for column in group_columns):
        return pd.DataFrame(columns=output_columns)

    analyzed = summary[
        (~summary["Error"].astype(bool))
        & (pd.to_numeric(summary["Retained data points"], errors="coerce") > 0)
    ].copy()
    if analyzed.empty:
        return pd.DataFrame(columns=output_columns)

    for column in group_columns:
        analyzed[column] = analyzed[column].astype(str).map(selected_biological_value)

    metrarea_columns = [metric for metric in GROUP_AVERAGE_PROPERTY_METRICS if metric in analyzed.columns]
    rows = []
    for group_values, group in analyzed.groupby(group_columns, dropna=False, sort=True):
        if not isinstance(group_values, tuple):
            group_values = (group_values,)
        row = dict(zip(group_columns, group_values))
        row["Analyzed specimens (n)"] = int(len(group))
        for metric in metrarea_columns:
            row[metric] = format_mean_sd(group[metric])
        rows.append(row)

    result = pd.DataFrame(rows, columns=group_columns + ["Analyzed specimens (n)"] + metrarea_columns)
    if factor_labels:
        result = result.rename(columns={key: value for key, value in factor_labels.items() if value})
    return result


def stats_metric_options(summary: pd.DataFrame) -> list[str]:
    return [
        metric for metric in GROUP_AVERAGE_PROPERTY_METRICS
        if metric in summary and np.isfinite(pd.to_numeric(summary[metric], errors="coerce")).any()
    ]


def build_statistics_controls(
    summary: pd.DataFrame,
    metrics: list[str],
    key_prefix: str = "stats",
    factor_labels: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, bool]:
    """Statistics follow the chart's specimen and property selection exactly."""
    with st.expander("Statistical model and comparisons", expanded=True):
        labels = factor_labels or {column: column for column in BAR_GRAPH_VARIABLES}
        factors = stats_factor_options(summary)
        displayed_factors = [labels.get(factor, factor) for factor in factors]
        st.caption("Model factors: " + (", ".join(displayed_factors) if displayed_factors else "None varying") +
                   f". Selected specimens: {len(summary)}. Independent specimens are assumed unless specified below.")
        controls = st.columns(2)
        design = controls[0].selectbox(
            "Experimental design", ["Independent specimens", "Paired / repeated specimens"],
            key=f"{key_prefix}_design",
        )
        family = controls[1].selectbox(
            "Pairwise comparisons", ["Simple effects", "All group pairs"], key=f"{key_prefix}_family",
            help="Simple effects compare groups differing in one biological variable. Holm correction includes all selected comparisons for each property, including those not visible in a panel.",
        )
        covariate_options = [
            name for name in summary if name.startswith("Metadata: ")
            and np.isfinite(pd.to_numeric(summary[name], errors="coerce")).sum() >= 3
            and pd.to_numeric(summary[name], errors="coerce").nunique() > 1
        ]
        covariates = st.multiselect(
            "Continuous covariates (optional)", covariate_options, key=f"{key_prefix}_covariates",
            help="Select only scientifically justified continuous covariates, not specimen identifiers. Adds common linear covariate slopes to the factorial model.",
        )
        annotate = st.checkbox("Show significant pairwise comparisons", value=True, key=f"{key_prefix}_show_stars")
        if design != "Independent specimens":
            st.warning("Paired/repeated specimens need an animal identifier and a repeated-measures or mixed-effects model. Independent tests and significance annotations are disabled.")
        results = generate_statistics_results_table(
            summary, metrics, covariates=covariates,
            comparison_family="all" if family == "All group pairs" else "simple",
            independent=design == "Independent specimens",
        )
        if any("yield" in metric.casefold() for metric in metrics) and "Yield method" in summary:
            detected_methods = set(summary["Yield method"].dropna()) - {"Not detected", ""}
            if len(detected_methods) > 1:
                st.warning("Yield comparisons include both proportional-limit and offset estimates. The successful method is recorded for each specimen; these definitions are not interchangeable.")
            if len(yield_offset_definitions(summary)) > 1:
                st.warning("Yield comparisons include different offset definitions (strain percentage or displacement). The basis and offset are recorded for each specimen; these estimates are not interchangeable.")
            proportional_rows = summary.loc[summary["Yield method"].eq("Proportional limit")]
            departures = pd.to_numeric(proportional_rows.get("Yield proportional departure used (%)", pd.Series(dtype=float)), errors="coerce").dropna()
            if departures.nunique() > 1:
                st.warning("Yield comparisons include different proportional-limit departure thresholds. The threshold used for each specimen is recorded; these definitions are not interchangeable.")
        if not results.empty and factor_labels:
            for column in ("Factors", "Test/effect", "Group 1", "Group 2", "Analysis note", "Note"):
                if column not in results:
                    continue
                results[column] = results[column].apply(
                    lambda value: value if pd.isna(value) else _replace_factor_labels(str(value), labels)
                )
        if not results.empty:
            overview_columns = [name for name in (
                "Metric", "Factors", "Method", "Analyzed specimens (n)", "Excluded specimens (n)",
                "Assumption result", "Analysis note", "Note",
            ) if name in results]
            overview = results.drop_duplicates(["Metric", "Method"])
            st.dataframe(overview[overview_columns].drop_duplicates(), width="stretch", hide_index=True)
            issues = results[results["Result type"] == "diagnostic"]
            for _, issue in issues.iterrows():
                st.warning(f"{issue['Metric']}: {issue['Note']}")
            if "Excluded specimens (n)" in results:
                affected = results.loc[results["Excluded specimens (n)"].gt(0)].drop_duplicates("Metric")
                exclusion_rows = []
                for _, row in affected.iterrows():
                    details = json.loads(row.get("Exclusion details (JSON)", "[]"))
                    exclusion_rows.extend(details)
                    ids = ", ".join(item["Specimen ID"] for item in details)
                    message = (
                        f"{row['Metric']}: {int(row['Analyzed specimens (n)'])} of "
                        f"{int(row['Selected specimens (n)'])} specimens analyzed. "
                        f"Excluded for this property: {ids}."
                    )
                    if any(item["Category"] != "Missing outcome" for item in details):
                        st.warning(message + " Missing model predictors can prevent comparisons from being annotated on affected bars.")
                    else:
                        st.info(message)
                if exclusion_rows:
                    with st.expander("Missing values by specimen and property"):
                        exclusion_table = pd.DataFrame(exclusion_rows)
                        exclusion_table["Reason"] = exclusion_table["Reason"].map(lambda value: _replace_factor_labels(value, labels))
                        st.dataframe(exclusion_table, width="stretch", hide_index=True)
        if covariates:
            st.caption("Bar heights remain unadjusted means. ANCOVA comparisons are adjusted to mean covariate values and assume common linear slopes; model suitability requires scientific review.")
        st.caption("Two-sided tests, alpha = 0.05. Pairwise p-values are adjusted within each property, not across properties. Stars denote adjusted p < 0.05, 0.01, 0.001, and 0.0001. Brackets compare bars within the same panel; all planned comparisons are included in the statistics download. Nonnormal factorial data receive observed-group rank tests, not factorial interaction tests.")
    return results, annotate


def parse_exported_mean_sd(value: object) -> tuple[float, float]:
    text = str(value).strip()
    if not text:
        return np.nan, np.nan
    if "+/-" in text:
        mean_text, sd_text = text.split("+/-", 1)
        return pd.to_numeric(mean_text.strip(), errors="coerce"), pd.to_numeric(sd_text.strip(), errors="coerce")
    return pd.to_numeric(text, errors="coerce"), np.nan


def parse_exported_p_value(value: object) -> float:
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return np.nan
    if text.startswith("<"):
        return pd.to_numeric(text[1:], errors="coerce")
    return pd.to_numeric(text, errors="coerce")


def manuscript_p_value(value: object) -> str:
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return "p not available"
    if text.startswith("<"):
        return f"p {text}"
    numeric = pd.to_numeric(text, errors="coerce")
    if not np.isfinite(numeric):
        return "p not available"
    if float(numeric) < 0.0001:
        return "p < 0.0001"
    return f"p = {float(numeric):.4f}"


def effect_label_to_text(effect: object, factors_text: object) -> str:
    label = str(effect)
    factors = [factor.strip() for factor in str(factors_text).split("+") if factor.strip()]
    for index, factor in enumerate(factors):
        label = label.replace(f"C(factor_{index})", factor)
    label = label.replace(":", " x ")
    return label


def readable_sex_text(value: object) -> str:
    text = selected_biological_value(str(value))
    if text.upper() == "M":
        return "male"
    if text.upper() == "F":
        return "female"
    return text


def narrative_group_label(genotype: object, age: object, sex: object) -> str:
    genotype_text = selected_biological_value(str(genotype))
    age_text = selected_biological_value(str(age))
    sex_text = readable_sex_text(sex)
    parts = [genotype_text]
    if age_text and age_text != "Unspecified":
        parts.append(age_text)
    if sex_text and sex_text != "Unspecified":
        parts.append(sex_text)
    return " ".join(parts) + " mice"


def readable_group_label(label: object) -> str:
    parts = [part.strip() for part in str(label).split("|")]
    if len(parts) >= 3:
        return narrative_group_label(parts[0], parts[1], parts[2])
    return str(label).strip()


def group_label_from_average_row(row: pd.Series) -> str:
    return narrative_group_label(
        row.get("Genotype", ""),
        row.get("Age", ""),
        row.get("Sex", ""),
    )


def metric_group_extremes(group_average_summary: pd.DataFrame, metric: str) -> tuple[str, float, str, float]:
    rows = []
    for _, row in group_average_summary.iterrows():
        mean_value, _ = parse_exported_mean_sd(row.get(metric, ""))
        if np.isfinite(mean_value):
            rows.append((group_label_from_average_row(row), float(mean_value)))
    if not rows:
        return "", np.nan, "", np.nan
    rows.sort(key=lambda item: item[1])
    low_label, low_value = rows[0]
    high_label, high_value = rows[-1]
    return low_label, low_value, high_label, high_value


def percent_difference(high_value: float, low_value: float) -> float:
    if not np.isfinite(high_value) or not np.isfinite(low_value) or low_value == 0:
        return np.nan
    return ((high_value - low_value) / abs(low_value)) * 100.0


def marginal_extremes(analyzed_summary: pd.DataFrame, factor: str, metric: str) -> tuple[str, float, float, str, float, float]:
    summaries = []
    if factor not in analyzed_summary.columns or metric not in analyzed_summary.columns:
        return "", np.nan, np.nan, "", np.nan, np.nan
    for level, group in analyzed_summary.groupby(factor, sort=True):
        values = pd.to_numeric(group[metric], errors="coerce").dropna()
        if len(values):
            summaries.append(
                (
                    str(level),
                    float(values.mean()),
                    float(values.std(ddof=1)) if len(values) > 1 else 0.0,
                )
            )
    if not summaries:
        return "", np.nan, np.nan, "", np.nan, np.nan
    summaries.sort(key=lambda item: item[1])
    low_label, low_mean, low_sd = summaries[0]
    high_label, high_mean, high_sd = summaries[-1]
    return low_label, low_mean, low_sd, high_label, high_mean, high_sd


def readable_biological_level(factor: str, level: str) -> str:
    level_text = str(level).strip()
    if factor == "Sex":
        if level_text.upper() == "M":
            return "male"
        if level_text.upper() == "F":
            return "female"
    if factor == "Age":
        return f"{level_text}"
    return level_text


def direction_sentence(analyzed_summary: pd.DataFrame, factor: str, metric: str) -> str:
    low_label, low_mean, low_sd, high_label, high_mean, high_sd = marginal_extremes(analyzed_summary, factor, metric)
    if not high_label or not low_label:
        return ""
    high_label = readable_biological_level(factor, high_label)
    low_label = readable_biological_level(factor, low_label)
    percent = percent_difference(high_mean, low_mean)
    percent_text = f", a {percent:.0f}% increase" if np.isfinite(percent) else ""
    return (
        f"{high_label} specimens had greater {metric} than {low_label} specimens "
        f"({high_mean:.2f} +/- {high_sd:.2f} vs. {low_mean:.2f} +/- {low_sd:.2f}{percent_text})"
    )


def posthoc_comparison_sentence(row: pd.Series) -> str:
    group_1 = readable_group_label(row.get("Group 1", ""))
    group_2 = readable_group_label(row.get("Group 2", ""))
    mean_1 = pd.to_numeric(row.get("Group 1 mean"), errors="coerce")
    mean_2 = pd.to_numeric(row.get("Group 2 mean"), errors="coerce")
    p_text = manuscript_p_value(row.get("Adjusted P value", ""))
    if np.isfinite(mean_1) and np.isfinite(mean_2):
        high_group, high_mean, low_group, low_mean = (
            (group_1, float(mean_1), group_2, float(mean_2))
            if mean_1 >= mean_2
            else (group_2, float(mean_2), group_1, float(mean_1))
        )
        percent = percent_difference(high_mean, low_mean)
        percent_text = f", {percent:.0f}% greater" if np.isfinite(percent) else ""
        return f"{high_group} exceeded {low_group} ({high_mean:.2f} vs. {low_mean:.2f}{percent_text}; {p_text})"
    return f"{group_1} differed from {group_2} ({p_text})"


def build_metric_narrative(
    analyzed_summary: pd.DataFrame,
    group_average_summary: pd.DataFrame,
    statistics_results: pd.DataFrame,
    metric: str,
) -> list[str]:
    paragraphs = []
    low_label, low_value, high_label, high_value = metric_group_extremes(group_average_summary, metric)
    range_text = ""
    if low_label and high_label:
        range_text = f" Group means ranged from {low_value:.2f} in {low_label} to {high_value:.2f} in {high_label}."

    metric_stats = statistics_results[statistics_results["Metric"].astype(str) == metric].copy()
    if metric_stats.empty:
        paragraphs.append(f"{metric} was summarized across metadata-defined groups.{range_text}")
        return paragraphs

    effect_rows = metric_stats[~metric_stats["Test/effect"].astype(str).str.contains("post-hoc", case=False, na=False)]
    sig_effect_rows = effect_rows[effect_rows["Significant (adjusted P < 0.05)"].astype(str).str.lower().eq("true")]
    posthoc_rows = metric_stats[metric_stats["Test/effect"].astype(str).str.contains("post-hoc", case=False, na=False)]
    sig_posthoc = posthoc_rows[posthoc_rows["Significant (adjusted P < 0.05)"].astype(str).str.lower().eq("true")]

    assumption_clause = ""
    if not effect_rows.empty:
        first = effect_rows.iloc[0]
        assumption = str(first.get("Assumption result", "")).strip()
        method = str(first.get("Method", "statistical testing"))
        if "violated" in assumption:
            assumption_clause = f" Because model assumptions were not fully satisfied ({assumption}), {method} was used."
        elif assumption:
            assumption_clause = f" Assumption testing supported parametric analysis ({assumption})."

    if sig_effect_rows.empty:
        paragraphs.append(
            f"{metric} did not differ significantly among the groups tested.{range_text}{assumption_clause}"
        )
        return paragraphs

    statements = []
    for _, row in sig_effect_rows.iterrows():
        method = str(row.get("Method", ""))
        effect = effect_label_to_text(row.get("Test/effect", ""), row.get("Factors", ""))
        statistic = pd.to_numeric(row.get("Statistic"), errors="coerce")
        df1 = pd.to_numeric(row.get("DF1"), errors="coerce")
        df2 = pd.to_numeric(row.get("DF2"), errors="coerce")
        p_text = manuscript_p_value(row.get("Adjusted P value", row.get("P value", "")))
        if "ANOVA" in method and np.isfinite(statistic) and np.isfinite(df1) and np.isfinite(df2):
            if " x " in effect:
                statements.append(f"a significant {effect} interaction was detected (F({df1:.0f},{df2:.0f}) = {statistic:.2f}, {p_text})")
            else:
                direction = direction_sentence(analyzed_summary, effect, metric)
                if direction:
                    statements.append(f"{direction} (F({df1:.0f},{df2:.0f}) = {statistic:.2f}, {p_text})")
                else:
                    statements.append(f"a significant {effect} effect was detected (F({df1:.0f},{df2:.0f}) = {statistic:.2f}, {p_text})")
        elif "Kruskal" in method and np.isfinite(statistic):
            statements.append(f"nonparametric testing revealed significant differences among biological group combinations (H = {statistic:.2f}, {p_text})")
        else:
            statements.append(f"{effect} was significant ({p_text})")

    paragraph = f"{metric} differed among the groups tested: " + "; ".join(statements) + f".{range_text}{assumption_clause}"
    paragraphs.append(paragraph)

    if not sig_posthoc.empty:
        comparisons = [posthoc_comparison_sentence(row) for _, row in sig_posthoc.iterrows()]
        paragraphs.append("Pairwise testing identified " + "; ".join(comparisons) + ".")
    elif not posthoc_rows.empty:
        paragraphs.append("However, no individual post-hoc group comparison remained significant after multiple-comparison correction.")

    return paragraphs


def metric_display_name(metric: str) -> str:
    return {
        "Maximum force (N)": "maximum force",
        "Maximum moment (N.mm)": "maximum bending moment",
        "Apparent modulus (MPa)": "apparent modulus",
        "Yield stress (MPa)": "yield stress",
        "Ultimate stress (MPa)": "ultimate stress",
        "Yield force (N)": "yield force",
        "Yield moment (N.mm)": "yield moment",
        "Elastic bending stiffness (N)": "elastic bending stiffness",
        "Work to maximum moment (N.mm^2)": "work to maximum moment",
    }.get(metric, metric)


def factor_display_name(factor: str) -> str:
    return {"Genotype": "genotype", "Sex": "sex", "Age": "age"}.get(factor, factor.lower())


def significant_main_effect_rows(statistics_results: pd.DataFrame, factor: str) -> pd.DataFrame:
    if statistics_results.empty:
        return pd.DataFrame()
    rows = statistics_results[
        statistics_results["Significant (adjusted P < 0.05)"].astype(str).str.lower().eq("true")
        & ~statistics_results["Test/effect"].astype(str).str.contains("post-hoc", case=False, na=False)
    ].copy()
    if rows.empty:
        return rows
    mapped = rows.apply(lambda row: effect_label_to_text(row.get("Test/effect", ""), row.get("Factors", "")), axis=1)
    return rows[mapped == factor]



def percent_increase_text(percent: float) -> str:
    if not np.isfinite(percent):
        return ""
    rounded = int(round(percent))
    return f", an increase of {rounded}%"


def sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def format_narrative_mean_sd(mean_value: float, sd_value: float) -> str:
    if not np.isfinite(mean_value):
        return "not available"
    if np.isfinite(sd_value):
        return f"{mean_value:.2f} +/- {sd_value:.2f}"
    return f"{mean_value:.2f}"


def factor_effect_sentence(analyzed_summary: pd.DataFrame, row: pd.Series, factor: str) -> str:
    metric = str(row.get("Metric", ""))
    statistic = pd.to_numeric(row.get("Statistic"), errors="coerce")
    df1 = pd.to_numeric(row.get("DF1"), errors="coerce")
    df2 = pd.to_numeric(row.get("DF2"), errors="coerce")
    p_text = manuscript_p_value(row.get("Adjusted P value", row.get("P value", "")))
    low_label, low_mean, low_sd, high_label, high_mean, high_sd = marginal_extremes(analyzed_summary, factor, metric)
    metric_name = metric_display_name(metric)

    if high_label and low_label and np.isfinite(high_mean) and np.isfinite(low_mean):
        high_readable = readable_biological_level(factor, high_label)
        low_readable = readable_biological_level(factor, low_label)
        percent = percent_difference(high_mean, low_mean)
        percent_text = percent_increase_text(percent)
        values = f"{format_narrative_mean_sd(high_mean, high_sd)} vs. {format_narrative_mean_sd(low_mean, low_sd)}"
        if factor == "Genotype":
            direction = f"{metric_name.capitalize()} was higher in {high_readable} than in {low_readable} femurs ({values}{percent_text})"
        elif factor == "Sex":
            direction = f"{high_readable.capitalize()} femurs had higher {metric_name} than {low_readable} femurs ({values}{percent_text})"
        elif factor == "Age":
            direction = f"{metric_name.capitalize()} was higher in {high_readable} than in {low_readable} mice ({values}{percent_text})"
        else:
            direction = f"{metric_name.capitalize()} was higher in {high_readable} than in {low_readable} ({values}{percent_text})"
    else:
        direction = f"{sentence_case(factor_display_name(factor))} was associated with {metric_name}"

    if np.isfinite(statistic) and np.isfinite(df1) and np.isfinite(df2):
        return f"{direction}; F({df1:.0f},{df2:.0f}) = {statistic:.2f}, {p_text}."
    return f"{direction}; {p_text}."


def factor_no_effect_sentence(statistics_results: pd.DataFrame, factor: str) -> str:
    if statistics_results.empty:
        return f"Statistical results were not available for the {factor_display_name(factor)} comparison."
    tested_metrics = sorted(statistics_results["Metric"].dropna().astype(str).unique())
    if not tested_metrics:
        return f"Statistical results were not available for the {factor_display_name(factor)} comparison."
    return f"No independent {factor_display_name(factor)} effect was detected for the structural or material outcomes tested."


def significant_posthoc_for_metrics(statistics_results: pd.DataFrame, metrics: set[str]) -> list[str]:
    if statistics_results.empty or not metrics:
        return []
    posthoc = statistics_results[
        statistics_results["Metric"].astype(str).isin(metrics)
        & statistics_results["Test/effect"].astype(str).str.contains("post-hoc", case=False, na=False)
        & statistics_results["Significant (adjusted P < 0.05)"].astype(str).str.lower().eq("true")
    ]
    return [posthoc_comparison_sentence(row) for _, row in posthoc.iterrows()]


def group_range_sentence(group_average_summary: pd.DataFrame, metric: str) -> str:
    low_label, low_value, high_label, high_value = metric_group_extremes(group_average_summary, metric)
    if not low_label or not high_label:
        return ""
    return f"Group means ranged from {low_value:.2f} in {low_label} to {high_value:.2f} in {high_label}."


def metric_priority(metric: str) -> tuple[int, str]:
    preferred_order = [
        "Yield stress (MPa)",
        "Ultimate stress (MPa)",
        "Apparent modulus (MPa)",
        "Energy to max stress (MPa)",
        "Maximum force (N)",
        "Maximum moment (N.mm)",
        "Elastic bending stiffness (N)",
        "Work to maximum moment (N.mm^2)",
    ]
    try:
        return preferred_order.index(metric), metric
    except ValueError:
        return len(preferred_order), metric


def ordered_factor_rows(statistics_results: pd.DataFrame, factor: str) -> pd.DataFrame:
    rows = significant_main_effect_rows(statistics_results, factor)
    if rows.empty:
        return rows
    rows = rows.copy()
    rows["_metric_order"] = rows["Metric"].astype(str).map(metric_priority)
    return rows.sort_values("_metric_order").drop(columns=["_metric_order"])


def factor_section_paragraphs(
    analyzed_summary: pd.DataFrame,
    statistics_results: pd.DataFrame,
    factor: str,
) -> list[str]:
    rows = ordered_factor_rows(statistics_results, factor)
    if rows.empty:
        return [factor_no_effect_sentence(statistics_results, factor)]

    material_rows = [row for _, row in rows.iterrows() if str(row.get("Metric", "")) in MATERIAL_PROPERTY_METRICS]
    structural_rows = [row for _, row in rows.iterrows() if str(row.get("Metric", "")) in STRUCTURAL_PROPERTY_METRICS]
    other_rows = [
        row
        for _, row in rows.iterrows()
        if str(row.get("Metric", "")) not in MATERIAL_PROPERTY_METRICS
        and str(row.get("Metric", "")) not in STRUCTURAL_PROPERTY_METRICS
    ]

    paragraphs = []
    if factor == "Genotype":
        ordered_groups = [material_rows, structural_rows, other_rows]
    else:
        ordered_groups = [structural_rows, material_rows, other_rows]
    for group in ordered_groups:
        if group:
            paragraphs.append(" ".join(factor_effect_sentence(analyzed_summary, row, factor) for row in group))

    metrics = set(rows["Metric"].astype(str))
    posthoc = significant_posthoc_for_metrics(statistics_results, metrics)
    if posthoc:
        paragraphs.append("Pairwise testing identified " + "; ".join(posthoc) + ".")
    return paragraphs


def significant_nonparametric_rows(statistics_results: pd.DataFrame) -> pd.DataFrame:
    if statistics_results.empty:
        return pd.DataFrame()
    rows = statistics_results[
        statistics_results["Significant (adjusted P < 0.05)"].astype(str).str.lower().eq("true")
        & statistics_results["Method"].astype(str).str.contains("Kruskal", case=False, na=False)
    ].copy()
    if rows.empty:
        return rows
    rows["_metric_order"] = rows["Metric"].astype(str).map(metric_priority)
    return rows.sort_values("_metric_order").drop(columns=["_metric_order"])


def nonparametric_group_paragraphs(group_average_summary: pd.DataFrame, statistics_results: pd.DataFrame) -> list[str]:
    rows = significant_nonparametric_rows(statistics_results)
    paragraphs = []
    for _, row in rows.iterrows():
        metric = str(row.get("Metric", ""))
        statistic = pd.to_numeric(row.get("Statistic"), errors="coerce")
        p_text = manuscript_p_value(row.get("Adjusted P value", row.get("P value", "")))
        metric_name = metric_display_name(metric)
        if np.isfinite(statistic):
            sentence = f"{metric_name.capitalize()} differed among the stratified genotype, age, and sex groups (H = {statistic:.2f}, {p_text})."
        else:
            sentence = f"{metric_name.capitalize()} differed among the stratified genotype, age, and sex groups ({p_text})."
        range_text = group_range_sentence(group_average_summary, metric)
        if range_text:
            sentence += " " + range_text
        paragraphs.append(sentence)
        posthoc = significant_posthoc_for_metrics(statistics_results, {metric})
        if posthoc:
            paragraphs.append("Pairwise testing identified " + "; ".join(posthoc) + ".")
        else:
            paragraphs.append("After correction for multiple testing, no single pairwise contrast accounted for the omnibus effect.")
    return paragraphs


def yield_methods_description(summary: pd.DataFrame) -> str:
    """Describe the recorded analysis, not the current sidebar selections."""
    methods = set(summary.get("Yield requested method", pd.Series(dtype=str)).dropna())
    methods.update(summary.get("Yield method", pd.Series(dtype=str)).dropna())
    attempted = summary.get("Yield methods attempted", pd.Series(dtype=str)).fillna("")
    for method in ("Offset", "Proportional limit"):
        if attempted.str.contains(method, regex=False).any():
            methods.add(method)
    text = ""
    if "Automatic" in methods:
        text += (
            "Yield criteria were selected separately for each specimen according to availability of a complete stress-strain curve. "
            "For structural-only analysis, proportional limit was attempted first, followed by 0.01 mm and 0.005 mm displacement offsets if needed. "
            "For specimens with stress and strain, 0.1% strain offset was attempted first, then 0.05%, followed by proportional limit if neither offset criterion was met. "
            "For direct material analysis, the stress-strain regression line was shifted by strain fractions of 0.001 and 0.0005. "
            "Equivalent displacement offsets were recorded for the structural display. The first valid estimate was retained. "
        )
        lower_attempts = [f"{percent:g}%" for percent in (5, 2.5)
                          if attempted.map(lambda trace: f"Proportional limit ({percent:g}%)" in trace.split(" -> ")[3:]).any()]
        if lower_attempts:
            text += (
                "When the initial automatic criteria failed, additional proportional-limit attempts used "
                + " then ".join(lower_attempts)
                + " departure from the elastic prediction, retaining the same smoothing, confirmation window, and pre-peak search restriction. "
            )
    if "Proportional limit" in methods:
        text += (
            "Yield was estimated operationally as the proportional limit: the first sustained downward crossing "
            "of (1-r) times the elastic prediction by the rolling-median-smoothed response, using E epsilon+b for material curves or K delta+b for structural-only curves, "
            "and r was the selected fractional departure. Only crossings after the fitted region and before "
            "the measured peak were eligible, with no post-peak points used for smoothing. This criterion "
            "describes departure from proportionality, not independently verified permanent deformation. "
        )
    if "Offset" in methods:
        text += (
            "Offset yield used the first pre-peak intersection after the elastic fit with a parallel line "
            "shifted by the selected offset: E(epsilon-offset_strain)+b in direct stress-strain analysis, "
            "or K(delta-offset)+b for structural-only analysis. "
        )
    criteria = summary.get("Yield criterion", pd.Series(dtype=str)).dropna()
    for criterion in criteria[criteria.astype(str).str.len() > 0].unique():
        text += f"The applied criterion was {criterion}. "
    used = summary.get("Yield method", pd.Series(dtype=str)).value_counts()
    if not used.empty:
        text += "Yield classifications were " + "; ".join(f"{method}, n={count}" for method, count in used.items()) + ". "
    fallback_count = int(summary.get("Yield fallback used", pd.Series(dtype=bool)).fillna(False).sum())
    if fallback_count:
        text += (
            f"For {fallback_count} specimen{'s' if fallback_count != 1 else ''} without a detected yield under the primary criterion, "
            "the alternative criterion supplied the yield estimate. The method used was retained per specimen; "
            "combined yield comparisons therefore contain different operational definitions. "
        )
    reduced_count = int(summary.get("Yield reduced offset used", pd.Series(dtype=bool)).fillna(False).sum())
    if reduced_count:
        text += (
            f"For {reduced_count} specimen{'s' if reduced_count != 1 else ''}, a single retry at half the primary offset supplied the estimate. "
            "The actual offset was recorded for each specimen; these adaptive estimates used a different proof-offset criterion. "
        )
    reduced_proportional_count = int(summary.get("Yield reduced proportional limit used", pd.Series(dtype=bool)).fillna(False).sum())
    if reduced_proportional_count:
        text += (
            f"A reduced proportional-limit departure threshold supplied the estimate for {reduced_proportional_count} specimens. "
            "These estimates used a different operational yield definition; the actual threshold was retained per specimen. "
        )
    text += "Yield remained missing when none of the attempted criteria was met; other specimen properties remained available. "
    return text


def generate_methods_narrative_text(
    analyzed_summary: pd.DataFrame,
    group_average_summary: pd.DataFrame,
    statistics_results: pd.DataFrame,
    geometry: BendingGeometry,
) -> str:
    geometry.validate()
    if geometry.test_type == THREE_POINT:
        test_name = "Three-point"
        moment_method = (
            f"Corrected force-displacement data were converted to the maximum bending moment at midspan using M = FS/4, "
            f"where F is the central applied force and S is the support span ({geometry.support_span_mm:g} mm). "
        )
        strain_equation = "epsilon = 12c delta/S^2"
    else:
        test_name = "Four-point"
        moment_method = (
            f"Corrected force-displacement data were converted to bending moment using M = F(S-L)/4, "
            f"where F is the total applied force, S is the lower support span ({geometry.support_span_mm:g} mm), "
            f"and L is the upper loading span ({geometry.loading_span_mm:g} mm). "
        )
        strain_equation = (
            "epsilon = 12c delta/[(S-L)(S+2L)]"
            if geometry.displacement_location == LOADING_POINTS
            else "epsilon = 24c delta/[3S^2-(S-L)^2]"
        )
    deflection_description = (
        "deflection at the upper loading points; crosshead travel was treated as loading-point specimen deflection"
        if geometry.effective_displacement_location == LOADING_POINTS
        else "midspan specimen deflection"
    )
    has_metadata = "Metadata matched" in analyzed_summary and analyzed_summary["Metadata matched"].fillna(False).any()
    has_derived_cy = (
        "Material geometry source" in analyzed_summary
        and analyzed_summary["Material geometry source"].astype(str).str.startswith("Supplied Ixx/Cy:").any()
    )
    geometry_method = (
        "Specimen-specific Ixx (mm^4) and the precomputed section modulus Ixx/Cy (mm^3) were imported from matched metadata. Stress was calculated directly as moment divided by the supplied Ixx/Cy. The surface distance was derived as Cy = Ixx / (Ixx/Cy), and this derived Cy was used as c in the strain conversion. Ixx and Ixx/Cy were required to describe the same bending axis and cross-sectional region; centroid coordinates CMx and CMy were not used. When the inputs were slice-averaged values, derived Cy was an effective distance rather than the arithmetic mean of slice-specific distances. "
        if has_derived_cy else ""
    )
    specimen_count = len(analyzed_summary)
    group_count = len(group_average_summary) if group_average_summary is not None else 0
    metadata_phrase = (
        f" Metadata were used to assign specimens to {group_count} genotype, age, and sex strata and to import specimen-specific cross-sectional inputs for material-property calculations."
        if has_metadata
        else " When metadata were not provided, analyses were limited to structural force-, displacement-, and bending-moment-based parameters."
    )
    stats_phrase = ""
    if statistics_results is not None and not statistics_results.empty:
        methods = statistics_results.loc[statistics_results["Method"] != "Not run", "Method"].dropna().unique()
        if len(methods):
            stats_phrase = (
                " Statistical comparisons were restricted to the specimens and properties selected for grouped analysis, with complete cases used separately for each property. "
                "Specimens were treated as independent observations. All varying genotype, age, and sex factors were retained; constant or entirely missing variables were not counted as factors. "
                "Residual normality and homogeneity of variance were assessed using Shapiro-Wilk and median-centered Levene tests, respectively. "
                "The applied analyses were " + "; ".join(methods) + ". "
                "Pairwise p-values were adjusted using Tukey HSD for homoscedastic one-way ANOVA or Holm correction for the full selected comparison family within each property, without correction across properties. "
                "Tests were two-sided with alpha = 0.05. Graph annotations represent adjusted pairwise comparisons, not omnibus effects."
            )
            if any("Type III" in method for method in methods):
                stats_phrase += " General linear models used Type III tests with sum contrasts, including interactions among the varying biological factors."
            if any("HC3" in method for method in methods):
                stats_phrase += " Heteroscedastic general linear models used HC3 covariance estimates."
            if any("ANCOVA" in method for method in methods):
                covariates_used = statistics_results.get("Covariates", pd.Series(dtype=str)).dropna().unique()
                stats_phrase += " ANCOVA included common linear slopes for the selected continuous covariates (" + "; ".join(covariates_used) + "), with group comparisons evaluated at mean covariate values."
            if any("Kruskal" in method or "Mann-Whitney" in method for method in methods):
                stats_phrase += " Rank tests compared distributions across observed biological combinations and were not interpreted as tests of factorial main effects or interactions."
        else:
            stats_phrase = " Inferential statistics were not reported because the selected design or data did not meet the requirements of the available models."

    paragraph = (
        f"{test_name} bending data were analyzed with a custom Python/Streamlit batch-processing application. "
        f"CSV files exported from the mechanical testing system were imported for {specimen_count} analyzed femurs. Specimen labels were identified from labeled CSV fields, with cell B4 and the original filename used as fallbacks. "
        "When metadata were supplied, specimen labels were matched first by exact or normalized alphanumeric identifiers. If those labels differed, a unique numeric specimen identifier of up to four digits was used as a fallback while letter prefixes and suffixes were ignored; ambiguous repeated numbers were excluded pending review. Displacement and force data were read from columns B and C beginning at row 11. "
        "Rows with missing or nonnumeric displacement or force values were excluded before analysis. "
        "For each specimen independently, the initial unloaded region of the force-displacement curve was identified from a smoothed force trace by estimating baseline force noise from the early portion of the record and selecting the first sustained loading point that exceeded the baseline threshold and maintained a positive local slope. "
        "All points before this onset were removed. Each specimen's onset displacement and onset force were subtracted from its retained displacement and force values, respectively, so both began at zero. Original instrument values were preserved separately. All subsequent calculations, including post-peak trimming, used these zero-referenced data. "
        "Post-peak tail data were removed when force dropped by the user-specified percentage from the specimen-specific maximum force. "
        f"{moment_method}"
        "Maximum force, maximum moment, displacement at maximum force and moment, and work to maximum moment were calculated from the corrected curves. "
        "Elastic bending stiffness was determined from the pre-peak moment-displacement data by fitting a linear regression to the region with high linearity according to the selected R^2 threshold, with manual adjustment available when needed. "
        f"{yield_methods_description(analyzed_summary)}"
        "Yield force or yield moment values that exceeded the corresponding maximum value were capped at the maximum value, and post-yield displacement was calculated as the displacement at maximum moment minus the yield displacement."
        f"{metadata_phrase} "
        f"{geometry_method}"
        f"When valid I/c and c values were available, bending stress was calculated as sigma = M/(I/c) and bending strain as {strain_equation}, "
        f"where delta was treated as {deflection_description} under a symmetric, simply supported, small-deflection Euler-Bernoulli beam model. "
        "The elastic fitting region was independently selected on each specimen's pre-peak stress-strain data using the selected linearity criterion, and apparent modulus was the slope of a direct stress-versus-strain regression. "
        "Yield stress and strain were obtained from the selected criterion applied directly to the smoothed stress-strain data, rather than by converting a structurally determined yield point. "
        "Ultimate stress and its corresponding strain were taken from the maximum of the measured corrected stress trace; strain at failure was the final retained strain. "
        "Energy density to maximum stress was calculated by trapezoidal integration of the measured stress-strain data in acquisition order up to the first maximum stress, in MPa (equivalently MJ/m^3). "
        "Group averages were calculated as mean +/- SD for each genotype, age, and sex combination."
        f"{stats_phrase}"
    )

    return "\n\n".join(["Biomechanical Data Analysis Methods", paragraph])

def narrative_text_to_doc_bytes(narrative: str) -> bytes:
    paragraphs = [paragraph.strip() for paragraph in narrative.split("\n\n") if paragraph.strip()]
    body_parts = []
    section_headings = {
        "Genotype",
        "Sex",
        "Age",
        "Stratified comparisons",
    }
    for index, paragraph in enumerate(paragraphs):
        if index == 0:
            body_parts.append(f"<h1>{escape(paragraph)}</h1>")
        elif paragraph in section_headings:
            body_parts.append(f"<h2>{escape(paragraph)}</h2>")
        else:
            body_parts.append(f"<p>{escape(paragraph)}</p>")
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>body{font-family:Times New Roman,serif;font-size:12pt;line-height:1.5;}"
        "h1{font-size:16pt;}h2{font-size:13pt;font-style:italic;margin-top:12pt;}p{margin:0 0 12pt 0;}</style></head><body>"
        + "".join(body_parts)
        + "</body></html>"
    )
    return html.encode("utf-8")


def generate_summary_table(processed_data: list[ProcessedSpecimen]) -> pd.DataFrame:
    rows = []
    for item in processed_data:
        row = {
                "Specimen ID": item.display_id,
                "Genotype": item.genotype,
                "Age": item.age,
                "Sex": item.sex,
                "Original specimen ID": item.specimen_id,
                "File name": item.file_name,
                "Specimen label source": item.label_source,
                "Metadata match method": item.metadata_match_method,
                "Original data points": item.original_points,
                "Retained data points": item.retained_points,
                "Leading flat-line points removed": item.removed_points,
                "Detected onset displacement": item.onset_displacement,
                "Detected onset force": item.onset_force,
                "Maximum force (N)": item.maximum_force,
                "Displacement at maximum force (mm)": item.displacement_at_maximum_force,
                "Maximum moment (N.mm)": item.maximum_moment,
                "Displacement at maximum moment (mm)": item.displacement_at_maximum_moment,
                "Work to maximum moment (N.mm^2)": item.work_to_maximum_force,
                "Elastic bending stiffness (N)": item.elastic_stiffness_n_per_mm,
                "Elastic stiffness R^2": item.stiffness_r2,
                "Stiffness region start displacement (mm)": item.stiffness_region_start_displacement,
                "Stiffness region end displacement (mm)": item.stiffness_region_end_displacement,
                "Stiffness region points": item.stiffness_region_points,
                "Stiffness region source": item.stiffness_region_source,
                "Yield displacement (mm)": item.yield_displacement,
                "Yield force (N)": item.yield_force,
                "Yield moment (N.mm)": item.yield_moment,
                "Yield offset used (mm)": item.yield_offset_mm,
                "Yield method": item.yield_method,
                "Yield requested method": item.yield_requested_method,
                "Yield criterion": item.yield_criterion,
                "Yield fallback used": item.yield_fallback_used,
                "Yield reduced offset used": item.yield_reduced_offset_used,
                "Yield methods attempted": item.yield_attempted_methods,
                "Yield analysis basis": item.yield_analysis_basis,
                "Yield offset basis": item.yield_offset_basis,
                "Yield offset used (%)": item.yield_offset_strain * 100,
                "Yield proportional departure used (%)": item.yield_proportional_departure_percent,
                "Yield reduced proportional limit used": item.yield_reduced_proportional_used,
                "Post-yield displacement (mm)": item.post_yield_displacement,
                "Metadata matched": item.metadata_matched,
                "Metadata ID": item.metadata_id,
                "Ixx (mm^4)": item.ixx_mm4,
                "I/c (mm^3)": item.section_modulus_mm3,
                "c (mm)": item.c_mm,
                "Material geometry source": item.material_geometry_source,
                "Apparent modulus (MPa)": item.elastic_modulus_mpa,
                "Apparent modulus R^2": item.elastic_modulus_r2,
                "Yield stress (MPa)": item.yield_stress_mpa,
                "Ultimate stress (MPa)": item.ultimate_stress_mpa,
                "Energy to max stress (MPa)": item.strain_energy_density_to_max_stress_mpa,
                "Strain at yield": item.strain_at_yield,
                "Strain at ultimate stress": item.strain_at_ultimate_stress,
                "Strain at failure": item.strain_at_failure,
                "Post-peak drop threshold (%)": item.post_peak_drop_percent,
                "Post-peak points removed": item.post_peak_points_removed,
                "Bending test": item.geometry.test_type,
                "Loading span L (mm)": item.geometry.effective_loading_span_mm,
                "Support span S (mm)": item.geometry.support_span_mm,
                "Displacement measurement location": item.geometry.effective_displacement_location,
                "Baseline force subtraction applied": item.subtract_baseline,
                "Warning": item.warning,
                "Error": item.error,
            }
        for column, value in item.metadata.items():
            row[f"Metadata: {column}"] = value
        rows.append(row)
    return pd.DataFrame(rows)


def select_processing_summary_columns(summary: pd.DataFrame) -> pd.DataFrame:
    """Return the user-facing processing summary with the requested result columns."""
    return summary[[column for column in PROCESSING_SUMMARY_COLUMNS if column in summary.columns]].copy()


def export_corrected_data(processed_data: list[ProcessedSpecimen]) -> pd.DataFrame:
    frames = [
        item.corrected_data
        for item in processed_data
        if not item.error and not item.corrected_data.empty
    ]
    if not frames:
        return pd.DataFrame(
            columns=[
                "specimen_id",
                "file_name",
                "original_specimen_id",
                "specimen_label_source",
                "metadata_id",
                "metadata_match_method",
                "data_point_index_after_correction",
                "corrected_displacement_mm",
                "force_n",
                "original_displacement_mm",
                "original_force_n",
                "displacement_origin_mm",
                "force_offset_subtracted_n",
                "correction_version",
                "bending_test",
                "loading_span_l_mm",
                "support_span_s_mm",
                "moment_per_force_mm",
                "displacement_measurement_location",
                "bending_moment_n_mm",
                "stiffness_region",
                "stiffness_fit_force_n",
                "offset_yield_line_force_n",
                "yield_point",
                "metadata_matched",
                "genotype",
                "age",
                "sex",
                "ixx_mm4",
                "material_geometry_source",
                "section_modulus_mm3",
                "c_mm",
                "tensile_stress_mpa",
                "tensile_strain",
                "elastic_modulus_fit_stress_mpa",
            ]
        )
    return pd.concat(frames, ignore_index=True)


def figure_to_bytes(fig: plt.Figure, file_format: str) -> bytes:
    buffer = BytesIO()
    fig.savefig(buffer, format=file_format, bbox_inches="tight")
    buffer.seek(0)
    return buffer.getvalue()


def show_plot_with_png_download(fig: plt.Figure, file_name: str) -> None:
    """Keep each download beside the exact figure currently displayed."""
    st.pyplot(fig, clear_figure=False)
    st.download_button(
        "Download PNG",
        figure_to_bytes(fig, "png"),
        file_name=file_name,
        mime="image/png",
        key=f"plot_png_{file_name}",
        icon=":material/download:",
        on_click="ignore",
    )


def plot_material_fit(specimen) -> plt.Figure:
    """Show the exact specimen-level data used for direct material analysis."""
    data = specimen.corrected_data
    tendon = "engineering_stress_mpa" in data
    strain_column = "engineering_strain" if tendon else "tensile_strain"
    stress_column = "engineering_stress_mpa" if tendon else "tensile_stress_mpa"
    x = data[strain_column].to_numpy(dtype=float)
    y = data[stress_column].to_numpy(dtype=float)
    peak = int(np.argmax(y))
    fig, ax = plt.subplots(figsize=(9, 6), dpi=150)
    ax.plot(x, y, color=UR_CHART_COLORS[0], linewidth=1.8, label="Corrected stress-strain")
    ax.fill_between(x[:peak + 1], y[:peak + 1], color=UR_CHART_COLORS[1], alpha=.12,
                    label="Energy density to maximum stress")
    region = data["modulus_region"].to_numpy(dtype=bool)
    ax.scatter(x[region], y[region], s=14, color="#ff9f1c", edgecolor="black", linewidth=.3,
               label="Modulus fitting region", zorder=4)
    ax.plot(x[region], data.loc[region, "elastic_modulus_fit_stress_mpa"], color="#d55e00",
            linewidth=2, label="Direct elastic fit", zorder=5)
    reference = data["yield_reference_stress_mpa"].to_numpy(dtype=float)
    fit_end = float(data["modulus_fit_end_strain"].iloc[0])
    window = (np.arange(len(data)) <= peak) & (x >= fit_end) & np.isfinite(reference)
    ax.plot(x[window], reference[window], linestyle="--", color="#666666", label="Yield criterion")
    if np.isfinite(specimen.yield_stress_mpa):
        ax.scatter([specimen.strain_at_yield], [specimen.yield_stress_mpa], marker="D", s=60,
                   color="#c1121f", edgecolor="black", label="Yield", zorder=6)
    ax.scatter([x[peak]], [y[peak]], marker="^", s=65, color="#00866a", edgecolor="black",
               label="Maximum stress", zorder=6)
    energy = getattr(specimen, "strain_energy_density_to_max_stress_mpa", None)
    if energy is None:
        energy = specimen.strain_energy_density_mj_m3
    details = [f"E = {specimen.elastic_modulus_mpa:.2f} MPa; R^2 = {specimen.elastic_modulus_r2:.4f}",
               f"Maximum stress = {y[peak]:.2f} MPa; strain = {x[peak]:.5f}",
               f"Energy to maximum stress = {energy:.3f} MJ/m^3"]
    if np.isfinite(specimen.yield_stress_mpa):
        details.append(f"Yield stress = {specimen.yield_stress_mpa:.2f} MPa; strain = {specimen.strain_at_yield:.5f}")
    else:
        details.append("Yield: not detected before maximum stress")
    ax.text(.02, .97, "\n".join(details), transform=ax.transAxes, va="top", fontsize=8,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": .9})
    ax.set(title=f"{specimen.display_id} | Direct Stress-Strain Analysis",
           xlabel="Strain (mm/mm)", ylabel="Stress (MPa)", ylim=(0, 1.10 * y[peak]))
    ax.legend(loc="lower right", fontsize=7)
    ax.grid(True, linewidth=.5, alpha=.3)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    return fig


def show_material_fit_inspector(processed, key: str) -> None:
    specimens = [item for item in processed if not item.error and
                 "material_analysis_basis" in item.corrected_data]
    if not specimens:
        return
    with st.expander("Individual stress-strain fits"):
        selected = st.selectbox("Specimen", range(len(specimens)),
                                format_func=lambda index: specimens[index].display_id,
                                key=f"{key}_material_fit_specimen")
        specimen = specimens[selected]
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", specimen.display_id)
        show_plot_with_png_download(plot_material_fit(specimen), f"{key}_{safe_id}_stress_strain_fit.png")


def excel_column_name(index: int) -> str:
    """Return the Excel column name for a 1-based column index."""
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Create a UTF-8 CSV payload with missing values and odd strings handled safely."""
    safe_df = df.where(pd.notna(df), "")
    csv_text = safe_df.to_csv(index=False, lineterminator="\n")
    return csv_text.encode("utf-8", errors="replace")


def result_download(label: str, file_name: str, data: bytes, mime: str) -> None:
    """Register this session's export without writing a shared static file."""
    st.download_button(
        label,
        data=data,
        file_name=file_name,
        mime=mime,
        key=f"result_download_{file_name}",
        on_click="ignore",
    )


def dataframe_to_xlsx_bytes(df: pd.DataFrame, sheet_name: str = "Results") -> bytes:
    """Create a simple XLSX workbook without requiring optional Excel dependencies."""
    buffer = BytesIO()
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    safe_sheet_name = sheet_name[:31].replace(":", " ").replace("/", " ").replace("\\", " ")

    rows = [list(df.columns)] + df.where(pd.notna(df), "").values.tolist()
    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            cell_ref = f"{excel_column_name(column_index)}{row_index}"
            if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
                if np.isfinite(float(value)):
                    cells.append(f'<c r="{cell_ref}"><v>{float(value)}</v></c>')
                    continue
                value = ""
            text = escape(str(value))
            cells.append(f'<c r="{cell_ref}" t="inlineStr"><is><t>{text}</t></is></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(sheet_rows)}</sheetData>"
        "</worksheet>"
    )

    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as workbook:
        workbook.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            "</Types>",
        )
        workbook.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            "</Relationships>",
        )
        workbook.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{escape(safe_sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
            "</workbook>",
        )
        workbook.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        workbook.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        workbook.writestr(
            "docProps/core.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            "<dc:creator>Biomechanical Batch Analyzer</dc:creator>"
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>'
            "</cp:coreProperties>",
        )
        workbook.writestr(
            "docProps/app.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
            'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
            "<Application>Biomechanical Batch Analyzer</Application>"
            "</Properties>",
        )

    buffer.seek(0)
    return buffer.getvalue()


def format_report_value(value) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.3f}"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return str(value)


def add_summary_table_pages(pdf: PdfPages, summary: pd.DataFrame, geometry: BendingGeometry) -> None:
    report_columns = [
        "Specimen ID",
        "Genotype",
        "Age",
        "Sex",
        "Maximum force (N)",
        "Maximum moment (N.mm)",
        "Displacement at maximum moment (mm)",
        "Work to maximum moment (N.mm^2)",
        "Elastic bending stiffness (N)",
        "Elastic stiffness R^2",
        "Yield force (N)",
        "Yield moment (N.mm)",
        "Yield displacement (mm)",
        "Apparent modulus (MPa)",
        "Yield stress (MPa)",
        "Ultimate stress (MPa)",
        "Energy to max stress (MPa)",
        "Strain at yield",
        "Strain at failure",
        "Post-yield displacement (mm)",
    ]
    available_columns = [column for column in report_columns if column in summary.columns]
    report_summary = summary[available_columns].copy()
    rows_per_page = 16

    for page_start in range(0, max(len(report_summary), 1), rows_per_page):
        page = report_summary.iloc[page_start : page_start + rows_per_page]
        fig, ax = plt.subplots(figsize=(11, 8.5), dpi=150)
        ax.axis("off")
        ax.set_title(f"Biomechanical Results Summary\n{geometry.description}", fontsize=14, fontweight="bold", pad=18)

        if page.empty:
            ax.text(0.5, 0.5, "No valid specimen results available.", ha="center", va="center")
        else:
            cell_text = [
                [format_report_value(value) for value in row]
                for row in page.to_numpy()
            ]
            table = ax.table(
                cellText=cell_text,
                colLabels=available_columns,
                cellLoc="center",
                colLoc="center",
                loc="center",
            )
            table.auto_set_font_size(False)
            table.set_fontsize(6)
            table.scale(1.0, 1.45)
            for (row_index, _), cell in table.get_celld().items():
                if row_index == 0:
                    cell.set_text_props(weight="bold")
                    cell.set_facecolor("#e9edf5")

        page_number = page_start // rows_per_page + 1
        page_count = int(np.ceil(max(len(report_summary), 1) / rows_per_page))
        fig.text(
            0.5,
            0.03,
            f"Summary page {page_number} of {page_count}",
            ha="center",
            fontsize=8,
        )
        fig.tight_layout(rect=[0.02, 0.06, 0.98, 0.95])
        pdf.savefig(fig)
        plt.close(fig)


def report_stress_strain_data(specimen: ProcessedSpecimen) -> Optional[tuple[pd.DataFrame, float]]:
    """Use corrected material data only, without altering any measured values."""
    columns = ["tensile_strain", "tensile_stress_mpa"]
    if specimen.error or specimen.corrected_data.empty or not all(
        column in specimen.corrected_data for column in columns
    ):
        return None
    data = specimen.corrected_data.copy()
    for column in columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    finite_stress = data.loc[np.isfinite(data["tensile_stress_mpa"]), "tensile_stress_mpa"]
    if finite_stress.empty:
        return None
    # This is the same peak definition used for the specimen's ultimate stress.
    ultimate_stress = float(finite_stress.max())
    valid = np.isfinite(data["tensile_strain"]) & np.isfinite(data["tensile_stress_mpa"])
    data = data.loc[valid].copy()
    if len(data) < 2 or data["tensile_strain"].nunique() < 2 or ultimate_stress <= 0:
        return None
    return data, ultimate_stress


def select_stress_strain_report_specimens(processed_data):
    """Report material-data gaps only for specimens that were actually analyzed."""
    included, missing_material = [], []
    for specimen in processed_data:
        if specimen.error or specimen.corrected_data.empty:
            continue
        if report_stress_strain_data(specimen) is None:
            missing_material.append(specimen)
        else:
            included.append(specimen)
    return included, missing_material


def add_stress_strain_overlays_to_report_axis(
    ax: plt.Axes, specimen: ProcessedSpecimen, data: pd.DataFrame, ultimate_stress: float,
) -> None:
    """Display native material fits, retaining support for older saved specimens."""
    region_column = "modulus_region" if "modulus_region" in data else "stiffness_region"
    if region_column in data:
        region = data.loc[data[region_column].fillna(False).astype(bool)]
        ax.scatter(
            region["tensile_strain"], region["tensile_stress_mpa"],
            color="#ff9f1c", edgecolor="black", linewidth=.3, s=12,
            zorder=4, label="Elastic region",
        )
        if "elastic_modulus_fit_stress_mpa" in region:
            fit = pd.to_numeric(region["elastic_modulus_fit_stress_mpa"], errors="coerce")
            valid = np.isfinite(fit)
            ax.plot(
                region.loc[valid, "tensile_strain"], fit.loc[valid],
                color="#d55e00", linestyle=":", linewidth=1.5, zorder=5,
                label="Elastic fit",
            )
    reference_column = "yield_reference_moment_n_mm" if "yield_reference_moment_n_mm" in data else "offset_yield_line_force_n"
    method = (
        str(data["yield_reference_method"].iloc[0]) if "yield_reference_method" in data and not data.empty
        else getattr(specimen, "yield_requested_method", "Offset")
    )
    if "yield_reference_stress_mpa" in data:
        offset_stress = pd.to_numeric(data["yield_reference_stress_mpa"], errors="coerce")
    elif reference_column in data and (
        np.isfinite(specimen.section_modulus_mm3) and specimen.section_modulus_mm3 > 0
    ):
        # The historical column name holds moment, not force, in this pipeline.
        offset_stress = pd.to_numeric(data[reference_column], errors="coerce") / specimen.section_modulus_mm3
    else:
        offset_stress = pd.Series(np.nan, index=data.index)
    if offset_stress.notna().any():
        valid = np.isfinite(offset_stress)
        if "modulus_fit_end_strain" in data:
            peak_strain = data.loc[data["tensile_stress_mpa"].idxmax(), "tensile_strain"]
            valid &= data["tensile_strain"].between(data["modulus_fit_end_strain"].iloc[0], peak_strain)
        ax.plot(
            data.loc[valid, "tensile_strain"], offset_stress.loc[valid],
            color="#666666", linestyle="--", linewidth=1, zorder=3,
            label="Proportional-limit criterion" if method == "Proportional limit" else "Offset yield line",
        )
    if np.isfinite(specimen.strain_at_yield) and np.isfinite(specimen.yield_stress_mpa):
        ax.scatter(
            [specimen.strain_at_yield], [specimen.yield_stress_mpa],
            marker="D", color="#c1121f", edgecolor="black", linewidth=.4,
            s=28, zorder=6, label="Proportional-limit stress" if method == "Proportional limit" else "Yield stress",
        )

    metrics = [f"Ultimate = {ultimate_stress:.2f} MPa"]
    if np.isfinite(specimen.elastic_modulus_mpa):
        metrics.append(f"E = {specimen.elastic_modulus_mpa:.2f} MPa")
    if np.isfinite(specimen.elastic_modulus_r2):
        metrics.append(f"R^2 = {specimen.elastic_modulus_r2:.3f}")
    if np.isfinite(specimen.yield_stress_mpa):
        label = "Proportional limit" if method == "Proportional limit" else "Offset yield"
        metrics.append(f"{label} = {specimen.yield_stress_mpa:.2f} MPa")
    else:
        metrics.append(f"{method}: not detected")
    metrics.extend(textwrap.wrap(getattr(specimen, "yield_criterion", ""), width=54))
    ax.text(
        .03, .97, "\n".join(metrics), transform=ax.transAxes,
        ha="left", va="top", fontsize=6.5,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": .85, "pad": 2},
    )


def add_individual_stress_strain_plot_pages(
    pdf: PdfPages, processed_data: list[ProcessedSpecimen],
) -> None:
    valid_specimens = []
    for specimen in processed_data:
        curve = report_stress_strain_data(specimen)
        if curve is not None:
            valid_specimens.append((specimen, *curve))
    if not valid_specimens:
        raise ValueError("No valid stress-strain plots are available. Matched Ixx and Ixx/Cy metadata are required.")

    for page_start in range(0, len(valid_specimens), 4):
        specimens = valid_specimens[page_start : page_start + 4]
        fig, axes = plt.subplots(2, 2, figsize=(11, 8.5), dpi=150)
        try:
            axes_flat = axes.flatten()
            for ax, (specimen, data, ultimate_stress) in zip(axes_flat, specimens):
                ax.plot(
                    data["tensile_strain"], data["tensile_stress_mpa"],
                    color=UR_CHART_COLORS[0], linewidth=1.6, label="Stress-strain",
                )
                add_stress_strain_overlays_to_report_axis(ax, specimen, data, ultimate_stress)
                # Lock limits after overlays so offset/fit lines cannot expand them.
                ax.set_ylim(0, 1.10 * ultimate_stress)
                ax.set_xlim(left=min(0, float(data["tensile_strain"].min())))
                ax.set_title(textwrap.fill(str(specimen.display_id), 44), fontsize=11, fontweight="bold")
                ax.set_xlabel("Bending strain (mm/mm)", fontsize=9)
                ax.set_ylabel("Bending stress (MPa)", fontsize=9)
                ax.grid(True, linewidth=.4, alpha=.35)
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                ax.tick_params(labelsize=8)
            for ax in axes_flat[len(specimens):]:
                ax.axis("off")
            descriptions = list(dict.fromkeys(item[0].geometry.description for item in specimens))
            fig.suptitle(
                "Individual Apparent Stress-Strain Curves\n" + " / ".join(descriptions),
                fontsize=13, fontweight="bold",
            )
            page_number = page_start // 4 + 1
            page_count = int(np.ceil(len(valid_specimens) / 4))
            fig.text(
                .5, .04,
                "Orange: elastic region; dotted: elastic fit; dashed: selected yield criterion; diamond: yield estimate (method labeled in each plot).",
                ha="center", fontsize=7,
            )
            fig.text(.5, .02, f"Plot page {page_number} of {page_count}", ha="center", fontsize=8)
            fig.tight_layout(rect=[.03, .065, .98, .93], h_pad=2.5, w_pad=2.2)
            pdf.savefig(fig)
        finally:
            plt.close(fig)


def generate_results_report_pdf(
    processed_data: list[ProcessedSpecimen],
    summary: pd.DataFrame,
    geometry: BendingGeometry,
) -> bytes:
    """Plot-only PDF; summary tables remain available through CSV/Excel exports."""
    buffer = BytesIO()
    with PdfPages(buffer) as pdf:
        add_individual_stress_strain_plot_pages(pdf, processed_data)
    buffer.seek(0)
    return buffer.getvalue()


def reset_application_state() -> None:
    """Clear only this session and move its uploader to a fresh batch key."""
    current_batch_id = st.session_state.get("batch_id", 0)
    for key in list(st.session_state.keys()):
        del st.session_state[key]

    st.session_state["batch_id"] = current_batch_id + 1
    st.session_state["app_state_version"] = APP_STATE_VERSION
    st.rerun()


def build_sidebar() -> tuple[OnsetParameters, StiffnessParameters, YieldParameters, bool, float]:
    st.sidebar.header("Onset detection")
    threshold_multiplier = st.sidebar.number_input(
        "Force threshold multiplier",
        min_value=0.1,
        max_value=50.0,
        value=0.1,
        step=0.1,
        help="Multiplier applied to baseline noise. Higher values delay onset detection.",
    )
    consecutive_points = st.sidebar.number_input(
        "Consecutive positive-slope points",
        min_value=1,
        max_value=50,
        value=15,
        step=1,
    )
    smoothing_window = st.sidebar.number_input(
        "Smoothing window size",
        min_value=1,
        max_value=101,
        value=5,
        step=2,
        help="Centered rolling median window. Even values are rounded down internally.",
    )
    min_force_rise_percent = st.sidebar.slider(
        "Minimum force rise (% of specimen range)",
        min_value=0.0,
        max_value=10.0,
        value=0.5,
        step=0.5,
        help=(
            "Each specimen must rise at least this much above its own baseline "
            "before onset is accepted."
        ),
    )
    max_onset_force = st.sidebar.number_input(
        "Maximum detected onset force (N)",
        min_value=0.0,
        max_value=10.0,
        value=1.0,
        step=0.1,
        help="The final selected onset point will be moved back if its force exceeds this value.",
    )
    st.sidebar.caption("Reference: displacement = 0 mm and force = 0 N at each specimen's loading onset.")
    st.sidebar.header("Post-peak trimming")
    trim_post_peak = st.sidebar.checkbox(
        "Delete data after post-peak force drop",
        value=True,
        help="For each specimen, remove tail data after force drops from that specimen's maximum force.",
    )
    post_peak_drop_percent = st.sidebar.slider(
        "Drop from maximum force (%)",
        min_value=1.0,
        max_value=90.0,
        value=15.0,
        step=1.0,
        disabled=not trim_post_peak,
        help="Example: 20% keeps data through the first post-peak point at or below 80% of max force.",
    )
    st.sidebar.header("Elastic stiffness")
    stiffness_r2_threshold = st.sidebar.slider(
        "Elastic fit R^2 threshold",
        min_value=0.900,
        max_value=0.999,
        value=0.950,
        step=0.001,
        format="%.3f",
        help="Automatic selection searches pre-peak regions meeting this R^2 threshold.",
    )
    stiffness_minimum_points = st.sidebar.number_input(
        "Minimum points in stiffness fit",
        min_value=2,
        max_value=100,
        value=25,
        step=1,
    )
    stiffness_max_search_points = st.sidebar.number_input(
        "Max stiffness search points",
        min_value=25,
        max_value=1000,
        value=250,
        step=25,
        help="Caps the automatic stiffness search for faster batch processing.",
    )
    manual_stiffness_region = st.sidebar.checkbox(
        "Manually set stiffness region",
        value=False,
        help="Apply the same corrected displacement window to each specimen before peak moment.",
    )
    manual_stiffness_start = st.sidebar.number_input(
        "Manual stiffness start displacement (mm)",
        min_value=0.0,
        value=0.0,
        step=0.01,
        format="%.3f",
        disabled=not manual_stiffness_region,
    )
    manual_stiffness_end = st.sidebar.number_input(
        "Manual stiffness end displacement (mm)",
        min_value=0.0,
        value=0.2,
        step=0.01,
        format="%.3f",
        disabled=not manual_stiffness_region,
    )
    st.sidebar.header("Yield estimation")
    yield_method = st.sidebar.selectbox(
        "Yield method", ["Automatic", "Proportional limit", "Offset"], key="yield_method_policy_v4",
        help="Automatic, per specimen: with stress-strain, try 0.1% strain offset, then 0.05%, then proportional limit. Without a complete material curve, try proportional limit, then 0.01 mm, then 0.005 mm. Optional 5% and 2.5% proportional limits follow only if this sequence fails. Shared by bending and tensile tests. Manual choices override this sequence.",
    )
    lower_proportional_fallback = st.sidebar.checkbox(
        "Try 5% then 2.5% proportional-limit fallbacks", value=True,
        key="yield_fallback_lower_proportional_limits", disabled=yield_method != "Automatic",
        help="Automatic mode only, after all initial criteria fail. These are departures from predicted force or moment, not strain offsets. Only thresholds below the selected departure are attempted; confirmation points and the pre-peak restriction remain unchanged.",
    )
    with st.sidebar.expander("Manual yield overrides", expanded=yield_method != "Automatic"):
        yield_fallback = st.checkbox(
            "Try the other method when yield is missing", value=True,
            key="yield_fallback_other_method", disabled=yield_method == "Automatic",
            help="Manual mode only: try the selected method first, then the other method if no valid yield is detected.",
        )
        half_offset_fallback = st.checkbox(
            "Try half the offset if both methods fail", value=True,
            key="yield_fallback_half_offset", disabled=yield_method == "Automatic" or not yield_fallback,
            help="Manual mode only: one final offset attempt at 50% of the configured displacement offset.",
        )
        use_fixed_yield_offset = st.checkbox(
            "Use fixed yield offset", value=True,
            help="Manual mode only: use a fixed displacement offset. The default is 0.01 mm.",
            disabled=yield_method == "Automatic" or (yield_method != "Offset" and not yield_fallback),
        )
        fixed_yield_offset_mm = st.number_input(
            "Fixed yield offset (mm)", min_value=0.0, value=0.01,
            step=0.001, format="%.3f",
            disabled=yield_method == "Automatic" or not use_fixed_yield_offset or (yield_method != "Offset" and not yield_fallback),
        )
    proportional_departure = st.sidebar.number_input(
        "Departure from elastic fit (%)", min_value=0.1, max_value=50.0,
        value=10.0, step=1.0, disabled=yield_method == "Offset" and not yield_fallback,
        help="First sustained crossing below (1 - departure/100) times the elastic prediction, after the fit and before the measured peak.",
    )
    proportional_points = st.sidebar.number_input(
        "Proportional-limit confirmation points", min_value=1, max_value=100,
        value=5, step=1, disabled=yield_method == "Offset" and not yield_fallback,
        help="Consecutive smoothed points required below the criterion. No peak substitution is made if the criterion is not met.",
    )
    yield_smoothing_window = st.sidebar.number_input(
        "Yield smoothing window",
        min_value=1,
        max_value=101,
        value=5,
        step=2,
        help="Rolling median used for yield detection; proportional-limit smoothing excludes post-peak data.",
    )
    st.sidebar.divider()
    st.sidebar.button(
        "Reset and start new batch",
        help="Clear uploaded files and prior results from this browser session.",
        on_click=reset_application_state,
    )

    parameters = OnsetParameters(
        threshold_multiplier=float(threshold_multiplier),
        consecutive_points=int(consecutive_points),
        smoothing_window=int(smoothing_window),
        min_force_rise_fraction=float(min_force_rise_percent) / 100.0,
        max_onset_force=float(max_onset_force),
    )
    stiffness_parameters = StiffnessParameters(
        r2_threshold=float(stiffness_r2_threshold),
        minimum_points=int(stiffness_minimum_points),
        max_search_points=int(stiffness_max_search_points),
        manual_region_enabled=manual_stiffness_region,
        manual_start_displacement=float(manual_stiffness_start),
        manual_end_displacement=float(manual_stiffness_end),
    )
    yield_parameters = YieldParameters(
        use_fixed_offset=use_fixed_yield_offset,
        fixed_offset_mm=float(fixed_yield_offset_mm),
        smoothing_window=int(yield_smoothing_window),
        method=yield_method,
        proportional_departure_fraction=float(proportional_departure) / 100.0,
        proportional_consecutive_points=int(proportional_points),
        fallback_other_method=yield_fallback,
        fallback_half_offset=half_offset_fallback,
        fallback_lower_proportional_limits=lower_proportional_fallback,
    )
    return (
        parameters,
        stiffness_parameters,
        yield_parameters,
        trim_post_peak,
        float(post_peak_drop_percent) / 100.0,
    )


def invalidate_geometry_results() -> None:
    """Discard calculated results on fixture changes while retaining uploaded files."""
    if st.session_state.get("processed_data"):
        st.session_state["geometry_changed"] = True
    st.session_state["processed_data"] = None


def invalidate_yield_results(parameters: YieldParameters) -> None:
    """Retain uploads but retire results from a different yield definition."""
    signature = (
        "direct-stress-strain-material-analysis-v6", parameters.method,
        parameters.use_fixed_offset, parameters.fixed_offset_mm,
        parameters.smoothing_window, parameters.proportional_departure_fraction,
        parameters.proportional_consecutive_points,
        parameters.fallback_other_method,
        parameters.fallback_half_offset,
        parameters.fallback_lower_proportional_limits,
    )
    if st.session_state.get("yield_analysis_signature") != signature:
        for result_key, flag in (("processed_data", "yield_changed"), ("tendon_processed_data", "tendon_yield_changed")):
            if st.session_state.get(result_key) is not None:
                st.session_state[flag] = True
            st.session_state[result_key] = None
        st.session_state["yield_analysis_signature"] = signature


def invalidate_outdated_corrections() -> None:
    """Clear pre-zeroing results without discarding the uploads or settings."""
    if st.session_state.get("correction_version") != CORRECTION_VERSION:
        st.session_state["correction_changed"] = st.session_state.get("processed_data") is not None
        st.session_state["processed_data"] = None
        st.session_state["correction_version"] = CORRECTION_VERSION


def invalidate_material_results() -> None:
    """Prevent old material results being shown under a new metadata mapping."""
    if st.session_state.get("processed_data"):
        st.session_state["material_inputs_changed"] = True
    st.session_state["processed_data"] = None


def invalidate_outdated_material_inputs() -> None:
    """Retire old c selections and cached results without clearing uploads."""
    if st.session_state.get("material_input_version") != MATERIAL_INPUT_VERSION:
        invalidate_material_results()
        for key in ("material_geometry_mode", "material_cy_column", "material_c_column", "material_ic_column"):
            st.session_state.pop(key, None)
        st.session_state["material_input_version"] = MATERIAL_INPUT_VERSION


def change_bending_test() -> None:
    # A segmented control can be deselected; keep one mode so uploads stay mounted.
    if st.session_state.get("bending_test_type") is None:
        st.session_state["bending_test_type"] = st.session_state.get("last_bending_test_type", THREE_POINT)
        return
    invalidate_geometry_results()


def build_geometry_inputs(test_type: str = THREE_POINT) -> tuple[BendingGeometry, bool]:
    st.subheader("Test geometry")
    geometry_cols = st.columns([2, 1])
    with geometry_cols[0]:
        schematic_path = THREE_POINT_SCHEMATIC_IMAGE_PATH if test_type == THREE_POINT else SCHEMATIC_IMAGE_PATH
        if schematic_path.exists():
            st.image(
                str(schematic_path),
                caption=(
                    "3-point bending setup: anterior-to-posterior loading (lateral view); "
                    "support span (S). AI-generated schematic, not to scale."
                    if test_type == THREE_POINT
                    else "4-point bending setup: anterior-to-posterior loading (lateral view); "
                    "loading span (L) and support span (S). AI-generated schematic, not to scale."
                ),
                width="stretch",
            )
        else:
            st.warning("Schematic image file was not found.")

    with geometry_cols[1]:
        loading_span_mm = 0.0
        displacement_location = MIDSPAN
        if test_type == FOUR_POINT:
            # The independent value survives Streamlit removing the hidden widget.
            loading_span_mm = st.number_input(
                "Loading span L (mm)",
                min_value=0.0,
                value=st.session_state.get("saved_loading_span_mm", 3.5),
                step=0.1,
                format="%.2f",
                key="loading_span_mm",
                on_change=invalidate_geometry_results,
                help="Distance between the two upper loading points.",
            )
            st.session_state["saved_loading_span_mm"] = loading_span_mm
        support_span_mm = st.number_input(
            "Support span S (mm)",
            min_value=0.0,
            value=9.5,
            step=0.1,
            format="%.2f",
            key="support_span_mm",
            on_change=invalidate_geometry_results,
            help="Distance between the two lower supports.",
        )
        if test_type == FOUR_POINT:
            locations = [MIDSPAN, LOADING_POINTS]
            displacement_location = st.selectbox(
                "Displacement measurement location", locations,
                index=locations.index(st.session_state.get("saved_displacement_location", MIDSPAN)),
                key="displacement_location", on_change=invalidate_geometry_results,
                help="Use the location represented by the testing-system displacement signal. Crosshead travel may include machine compliance and contact indentation; this app does not remove those contributions.",
            )
            st.session_state["saved_displacement_location"] = displacement_location
        st.latex(r"M = \frac{FS}{4}" if test_type == THREE_POINT else r"M = \frac{F(S-L)}{4}")
        st.latex(
            r"\epsilon = \frac{12c\delta}{S^2}"
            if test_type == THREE_POINT
            else (
                r"\epsilon = \frac{12c\delta}{(S-L)(S+2L)}"
                if displacement_location == LOADING_POINTS
                else r"\epsilon = \frac{24c\delta}{3S^2-(S-L)^2}"
            )
        )
        st.caption(f"F: total applied force. Displacement: {displacement_location.lower()}. Small-deflection beam model; no machine-compliance correction.")

    geometry = BendingGeometry(test_type, float(support_span_mm), float(loading_span_mm), displacement_location)
    try:
        geometry.validate()
    except ValueError as exc:
        st.error(str(exc))
        return geometry, False
    return geometry, True


def build_metadata_inputs() -> tuple[
    dict[str, dict[str, list[dict[str, str]]]],
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    pd.DataFrame | None,
    str | None,
]:
    st.subheader("Optional specimen metadata")
    metadata_file = st.file_uploader(
        "Upload metadata (CSV or Excel)",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=False,
        key=f"metadata_csv_file_{st.session_state['batch_id']}",
        help=(
            "Optional. Include one row per specimen with an ID column, specimen information, "
            "Ixx in mm^4 and Ixx/Cy in mm^3. Cy is derived from these two inputs, not from CMy."
        ),
    )
    if metadata_file is None:
        return {}, None, None, None, None, None, None, None

    try:
        metadata_df = load_metadata_data_file(metadata_file)
    except Exception as exc:
        st.warning(f"Metadata file could not be loaded: {exc}")
        return {}, None, None, None, None, None, None, None

    columns = list(metadata_df.columns)
    id_default = infer_column_index(columns, ["specimen id", "sample id", "id #", "id", "specimen", "sample", "mouse"])
    id_column = st.selectbox(
        "Specimen ID column",
        columns,
        index=id_default,
        help="Finds specimen IDs in filenames, labeled cells, and instrument results tables. Matches full labels first, then unique numbers (up to four digits). Explicit metadata alias columns, including microCT sample name, are also checked. Conflicting IDs require review. Repeated full labels can be distinguished by an Instron Run # column and the export filename's run suffix.",
    )
    geometry_options = [None] + [column for column in columns if not is_centroid_column(column)]
    geometry_cols = st.columns(2)
    inertia_column = geometry_cols[0].selectbox(
        "Ixx column (mm^4)", geometry_options,
        index=geometry_options.index(infer_geometry_column(columns, "ixx")),
        format_func=lambda value: "Select column" if value is None else value,
        key="material_ixx_column",
        help="Second moment of area about the neutral x bending axis, in mm^4. Must match the axis and region used for Ixx/Cy.",
    )
    section_modulus_column = geometry_cols[1].selectbox(
        "Ixx/Cy column (mm^3)", geometry_options,
        index=geometry_options.index(infer_geometry_column(columns, "ic")),
        format_func=lambda value: "Select column" if value is None else value,
        key="material_ixx_cy_column",
        help="The precomputed Ixx/Cy value, in mm^3. Stress = M / (Ixx/Cy); surface distance Cy = Ixx / (Ixx/Cy). Not Imin/Cmin or CMy.",
    )
    st.latex(r"\sigma = \frac{M}{(I_{xx}/C_y)},\qquad c=C_y=\frac{I_{xx}}{(I_{xx}/C_y)}")
    st.caption("Ixx and Ixx/Cy must refer to the same bending axis and region. For slice-averaged inputs, derived Cy is an effective surface distance. CMx and CMy are centroid coordinates and are excluded.")
    if inertia_column is None or section_modulus_column is None:
        st.warning("Ixx and Ixx/Cy are not both mapped. Both are required for strain-dependent properties; structural analysis remains available.")
    elif inertia_column == section_modulus_column:
        st.warning("Ixx and Ixx/Cy require different columns and different units.")
    excluded = {id_column, inertia_column, section_modulus_column}
    biological_options = [column for column in columns if column not in excluded]
    biological_defaults = infer_biological_metadata_columns(metadata_df, excluded)
    biological_columns = st.multiselect(
        "Biological variables",
        biological_options,
        default=biological_defaults,
        max_selections=3,
        help=(
            "Choose up to three metadata columns for grouped curves, property graphs, "
            "group averages, and statistical analysis. The original column headings are preserved."
        ),
        key="bending_biological_columns",
    )
    genotype_column, age_column, sex_column = biological_role_columns(biological_columns)
    with st.expander("Preview metadata"):
        st.dataframe(metadata_df.head(100), width="stretch")

    return (
        build_metadata_lookup(metadata_df, id_column),
        id_column,
        genotype_column,
        age_column,
        sex_column,
        section_modulus_column,
        metadata_df,
        inertia_column,
    )


def build_tendon_metadata_inputs():
    st.subheader("Optional tendon metadata")
    metadata_file = st.file_uploader(
        "Upload tendon metadata (CSV or Excel)",
        type=["csv", "xlsx", "xls"], accept_multiple_files=False,
        key=f"tendon_metadata_{st.session_state['batch_id']}",
        help="One row per specimen. The first Excel worksheet is used.",
    )
    if metadata_file is None:
        return {}, None, None, None, None, None, None, None
    try:
        metadata_df = load_metadata_data_file(metadata_file)
    except Exception as exc:
        st.warning(f"Tendon metadata could not be loaded: {exc}")
        return {}, None, None, None, None, None, None, None

    columns = list(metadata_df.columns)
    id_column = st.selectbox(
        "Tendon specimen ID column", columns,
        index=infer_column_index(columns, ["sample label or id", "specimen", "sample", "id"]),
        key="tendon_metadata_id_column",
    )
    optional_columns = [None] + columns
    geometry_cols = st.columns(2)
    area_default = infer_optional_column_index(columns, ["cross-sectional area", "cross sectional area", "area", "csa"])
    gauge_default = infer_optional_column_index(columns, ["initial gauge length", "gauge length", "initial length", "l0"])
    area_column = geometry_cols[0].selectbox(
        "Cross-sectional area column (mm^2)", optional_columns,
        index=(area_default + 1 if area_default is not None else 0),
        format_func=lambda value: "None (structural only)" if value is None else value,
        key="tendon_area_column",
    )
    gauge_column = geometry_cols[1].selectbox(
        "Initial gauge length column (mm)", optional_columns,
        index=(gauge_default + 1 if gauge_default is not None else 0),
        format_func=lambda value: "None (structural only)" if value is None else value,
        key="tendon_gauge_column",
    )

    excluded = {id_column, area_column, gauge_column}
    biological_options = [column for column in columns if column not in excluded]
    biological_defaults = infer_biological_metadata_columns(metadata_df, excluded)
    biological_columns = st.multiselect(
        "Biological variables",
        biological_options,
        default=biological_defaults,
        max_selections=3,
        help=(
            "Choose up to three metadata columns for grouped curves, property graphs, "
            "group averages, and statistical analysis. The original column headings are preserved."
        ),
        key="tendon_biological_columns",
    )
    genotype_column, age_column, sex_column = biological_role_columns(biological_columns)
    with st.expander("Preview tendon metadata"):
        st.dataframe(metadata_df.head(100), width="stretch")
    return (
        build_metadata_lookup(metadata_df, id_column), id_column,
        genotype_column, age_column, sex_column,
        area_column, gauge_column, metadata_df,
    )


def tendon_group_average_table(
    summary: pd.DataFrame,
    factor_labels: dict[str, str] | None = None,
) -> pd.DataFrame:
    metrics = [
        "Maximum force (N)", "Displacement at maximum force (mm)",
        "Work to maximum force (mJ)", "Tensile stiffness (N/mm)",
        "Yield force (N)", "Yield displacement (mm)",
        "Elastic modulus (MPa)", "Yield stress (MPa)",
        "Ultimate tensile stress (MPa)",
        "Strain-energy density to maximum stress (MJ/m^3)",
        "Strain at yield", "Strain at ultimate stress", "Strain at failure",
    ]
    if summary.empty:
        return pd.DataFrame()
    data = summary[(~summary["Error"].astype(bool)) & (summary["Retained data points"] > 0)].copy()
    if data.empty:
        return pd.DataFrame()
    for column in ("Genotype", "Age", "Sex"):
        data[column] = data[column].fillna("").astype(str).map(selected_biological_value)
    rows = []
    for values, group in data.groupby(["Genotype", "Age", "Sex"], dropna=False):
        row = dict(zip(["Genotype", "Age", "Sex"], values))
        row["Analyzed specimens (n)"] = len(group)
        for metric in metrics:
            if metric in group:
                row[metric] = format_mean_sd(group[metric])
        rows.append(row)
    result = pd.DataFrame(rows)
    if factor_labels:
        result = result.rename(columns={key: value for key, value in factor_labels.items() if value})
    return result


def generate_tendon_report_pdf(processed: list[TendonProcessedSpecimen]) -> bytes:
    buffer = BytesIO()
    valid = [item for item in processed if not item.error and not item.corrected_data.empty]
    with PdfPages(buffer) as pdf:
        for page_start in range(0, len(valid), 4):
            specimens = valid[page_start:page_start + 4]
            fig, axes = plt.subplots(2, 2, figsize=(11, 8.5), dpi=150)
            for ax, specimen in zip(axes.flat, specimens):
                data = specimen.corrected_data
                ax.plot(data["corrected_displacement_mm"], data["force_n"], color=UR_NAVY, linewidth=1.5)
                region = data[data.get("stiffness_region", False).astype(bool)] if "stiffness_region" in data else pd.DataFrame()
                if not region.empty:
                    ax.scatter(region["corrected_displacement_mm"], region["force_n"], color=UR_YELLOWJACKET_GOLD, s=12, zorder=3)
                    ax.plot(region["corrected_displacement_mm"], region["stiffness_fit_force_n"], color="#d55e00", linestyle=":")
                reference_column = "tendon_yield_reference_n" if "tendon_yield_reference_n" in data else "tendon_offset_yield_line_n"
                if reference_column in data:
                    ax.plot(data["corrected_displacement_mm"], data[reference_column], color=UR_CHARCOAL, linestyle="--", linewidth=1)
                if np.isfinite(specimen.yield_displacement):
                    ax.scatter([specimen.yield_displacement], [specimen.yield_force], marker="D", color="#c1121f", s=30, zorder=4)
                ax.text(.03, .97, f"{specimen.yield_method}\n" + (
                    f"Yield = {specimen.yield_force:.2f} N" if np.isfinite(specimen.yield_force)
                    else f"{specimen.yield_requested_method}: not detected"
                ) + "\n" + "\n".join(textwrap.wrap(specimen.yield_criterion, width=54)),
                        transform=ax.transAxes, va="top", fontsize=7,
                        bbox={"facecolor": "white", "edgecolor": "none", "alpha": .85})
                ax.set_title(specimen.display_id, fontsize=10, fontweight="bold")
                ax.set(xlabel="Displacement (mm)", ylabel="Force (N)", xlim=(0, None), ylim=(0, 1.1 * float(data.force_n.max())))
                ax.grid(True, linewidth=.4, alpha=.35); ax.spines[["top", "right"]].set_visible(False)
            for ax in axes.flat[len(specimens):]:
                ax.axis("off")
            fig.suptitle("Individual Tendon Tensile Curves", fontsize=14, fontweight="bold")
            fig.text(.5, .02, "Dashed line: selected yield criterion; diamond: yield estimate; method labeled in each plot.", ha="center", fontsize=8)
            fig.tight_layout(rect=[.02, .05, .98, .95])
            pdf.savefig(fig); plt.close(fig)
    buffer.seek(0)
    return buffer.getvalue()


def build_tendon_bar_layout_controls(
    summary: pd.DataFrame,
    active_factor_roles: list[str],
    factor_labels: dict[str, str],
) -> tuple[str, Optional[str]]:
    """Default to treatment clusters with sex series using metadata headings."""
    data = normalize_bar_graph_data(summary)
    varying = [role for role in active_factor_roles if data[role].nunique() > 1]
    treatment = next((role for role in active_factor_roles if factor_labels[role].casefold() == "treatment"), None)
    sex = next((role for role in active_factor_roles if factor_labels[role].casefold() == "sex"), None)
    default_x = treatment or next(iter(varying), active_factor_roles[0])
    x_key, series_key = "tendon_bar_x_variable", "tendon_bar_series_variable"
    if st.session_state.get(x_key) not in active_factor_roles:
        st.session_state[x_key] = default_x
    columns = st.columns(2)
    x_variable = columns[0].selectbox(
        "Group bars by", active_factor_roles, key=x_key,
        format_func=lambda role: factor_labels[role],
    )
    series_options = [None] + [role for role in active_factor_roles if role != x_variable]
    default_series = sex if sex != x_variable else treatment
    if default_series not in series_options or default_series is None:
        default_series = next((role for role in varying if role != x_variable), None)
    if series_key not in st.session_state or st.session_state[series_key] not in series_options:
        st.session_state[series_key] = default_series
    series_variable = columns[1].selectbox(
        "Side-by-side bars", series_options, key=series_key,
        format_func=lambda role: "None (separate panels)" if role is None else factor_labels[role],
    )
    return x_variable, series_variable


def render_tendon_analysis(
    parameters: OnsetParameters,
    stiffness_parameters: StiffnessParameters,
    yield_parameters: YieldParameters,
    trim_post_peak: bool,
    post_peak_drop_fraction: float,
) -> None:
    render_tendon_header()
    schematic_column, calculation_column = st.columns([1.05, 1], gap="large")
    with schematic_column:
        if TENDON_TENSILE_SCHEMATIC_IMAGE_PATH.exists():
            st.image(
                str(TENDON_TENSILE_SCHEMATIC_IMAGE_PATH),
                width="stretch",
                caption="Tendon specimen secured between tensile grips for uniaxial loading.",
            )
    with calculation_column:
        st.markdown("#### Calculation basis")
        st.markdown("**Structural properties**")
        st.latex(r"K=\frac{dF}{d\delta}")
        st.latex(r"W_{max}=\int_0^{\delta_{max}}F\,d\delta")
        st.markdown("**Material properties**")
        st.latex(r"\sigma=\frac{F}{A},\qquad \epsilon=\frac{\delta}{L_0}")
        st.latex(r"E=\frac{d\sigma}{d\epsilon}=K\frac{L_0}{A}")
        st.caption(
            "Engineering stress and strain are calculated only when positive area and "
            "gauge length are available. Work is reported in mJ; stress-strain area is MJ/m^3."
        )

    metadata_lookup, metadata_id_column, genotype_column, age_column, sex_column, area_column, gauge_column, metadata_df = build_tendon_metadata_inputs()
    factor_labels = biological_factor_label_map(genotype_column, age_column, sex_column)
    metadata_signature = (
        metadata_id_column, genotype_column, age_column, sex_column, area_column, gauge_column,
        "peak-yield-fallback-v1",
        tuple(metadata_df.columns) if metadata_df is not None else None,
        pd.util.hash_pandas_object(metadata_df, index=True).values.tobytes() if metadata_df is not None else None,
    )
    if st.session_state.get("tendon_metadata_signature") != metadata_signature:
        st.session_state["tendon_processed_data"] = None
        st.session_state["tendon_metadata_signature"] = metadata_signature
    active_factor_roles = [
        internal for internal, selected in zip(BAR_GRAPH_VARIABLES, (genotype_column, age_column, sex_column))
        if selected is not None
    ]
    uploaded_files = st.file_uploader(
        "Upload tendon test files (CSV or Excel)", type=["csv", "xlsx", "xls"],
        accept_multiple_files=True, key=f"tendon_test_files_{st.session_state['batch_id']}",
        help="Sample labels and the displacement/force table are detected from the file headings. Legacy files without headings use columns B/C from row 11. The first Excel worksheet is used.",
    )
    if st.button("Run tendon batch processing", type="primary", disabled=not uploaded_files, key="run_tendon_processing") and uploaded_files:
        st.session_state["tendon_yield_changed"] = False
        used_ids: set[str] = set()
        st.session_state["tendon_processed_data"] = [
            process_tendon_file(
                file, parameters, stiffness_parameters, yield_parameters,
                trim_post_peak, post_peak_drop_fraction, used_ids,
                metadata_lookup, metadata_df is not None, metadata_id_column,
                genotype_column, age_column, sex_column, area_column, gauge_column,
            )
            for file in uploaded_files
        ]

    processed = st.session_state.get("tendon_processed_data")
    if not processed:
        st.info("Yield method or settings changed. Run tendon batch processing again with the retained uploads." if st.session_state.get("tendon_yield_changed") else "Upload tendon force-displacement files and run tendon batch processing.")
        return
    full_summary = generate_tendon_summary(processed)
    summary = full_summary.loc[
        (~full_summary["Error"].astype(bool)) & (full_summary["Retained data points"] > 0)
    ].copy()
    valid = [item for item in processed if not item.error and item.retained_points > 0]
    metrics = st.columns(3)
    metrics[0].metric("Processed tendons", len(valid))
    metrics[1].metric("Warnings", sum(bool(item.warning) for item in processed))
    metrics[2].metric("Errors", sum(bool(item.error) for item in processed))
    with st.expander("Tendon specimen label matching", expanded=any(bool(item.error) for item in processed)):
        audit_columns = [
            "File name", "Original specimen ID", "Specimen ID", "Specimen label source",
            "Metadata ID", "Metadata match method", "Instron Run #", "Warning", "Error",
        ]
        st.dataframe(full_summary[[column for column in audit_columns if column in full_summary]], hide_index=True, width="stretch")
    if not valid:
        st.error("No tendon specimens were successfully processed. Review the summary below.")
        st.dataframe(public_summary_with_biological_headers(full_summary, factor_labels), width="stretch")
        return

    st.subheader("Raw tendon data")
    show_plot_with_png_download(plot_raw_curves(processed), "tendon_raw_force_displacement.png")
    st.subheader("Corrected tendon force-displacement")
    show_plot_with_png_download(plot_tendon_force_curves(processed), "tendon_corrected_force_displacement.png")
    st.subheader("Tensile stiffness overlay")
    show_plot_with_png_download(plot_tendon_force_curves(processed, "stiffness"), "tendon_stiffness_overlay.png")
    st.subheader("Yield estimation overlay")
    show_plot_with_png_download(plot_tendon_force_curves(processed, "yield"), "tendon_yield_overlay.png")
    if any(np.isfinite(item.ultimate_stress_mpa) for item in valid):
        st.subheader("Engineering stress-strain data")
        show_plot_with_png_download(plot_tendon_stress_strain(processed), "tendon_engineering_stress_strain.png")
        show_material_fit_inspector(processed, "tendon")

    statistics_results = pd.DataFrame()
    has_groups = bool(active_factor_roles) and any(
        summary[role].fillna("").astype(str).str.strip().astype(bool).any()
        for role in active_factor_roles
    )
    if metadata_df is not None and has_groups:
        st.subheader("Average tendon curves by selected biological variables")
        genotype_options, age_options, sex_options = biological_filter_options(processed)
        filter_cols = st.columns(3)
        selected_genotypes = filter_cols[0].multiselect(
            f"{factor_labels['Genotype']} values to plot", genotype_options, default=genotype_options,
            key="tendon_average_genotypes",
        )
        selected_ages = filter_cols[1].multiselect(
            f"{factor_labels['Age']} values to plot", age_options, default=age_options,
            key="tendon_average_ages",
        )
        selected_sexes = filter_cols[2].multiselect(
            f"{factor_labels['Sex']} values to plot", sex_options, default=sex_options,
            key="tendon_average_sexes",
        )
        selected_sets = (set(selected_genotypes), set(selected_ages), set(selected_sexes))
        average_force = plot_average_grouped_curves(
            processed, "corrected_displacement_mm", "force_n",
            "Displacement (mm)", "Force (N)", "Average Tendon Force-Displacement Curves",
            *selected_sets, factor_labels=factor_labels, common_prepeak=True, show_mean_peak=True,
        )
        show_plot_with_png_download(average_force, "average_tendon_force_displacement.png")
        if any(np.isfinite(item.ultimate_stress_mpa) for item in valid):
            average_stress = plot_average_grouped_curves(
                processed, "engineering_strain", "engineering_stress_mpa",
                "Engineering strain (mm/mm)", "Engineering stress (MPa)",
                "Average Tendon Engineering Stress-Strain Curves", *selected_sets,
                factor_labels=factor_labels, common_prepeak=True,
            )
            show_plot_with_png_download(average_stress, "average_tendon_stress_strain.png")

        filtered_summary = filtered_summary_for_biological_strata(summary, *selected_sets)
        tendon_metric_options = [
            metric for metric in (
                "Maximum force (N)", "Displacement at maximum force (mm)",
                "Work to maximum force (mJ)", "Tensile stiffness (N/mm)",
                "Yield force (N)", "Yield displacement (mm)",
                "Elastic modulus (MPa)", "Yield stress (MPa)",
                "Ultimate tensile stress (MPa)",
                "Strain-energy density to maximum stress (MJ/m^3)",
                "Strain at yield", "Strain at ultimate stress", "Strain at failure",
            )
            if metric in filtered_summary
            and np.isfinite(pd.to_numeric(filtered_summary[metric], errors="coerce")).any()
        ]
        st.subheader("Tendon property graphs and statistics")
        default_tendon_metrics = [metric for metric in (
            "Ultimate tensile stress (MPa)", "Elastic modulus (MPa)",
            "Yield stress (MPa)", "Strain-energy density to maximum stress (MJ/m^3)",
        ) if metric in tendon_metric_options]
        if not default_tendon_metrics:
            default_tendon_metrics = [metric for metric in (
                "Maximum force (N)", "Displacement at maximum force (mm)",
            ) if metric in tendon_metric_options]
        selected_tendon_metrics = st.multiselect(
            "Tendon properties to plot", tendon_metric_options,
            default=default_tendon_metrics,
            key="tendon_bar_metrics",
        )
        x_variable, series_variable = build_tendon_bar_layout_controls(
            filtered_summary, active_factor_roles, factor_labels,
        )
        statistics_results, show_significance = build_statistics_controls(
            filtered_summary, selected_tendon_metrics, key_prefix="tendon_stats",
            factor_labels=factor_labels,
        )
        tendon_bar_figure = plot_metric_bar_graphs(
            filtered_summary, selected_tendon_metrics, x_variable, series_variable,
            statistics_results=statistics_results if show_significance else None,
            factor_labels=factor_labels,
        )
        show_plot_with_png_download(tendon_bar_figure, "tendon_selected_property_graphs.png")
        if not statistics_results.empty:
            with st.expander("Full tendon statistical results"):
                st.dataframe(statistics_results.where(pd.notna(statistics_results), ""), width="stretch")

    st.subheader("Tendon results")
    public_summary = public_summary_with_biological_headers(summary, factor_labels)
    st.dataframe(public_summary, width="stretch")
    group_averages = tendon_group_average_table(summary, factor_labels) if metadata_df is not None else pd.DataFrame()
    downloads = st.columns(6)
    downloads[0].download_button("Corrected data CSV", dataframe_to_csv_bytes(export_tendon_corrected_data(processed)), "tendon_corrected_data.csv", "text/csv", key="tendon_corrected_csv")
    downloads[1].download_button("Results CSV", dataframe_to_csv_bytes(public_summary), "tendon_results.csv", "text/csv", key="tendon_results_csv")
    downloads[2].download_button("Results Excel", dataframe_to_xlsx_bytes(public_summary, "Tendon results"), "tendon_results.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="tendon_results_xlsx")
    if not group_averages.empty:
        downloads[3].download_button("Group averages CSV", dataframe_to_csv_bytes(group_averages), "tendon_group_averages.csv", "text/csv", key="tendon_group_csv")
    if not statistics_results.empty:
        downloads[4].download_button("Statistics CSV", dataframe_to_csv_bytes(statistics_results), "tendon_statistics.csv", "text/csv", key="tendon_statistics_csv")
    downloads[5].download_button("Results report PDF", generate_tendon_report_pdf(processed), "tendon_tensile_results_report.pdf", "application/pdf", key="tendon_report_pdf")


def render_bending_analysis(
    parameters: OnsetParameters,
    stiffness_parameters: StiffnessParameters,
    yield_parameters: YieldParameters,
    trim_post_peak: bool,
    post_peak_drop_fraction: float,
) -> None:

    test_type = st.segmented_control(
        "Bending test",
        options=[THREE_POINT, FOUR_POINT],
        default=THREE_POINT,
        key="bending_test_type",
        on_change=change_bending_test,
    )
    if test_type is None:
        st.info("Select a bending test to continue.")
        return
    st.session_state["last_bending_test_type"] = test_type
    render_ur_brand_header(test_type)

    geometry, geometry_valid = build_geometry_inputs(test_type)
    (
        metadata_lookup,
        metadata_id_column,
        genotype_column,
        age_column,
        sex_column,
        section_modulus_column,
        metadata_df,
        inertia_column,
    ) = build_metadata_inputs()
    factor_labels = biological_factor_label_map(genotype_column, age_column, sex_column)
    active_factor_roles = [
        internal for internal, selected in zip(BAR_GRAPH_VARIABLES, (genotype_column, age_column, sex_column))
        if selected is not None
    ]
    metadata_signature = (
        metadata_id_column, genotype_column, age_column, sex_column,
        section_modulus_column, inertia_column,
        tuple(metadata_df.columns) if metadata_df is not None else None,
        pd.util.hash_pandas_object(metadata_df, index=True).values.tobytes() if metadata_df is not None else None,
    )
    if st.session_state.get("material_metadata_signature") != metadata_signature:
        invalidate_material_results()
        st.session_state["material_metadata_signature"] = metadata_signature
    uploaded_files = st.file_uploader(
        "Upload CSV files",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
        key=f"uploaded_csv_files_{st.session_state['batch_id']}",
        help="CSV and Excel files are accepted; the first Excel worksheet is used.",
    )

    run_processing = st.button(
        "Run batch processing",
        type="primary",
        disabled=not uploaded_files or not geometry_valid,
    )

    if run_processing and uploaded_files:
        st.session_state["yield_changed"] = False
        st.session_state["geometry_changed"] = False
        st.session_state["label_matching_changed"] = False
        st.session_state["material_inputs_changed"] = False
        st.session_state["correction_changed"] = False
        used_ids: set[str] = set()
        metadata_filter_required = metadata_df is not None
        st.session_state["processed_data"] = [
            process_file(
                file,
                parameters,
                stiffness_parameters,
                yield_parameters,
                trim_post_peak,
                post_peak_drop_fraction,
                geometry,
                used_ids,
                metadata_lookup,
                metadata_filter_required,
                metadata_id_column,
                genotype_column,
                age_column,
                sex_column,
                section_modulus_column,
                inertia_column,
            )
            for file in uploaded_files
        ]

    processed_data = st.session_state.get("processed_data")
    if not processed_data:
        if st.session_state.get("yield_changed"):
            st.info("Yield method or settings changed. Run batch processing again with the retained uploads.")
        elif st.session_state.get("correction_changed"):
            st.warning("Correction updated: each specimen is now zeroed in both displacement and force before all calculations. Run batch processing again; previous results must not be reused.")
        elif st.session_state.get("material_inputs_changed"):
            st.info("Metadata or material geometry changed. Run batch processing again with the retained uploads and settings.")
        elif st.session_state.get("label_matching_changed"):
            st.info("Specimen matching updated. Run batch processing again with the retained uploads and settings.")
        elif st.session_state.get("geometry_changed"):
            st.info("Test geometry changed. Run batch processing to calculate results for the selected setup.")
        else:
            st.info("Upload one or more CSV or Excel files, adjust parameters if needed, then run batch processing.")
        return

    full_summary = generate_summary_table(processed_data)
    metadata_skipped_mask = full_summary["Error"].astype(str).str.startswith("Skipped because")
    summary = (
        full_summary.loc[~metadata_skipped_mask].copy()
        if metadata_df is not None
        else full_summary
    )
    corrected = export_corrected_data(processed_data)
    analyzed_summary = summary[
        (~summary["Error"].astype(bool))
        & (pd.to_numeric(summary["Retained data points"], errors="coerce") > 0)
    ].copy()
    processing_summary = select_processing_summary_columns(analyzed_summary)
    public_processing_summary = public_summary_with_biological_headers(processing_summary, factor_labels)
    group_average_summary_internal = (
        generate_group_average_results_table(summary)
        if metadata_df is not None
        else pd.DataFrame(columns=["Genotype", "Age", "Sex", "Analyzed specimens (n)"] + GROUP_AVERAGE_PROPERTY_METRICS)
    )
    group_average_summary = public_summary_with_biological_headers(
        group_average_summary_internal, factor_labels,
    )
    errors = summary["Error"].astype(bool).sum()
    warnings = summary["Warning"].astype(bool).sum()
    valid_count = len(summary) - int(errors)
    skipped_by_metadata = int(metadata_skipped_mask.sum())

    metric_cols = st.columns(3)
    metric_cols[0].metric("Processed specimens", valid_count)
    metric_cols[1].metric("Warnings", int(warnings))
    metric_cols[2].metric("Errors", int(errors))
    if skipped_by_metadata:
        if skipped_by_metadata == len(full_summary):
            st.warning(
                f"No specimens were analyzed: metadata matching skipped all {skipped_by_metadata} uploaded files. "
                "Review the selected Specimen ID column and the specimen label matching table below."
            )
        else:
            st.info(
                f"Metadata filter skipped {skipped_by_metadata} uploaded file(s). "
                "Only specimens matched to the uploaded metadata file were analyzed."
            )

    with st.expander("Specimen label matching", expanded=bool(skipped_by_metadata)):
        label_audit = full_summary[[
            "File name", "Original specimen ID", "Specimen ID", "Specimen label source",
            "Metadata ID", "Metadata match method", "Warning", "Error",
        ]].copy()
        st.dataframe(label_audit, hide_index=True, width="stretch")

    if valid_count:
        st.subheader("Raw data")
        raw_fig = plot_raw_curves(processed_data)
        show_plot_with_png_download(raw_fig, "raw_force_displacement_curves.png")

        st.subheader("Corrected processed data")
        corrected_fig = plot_composite_curves(processed_data)
        show_plot_with_png_download(corrected_fig, "corrected_force_displacement_curves.png")

        st.subheader("Moment-displacement data")
        moment_fig = plot_moment_displacement_curves(processed_data)
        show_plot_with_png_download(moment_fig, "moment_displacement_curves.png")

        st.subheader("Moment-displacement stiffness overlay")
        stiffness_fig = plot_stiffness_overlay_curves(processed_data)
        show_plot_with_png_download(stiffness_fig, "moment_displacement_stiffness_overlay.png")

        st.subheader("Moment-displacement yield overlay")
        yield_fig = plot_yield_overlay_curves(processed_data)
        show_plot_with_png_download(yield_fig, "moment_displacement_yield_overlay.png")

        has_material_data = summary["Metadata matched"].fillna(False).astype(bool).any()
        if has_material_data:
            st.subheader("Apparent stress-strain data")
            stress_strain_fig = plot_stress_strain_curves(processed_data)
            show_plot_with_png_download(stress_strain_fig, "apparent_stress_strain_curves.png")
            show_material_fit_inspector(processed_data, "bending")

        statistics_results = pd.DataFrame()
        has_biological_data = bool(active_factor_roles) and any(
            summary[role].fillna("").astype(str).str.strip().astype(bool).any()
            for role in active_factor_roles
        )
        selected_genotypes = set()
        selected_ages = set()
        selected_sexes = set()
        filtered_biological_summary = summary
        if has_biological_data:
            st.subheader("Average curves by selected biological variables")
            genotype_options, age_options, sex_options = biological_filter_options(processed_data)
            filter_cols = st.columns(3)
            selected_genotypes_list = filter_cols[0].multiselect(
                f"{factor_labels['Genotype']} values to plot",
                genotype_options,
                default=genotype_options,
                help="Choose which genotype groups are included in averaged plots.",
            )
            selected_ages_list = filter_cols[1].multiselect(
                f"{factor_labels['Age']} values to plot",
                age_options,
                default=age_options,
                help="Choose which age strata are included in averaged plots.",
            )
            selected_sexes_list = filter_cols[2].multiselect(
                f"{factor_labels['Sex']} values to plot",
                sex_options,
                default=sex_options,
                help="Choose which sex strata are included in averaged plots.",
            )
            selected_genotypes = set(selected_genotypes_list)
            selected_ages = set(selected_ages_list)
            selected_sexes = set(selected_sexes_list)
            filtered_biological_summary = filtered_summary_for_biological_strata(
                summary,
                selected_genotypes,
                selected_ages,
                selected_sexes,
            )
            if has_material_data:
                average_stress_fig = plot_average_grouped_curves(
                    processed_data,
                    "tensile_strain",
                    "tensile_stress_mpa",
                    "Bending Strain",
                    "Bending Stress (MPa)",
                    "Average Apparent Stress-Strain Curves",
                    selected_genotypes,
                    selected_ages,
                    selected_sexes,
                    factor_labels=factor_labels,
                )
                show_plot_with_png_download(average_stress_fig, "average_stress_strain_by_genotype_age_sex.png")
            else:
                st.info("Average stress-strain curves require matched metadata with valid Ixx and Cy, or precomputed I/c and c.")

            st.subheader("Bar graphs for selected properties")
            filtered_bar_graph_summary, selected_bar_graph_metrics, bar_x_variable, bar_series_variable = build_bar_graph_controls(
                summary,
                {"Genotype": selected_genotypes_list, "Age": selected_ages_list, "Sex": selected_sexes_list},
                factor_labels,
            )
            selected_material_metrics = [
                metric for metric in selected_bar_graph_metrics if metric in MATERIAL_BAR_GRAPH_METRICS
            ]
            if selected_material_metrics and not filtered_bar_graph_summary.empty:
                material_metric = selected_material_metrics[0]
                material_values = pd.to_numeric(filtered_bar_graph_summary[material_metric], errors="coerce")
                material_count = int(material_values.notna().sum())
                selected_count = int(len(filtered_bar_graph_summary))
                if material_count < selected_count:
                    st.warning(
                        f"{material_metric} is available for {material_count} of {selected_count} selected specimens. "
                        "See the specimen warnings below for missing material inputs, elastic fits, or yield estimates."
                    )
                    missing_material = filtered_bar_graph_summary[material_values.isna()][
                        ["Specimen ID", "Genotype", "Age", "Sex", "Metadata matched", "Ixx (mm^4)", "I/c (mm^3)", "c (mm)", "Material geometry source", "Warning"]
                    ].copy()
                    with st.expander("Show specimens excluded from material-property plots"):
                        st.dataframe(missing_material, width="stretch")
            statistics_results, show_significance = build_statistics_controls(
                filtered_bar_graph_summary, selected_bar_graph_metrics,
                factor_labels=factor_labels,
            )
            bar_graph_fig = plot_metric_bar_graphs(
                filtered_bar_graph_summary,
                selected_bar_graph_metrics,
                bar_x_variable,
                bar_series_variable,
                statistics_results=statistics_results if show_significance else None,
                factor_labels=factor_labels,
            )
            show_plot_with_png_download(bar_graph_fig, "selected_property_bar_graphs_by_biological_strata.png")

        if metadata_df is not None:
            st.subheader("Statistical analysis")
            if not has_biological_data:
                stats_metrics = st.multiselect(
                    "Properties for statistics", stats_metric_options(analyzed_summary),
                    key="stats_properties_without_chart",
                )
                statistics_results, _ = build_statistics_controls(
                    analyzed_summary, stats_metrics, factor_labels=factor_labels,
                )
            if not STATISTICS_AVAILABLE:
                st.warning("Statistical analysis requires scipy and statsmodels.")
            elif not statistics_results.empty:
                st.caption(("These results use the selected bar-graph specimens and properties. " if has_biological_data else "These results use the selected properties and all analyzed specimens. ") + "Omnibus effects and multiplicity-adjusted pairwise comparisons are reported separately.")
                with st.expander("Full statistical results"):
                    st.dataframe(statistics_results.where(pd.notna(statistics_results), "").astype(str), width="stretch")
            else:
                st.info("Select properties and at least two biological groups for statistical analysis.")

        download_cols = st.columns(6)
        with download_cols[0]:
            result_download(
                "Corrected data CSV", "corrected_force_displacement_data.csv",
                dataframe_to_csv_bytes(corrected), "text/csv",
            )
        with download_cols[1]:
            result_download(
                "Summary CSV", "processing_summary_analyzed_specimens.csv",
                dataframe_to_csv_bytes(public_processing_summary), "text/csv",
            )
        with download_cols[2]:
            result_download(
                "Summary Excel", "processing_summary_analyzed_specimens.xlsx",
                dataframe_to_xlsx_bytes(public_processing_summary, sheet_name="Analyzed specimens"),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        if metadata_df is not None:
            with download_cols[3]:
                result_download(
                    "Group averages CSV", "group_average_structural_material_properties.csv",
                    dataframe_to_csv_bytes(group_average_summary), "text/csv",
                )
            if not statistics_results.empty:
                with download_cols[4]:
                    result_download(
                        "Stats results CSV", "statistical_analysis_results.csv",
                        dataframe_to_csv_bytes(statistics_results), "text/csv",
                    )
            narrative_text = generate_methods_narrative_text(
                analyzed_summary,
                group_average_summary_internal,
                statistics_results,
                geometry,
            )
            with download_cols[5]:
                result_download(
                    "Methods DOC", "biomechanical_analysis_methods.doc",
                    narrative_text_to_doc_bytes(narrative_text), "application/msword",
                )
        report_specimens, missing_report_material = select_stress_strain_report_specimens(processed_data)
        if not report_specimens:
            st.info("The stress-strain PDF requires analyzed specimens with valid Ixx and Ixx/Cy metadata.")
        if missing_report_material:
            excluded_ids = [str(item.display_id) for item in missing_report_material]
            st.warning("Analyzed specimens without valid material curves are excluded from the stress-strain PDF: " + ", ".join(excluded_ids))
        st.download_button(
            "Download results report PDF",
            generate_results_report_pdf(report_specimens, summary, geometry) if report_specimens else b"",
            file_name="biomechanical_results_report.pdf",
            mime="application/pdf",
            disabled=not report_specimens,
        )
    else:
        st.error("No valid specimens were processed. Review the errors in the summary table.")

    st.subheader("Processing summary")
    st.dataframe(public_processing_summary, width="stretch")

    if not corrected.empty:
        with st.expander("Preview corrected data"):
            st.dataframe(corrected.head(500), width="stretch")


def main() -> None:
    st.set_page_config(
        page_title="URochester | Biomechanics Batch Analyzer",
        page_icon="",
        layout="wide",
    )
    apply_ur_brand_theme()
    st.sidebar.caption(
        "Research use only. Upload only data approved for external hosting. "
        "Files are processed on the hosting server, not solely in your browser."
    )

    if st.session_state.get("app_state_version") != APP_STATE_VERSION:
        next_batch_id = st.session_state.get("batch_id", 0) + 1
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.session_state["batch_id"] = next_batch_id
        st.session_state["app_state_version"] = APP_STATE_VERSION

    st.session_state.setdefault("batch_id", 0)
    st.session_state.setdefault("processed_data", None)
    st.session_state.setdefault("tendon_processed_data", None)
    invalidate_outdated_corrections()
    invalidate_outdated_material_inputs()
    if st.session_state.get("label_matching_version") != LABEL_MATCHING_VERSION:
        st.session_state["label_matching_changed"] = st.session_state["processed_data"] is not None
        st.session_state["processed_data"] = None
        st.session_state["tendon_processed_data"] = None
        st.session_state["label_matching_version"] = LABEL_MATCHING_VERSION

    (
        parameters,
        stiffness_parameters,
        yield_parameters,
        trim_post_peak,
        post_peak_drop_fraction,
    ) = build_sidebar()
    invalidate_yield_results(yield_parameters)

    bending_tab, tendon_tab = st.tabs(["Bone bending", "Tendon tensile test"])
    with bending_tab:
        render_bending_analysis(
            parameters, stiffness_parameters, yield_parameters,
            trim_post_peak, post_peak_drop_fraction,
        )
    with tendon_tab:
        render_tendon_analysis(
            parameters, stiffness_parameters, yield_parameters,
            trim_post_peak, post_peak_drop_fraction,
        )


if __name__ == "__main__":
    main()
