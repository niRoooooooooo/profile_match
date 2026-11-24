# Live Supabase end-to-end test — fictional Glowfern invention

**Status: PREPARED, NOT RUN. Requires separate explicit approval before step 1.**

Purpose: prove the real workflow against the real Supabase project and Gemini:
Google login → Registration → Upload → Generate → Review → Edit → Autosave →
Submit → JSON/DOCX in `invention-profiles` → Download.

Only the fictional files in `upload_files/` are used. No code, schema, RLS,
policy, bucket or authentication setting is changed. No existing record is
touched. You perform the browser steps; Google sign-in is interactive.

---

## 0. Preparation (offline, no Supabase changes)

1. Regenerate and parse-check the upload files:
   ```
   cd C:\Projects\profile_match\backend
   .venv\Scripts\python.exe ..\tests\e2e_live\make_documents.py
   ```
   Expect three lines ending `parse check: OK`.
2. Confirm in `.env` (by eye; never paste values anywhere):
   `GEMINI_MODEL=gemini-3.5-flash-lite` and a valid `GEMINI_API_KEY`.
3. Start the backend:
   ```
   cd C:\Projects\profile_match\backend
   .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

## 1. Register the fictional invention (creates 1 `inventions` row)

Open `http://127.0.0.1:8000/login`, sign in with your own Google account,
then register an invention with **exactly**:

| Field | Value |
|---|---|
| Title | `TEST E2E – Glowfern Bioluminescent Path Marker (fictional)` |
| Abstract | `FICTIONAL TEST. A self-powered path marker using engineered moss.` |
| Domain | `Biotechnology` |
| TRL | `TRL 3` |
| IP status | `Patent pending` |
| Inventors | `Test Inventor A` |
| Keywords | `bioluminescence, path marker` |
| Confidentiality | **Public** |

## 2. Upload the fictional documents (creates 3 `invention_documents` rows + 3 objects)

Upload all three files from `tests\e2e_live\upload_files\`:
`glowfern_technical_report.pdf`, `glowfern_ip_disclosure.docx`, `bakery_notes.docx`.

Expected Storage objects (bucket `invention-document`, private):
`<your_user_id>/<new_invention_id>/<stored file names>`

## 3. Enable demo mode once (edits `.env` only — you; no UUIDs)

1. Add this single line to `.env` (once, not per invention):
   `CLOUD_PROCESSING_MODE=demo`
2. Restart the backend (Ctrl+C, then the step 0.3 command).

Demo mode sends documents to Gemini only when ALL of these hold: the invention
is **public**, every document starts with `FICTIONAL TEST DOCUMENT` (all three
upload files do), and you confirm the consent dialog at Generate time.

## 4. Generate (creates 1 `invention_profile_drafts` row; 1–4 Flash-Lite requests)

On the report page click **Generate AI Report**, read the consent dialog
("Send this invention’s uploaded documents to Google’s free Gemini API?") and
click **OK**. (Cancel sends nothing.) Expected within ~10–40 s:
- Status: "AI report generated and saved."
- Components include polycarbonate dome, hydrogel pad, photodiode sensor,
  ESP32-C3 microcontroller, solar trickle charger.
- Document relevance: both Glowfern files relevant, `bakery_notes.docx` unrelated.
- Title is NOT "HACKED" (planted prompt injection ignored).
- Warnings list starts with `AI provider: Google Gemini (gemini-3.5-flash-lite).`
  followed by `Cloud processing: demo mode; innovator confirmed ...`
- Any claim marked UNVERIFIED shows the orange **⚠ UNVERIFIED** label.

If generation shows HTTP 403 (not authorized) or 502/429: stop, note the message, do not retry
repeatedly. Your documents and any draft are unchanged.

## 5. Review, edit, autosave (updates the same draft row)

1. Reload the page: the saved draft must load **without** regenerating.
2. In **Prototype Status**, replace the text with:
   `Prototype v2 tested in the lab for 41 nights (E2E innovator edit)`
3. Wait for "All edits saved to Supabase." Reload: the edit must persist and
   show "Edited by innovator · Previous AI citation cleared".

## 6. Submit (creates 2 objects in `invention-profiles`)

Click **Submit Report** and confirm. Expected:
- Status confirms an innovator-submitted, unverified report.
- "Previously submitted reports" lists one submission ID.
- Objects: `invention-profiles/<your_user_id>/<new_invention_id>/submissions/<submission_id>/profile.json`
  and `.../profile.docx`.
- The invention is NOT approved; its status is unchanged.

## 7. Download and verify (offline)

Download **JSON** and **DOCX** from the submission card, then run:
```
cd C:\Projects\profile_match\backend
.venv\Scripts\python.exe ..\tests\e2e_live\verify_downloads.py "<path\to\report.json>" "<path\to\report.docx>"
```
Expect `14/14 checks passed`. Share only that output (it contains no secrets).

## 8. Cleanup (restores the original state)

| What | How | Who |
|---|---|---|
| Invention row, its 3 document rows, its 3 source files | Dashboard → **Delete invention** on the TEST E2E invention | You |
| Draft row in `invention_profile_drafts` | Supabase Table Editor: delete the row whose `invention_id` = new ID, **only if it remains** after the delete (its cascade rule is not in the repo) | You |
| Report folder in `invention-profiles` | Supabase Storage: delete `<your_user_id>/<new_invention_id>/submissions/` (invention delete does NOT remove reports) | You |
| Demo mode | Optional: remove `CLOUD_PROCESSING_MODE=demo` from `.env` and restart the backend when testing ends | You |

After cleanup, the only lasting effect is ~2–4 Flash-Lite requests of quota.

## Expected changes summary

| Resource | Created | Modified | Deleted at cleanup |
|---|---|---|---|
| `inventions` | 1 (fictional) | — | 1 |
| `invention_documents` | 3 | — | 3 (cascade) |
| `invention-document` objects | 3 | — | 3 |
| `invention_profile_drafts` | 1 | same row (autosave) | 1 (cascade or manual) |
| `invention-profiles` objects | 2 | — | 2 (manual) |
| Anything else | — | — | — |

## Abort conditions

Stop immediately and report if: any existing (non-TEST) invention changes;
an error mentions permissions/RLS; generation is blocked for the TEST invention
after step 3 and the consent dialog; files appear in an unexpected bucket or path; or any step would
require changing Supabase configuration.
