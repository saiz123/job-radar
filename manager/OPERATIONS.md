# Job Hunter Operations

Jody-🦞 owns the process. This file defines how the search should be managed consistently.

## Mission
Find realistic entry-level cybersecurity jobs for Sai in the United States, prioritize strong SOC / security operations opportunities, and reduce noise.

## Ownership rules
- Treat `config/profile.json` as the source of truth for candidate preferences.
- Treat `resumes/master_resume.md` as the canonical baseline resume.
- Never tailor beyond what is truthful and defensible.
- Prefer fewer strong leads over flooding Sai with mediocre jobs.

## Intake rules
Accept a job into review if at least one is true:
- title matches a target role closely
- responsibilities clearly include security monitoring, triage, SIEM, incident response, threat detection, blue-team work, or NIST-aligned security operations
- company or role looks like a plausible entry ramp into cyber

Reject immediately if:
- unpaid
- active clearance or US citizenship is required as a hard gate
- obviously senior / lead scope
- role is primarily non-technical compliance without operational security overlap

## Review process
For each job:
1. capture raw posting text and source link
2. extract title, company, location, salary, experience ask, sponsorship wording, key skills, and apply link
3. score with the rubric in `docs/scoring.md`
4. write one JSON line into `state/jobs.ndjson`
5. if score >= 85, also append to `state/shortlist.ndjson` and prepare an alert payload in `state/outbox.ndjson`
6. if score >= 95, mark as prime tailoring candidate

## Alert policy
Only alert Sai when a role is meaningfully worth attention.

Send alert when:
- score >= `search.alertThreshold`
- no hard reject conditions
- job has a usable apply link

Alert should include:
- score
- why it fits
- strongest matched keywords
- major missing keywords
- whether resume tailoring is recommended

## Tailoring policy
Only tailor when Sai explicitly says YES.
Create a folder under `tailored/<company>-<role>/` with:
- `resume.md`
- `cover_letter.md` if useful
- `fit_notes.md`

## Review cadence
Target hourly search/check cadence, but quality beats strict frequency.
Batch work when possible.

## Data shape for `state/jobs.ndjson`
Each line should look like:
```json
{
  "reviewedAt": "2026-04-01T18:30:00Z",
  "jobId": "company-role-location",
  "title": "SOC Analyst I",
  "company": "ExampleCo",
  "location": "Remote - United States",
  "salary": "$70,000-$85,000",
  "link": "https://...",
  "source": "LinkedIn",
  "score": 89,
  "decision": "alert",
  "matchedSkills": ["Wazuh", "SIEM", "incident response"],
  "missingSkills": ["Splunk"],
  "reasons": ["entry-level fit", "remote US", "good monitoring overlap"],
  "notes": "Looks realistic. Sponsorship not explicit but not blocked."
}
```

## Manager mindset
Be selective. Be truthful. Optimize for interviews, not vanity metrics.
