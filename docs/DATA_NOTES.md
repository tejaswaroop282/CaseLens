# Data notes (verify on the real files — hard rule 11)

Status: **not yet verified** — the HI-Small files have not been downloaded. Fill in each line from the
`pipeline_runs` notes of the `staging` and `labels` steps (`python -m pipeline.run --step all`).

| Assumption | Expected | Measured | Loader decision |
|---|---|---|---|
| Header of `HI-Small_Trans.csv` | 11 columns, two named `Account` | | read with explicit names, `header=0` |
| Timestamp format | `YYYY/MM/DD HH:MM`, read as UTC | | `%Y/%m/%d %H:%M`; failures rejected and logged |
| File sorted by time | probably | | if sorted, reading stops after the slice |
| Account ids unique across banks | unknown | | if not, ids become `bank|account` (`pipeline_meta.account_key`) |
| Account id shape (for `ID_PATTERN`) | about 9 hex characters | | adjust `ID_PATTERN` in `.env` |
| Patterns file shape | `BEGIN LAUNDERING ATTEMPT - TYPE` … `END …`, same 11-column lines | | parser in `pipeline/patterns.py` |
| Pattern lines match transactions by row key | yes; duplicates possible | | all matching `tx_id`s attached |
| Rows in the first 24 hours | about 0.5 million (estimate) | | |
| Laundering share in the slice | about 0.1 % | | |
| Complete fan-out / fan-in blocks in the slice | at least 10 each | | `slice_advice` result and chosen `SLICE_HOURS` |
| Payment formats | includes a wire-like value (`Wire`?) | | needed by eval worry p07 |
| Rejected rows | ≤ 0.1 % | | |
| MongoDB size of the slice | 0.2–0.6 GB (estimate) | | |
| Disk use after M1 (`disk_report`) | well under 10 GB | | |

## Decisions made without data

- F6 prior activity is not filtered by the scenario's payment formats (it is the account's earlier same-direction activity); the window facts F1–F5 and F7–F10 are.
- F10 `total_amount` is a `{currency: total}` map because amounts are only summed within one currency.
- The data origin is derived from each alert (`window_start − bucket × window_hours`) so the tools do not need `pipeline_meta`.
