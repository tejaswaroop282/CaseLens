# 01 — Data pipeline (M1)

Goal: put a **small slice** of public data into S3 unchanged (raw), clean it into MongoDB (staging), and load regulatory PDF chunks into embedded Chroma. Every step is a Python command, idempotent, and writes a record to `pipeline_runs`. Windows (PowerShell); keep the code cross-platform.

## 1. Sources

| Source | What | Notes |
|---|---|---|
| IBM AML (Kaggle `ealtman2019/ibm-transactions-for-anti-money-laundering-aml`) | **Two files only:** `HI-Small_Trans.csv` (roughly 0.5 GB) and `HI-Small_Patterns.txt`. The accounts file is **not needed** (entity names are anonymized and unused) | Simulated by IBM, labeled. License CDLA-Sharing-1.0. Record in `docs/SOURCES.md` |
| Regulatory PDFs | 3 to 5 public guidance documents (typology reports, red-flag lists, suspicious-transaction guidance from FATF, FinCEN, FIU-IND or similar) | Text PDFs only. List each in `docs/SOURCES.yaml`: `doc_id`, `title`, `url`, `retrieved_on`, `file` |

**Never download the whole Kaggle dataset.** It includes Medium and Large variants that are many gigabytes. Download the two files one by one.

Download (PowerShell, from the project root; on the host). Follow Kaggle's current instructions for the API token (check) and never commit it:

```
pip install kaggle
kaggle datasets files ealtman2019/ibm-transactions-for-anti-money-laundering-aml        # lists file names and sizes: check first
kaggle datasets download -d ealtman2019/ibm-transactions-for-anti-money-laundering-aml -f HI-Small_Trans.csv    -p data\ibm
kaggle datasets download -d ealtman2019/ibm-transactions-for-anti-money-laundering-aml -f HI-Small_Patterns.txt -p data\ibm
# a file may arrive as .zip: Expand-Archive data\ibm\<file>.zip data\ibm ; then delete the .zip
python -m pipeline.disk_report
```

Use the exact file names the listing shows. After `raw` uploads to S3, and `staging` and `labels` succeed, delete local copies unless `KEEP_LOCAL_RAW=true`.

## 2. S3 layout (raw layer)

```
s3://<bucket>/raw/ibm_aml/HI-Small_Trans.csv
s3://<bucket>/raw/ibm_aml/HI-Small_Patterns.txt
s3://<bucket>/raw/reg_docs/<doc_id>.pdf
```

Raw objects are never modified. Store the SHA-256 in object metadata and in `pipeline_runs`. The bucket blocks public access and uses default encryption.

## 3. Commands

```
python -m pipeline.slice_advice                       # reads only the patterns file; recommends SLICE_HOURS
python -m pipeline.run --step raw|staging|labels|docs|dq|all [--force]
python -m pipeline.disk_report
```

Order for `all`: `raw` → `staging` → `labels` → `docs` → `dq`.

Each step reads inputs from the local cache `data/` (downloading from S3 if missing), writes outputs, appends one document to `pipeline_runs`, and is skipped if its `config_hash` is unchanged unless `--force`. `config_hash` = hash of (source checksums, `SLICE_HOURS`, `MAX_ROWS`, `ID_PATTERN`).

`pipeline_runs` document:

```json
{"run_id": "…", "step": "staging", "status": "ok", "config_hash": "…",
 "started_at": "…", "finished_at": "…",
 "row_counts": {"read": 5078345, "in_slice": 480000, "written": 480000, "rejected": 0}, "notes": []}
```

`pipeline_meta` (one document, `_id: "meta"`):

```json
{"_id": "meta", "dataset": "HI-Small", "data_origin": "2022-09-01T00:00:00Z",
 "slice_hours": 24, "slice_end": "2022-09-02T00:00:00Z", "account_key": "account",
 "built_at": "…"}
```

`data_origin` = UTC midnight of the earliest transaction timestamp. All windows count from it.

## 4. `slice_advice` (choose the smallest useful slice)

Reads only `HI-Small_Patterns.txt` (small). For each pattern block of type FAN-OUT or FAN-IN, find the first and last timestamp. Approximate the origin as the midnight of the earliest pattern timestamp. For `H` in 6, 12, 24, 48, 72 print how many fan-out and fan-in blocks lie **fully inside** the first `H` hours. Recommend the smallest `H` with at least 10 blocks of each type; if none qualifies, recommend the largest `H` and say so. The user sets `SLICE_HOURS` from this. Rationale: with too few labeled blocks, pattern recall and the evaluation sets are meaningless; with too many hours, disk and time grow.

