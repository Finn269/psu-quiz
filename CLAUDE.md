# psu-quiz — project notes for Claude

## Rule: bump the build label on every edit
- `index.html` has a build label in the top bar: `build YYYY-MM-DD.N`.
- Every time `index.html` is changed, update this label before committing.
- Use today's date, and if the date is the same as the last build, increase `N` by 1.
- Current value: `build 2026-11-03.1`

## Rule: reply language
- Always reply in Thai, even when the user writes in English.
- Use plain everyday Thai that anyone can understand. Avoid technical jargon, or explain it in simple words when it is needed.
- Keep answers short and to the point, to save tokens.
