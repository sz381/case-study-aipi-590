# Southwest Q3 2026 Alternative-Data Forecast

This repository forecasts two Southwest Airlines Q3 2026 figures before the
October 21 earnings release:

1. Revenue passengers carried
2. Average passenger fare

The analysis is intentionally simple and explainable. It combines Southwest's
latest reported growth with public alternative-data signals, evaluates the
method quarter by quarter, and calibrates uncertainty using only residuals that
would have been available before the target quarter.

## Data cutoff

- Analysis cutoff: **October 16, 2026**
- Target quarter: **2026Q3**
- No information published after the forecast form's October 21 noon deadline
  enters the model.
- The model uses only files supplied with the case. BTS T-100 is used as a
  cross-check, not as a fitted input.

## Model

For each target, the year-ago Q3 value is scaled by the average of two
year-over-year growth signals:

- **Passengers:** 50% Southwest's latest reported passenger growth and 50% Q3
  national TSA checkpoint growth.
- **Fare:** 50% Southwest's latest reported fare growth and 50% Q3 BLS
  airline-fare CPI growth.

The weights are fixed in advance rather than optimized on the small sample.

## Final forecast

| Metric | Point | Rolling conformal 80% interval | Calibration observations | Walk-forward coverage |
|---|---:|---:|---:|---:|
| Revenue passengers | **33.516 million** | **31.444–35.587 million** | 12 | 10/10 (100%) |
| Average passenger fare | **$223.32** | **$205.32–$241.32** | 12 | 12/12 (100%) |

The observed coverage is above 80%, so these intervals were conservative in
the available walk-forward evaluation. The evaluation sample is small and is
reported explicitly rather than treating 100% as a stable performance claim.

## Revenue reconciliation

- Point passenger revenue: **$7.485 billion**
- Guidance-implied operating revenue: **$8.083–$8.304 billion**
- Guidance-implied passenger revenue at the case's 92% share assumption:
  **$7.437–$7.640 billion**

The model's $7.485 billion point forecast is inside the guidance-implied
passenger-revenue range. Multiplying the lower and upper marginal forecast
endpoints gives $6.456–$8.588 billion, but that mechanical product is **not** a
joint 80% interval.

## Walk-forward backtest

Every row forecasts a quarter using only lagged Southwest observations and the
contemporaneous public TSA or CPI quarter. Evaluation covers 2022Q1–2026Q2.

Overall mean absolute percentage error:

| Target | Same quarter last year | Latest company growth | Alternative-data blend |
|---|---:|---:|---:|
| Passengers | 12.08% | 6.53% | **4.38%** |
| Fare | 10.17% | **4.98%** | 6.13% |

The notebook also reports the results separately for:

- **Pre-change:** through 2025Q1
- **Changeover:** 2025Q2–2025Q4, when bag fees and other commercial changes
  began
- **Post-change:** 2026Q1 onward, after assigned seating and extra-legroom
  products launched

The blend materially improves the passenger forecast. The fare blend does not
beat the latest-company-growth baseline over the full history, although it is
more competitive after the business-model change.

## Cleaning and disruption decisions

- The TSA file contains every calendar day in its stated range. Daily counts
  are summed without imputation or rescaling.
- October 1–November 12, 2025 and February 14–April 30, 2026 are explicitly
  flagged as checkpoint-disruption periods. The affected predictions remain in
  the backtest, but their passenger residuals are excluded from conformal
  calibration because traffic may reflect staffing constraints rather than
  demand.
- A BLS fare quarter is used only when all three monthly observations exist.
  October 2025 is missing, so the 2025Q4 fare blend is unavailable rather than
  silently averaging two months.
- Southwest revenue passengers are converted from thousands to millions. No
  Southwest rows are imputed.
- The 2020 collapse remains in the source file but the reported evaluation
  begins in 2022.

The notebook prints a complete cleaning-decision table and the flagged quarter
counts.

## T-100 July cross-check

Southwest's July 2026 domestic T-100 data show:

- Segment passengers: **-0.46% year over year**
- Seats: **-0.95%**
- ASMs: **-1.84%**
- Load factor: **+1.2 percentage points**

This is a useful challenge to the model's -3.08% Q3 revenue-passenger growth
estimate. It does not replace the point estimate because T-100 covers only
July, is domestic-only, and counts passengers by flight segment rather than by
one-way revenue journey.

## Reproduce the analysis

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m src.southwest_forecast
```

Open `notebooks/southwest_form_answers.ipynb` for the narrated tables used in
the submission.

## Repository layout

```text
Case Study Data Files/              Supplied public datasets
Case Study Docket ... .pdf          Assignment and source notes
notebooks/southwest_form_answers.ipynb
src/southwest_forecast.py           Reusable analysis implementation
tests/test_forecast.py              Forecast and reconciliation checks
requirements.txt                    Pinned runtime dependencies
```

## Limitations

- TSA traffic covers all airlines and can move differently from Southwest's
  market share.
- BLS CPI covers the airline industry and may include travel booked for later
  periods.
- The post-change regime has very few reported quarters.
- The conformal method improves auditability but cannot create a large sample;
  both calibration size and realized walk-forward coverage should accompany
  every interval.