## 5. Step specs

### 5.1 `raw`
Upload local files to S3, compute SHA-256, record it. Download from S3 if local files are missing.

### 5.2 `staging` (transactions only)

Pass 1: read only the timestamp column to find the earliest timestamp (sets `data_origin`) and check whether the file is sorted by time. Pass 2: read in chunks of 100,000 rows.

```python
COLS = ["ts_raw","from_bank","from_account","to_bank","to_account","amount_received","currency_received",
        "amount_paid","currency_paid","payment_format","is_laundering"]
pd.read_csv(path, header=0, names=COLS, dtype=str, chunksize=100_000)     # the file has two columns named "Account"
```

Rules:
1. Strip whitespace. Keep ids as **strings**.
2. Parse `ts_raw` with the expected format `%Y/%m/%d %H:%M` as UTC (**verify on the first rows**). Rows that fail go to `rejected` and are logged (first 20 examples).
3. Cast amounts to float; reject non-positive or non-numeric amounts.
4. `tx_id = f"HI-Small-{row_index}"` (0-based row number in the file; stable).
5. **Account key decision (verify):** check whether `Account` values are unique across banks. If one id appears under more than one bank, set `from_account = f"{from_bank}|{from_account}"` (same for `to_account`) and `pipeline_meta.account_key = "bank_account"`. Write the finding to `docs/DATA_NOTES.md`.
6. Apply the slice: keep rows with `ts < data_origin + SLICE_HOURS hours` (and at most `MAX_ROWS`). Rows outside the slice are read and skipped. Every 500,000 rows read, check the MongoDB size; if `storageSize + indexSize` exceeds `MONGO_MAX_GB`, stop with a clear error.
7. **Drop the label column from the transaction document.**
8. For every in-slice row with `is_laundering == "1"`, write `(tx_id, row_key)` to `data/label_rows.jsonl`, where
```python
row_key = sha1("|".join([ts_raw, from_bank, from_account_raw, to_bank, to_account_raw,
                         amount_received, currency_received, amount_paid, currency_paid, payment_format])).hexdigest()
```
   (raw strings exactly as read).
9. `insert_many(docs, ordered=False)`. Create indexes after all inserts.

`stg_transactions` document:

```json
{"tx_id": "HI-Small-1048576", "ts": "2022-09-01T14:20:00Z",
 "from_bank": "011", "from_account": "8000EBD30", "to_bank": "012", "to_account": "8000EBD31",
 "amount_paid": 3697.34, "currency_paid": "US Dollar",
 "amount_received": 3697.34, "currency_received": "US Dollar", "payment_format": "Reinvestment"}
```

Indexes: unique `tx_id`; `(from_account, ts)`; `(to_account, ts)`.

### 5.3 `labels` (evaluation-only collections)

Collections `stg_labels` and `stg_pattern_blocks`. **Only evaluation code and the scenario-examples endpoint may read them.**

`stg_labels` (one document per in-slice laundering transaction; absence means not laundering):

```json
{"tx_id": "HI-Small-1048576", "is_laundering": true, "pattern_type": "fan_out", "pattern_id": "HI-Small-P00042"}
```

`pattern_type` is `fan_out`, `fan_in`, or `other` (laundering transaction in some other block type, or in none).

Parse `Patterns.txt` (expected shape; **verify on the real file**):

```
BEGIN LAUNDERING ATTEMPT - FAN-OUT
<csv transaction line>
…
END LAUNDERING ATTEMPT - FAN-OUT
```

Rules: normalize the block type to lowercase with underscores; assign `pattern_id = f"HI-Small-P{n:05d}"` in file order; compute the same `row_key` per line and look it up in `label_rows.jsonl`; if a key matches several `tx_id`s attach all of them. Store a block in `stg_pattern_blocks` **only if** its type is `fan_out` or `fan_in` **and** all its matched transactions are inside the slice:

```json
{"pattern_id": "HI-Small-P00042", "pattern_type": "fan_out", "tx_ids": ["…"], "n_lines": 12, "n_matched": 12, "n_unmatched": 0}
```

