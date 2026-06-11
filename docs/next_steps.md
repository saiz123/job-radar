# Next Steps

1. Build parser/search adapters for fetchable sources (Greenhouse, Lever, Ashby, company career pages).
2. Add normalization pipeline to store jobs in data/jobs.json.
3. Add scorer to compare jobs against config/profile.json and resumes/master_resume.md.
4. Add resume tailoring generator and artifact storage under resumes/tailored/.
5. Add CSV/XLSX export pipeline for applications.
6. Add Telegram alert sender via current OpenClaw session once approved.

## Current blocker
Shell execution is currently unavailable due to local OpenClaw gateway pairing error, so implementation is scaffolded but not runnable yet from this session.
