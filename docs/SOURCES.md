# Data sources and licenses

| Source | What CaseLens uses | License / terms | Where it is kept |
|---|---|---|---|
| IBM Transactions for Anti-Money Laundering (Kaggle `ealtman2019/ibm-transactions-for-anti-money-laundering-aml`), HI-Small | `HI-Small_Trans.csv`, `HI-Small_Patterns.txt` only, first `SLICE_HOURS` | CDLA-Sharing-1.0 | `s3://<bucket>/raw/ibm_aml/`; local copy deleted after staging |
| FinCEN Advisory FIN-2014-A005 (Funnel Accounts and TBML) | text chunks for the typology agent | US government publication | `s3://<bucket>/raw/reg_docs/`, `data/reg_docs/` |
| FFIEC BSA/AML Examination Manual, Appendix F (Red Flags), v. 2/27/2015 | text chunks | US government publication | same |
| FATF, INTERPOL, Egmont Group (2023), *Illicit Financial Flows from Cyber-Enabled Fraud* | text chunks | © FATF/OECD, INTERPOL, Egmont Group; reproduction requires permission. Kept private (gitignored folder, private bucket); the app shows short cited excerpts and links to the official page | same |

Exact URLs and retrieval dates: `docs/SOURCES.yaml`.

The IBM data is **simulated** by IBM from a multi-agent virtual world. It is not real customer data, and results on it do not show how a real bank's data would behave.