Report dropped blocks and unmatched lines in the run notes.

### 5.4 `docs` (regulatory PDFs → embedded Chroma)

1. Read `docs/SOURCES.yaml`; ensure each PDF is in S3 and cached locally.
2. Extract text per page with `pypdf`; skip empty pages (log them).
3. `RecursiveCharacterTextSplitter(chunk_size=900, chunk_overlap=150)`.
4. `chunk_id = f"c_{doc_id}_{page:04d}_{n:03d}"`. Metadata: `{doc_id, title, source_url, page, chunk_id}`.
5. Idempotency: delete existing chunks of that `doc_id` (`delete(where={"doc_id": doc_id})`), then add.
6. Embeddings: `BedrockEmbeddings(model_id=BEDROCK_EMBED_ID, region_name=..., model_kwargs={"dimensions": EMBED_DIMENSIONS, "normalize": True})` (Titan v2 request options; check the Bedrock docs). Batch of 32 chunks. Estimate tokens as characters / 4, add to the ledger, and **stop if `EMBED_TOKEN_BUDGET` would be exceeded**. Embed each PDF once; skip when `config_hash` is unchanged.
7. Store in embedded Chroma at `CHROMA_PATH` (`Chroma(collection_name="reg_docs", embedding_function=..., persist_directory=CHROMA_PATH)`). The same embedding settings are used for queries.
8. Log: documents, pages, chunks, characters, estimated tokens.

### 5.5 `dq` (data quality)

One `dq_reports` document per run: `{run_id, layer, checks: [{name, status, value, expected, detail}]}`. Any failed check makes the command exit non-zero.

| Layer | Check | Pass when |
|---|---|---|
| raw | S3 object exists and its SHA-256 metadata equals the checksum recorded by the `raw` step in `pipeline_runs` (local files may already be deleted) | equal |
| staging | `written + rejected == in_slice` | equal |
| staging | rejected share | at most 0.1 percent |
| staging | nulls in required fields; duplicate `tx_id` | 0 |
| staging | timestamp range | within `[data_origin, slice_end)` |
| staging | `stg_transactions` has no label field | true |
| labels | laundering share in the slice | report (warn if far from about 0.1 percent) |
| labels | complete fan blocks in the slice, per type | at least 10 each (warn otherwise; raise `SLICE_HOURS`) |
| labels | unmatched pattern lines | fail if more than 5 percent |
| docs | chunks per document | at least 1; all metadata present |
| docs | estimated embedding tokens | within `EMBED_TOKEN_BUDGET` |
| disk | MongoDB `storageSize + indexSize` | below `MONGO_MAX_GB` (fail); warn above 70 percent of it |
| disk | size of `data/` | under 1 GB when `KEEP_LOCAL_RAW=false` (warn) |

## 6. `disk_report`

`python -m pipeline.disk_report` (pure Python, works on Windows) prints: sizes of `data/`, `data/chroma`, `.venv` if present; MongoDB `storageSize`, `indexSize` per collection; `docker system df` if the Docker CLI exists; total against `DISK_BUDGET_GB`. Warn above 70 percent and list cleanup steps (delete local raw files, lower `SLICE_HOURS`, `docker image prune -f`, `docker builder prune -f`, `docker compose down -v`).

## 7. MongoDB indexes (all collections)

- `stg_transactions`: unique `tx_id`; `(from_account, ts)`; `(to_account, ts)`
- `stg_labels`: unique `tx_id`. `stg_pattern_blocks`: unique `pattern_id`; `pattern_type`
- `alert_truth`: unique `alert_id`
- `alerts`: unique `alert_id`; `(scenario_id, status)`; `account_id`
- `cases`: unique `case_id`; `alert_id`. `decisions`: `case_id`. `scenarios`: unique `scenario_id`. `llm_usage`: `ts`

## 8. Tests

- `test_row_key_matches_pattern_lines` (small fixture pair)
- `test_staging_has_no_label_field`
- `test_timestamp_parse_rejects_bad_rows`
- `test_slice_keeps_only_first_hours`
- `test_account_key_decision_recorded`
- `test_patterns_parser_types_and_ids`; `test_blocks_outside_slice_are_dropped`
- `test_slice_advice_counts_blocks_inside_window`
- `test_embedding_budget_guard_stops_ingestion`
- `test_dq_fails_on_duplicate_tx_id`
