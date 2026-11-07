# psu-quiz — project notes for Claude

## Rule: bump the build label on every edit
- `index.html` has a build label in the top bar: `build YYYY-MM-DD.N`.
- Every time `index.html` is changed, update this label before committing.
- Use today's date, and if the date is the same as the last build, increase `N` by 1.
- The current value is whatever is in `index.html` (read it there; do not copy it into this file).

## Rule: reply language
- Always reply in Thai, even when the user writes in English.
- Use plain everyday Thai that anyone can understand. Avoid technical jargon, or explain it in simple words when it is needed.
- Keep answers very short to save tokens: max ~6 lines or a few bullets. No long intros, no repeating what was done, no option lists unless asked.
- Do not narrate each tool step. Report only the result and the one thing needed from the user.

## Library (clean exam bank)
- Pipeline lives in `library/` (see `library/README.md`). PDFs go in `library/raw/<Block>/<cohort>/MCQ.pdf` and `MCQ-key.pdf`; run `python3 library/tools/build_clean.py --all`.
- Never guess an answer key. Correct answer comes only from highlight/text in the key file, or from a human decision (`library/decisions/`).
- Only questions with status `verified` are used for quizzes. After changing `library/tools/`, run `python3 library/tools/selftest.py`.
- The web app reads `library/clean/index.json`, so it must be served over http (GitHub Pages or `python3 -m http.server`).
- Answer keys are student-made and can be wrong. Each question carries `opinions` from several sources (file key, `cross_cohort` duplicates, `ai`, `lecture`). If any source disagrees, status becomes `review` and the user decides in the review tab (user decision always wins). AI opinions live in `library/opinions/<slug>.ai.json` and are advisory only.
- Getting PDFs from Drive yourself: call `mcp__Google_Drive__download_file_content` with the fileId (ids are in `library/manifest.json`). The result is too big for chat and is saved to a file (path is in the message); decode it with `python3 library/tools/drive_import.py <saved file> library/raw/<Block>/<cohort>/MCQ.pdf <expected bytes>` (use `MCQ-key.pdf` for keys). Limits: Drive refuses files over 10 MB, and the connection drops above roughly 5.5 MB; ask the user to upload those two kinds of files via GitHub instead.
- After a new PDF layout appears, run `selftest.py`, rebuild, then check a random sample of detected answers by eye (contact sheet of key crops) before trusting it. Past failures: X marks read as circles, faint background watermarks read as highlights, two-column layouts.
