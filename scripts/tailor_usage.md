# Tailoring Usage

## Input
Use a processed job JSON file created by `scripts/run_pipeline.py`.

## Command
```bash
python3 scripts/tailor_job.py processed/<job-file>.json
```

## Output
Creates a folder in `tailored/company-role/` containing:
- `resume.md`
- `cover_letter.md`
- `fit_notes.md`
- `package.json`

Also appends a row to:
- `state/applications.csv`

## Workflow
1. review a job
2. if Sai says YES
3. run tailor script on that processed job
4. send back the tailored file paths
5. apply using the stored link and materials
