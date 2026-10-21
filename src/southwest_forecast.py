"""Reproducible Southwest Q3 2026 alternative-data forecast.

The point model intentionally stays simple and explainable.  The surrounding
code makes the data cutoff, cleaning decisions, walk-forward evaluation, and
uncertainty calibration explicit.
"""

from __future__ import annotations

from math import ceil
from pathlib import Path

import numpy as np
import pandas as pd


DATA_CUTOFF = "2026-10-16"
TARGET_QUARTER = pd.Period("2026Q3", freq="Q")
BACKTEST_START = pd.Period("2022Q1", freq="Q")
BACKTEST_END = pd.Period("2026Q2", freq="Q")
CALIBRATION_WINDOW = 12
TARGET_COVERAGE = 0.80

DATA_FILES = {
    "southwest": "southwest_quarterly_stats_2019Q1_2026Q2.csv",
    "tsa": "tsa_daily_checkpoint_2019-01-01_2026-09-30.csv",
    "cpi": "bls_airline_fares_cpi_CUUR0000SETG01_2018-01_2026-09.csv",
    "t100": "bts_t100_domestic_segment_southwest_WN_monthly_2019-01_2026-07.csv",
}

TSA_DISRUPTIONS = (
    ("2025-10-01", "2025-11-12", "federal shutdown"),
    ("2026-02-14", "2026-04-30", "DHS funding lapse"),
)


def repository_root(start: Path | None = None) -> Path:
    """Find the repository from the module, repository root, or notebook folder."""
    candidates = []
    if start is not None:
        candidates.extend([start.resolve(), *start.resolve().parents])
    module_root = Path(__file__).resolve().parents[1]
    candidates.extend([module_root, *module_root.parents])
    for candidate in candidates:
        if (candidate / "Case Study Data Files").is_dir():
            return candidate
    raise FileNotFoundError("Could not locate 'Case Study Data Files'.")


def load_inputs(root: Path | None = None) -> dict[str, pd.DataFrame]:
    root = repository_root(root)
    folder = root / "Case Study Data Files"
    frames = {name: pd.read_csv(folder / filename) for name, filename in DATA_FILES.items()}
    for name, frame in frames.items():
        if frame.empty:
            raise ValueError(f"{name} input is empty")
        if frame.duplicated().any():
            raise ValueError(f"{name} input contains duplicate rows")
    return frames


