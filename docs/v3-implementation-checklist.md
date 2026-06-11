# V3 Automation Implementation Checklist

This checklist is for building the V3 staffing automation operated by Jody.

## 0. Ground the automation contract
- [ ] Confirm Jody is the operator of the workflow, not a separate autonomous app.
- [ ] Treat `docs/v3-automation-requirements.md` as the source of truth.
- [ ] Define what counts as an "appliable job" for Sai.
- [ ] Define the exact daily success condition: 15 new appliable jobs per UTC day.
- [ ] Define when the automation should pause, resume, or notify Sai.

## 1. Candidate truth source
- [ ] Confirm `resumes/master_resume.md` is the canonical resume baseline.
- [ ] Confirm `config/profile.json` contains Sai's real constraints:
  - [ ] sponsorship required
  - [ ] US-only roles
  - [ ] target role families
  - [ ] salary floor
  - [ ] relocation / remote / hybrid / onsite preferences
- [ ] Add explicit truthfulness guardrails for tailoring.
- [ ] Define which skills are production experience versus lab exposure.

## 2. Database design
- [ ] Expand or replace the current V3 schema to support the automation workflow.
- [ ] Add a `jobs` model/table for canonical stored opportunities.
- [ ] Add a `job_scores` model/table or equivalent score fields for:
  - [ ] overall fit
  - [ ] ATS score
  - [ ] skill match
  - [ ] experience fit
  - [ ] sponsorship likelihood
- [ ] Add a `job_status_history` table or equivalent audit trail.
- [ ] Add a `resume_versions` table.
- [ ] Add a `notifications` table for Telegram sends and replies.
- [ ] Add a `daily_runs` or `daily_targets` table for tracking the 15/day goal.
- [ ] Add indexes for common filters like status, score, date, company, title.

## 3. Resume artifact storage
- [ ] Keep tailored resumes as versioned files on disk.
- [ ] Standardize resume folder layout per job.
- [ ] Store DB metadata for each resume version:
  - [ ] job id
  - [ ] resume path
  - [ ] created time
  - [ ] iteration number
  - [ ] ATS score
  - [ ] summary of changes
  - [ ] truthfulness notes
- [ ] Add version linking from tailored resumes back to the master resume baseline.

## 4. Discovery automation
- [ ] Define all active sources the automation should search.
- [ ] Keep direct-source expansion as the preferred path.
- [ ] Improve official-source discovery coverage beyond current Greenhouse/Lever/company pages.
- [ ] Add better support for Workday-like sources.
- [ ] Add source quality tracking.
- [ ] Add deduplication across URLs, requisitions, and near-duplicate titles.
- [ ] Add retry/backoff behavior for flaky sources.
- [ ] Add scheduling so discovery keeps running until the daily target is reached.

## 5. Appliable-job decision engine
- [ ] Define the rules that make a job appliable for Sai.
- [ ] Reject obvious blockers automatically.
- [ ] Score truth-based fit against Sai's master resume.
- [ ] Distinguish between:
  - [ ] good fit
  - [ ] stretch but possible
  - [ ] not worth applying
- [ ] Mark jobs as "new appliable" only once per day target accounting.
- [ ] Prevent duplicate counting toward the 15/day target.

## 6. Scoring engine
- [ ] Define the overall fit score formula.
- [ ] Define the ATS-style score formula.
- [ ] Define a skill match breakdown.
- [ ] Define an experience-level fit breakdown.
- [ ] Define sponsorship likelihood scoring.
- [ ] Add score reasoning/explanations for the UI.
- [ ] Add thresholds for:
  - [ ] store only
  - [ ] shortlist
  - [ ] notify Sai
  - [ ] enter tailoring loop

## 7. Tailoring automation
- [ ] Build a per-job truthful tailoring generator from the master resume.
- [ ] Generate a first-pass tailored resume for strong jobs.
- [ ] Record exactly what changed from the master resume.
- [ ] Generate fit notes explaining match and gaps.
- [ ] Ensure every tailored output stays defensible and truthful.
- [ ] Add a stop condition when no further truthful improvements remain.

## 8. ATS improvement loop
- [ ] Build an ATS evaluator for a job + resume pair.
- [ ] Run ATS scoring on the initial tailored resume.
- [ ] If ATS score > 85, prepare the job for notification.
- [ ] If Sai approves, run iterative resume-improvement passes.
- [ ] Re-score after each pass.
- [ ] Stop when ATS score reaches 95+ or gains plateau.
- [ ] Persist every iteration and score in the database.

