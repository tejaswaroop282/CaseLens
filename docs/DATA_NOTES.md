# Data notes (verified on the real files — hard rule 11)

Status: **verified on 2026-11-14** with the raw, staging, labels and dq steps (dq: 16 checks, 0 failed, 2 warnings).
Sources: `pipeline_runs` notes and direct queries on `stg_transactions`. The local raw files were then deleted
(`KEEP_LOCAL_RAW=false`); the originals are in S3 `raw/ibm_aml/`.

| Assumption | Expected | Measured | Loader decision |
|---|---|---|---|
| Header of `HI-Small_Trans.csv` | 11 columns, two named `Account` | All 5,078,345 rows read, 0 rejected | Explicit names, `header=0` |
| Timestamp format | `YYYY/MM/DD HH:MM`, read as UTC | 0 unparseable; file spans 2022-09-01 00:00 to 2022-09-18 16:18 | `%Y/%m/%d %H:%M` |
| File sorted by time | probably | **Not sorted** | Whole file scanned (about 2.5 min); no early stop |
| Account ids unique across banks | unknown | **Not unique:** 515,080 distinct ids, 8 under more than one bank | `account_key=bank_account`; ids stored as `bank` + `\|` + `account` |
| Account id shape (for `ID_PATTERN`) | about 9 hex characters | 9 hex characters after the bank prefix (e.g. `8000EBD30`); 20,000 sampled ids all match | Default `ID_PATTERN` kept |
| Patterns file shape | `BEGIN LAUNDERING ATTEMPT - TYPE` … `END …` | 370 blocks; types bipartite, cycle, fan_in, fan_out, gather_scatter, random, scatter_gather, stack | Parser unchanged |
| Pattern lines match transactions by row key | yes | 1,641 of 1,641 in-slice lines matched | All matching `tx_id`s attached |
| Rows in the slice | about 0.5 million per 24 h (estimate) | 3,731,672 rows in 168 h (72 h: 2,076,752) | — |
| Laundering share in the slice | about 0.1 % | 0.081 % | — |
| Complete fan-out / fan-in blocks in the slice | at least 10 each | **24 fan-out, 16 fan-in** at 168 h (72 h: 3 / 1; 96 h: 10 / 5) | `SLICE_HOURS=168` (raised from 72 with the user's OK) |
| Payment formats | includes a wire-like value | ACH, Bitcoin, Cash, Cheque, Credit Card, Reinvestment, Wire | `Wire` exists for eval worry p07 |
| Rejected rows | ≤ 0.1 % | 0 | — |
| MongoDB size of the slice | 0.2–0.6 GB (estimate) | 0.79 GB at 168 h (storage + indexes) | Under `MONGO_MAX_GB=1` |
| Disk use after M1 (`disk_report`) | well under 10 GB | 1.22 GB of 10 GB | — |

## Finding: IBM fan patterns are low and slow

Measured on all 88 fan blocks in `HI-Small_Patterns.txt`: median 7 (fan-out) and 8 (fan-in) transactions, at most 16;
median span 77 h (fan-out) and 85 h (fan-in), at most 96 h, often one payment every few hours. Consequences:

- A rule such as "10 or more counterparties in 24 hours" cannot catch them. A read-only threshold sweep on the 72 h
  slice (windows 6/12/24 h, thresholds 5/10/20/40) caught at most 1 of 3 fan-out and 0 of 1 fan-in blocks.
- Catching them needs a long window (about 96 h) and a low threshold (about 5); the risk owner chooses the numbers.
- Short slices cut blocks off, so `slice_advice` now checks slices up to 432 h (it stopped at 72 h before).
- Read-only sweep on the 168 h slice (fixed buckets; precision = alerts with at least one laundering transaction):

  | Direction | Window | Min counterparties | Alerts | Precision | Fan blocks caught |
  |---|---|---|---|---|---|
  | out | 72 h | 8 | 7,967 | 1.4 % | 9 / 24 |
  | out | 168 h | 3 | 88,876 | 1.2 % | 23 / 24 |
  | out | 168 h | 8 | 8,987 | 1.3 % | 11 / 24 |
  | in | 72 h | 8 | 2,686 | 7.4 % | 6 / 16 |
  | in | 168 h | 5 | 19,469 | 3.4 % | 14 / 16 |
  | in | 168 h | 8 | 3,526 | 6.9 % | 7 / 16 |

  Catching most fan blocks costs tens of thousands of alerts at 1–3 % precision; settings under `MAX_ALERTS=5000`
  catch about half or fewer. The rule alone is noisy, which is the problem the investigation step is meant to help with.

## Decisions made without data

- F6 prior activity is not filtered by the scenario's payment formats (it is the account's earlier same-direction activity); the window facts F1–F5 and F7–F10 are.
- F10 `total_amount` is a `{currency: total}` map because amounts are only summed within one currency.
- The data origin is derived from each alert (`window_start − bucket × window_hours`) so the tools do not need `pipeline_meta`.

## Upload of day 8 (M7, 2026-11-18)

- 482,773 rows for 2022-09-08, 0 rejected, 539 labeled; after the append the data ends at 2022-09-09 00:00 (192 h),
  4,214,445 staging rows, 27 fan-out and 21 fan-in complete blocks; dq 20 checks, 0 failed.
- Fresh inserts grew MongoDB by about 1.3 KB per row (compacted average about 0.28 KB per row), so `MONGO_MAX_GB` was
  raised from 1 to 2 with the user's approval. The upload size check uses the larger figure.

