# data/

This folder is populated at runtime and is gitignored except for this file. Nothing here should ever be committed — it's all personal (your resume, generated application materials, credentials cache, tracking history).

Put your resume here to get started:

- `data/<your_name>_Resume.docx` — your base resume (any filename ending in `.docx`). The agent picks the most recently modified `.docx` in this folder.

Everything else is generated automatically as you use the tool:

| Path | What it is |
|---|---|
| `discovered_jobs.json` | All jobs found across runs |
| `job_tracker.xlsx` | Excel tracker (Discovered Jobs + Applications & Status sheets) |
| `applications.csv` / `applications.json` | Log of every application sent |
| `linkedin_session.json` | Cached LinkedIn login session (Playwright storage state) |
| `resumes/` | Tailored resume `.docx`/`.pdf` per job |
| `cover_letters/` | Generated cover letters per job |
| `web_state/` | Web app's in-progress run state |
| `*.png` | Debug screenshots taken during scraping |
