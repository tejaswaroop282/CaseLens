# CaseLens walkthrough (3–5 minute demo)

A script for a screen recording or a live demo. It uses the data and runs described in the README; every number
mentioned here was measured on that data. Record with OBS or the Windows Game Bar (Win + Alt + R).

**Before you start:** MongoDB running (`docker compose up -d mongo`), API and frontend running, browser at the sign-in
page, browser zoom at 100 %.

## 1. The problem (20 s) — sign-in page

> "Banks raise thousands of money-laundering alerts, and most are false alarms. Rules are slow to improve because
> nobody measures them before they go live. CaseLens tackles one pattern — the fan pattern, one account versus many
> counterparties — with two roles: a risk owner who designs rules, and an analyst who reviews alerts."

Point at the two demo accounts.

## 2. Risk owner: from a worry to a measured rule (90 s)

1. Sign in as **meera / owner123**. Show the **Overview**: drafts to approve, rules in use, rule performance table.
   > "Three rules have run on 4.2 million simulated transactions. Look at the first one: a 12-hour rule raised 680
   > alerts and caught zero of the 16 real fan-in patterns."
2. Open **Scenario Studio**, click a sample worry or type:
   *"Flag any account that receives money from 8 or more different accounts within 3 days."* → **Draft scenario**.
   > "The AI can only fill a closed schema — direction and two numbers. It cannot write queries or code."
3. On the draft: show direction, numbers, harmless look-alikes and the AI rationale. Point out **Approve**:
   > "Nothing runs until a human approves it, and the approval is recorded under my name."
   (To save time, open the existing completed "8 or more … 3 days" scenario instead of running a new one.)
4. Show the results: **2,381 alerts, 7.7 % precision, 4 of 11 patterns caught**, plus the real examples table.
   > "This rule catches real laundering, but 92 % of its alerts are false alarms. That is the analyst's problem."

## 3. Analyst: from an alert to a decision (90 s)

1. **Sign out**, sign in as **ravi / analyst123**. Show the **Overview**: cases ready for a decision.
2. Open the **Alert queue**; point at an investigated alert and click **Review** (or **Investigate** on a new one —
   about 25 seconds).
3. On the case page, walk left to right:
   - **Fact sheet** — "every number is computed by code from the transactions."
   - **AI suggestion and claims** — click a fact chip (F1, F3 …) to show the evidence behind a claim.
   - **What the guidance says** — click a chunk chip to show the FFIEC or FinCEN excerpt.
   - **Possible harmless explanations** and **missing evidence**.
   - Status pills **Checked / Checks passed** — "a plain-code checker verified every number and id."
4. Type a reason and click **Escalate** (or Dismiss).
   > "The AI never decides. My decision is final, recorded under my name, and sent to the downstream case system."

## 4. New data arrives (40 s)

Sign in as **meera** again → **Upload transactions**. Show the uploads list:

> "Day 8 of the same IBM data — 482,773 transactions — was validated, appended and copied to S3. Approved rules ran on
> the new day only: 99 new alerts, none duplicated. Uploading the same file again adds nothing."

## 5. Results and honesty (30 s)

Show the README **Results** section:

> "On 30 held-out alerts, CaseLens never marked a suspicious alert as legitimate, and every claim was backed by cited
> facts. It did not reduce the review load — it sent every alert to a human — so its value here is a fast,
> evidence-checked case file, not automatic triage. Total AI cost: zero dollars."

## Tips

- Keep one completed scenario and a few investigated cases ready, so you do not wait on the AI during the recording.
- If an investigation fails with "high demand", that is the Gemini free tier; click **Re-investigate**.
