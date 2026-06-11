# Reply Flow

## When Sai replies YES
1. load the shortlisted job record
2. create `tailored/<company>-<role>/`
3. generate `resume.md` targeted to the posting while staying truthful
4. generate `cover_letter.md` if the job would benefit from it
5. generate `fit_notes.md` with keyword mapping and interview framing
6. estimate whether the tailored package plausibly reaches >=95 relevance under the rubric
7. append a row to `state/applications.csv` with the apply link and artifact paths
8. send Sai a concise update with the tailored file paths or links

## When Sai replies NO
- do not tailor
- leave the reviewed record in the ledger
- optionally mark the job as skipped in notes later

## Gold rule
Relevance should increase through better framing and keyword alignment, not by inventing experience.
