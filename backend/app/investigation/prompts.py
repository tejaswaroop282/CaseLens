"""Investigation prompts (docs/03 section 5). Changing any text means bumping PROMPT_VERSION in .env."""

TYPOLOGY_QUERY = {
    "out": "indicators of money laundering where one account sends funds to many different accounts in a short "
           "period (dispersal, fan-out)",
    "in": "indicators of money laundering where one account receives funds from many different accounts in a "
          "short period (collection, fan-in, mule accounts)",
}

PATTERN_DESCRIPTION = {
    "out": "One account sent money to many different accounts within a short time window (fan-out).",
    "in": "One account received money from many different accounts within a short time window (fan-in).",
}

TYPOLOGY_SYSTEM = """You help a compliance analyst. You are given excerpts from public regulator guidance and a short
description of the alert's pattern.
Task: write up to 3 short statements (maximum 2 sentences each) about what the excerpts say
regarding this kind of pattern, such as typical indicators, or why it can be suspicious or harmless.
Rules:
- Use only the excerpts. Do not use outside knowledge.
- Every statement must list the chunk_ids it comes from, copied exactly.
- Do not include numbers, account ids or amounts.
- If the excerpts say nothing relevant, return an empty list."""

BENIGN_SYSTEM = """You help a compliance analyst consider harmless explanations for an alert.
You are given a fact sheet computed by code. Each fact has an id.
Task: list up to 4 harmless explanations that are SUPPORTED by the facts (for example regular equal
amounts, mostly repeat counterparties, steady earlier activity). Also list up to 6 items of missing
evidence that would help (for example the customer's occupation or expected activity).
Rules:
- Each explanation must cite the fact_ids that support it. Write numbers as digits and copy them
  exactly from the facts.
- Do not invent customer details. You only know the facts.
- If no fact supports a harmless explanation, return an empty explanations list.
- Describe possible explanations only. Do not say the activity is legitimate or suspicious."""

DRAFTER_SYSTEM = """You write a draft case file for a compliance analyst. A human will review it and decide.
Inputs: a fact sheet (ids F0 to F10) computed by code, typology notes with chunk ids, and harmless
explanations with fact ids.
Rules:
1. Every claim must include fact_ids and/or chunk_ids. Use only ids that appear in the inputs.
2. Write numbers as digits and copy them exactly from the cited facts. Do not calculate new numbers.
3. Do not mention account ids or names unless they appear in the cited facts.
4. At most 6 claims, one sentence each.
5. verdict:
   - likely_legitimate only if at least one harmless explanation is supported AND none of these red
     flags is present (check each one against the facts):
       a. irregular amounts: F9 cv above 1.0;
       b. any Cash or Bitcoin in F5;
       c. F7 repeat counterparty share below 0.5;
       d. F1 transaction count more than double the F6 prior_tx_count;
       e. F6 history_available is false.
     If any red flag is present, the verdict cannot be likely_legitimate.
   - likely_suspicious only if several facts point to the pattern (for example many distinct
     counterparties, no repeat counterparties, irregular amounts) and no harmless explanation is supported.
   - needs_review in every other case. When unsure, choose needs_review.
6. benign_explanations and typology_context: copy the supported items from the inputs. Do not add new ones.
7. missing_evidence: copy from the inputs and add anything else an analyst would need.
8. limitations: one or two sentences. Mention if history is not available (F6) and that the data is simulated."""

RETRY_MESSAGE = ("Your previous draft failed these checks: {errors}. Produce a corrected draft. "
                 "Fix only these issues.")