## 9. Telegram interaction flow
- [ ] Define the Telegram message format for strong jobs.
- [ ] Include title, company, fit, ATS score, why it matches, and apply link.
- [ ] Ask Sai whether to proceed with the resume-improvement loop.
- [ ] Route YES/NO replies to the correct job reliably.
- [ ] Update DB status on send, approval, rejection, and completion.
- [ ] Prevent ambiguous reply handling.

## 10. Continuous automation loop
- [ ] Create a single orchestrator for the staffing workflow.
- [ ] On each run:
  - [ ] discover leads
  - [ ] verify canonical jobs
  - [ ] score and classify jobs
  - [ ] count new appliable jobs for the day
  - [ ] generate initial tailored resumes where appropriate
  - [ ] run ATS scoring
  - [ ] notify Sai on threshold hits
- [ ] Keep running until 15 new appliable jobs are found for the day.
- [ ] After reaching the target, reduce activity to monitoring/maintenance.
- [ ] Reset or reopen the target on the next UTC day.

## 11. Web UI, Jobright-style
- [ ] Replace the current dashboard with a staffing-style jobs interface.
- [ ] Build a list view with cards/rows for jobs.
- [ ] Show:
  - [ ] title
  - [ ] company
  - [ ] location
  - [ ] work mode
  - [ ] job type
  - [ ] experience level
  - [ ] salary if available
  - [ ] sponsorship likelihood
  - [ ] overall fit score
  - [ ] ATS score
  - [ ] status
  - [ ] apply link/action
- [ ] Build a job detail panel/view.
- [ ] Show:
  - [ ] job description
  - [ ] score breakdown
  - [ ] why it matches
  - [ ] missing keywords
  - [ ] current tailored resume
  - [ ] resume version history
  - [ ] actions like apply, skip, approve loop
- [ ] Add filters for status, score, company, source, sponsorship, date.

## 12. Resume visibility in UI
- [ ] Show whether a tailored resume exists for each job.
- [ ] Show current resume version score.
- [ ] Show iteration history.
- [ ] Allow opening/downloading the current tailored resume.
- [ ] Show concise change summaries between versions.

## 13. State management and categories
- [ ] Define canonical job states.
- [ ] Define transitions between states.
- [ ] Make statuses visible in the UI and DB.
- [ ] Ensure every important action leaves an auditable record.

## 14. Quality and safety checks
- [ ] Add validation that tailoring does not invent claims.
- [ ] Add checks for malformed or low-confidence job records.
- [ ] Add checks for missing apply links.
- [ ] Add checks for duplicate notifications.
- [ ] Add checks for reply ambiguity.
- [ ] Add safe handling for flaky source pages.

## 15. Reporting and observability
- [ ] Show daily progress toward 15 appliable jobs.
- [ ] Show how many jobs were discovered, reviewed, appliable, alerted, tailored, and applied.
- [ ] Show why jobs were rejected.
- [ ] Show source health and source yield.
- [ ] Log automation runs in a way Jody can inspect quickly.

## 16. Migration from current code
- [ ] Map current V3 tables to the new workflow.
- [ ] Preserve useful existing discovered/canonical data where possible.
- [ ] Reuse the current tailoring pieces only where they fit the truthfulness model.
- [ ] Reuse current Telegram/reply handling only after job-correlation is made reliable.
- [ ] Rework the current dashboard into the new UI instead of maintaining two competing views.

## 17. First practical milestone
- [ ] One orchestrated automation run can:
  - [ ] discover jobs
  - [ ] store them in DB
  - [ ] classify appliable jobs
  - [ ] generate an initial tailored resume
  - [ ] compute ATS score
  - [ ] show the result in the web UI
  - [ ] notify Sai for a strong job
- [ ] The system can do this repeatedly without manual cleanup.

## 18. Done definition
The automation is meaningfully usable when:
- [ ] Jody can run it continuously.
- [ ] It can reach 15 new appliable jobs in a day when sources allow.
- [ ] Jobs are stored, scored, categorized, and visible in the UI.
- [ ] Tailored resumes are versioned and tracked.
- [ ] ATS-style scoring and improvement loop work truthfully.
- [ ] Telegram approval works reliably.
- [ ] Sai can see and act on strong opportunities without digging through raw files.
