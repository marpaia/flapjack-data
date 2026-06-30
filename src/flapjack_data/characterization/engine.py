"""The characterization engine: turn an :class:`AnalysisSpec` into result rows.

Requires the ``[analysis]`` extra (numpy/scipy/pandas). The engine reads the flattened
measurement frame from a :class:`~flapjack_data.storage.CharacterizationStorage`, assembles a
pandas DataFrame, and dispatches on the analysis type — mirroring Flapjack's ``Analysis`` class —
to produce :class:`~flapjack_data.model.CharacterizationDatum` rows. Time-series analyses emit
one row per timepoint; aggregate analyses emit one row per (sample, signal) with ``time`` unset.

Unlike Flapjack, results are returned as typed objects and can be persisted/cached: ``run`` looks
up a previously computed run by the spec's stable hash before recomputing.
"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from scipy.signal import savgol_filter

from flapjack_data.characterization import inverse, wellfare
from flapjack_data.characterization.types import (
    AGGREGATE_TYPES,
    AnalysisSpec,
    AnalysisType,
    CharacterizationResult,
    MeasurementFrameRow,
    Selection,
)
from flapjack_data.model import Characterization, CharacterizationDatum
from flapjack_data.storage import CharacterizationStorage

#: Whether an analysis subtracts background before running (matches Flapjack's table).
_REMOVE_BACKGROUND = {
    AnalysisType.VELOCITY: False,
    AnalysisType.MEAN_VELOCITY: False,
    AnalysisType.MAX_VELOCITY: False,
    AnalysisType.EXPRESSION_RATE_INDIRECT: True,
    AnalysisType.EXPRESSION_RATE_DIRECT: True,
    AnalysisType.EXPRESSION_RATE_INVERSE: True,
    AnalysisType.MEAN_EXPRESSION: True,
    AnalysisType.MAX_EXPRESSION: True,
    AnalysisType.INDUCTION_CURVE: True,
    AnalysisType.KYMOGRAPH: True,
    AnalysisType.HEATMAP: True,
    AnalysisType.ALPHA: True,
    AnalysisType.RHO: True,
    AnalysisType.BACKGROUND_CORRECT: True,
}

#: The result column each analysis writes into the frame.
_METRIC_COLUMN = {
    AnalysisType.VELOCITY: "Velocity",
    AnalysisType.MEAN_VELOCITY: "Velocity",
    AnalysisType.MAX_VELOCITY: "Velocity",
    AnalysisType.EXPRESSION_RATE_INDIRECT: "Rate",
    AnalysisType.EXPRESSION_RATE_DIRECT: "Rate",
    AnalysisType.EXPRESSION_RATE_INVERSE: "Rate",
    AnalysisType.MEAN_EXPRESSION: "Expression",
    AnalysisType.MAX_EXPRESSION: "Expression",
    AnalysisType.ALPHA: "Alpha",
    AnalysisType.RHO: "Rho",
    AnalysisType.BACKGROUND_CORRECT: "Measurement",
}

_FRAME_COLUMNS = [
    "Sample",
    "Signal_id",
    "Signal",
    "Color",
    "Measurement",
    "Time",
    "Assay",
    "Study",
    "Media",
    "Strain",
    "Vector",
    "Row",
    "Column",
    "Concentrations",
]


def gompertz(t, y0, ymax, um, lag):
    """Gompertz growth model (biomass as a function of time)."""
    a = np.log(ymax / y0)
    log_rel_od = a * np.exp(-np.exp(((um * np.exp(1)) / a) * (lag - t) + 1))
    return y0 * np.exp(log_rel_od)


def _build_frame(rows: Iterable[MeasurementFrameRow]) -> pd.DataFrame:
    records = [
        {
            "Sample": r.sample_id,
            "Signal_id": r.signal_id,
            "Signal": r.signal,
            "Color": r.color,
            "Measurement": r.value,
            "Time": r.time,
            "Assay": r.assay_id,
            "Study": r.study_id,
            "Media": r.media,
            "Strain": r.strain,
            "Vector": r.vector,
            "Row": r.row,
            "Column": r.col,
            "Concentrations": r.concentrations,
        }
        for r in rows
    ]
    if not records:
        return pd.DataFrame(columns=_FRAME_COLUMNS)
    return pd.DataFrame.from_records(records)


def _odd_window(window: int, n: int) -> int:
    """Largest valid odd Savitzky-Golay window ≤ ``window`` and ≤ ``n`` (0 if too few points)."""
    w = int(window)
    if w % 2 == 0:
        w += 1
    if w > n:
        w = n if n % 2 == 1 else n - 1
    return w if w >= 3 else 0


def _smooth(values: np.ndarray, window: int, deriv: int = 0) -> np.ndarray:
    w = _odd_window(window, len(values))
    if w == 0:
        if deriv == 1:
            return np.gradient(values)
        return values
    return savgol_filter(values, w, 2, deriv=deriv, mode="interp")


class Engine:
    """Computes one :class:`AnalysisSpec` against a :class:`CharacterizationStorage`."""

    def __init__(self, spec: AnalysisSpec, storage: CharacterizationStorage) -> None:
        self.spec = spec
        self.storage = storage
        self.biomass_id = spec.biomass_signal_id
        self.ref_id = spec.ref_signal_id
        self._background: dict = {}
        self._dispatch = {
            AnalysisType.VELOCITY: self.velocity,
            AnalysisType.MEAN_VELOCITY: self.mean_velocity,
            AnalysisType.MAX_VELOCITY: self.max_velocity,
            AnalysisType.EXPRESSION_RATE_INDIRECT: self.expression_rate_indirect,
            AnalysisType.EXPRESSION_RATE_DIRECT: self.expression_rate_direct,
            AnalysisType.EXPRESSION_RATE_INVERSE: self.expression_rate_inverse,
            AnalysisType.MEAN_EXPRESSION: self.mean_expression,
            AnalysisType.MAX_EXPRESSION: self.max_expression,
            AnalysisType.INDUCTION_CURVE: self.induction_curve,
            AnalysisType.KYMOGRAPH: self.kymograph,
            AnalysisType.HEATMAP: self.heatmap,
            AnalysisType.ALPHA: self.ratiometric_alpha,
            AnalysisType.RHO: self.ratiometric_rho,
            AnalysisType.BACKGROUND_CORRECT: self.background_correct,
        }

    # Frame assembly -------------------------------------------------------------------

    def analyze(self) -> pd.DataFrame:
        df = _build_frame(self.storage.measurement_frame(self.spec.selection))
        if _REMOVE_BACKGROUND[self.spec.type] and len(df) > 0:
            df = self.bg_correct(df)
        return self._dispatch[self.spec.type](df)

    def get_biomass(self, sample_ids: Iterable[int]) -> pd.DataFrame:
        if self.biomass_id is None:
            return pd.DataFrame(columns=_FRAME_COLUMNS)
        selection = Selection(sample_ids=list({int(s) for s in sample_ids}), signal_ids=[self.biomass_id])
        return _build_frame(self.storage.measurement_frame(selection))

    # Background correction ------------------------------------------------------------

    def _compute_background(self, assay, media, df: pd.DataFrame):
        blanks = df[(df["Assay"] == assay) & (df["Media"] == media)]
        no_cells = blanks[blanks["Vector"].isna() & blanks["Strain"].isna()]
        no_dna = blanks[blanks["Vector"].isna()]

        def stats(sub: pd.DataFrame) -> dict:
            out: dict = {}
            for signal_id, group in sub.groupby("Signal_id"):
                grouped = group.groupby("Time")["Measurement"]
                out[signal_id] = (grouped.mean(), grouped.std().fillna(0.0))
            return out

        return stats(no_cells), stats(no_dna)

    def _get_background(self, assay, media, df: pd.DataFrame):
        key = (assay, media)
        if key not in self._background:
            self._background[key] = self._compute_background(assay, media, df)
        return self._background[key]

    def bg_correct(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) == 0:
            return df
        meas = df.dropna(subset=["Vector"])
        if len(meas) == 0:
            return meas

        rows = []
        for _, sample_data in meas.groupby("Sample"):
            assay = sample_data["Assay"].iloc[0]
            media = sample_data["Media"].iloc[0]
            bg_media, bg_strain = self._get_background(assay, media, df)
            for signal_id, signal_data in sample_data.groupby("Signal_id"):
                signal_data = signal_data.sort_values("Time").copy()
                source = bg_media if signal_id == self.biomass_id else bg_strain
                mean_std = source.get(signal_id)
                values = signal_data["Measurement"].values.astype(float)
                if mean_std is not None:
                    mean_series, std_series = mean_std
                    subtract = signal_data["Time"].map(mean_series).fillna(0.0).values
                    values = values - subtract
                    if self.spec.remove_data:
                        std = signal_data["Time"].map(std_series).fillna(0.0).values
                        if signal_id == self.biomass_id:
                            floor = np.maximum(self.spec.bg_correction * std, self.spec.min_biomass)
                        else:
                            floor = self.spec.bg_correction * std
                        values = np.where(values < floor, np.nan, values)
                signal_data["Measurement"] = values
                rows.append(signal_data)

        result = pd.concat(rows) if rows else pd.DataFrame(columns=df.columns)
        if len(result) > 0:
            result = result.dropna(subset=["Measurement"])
        return result

    # Time-series analyses -------------------------------------------------------------

    def background_correct(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def velocity(self, df: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for _, sample_data in df.groupby("Sample"):
            for _, data in sample_data.groupby("Signal_id"):
                data = data.sort_values("Time").copy()
                val = data["Measurement"].values.astype(float)
                if len(val) <= max(self.spec.pre_smoothing, self.spec.post_smoothing):
                    continue
                velocity = _smooth(val, self.spec.pre_smoothing, deriv=1)
                if self.spec.post_smoothing > 0:
                    velocity = _smooth(velocity, self.spec.post_smoothing)
                data["Velocity"] = velocity
                rows.append(data)
        return pd.concat(rows) if rows else pd.DataFrame(columns=df.columns)

    def expression_rate_indirect(self, df: pd.DataFrame) -> pd.DataFrame:
        density_df = self.bg_correct(self.get_biomass(df["Sample"].unique()))
        rows = []
        for samp_id, sample_data in df.groupby("Sample"):
            density = density_df[density_df["Sample"] == samp_id].sort_values("Time")
            density_time = density["Time"].values.astype(float)
            density_val = density["Measurement"].values.astype(float)
            for _, data in sample_data.groupby("Signal_id"):
                data = data.sort_values("Time").copy()
                time = data["Time"].values.astype(float)
                val = data["Measurement"].values.astype(float)
                min_pts = max(self.spec.pre_smoothing, self.spec.post_smoothing)
                if len(val) <= min_pts or len(density_val) <= min_pts:
                    continue
                sdensity = wellfare.Curve(density_time, _smooth(density_val, self.spec.pre_smoothing))
                tmin = max(time.min(), density_time.min())
                tmax = min(time.max(), density_time.max())
                mask = (time >= tmin) & (time < tmax)
                data = data[(data["Time"] >= tmin) & (data["Time"] < tmax)].copy()
                if mask.sum() < 2:
                    continue
                dt = float(np.mean(np.diff(time)))
                dvaldt = _smooth(val, self.spec.pre_smoothing, deriv=1)[mask] / dt
                ksynth = dvaldt / sdensity(time[mask])
                if self.spec.post_smoothing > 0:
                    ksynth = _smooth(ksynth, self.spec.post_smoothing)
                data["Rate"] = ksynth
                rows.append(data)
        return pd.concat(rows) if rows else pd.DataFrame(columns=df.columns)

    def _expression_rate_model(self, df: pd.DataFrame, *, method: str) -> pd.DataFrame:
        if len(df) == 0:
            return df
        density_df = self.bg_correct(self.get_biomass(df["Sample"].unique()))
        if len(density_df) == 0:
            return density_df
        rows = []
        for samp_id, sample_data in df.groupby("Sample"):
            density = density_df[density_df["Sample"] == samp_id].sort_values("Time")
            odt = density["Time"].values.astype(float)
            ody = density["Measurement"].values.astype(float)
            if len(odt) < 2:
                continue
            cod = wellfare.Curve(odt, ody)
            ttu = np.linspace(odt.min(), odt.max(), 100, endpoint=False)
            for signal_id, data in sample_data.groupby("Signal_id"):
                data = data.sort_values("Time").copy()
                fpt = data["Time"].values.astype(float)
                fpy = data["Measurement"].values.astype(float)
                if len(fpy) <= 1:
                    continue
                cfp = wellfare.Curve(fpt, fpy)
                try:
                    if method == "direct":
                        if signal_id == self.biomass_id:
                            rate = wellfare.infer_growth_rate(cod, ttu, eps_L=self.spec.eps_L, positive=True)
                        else:
                            rate = wellfare.infer_synthesis_rate_onestep(
                                cfp, cod, ttu, degr=self.spec.degr, eps_L=self.spec.eps_L, positive=True
                            )
                    else:
                        if signal_id == self.biomass_id:
                            rate = inverse.characterize_growth(
                                cod(ttu), ttu, n_gaussians=self.spec.n_gaussians, epsilon=self.spec.eps
                            )
                        else:
                            rate = inverse.characterize(
                                cfp(ttu),
                                cod(ttu),
                                ttu,
                                gamma=self.spec.degr,
                                n_gaussians=self.spec.n_gaussians,
                                epsilon=self.spec.eps,
                            )
                    data["Rate"] = rate(fpt)
                    rows.append(data)
                except Exception:
                    continue
        result = pd.concat(rows) if rows else pd.DataFrame(columns=df.columns)
        if len(result) > 0:
            result = result.dropna(subset=["Rate"])
        return result

    def expression_rate_direct(self, df: pd.DataFrame) -> pd.DataFrame:
        return self._expression_rate_model(df, method="direct")

    def expression_rate_inverse(self, df: pd.DataFrame) -> pd.DataFrame:
        return self._expression_rate_model(df, method="inverse")

    # Aggregate analyses ---------------------------------------------------------------

    def _aggregate(self, df: pd.DataFrame, column: str, func: str, out_column: str) -> pd.DataFrame:
        if len(df) == 0:
            return df
        agg = {c: "first" for c in df.columns if c not in ("Sample", "Signal", column)}
        agg[column] = func
        grouped = df.groupby(["Sample", "Signal_id"], as_index=False).agg(agg)
        return grouped.rename(columns={column: out_column})

    def mean_expression(self, df: pd.DataFrame) -> pd.DataFrame:
        return self._aggregate(df, "Measurement", "mean", "Expression")

    def max_expression(self, df: pd.DataFrame) -> pd.DataFrame:
        return self._aggregate(df, "Measurement", "max", "Expression")

    def mean_velocity(self, df: pd.DataFrame) -> pd.DataFrame:
        return self._aggregate(self.velocity(df), "Velocity", "mean", "Velocity")

    def max_velocity(self, df: pd.DataFrame) -> pd.DataFrame:
        return self._aggregate(self.velocity(df), "Velocity", "max", "Velocity")

    # Dose-response analyses -----------------------------------------------------------

    def induction_curve(self, df: pd.DataFrame) -> pd.DataFrame:
        assert self.spec.function is not None, "Induction Curve requires a `function`"
        analyte = self.spec.analyte_id
        data = df[df["Concentrations"].apply(lambda c: analyte in c)].copy()
        if len(data) == 0:
            return pd.DataFrame(columns=df.columns)
        data["Concentration"] = data["Concentrations"].apply(lambda c: c[analyte])
        return self._dispatch[self.spec.function](data)

    def kymograph(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.induction_curve(df)

    def heatmap(self, df: pd.DataFrame) -> pd.DataFrame:
        assert self.spec.function is not None, "Heatmap requires a `function`"
        analyte1, analyte2 = self.spec.analyte1_id, self.spec.analyte2_id
        data = df[df["Concentrations"].apply(lambda c: analyte1 in c and analyte2 in c)].copy()
        if len(data) == 0:
            return pd.DataFrame(columns=df.columns)
        data["Concentration A"] = data["Concentrations"].apply(lambda c: c[analyte1])
        data["Concentration B"] = data["Concentrations"].apply(lambda c: c[analyte2])
        return self._dispatch[self.spec.function](data)

    # Ratiometric analyses -------------------------------------------------------------

    def ratiometric_alpha(self, df: pd.DataFrame) -> pd.DataFrame:
        density_df = self.bg_correct(self.get_biomass(df["Sample"].unique()))
        rows = []
        for samp_id, sample_data in df.groupby("Sample"):
            oddf = density_df[density_df["Sample"] == samp_id].sort_values("Time")
            odt = oddf["Time"].values.astype(float)
            odval = oddf["Measurement"].values.astype(float)
            odt = odt[odval > 0.0]
            odval = odval[odval > 0.0]
            if len(odval) < 4:
                continue
            try:
                bounds = ([1e-2, 0.01, 0, -24], [1, 4, 2, 24])
                params, _ = curve_fit(gompertz, odt, odval, bounds=bounds)
            except Exception:
                continue
            y0, ymax, um, lag = params
            a = np.log(ymax / y0)
            tm = (a / (np.exp(1) * um)) + lag
            doubling = np.log(2) / um
            t1, t2 = tm, tm + self.spec.ndt * doubling

            for _, data in sample_data.groupby("Signal_id"):
                window = data[(data["Time"] >= t1) & (data["Time"] <= t2)].sort_values("Time")
                od_window = oddf[(oddf["Time"] >= t1) & (oddf["Time"] <= t2)].sort_values("Time")
                mt = window["Time"].values.astype(float)
                mval = window["Measurement"].values.astype(float)
                ot = od_window["Time"].values.astype(float)
                ov = od_window["Measurement"].values.astype(float)
                first = data.iloc[0].copy()
                if len(mt) > 1 and len(ot) > 1:
                    tmin = max(ot.min(), mt.min())
                    tmax = min(ot.max(), mt.max())
                    times = np.linspace(tmin, tmax, 100)
                    smval = np.interp(times, mt, mval)
                    sodval = np.interp(times, ot, ov)
                    slope = np.polyfit(sodval, smval, 1)[0]
                    first["Alpha"] = slope
                else:
                    first["Alpha"] = np.nan
                rows.append(first)
        if not rows:
            return pd.DataFrame(columns=list(df.columns) + ["Alpha"])
        return pd.DataFrame(rows)

    def ratiometric_rho(self, df: pd.DataFrame) -> pd.DataFrame:
        alpha = self.ratiometric_alpha(df)
        if len(alpha) == 0:
            return alpha
        alpha_ref = alpha[alpha["Signal_id"] == self.ref_id]
        if len(alpha_ref) == 0:
            return alpha_ref
        alpha = alpha.sort_values("Sample")
        alpha_ref = alpha_ref.sort_values("Sample")
        alpha = alpha.copy()
        alpha["Rho"] = alpha["Alpha"].values / alpha_ref["Alpha"].values
        return alpha


def _effective_type(spec: AnalysisSpec) -> AnalysisType:
    """For dose-response wrappers the result shape is that of the inner ``function``."""
    if spec.type in (AnalysisType.INDUCTION_CURVE, AnalysisType.KYMOGRAPH, AnalysisType.HEATMAP):
        assert spec.function is not None, f"{spec.type.value} requires a `function`"
        return spec.function
    return spec.type


def _cell(row: pd.Series, column: str):
    if column in row and not (isinstance(row[column], float) and math.isnan(row[column])):
        return float(row[column])
    return None


def _to_data(df: pd.DataFrame, spec: AnalysisSpec) -> list[CharacterizationDatum]:
    effective = _effective_type(spec)
    metric_column = _METRIC_COLUMN[effective]
    metric_name = metric_column if effective != AnalysisType.BACKGROUND_CORRECT else "Measurement"
    is_aggregate = effective in AGGREGATE_TYPES
    if spec.type == AnalysisType.RHO:
        metric_column, metric_name = "Rho", "Rho"

    data: list[CharacterizationDatum] = []
    for _, row in df.iterrows():
        if metric_column not in row:
            continue
        value = row[metric_column]
        if value is None or (isinstance(value, float) and math.isnan(value)):
            continue
        concentration = _cell(row, "Concentration")
        if concentration is None:
            concentration = _cell(row, "Concentration A")
        data.append(
            CharacterizationDatum(
                characterization_id=0,
                sample_id=int(row["Sample"]),
                signal_id=int(row["Signal_id"]),
                metric=metric_name,
                value=float(value),
                time=None if is_aggregate else float(row["Time"]),
                concentration=concentration,
                concentration2=_cell(row, "Concentration B"),
            )
        )
    return data


def run(
    spec: AnalysisSpec,
    storage: CharacterizationStorage,
    *,
    persist: bool = False,
    use_cache: bool = True,
) -> CharacterizationResult:
    """Compute (or fetch from cache) the characterization described by ``spec``.

    With ``use_cache`` (default) a previously persisted run with the same params hash is returned
    instead of recomputing. With ``persist`` the freshly computed run and its rows are saved.
    """
    if use_cache:
        existing = storage.query_characterizations(analysis_type=spec.type.value, params_hash=spec.params_hash())
        if existing:
            run_row = existing[0]
            assert run_row.id is not None
            return CharacterizationResult(run_row, storage.get_characterization_data(run_row.id))

    result_df = Engine(spec, storage).analyze()
    data = _to_data(result_df, spec)
    characterization = Characterization(
        analysis_type=spec.type.value,
        spec=spec.to_dict(),
        params_hash=spec.params_hash(),
    )
    if persist:
        stored = storage.save_characterization(characterization, data)
        assert stored.id is not None
        return CharacterizationResult(stored, storage.get_characterization_data(stored.id))
    return CharacterizationResult(characterization, data)
