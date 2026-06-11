# V3 Automation Requirements

## Goal
Create an automation run by Jody that behaves like a personal staffing assistant for Sai's first cybersecurity job search, without requiring a full standalone product build first.

This is explicitly an automation operated by Jody, not a separate autonomous product that replaces Jody.

## Core behavior
1. Continuously discover new cybersecurity jobs relevant to Sai.
2. Keep running until it finds **15 new appliable jobs per day**.
3. Judge appliable jobs using Sai's master resume, profile constraints, and truthful fit.
4. Score and categorize jobs so the best opportunities rise to the top.
5. Generate job-specific truthful tailored resumes.
6. Run ATS-style scoring against each job and tailored resume.
7. If ATS score is greater than 85, send Sai a Telegram notification with the apply link and summary.
8. If Sai replies YES, continue the truthful resume-improvement loop until the score reaches 95+ or no truthful improvement remains.
9. Store jobs and resume records in a database.
10. Display the stored information in a web page with a Jobright-style layout.

## Daily target requirement
- Target: **15 new appliable jobs per UTC day**.
- The automation should keep sourcing and evaluating jobs until the target is reached.
- Once the target is reached, it can stop active discovery for the day and continue monitoring/checking on the next cycle.

## Job storage requirement
Store job records in a database with fields such as:
- job id
- title
- company
- location
- work mode (remote / hybrid / onsite)
- job type (full-time / internship / contract)
- experience level
- salary if known
- source
- original application URL
- cleaned canonical URL
- discovered time
- score state
- status
- sponsorship likelihood
- notes / reasoning

## Resume storage requirement
Store tailored resume records for each job.
Preferred design:
- resume files live on disk as versioned files
- database stores metadata and file paths

Resume record fields should include:
- resume version id
- linked job id
- source master resume version
- tailored resume path
- created time
- ATS score
- fit summary
- improvement iteration count
- truthfulness / guardrail notes

## Scoring and categorization requirement
Each job should be categorized or scored with at least:
- overall fit score
- ATS score
- skill match score
- experience-level fit
- sponsorship likelihood
- category or decision state

Suggested states:
- discovered
- reviewed
- appliable
- shortlisted
- alerted
- tailoring-in-progress
- awaiting-approval
- approved-for-loop
- applied
- rejected
- archived

## Tailoring requirement
- Use Sai's master resume as the baseline.
- Tailor per job without lying or inventing experience.
- Highlight true overlap with the job description.
- Track each iteration of the tailored resume.
- Stop improving when:
  - ATS score reaches 95+, or
  - no more truthful improvement remains.

## Telegram requirement
When a job crosses the ATS threshold:
- send Sai a Telegram notification containing:
  - title
  - company
  - overall fit
  - ATS score
  - why it matches
  - apply link
  - whether more tailoring is recommended

Then ask whether to proceed.
- If Sai says YES, enter the resume-improvement loop.
- If Sai says NO, keep the job stored and marked accordingly.

## Web UI requirement
Build a webpage that displays the stored jobs and resume data in a layout inspired by Jobright.

### List view should show
- title
- company
- location
- remote / hybrid / onsite
- job type
- experience level
- salary if available
- sponsorship likelihood
- overall match score
- ATS score
- apply button/link
- status such as saved / alerted / tailored / applied / rejected

### Detail view should show
- full job description
- why it matches Sai
- missing keywords
- score breakdown
- current tailored resume version
- resume iteration history
- actions like open resume, apply, skip, approve tailoring loop

## Guardrails
- Never fabricate experience.
- Never claim skills Sai does not actually have.
- Tailoring must remain truthful and defensible.
- Resume improvement must stop when only dishonest gains remain.

## Product framing
This is an automation-first personal staffing workflow, not necessarily a fully independent product yet.
The automation can own the workflow while the web page and database provide visibility, tracking, and control.