def prepare_quarterly(inputs: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Clean inputs and align them on a quarterly PeriodIndex.

    TSA observations are retained, not imputed.  Known operational disruption
    days are flagged so affected quarters can be excluded from calibration.
    BLS CPI quarters must have all three monthly observations.
    """
    sw = inputs["southwest"].copy()
    sw.index = pd.PeriodIndex(sw["quarter"], freq="Q")

    tsa = inputs["tsa"].copy()
    tsa["date"] = pd.to_datetime(tsa["date"], errors="raise")
    expected_dates = pd.date_range(tsa["date"].min(), tsa["date"].max(), freq="D")
    missing_dates = expected_dates.difference(tsa["date"])
    if len(missing_dates):
        raise ValueError(f"TSA input is missing {len(missing_dates)} calendar dates")
    if tsa["passengers_screened"].isna().any() or tsa["passengers_screened"].lt(0).any():
        raise ValueError("TSA passenger counts must be complete and nonnegative")

    tsa["disruption_reason"] = ""
    for start, end, reason in TSA_DISRUPTIONS:
        mask = tsa["date"].between(start, end)
        tsa.loc[mask, "disruption_reason"] = reason
    tsa["tsa_disruption"] = tsa["disruption_reason"].ne("")
    tsa["quarter"] = tsa["date"].dt.to_period("Q")
    tsa_q = tsa.groupby("quarter").agg(
        tsa_total=("passengers_screened", "sum"),
        tsa_days=("date", "size"),
        tsa_disruption_days=("tsa_disruption", "sum"),
    )
    tsa_q["tsa_clean_for_calibration"] = tsa_q["tsa_disruption_days"].eq(0)

    cpi = inputs["cpi"].copy()
    cpi["date"] = pd.to_datetime(cpi["observation_date"], errors="raise")
    cpi["quarter"] = cpi["date"].dt.to_period("Q")
    cpi_q = cpi.groupby("quarter").agg(
        airline_cpi=("CUUR0000SETG01", "mean"),
        cpi_months=("CUUR0000SETG01", "count"),
    )
    cpi_q["cpi_complete"] = cpi_q["cpi_months"].eq(3)
    cpi_q["airline_cpi"] = cpi_q["airline_cpi"].where(cpi_q["cpi_complete"])

    data = pd.concat(
        [
            sw["revenue_passengers_000"].div(1000).rename("passengers"),
            sw["avg_passenger_fare_usd"].rename("fare"),
            sw["asm_millions"],
            sw["rasm_cents"],
            tsa_q,
            cpi_q,
        ],
        axis=1,
    ).sort_index()

    cleaning_log = pd.DataFrame(
        [
            {
                "dataset": "TSA daily checkpoints",
                "decision": "Sum daily counts to calendar quarters; do not impute or rescale.",
                "reason": "The daily file has complete calendar coverage.",
                "impact": f"{int(tsa['tsa_disruption'].sum())} days flagged; affected quarters excluded from calibration.",
            },
            {
                "dataset": "TSA disruption periods",
                "decision": "Flag 2025-10-01 to 2025-11-12 and 2026-02-14 to 2026-04-30.",
                "reason": "Checkpoint throughput may reflect staffing and collection constraints, not demand.",
                "impact": "Point-model rows remain visible; contaminated residuals are not calibration data.",
            },
            {
                "dataset": "BLS airline-fare CPI",
                "decision": "Use a quarterly mean only when all three monthly observations exist.",
                "reason": "October 2025 is blank; silently averaging two months changes the estimand.",
                "impact": "The 2025Q4 fare blend is unavailable and excluded from calibration.",
            },
            {
                "dataset": "Southwest quarterly statistics",
                "decision": "Convert revenue passengers from thousands to millions; retain reported fares.",
                "reason": "Keeps the forecast output in the form's requested units.",
                "impact": "No rows imputed; 2020 remains in the source but evaluation begins in 2022.",
            },
            {
                "dataset": "BTS T-100",
                "decision": "Use July 2026 only as a directional cross-check.",
                "reason": "It is domestic, one month, and measures segment/enplaned passengers rather than revenue passengers.",
                "impact": "It does not mechanically change the submitted point estimate.",
            },
        ]
    )
    return data, cleaning_log


def make_predictions(data: pd.DataFrame) -> pd.DataFrame:
    signals = data[["passengers", "fare", "tsa_total", "airline_cpi"]]
    yoy = signals.pct_change(periods=4, fill_method=None)
    pred = pd.DataFrame(index=data.index)

    for target in ("passengers", "fare"):
        pred[f"same_year_ago_{target}"] = data[target].shift(4)
        pred[f"company_growth_{target}"] = data[target].shift(4) * (
            1 + yoy[target].shift(1)
        )

    pred["blend_passengers"] = data["passengers"].shift(4) * (
        1 + 0.5 * yoy["passengers"].shift(1) + 0.5 * yoy["tsa_total"]
    )
    pred["blend_fare"] = data["fare"].shift(4) * (
        1 + 0.5 * yoy["fare"].shift(1) + 0.5 * yoy["airline_cpi"]
    )
    return pred


def regime_for_quarter(quarter: pd.Period) -> str:
    if quarter <= pd.Period("2025Q1", freq="Q"):
        return "pre-change"
    if quarter <= pd.Period("2025Q4", freq="Q"):
        return "changeover"
    return "post-change"


def build_backtest(data: pd.DataFrame, predictions: pd.DataFrame) -> pd.DataFrame:
    periods = data.loc[BACKTEST_START:BACKTEST_END].index
    backtest = pd.DataFrame(index=periods)
    backtest.index.name = "quarter"
    backtest["regime"] = [regime_for_quarter(q) for q in periods]
    backtest["tsa_disruption_days"] = data.loc[periods, "tsa_disruption_days"].fillna(0).astype(int)
    backtest["cpi_complete"] = data.loc[periods, "cpi_complete"].fillna(False).astype(bool)

    for target in ("passengers", "fare"):
        backtest[f"actual_{target}"] = data.loc[periods, target]
        for model in ("same_year_ago", "company_growth", "blend"):
            prediction = predictions.loc[periods, f"{model}_{target}"]
            backtest[f"{model}_{target}"] = prediction
            backtest[f"error_{model}_{target}"] = (
                backtest[f"actual_{target}"] / prediction - 1
            )
            backtest[f"ape_{model}_{target}"] = backtest[
                f"error_{model}_{target}"
            ].abs()
    return backtest


def summarize_backtest(backtest: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    regimes = ["overall", "pre-change", "changeover", "post-change"]
    for regime in regimes:
        sample = backtest if regime == "overall" else backtest[backtest["regime"].eq(regime)]
        for target in ("passengers", "fare"):
            for model in ("same_year_ago", "company_growth", "blend"):
                values = sample[f"ape_{model}_{target}"].dropna()
                rows.append(
                    {
                        "regime": regime,
                        "target": target,
                        "model": model,
                        "n": len(values),
                        "mape_pct": 100 * values.mean() if len(values) else np.nan,
                    }
                )
    return pd.DataFrame(rows)


def valid_blend_errors(backtest: pd.DataFrame, target: str) -> pd.Series:
    errors = backtest[f"error_blend_{target}"].copy()
    if target == "passengers":
        errors = errors.where(backtest["tsa_disruption_days"].eq(0))
    elif target == "fare":
        errors = errors.where(backtest["cpi_complete"])
    else:
        raise ValueError(f"Unknown target: {target}")
    return errors.dropna()


def conformal_margin(
    errors: pd.Series,
    coverage: float = TARGET_COVERAGE,
    window: int = CALIBRATION_WINDOW,
) -> tuple[float, int, int]:
    """Finite-sample absolute-residual quantile over a trailing window."""
    residuals = errors.dropna().abs().tail(window).sort_values().to_numpy()
    n = len(residuals)
    if n == 0:
        raise ValueError("At least one calibration residual is required")
    rank = min(ceil((n + 1) * coverage), n)
    return float(residuals[rank - 1]), n, rank


def walk_forward_coverage(
    backtest: pd.DataFrame,
    target: str,
    coverage: float = TARGET_COVERAGE,
    window: int = CALIBRATION_WINDOW,
    min_calibration: int = 5,
) -> dict[str, float | int]:
    """Evaluate intervals using only residuals available before each quarter."""
    errors = valid_blend_errors(backtest, target)
    history: list[float] = []
    covered: list[bool] = []
    for _, error in errors.items():
        if len(history) >= min_calibration:
            margin, _, _ = conformal_margin(pd.Series(history), coverage, window)
            covered.append(abs(error) <= margin)
        history.append(float(error))
    return {
        "evaluation_n": len(covered),
        "covered_n": int(sum(covered)),
        "coverage_pct": 100 * float(np.mean(covered)) if covered else np.nan,
    }


def t100_cross_check(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    t100 = inputs["t100"].copy().set_index("month")
    old = t100.loc["2025-07"]
    new = t100.loc["2026-07"]
    rows = []
    for field in ("departures_performed", "seats", "segment_passengers", "asm", "rpm"):
        rows.append(
            {
                "metric": field,
                "2025-07": old[field],
                "2026-07": new[field],
                "yoy_change_pct": 100 * (new[field] / old[field] - 1),
            }
        )
    rows.append(
        {
            "metric": "load_factor_pct",
            "2025-07": old["load_factor_pct"],
            "2026-07": new["load_factor_pct"],
            "yoy_change_pct": new["load_factor_pct"] - old["load_factor_pct"],
        }
    )
    return pd.DataFrame(rows)


def final_forecast(
    data: pd.DataFrame,
    predictions: pd.DataFrame,
    backtest: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for target, label, unit in (
        ("passengers", "Revenue passengers", "million"),
        ("fare", "Average passenger fare", "USD"),
    ):
        point = float(predictions.loc[TARGET_QUARTER, f"blend_{target}"])
        errors = valid_blend_errors(backtest, target)
        margin, calibration_n, rank = conformal_margin(errors)
        diagnostic = walk_forward_coverage(backtest, target)
        rows.append(
            {
                "metric": label,
                "unit": unit,
                "point": point,
                "lower_80": point * (1 - margin),
                "upper_80": point * (1 + margin),
                "calibration_n": calibration_n,
                "conformal_rank": rank,
                "margin_pct": 100 * margin,
                "walk_forward_n": diagnostic["evaluation_n"],
                "walk_forward_coverage_pct": diagnostic["coverage_pct"],
            }
        )
    forecast = pd.DataFrame(rows).set_index("metric")

    passenger_revenue_b = (
        forecast.loc["Revenue passengers", "point"]
        * forecast.loc["Average passenger fare", "point"]
        / 1000
    )
    product_lower_b = (
        forecast.loc["Revenue passengers", "lower_80"]
        * forecast.loc["Average passenger fare", "lower_80"]
        / 1000
    )
    product_upper_b = (
        forecast.loc["Revenue passengers", "upper_80"]
        * forecast.loc["Average passenger fare", "upper_80"]
        / 1000
    )

    base = data.loc[pd.Period("2025Q3", freq="Q")]
    operating_low_b = base["asm_millions"] * 0.99 * base["rasm_cents"] * 1.175 / 100 / 1000
    operating_high_b = base["asm_millions"] * base["rasm_cents"] * 1.195 / 100 / 1000
    passenger_low_b = operating_low_b * 0.92
    passenger_high_b = operating_high_b * 0.92

    reconciliation = pd.DataFrame(
        [
            {
                "measure": "Model passenger revenue",
                "point_usd_b": passenger_revenue_b,
                "lower_usd_b": product_lower_b,
                "upper_usd_b": product_upper_b,
                "note": "Bounds mechanically multiply marginal endpoints; they are not a joint 80% interval.",
            },
            {
                "measure": "Guidance-implied operating revenue",
                "point_usd_b": np.nan,
                "lower_usd_b": operating_low_b,
                "upper_usd_b": operating_high_b,
                "note": "Q3 2025 ASMs/RASM adjusted by Q3 2026 capacity and RASM guidance.",
            },
            {
                "measure": "Guidance-implied passenger revenue",
                "point_usd_b": np.nan,
                "lower_usd_b": passenger_low_b,
                "upper_usd_b": passenger_high_b,
                "note": "Assumes passenger revenue is 92% of operating revenue, as stated in the case.",
            },
        ]
    ).set_index("measure")
    return forecast, reconciliation


def run_analysis(root: Path | None = None) -> dict[str, object]:
    inputs = load_inputs(root)
    data, cleaning_log = prepare_quarterly(inputs)
    predictions = make_predictions(data)
    backtest = build_backtest(data, predictions)
    forecast, reconciliation = final_forecast(data, predictions, backtest)
    return {
        "inputs": inputs,
        "data": data,
        "cleaning_log": cleaning_log,
        "predictions": predictions,
        "backtest": backtest,
        "backtest_summary": summarize_backtest(backtest),
        "t100_cross_check": t100_cross_check(inputs),
        "forecast": forecast,
        "reconciliation": reconciliation,
    }


def main() -> None:
    result = run_analysis()
    with pd.option_context("display.max_columns", None, "display.width", 180):
        print("\nFINAL FORECAST")
        print(result["forecast"].round(3).to_string())
        print("\nREVENUE RECONCILIATION")
        print(result["reconciliation"].round(3).to_string())
        print("\nBACKTEST SUMMARY")
        print(result["backtest_summary"].round(3).to_string(index=False))
        print("\nT-100 JULY CROSS-CHECK")
        print(result["t100_cross_check"].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
