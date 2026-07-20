# Job Monitor

Automated job-posting monitor for selected companies. It fetches career-page jobs, normalizes postings, filters for AI/ML/data-science-related roles, deduplicates against a Google Sheet, appends new matches, and logs each run.

The scheduler is GitHub Actions, so the monitor continues running when your laptop is off.

## Architecture

```text
GitHub Actions cron/manual run
  -> CLI
  -> YAML config validation
  -> source adapter per company
  -> deterministic filtering
  -> deduplication against Google Sheet
  -> append Jobs rows and Run Log row
```

The design is intentionally small: Python package, YAML config, HTTP adapters, Google Sheets as persistent storage, tests, and GitHub Actions. There is no database, Docker, queue, or browser automation in the MVP.

## Supported ATS systems

Implemented and tested:

- Greenhouse public board API
- Lever postings API
- Ashby job board API

Explicitly unsupported in this MVP:

- Workday: public career APIs and payloads vary by tenant.
- SmartRecruiters: adapter structure exists, but support is not claimed until tested.
- Company-specific custom sites: add a dedicated adapter before enabling them.

## Setup

Requires Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Validate the example config:

```bash
python -m job_monitor --config config/companies.yml validate-config
```

## Configure companies

Edit `config/companies.yml` to add, remove, enable, or disable companies.

Example Greenhouse entry:

```yaml
companies:
  - name: Example Company
    slug: example-company
    enabled: true
    source_type: greenhouse
    ats_identifier: verified-greenhouse-board-token
    careers_url: https://www.example.com/careers
    location_filters:
      - United States
      - Remote
```

You can also provide a full `api_endpoint` if a company uses a compatible endpoint but the slug is not enough.

## Local execution

Dry-run mode fetches and filters jobs but does not write to Google Sheets:

```bash
python -m job_monitor --config config/companies.yml run --dry-run
```

Run one company:

```bash
python -m job_monitor --config config/companies.yml run --company example-company --dry-run
```

Run and write to Google Sheets:

```bash
export GOOGLE_SHEET_ID="your-sheet-id"
export GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account", ...}'
python -m job_monitor --config config/companies.yml run
```

## Google Cloud and Sheets setup

1. Create or select a Google Cloud project.
2. Enable the Google Sheets API.
3. Create a service account.
4. Create a JSON key for the service account.
5. Create a Google Sheet.
6. Share the sheet with the service-account email address, usually ending in `iam.gserviceaccount.com`.
7. Give the service account editor access to the sheet.

Required environment variables:

```bash
GOOGLE_SHEET_ID=...
GOOGLE_SERVICE_ACCOUNT_JSON='...full JSON service account key...'
```

Do not commit credentials.

## GitHub Actions setup

Add these repository secrets:

- `GOOGLE_SERVICE_ACCOUNT_JSON`
- `GOOGLE_SHEET_ID`

The workflow runs every 12 hours and supports manual `workflow_dispatch`. GitHub Actions cron timing is approximate and may be delayed.

By default the workflow uses:

```yaml
JOB_MONITOR_CONFIG: config/companies.yml
```

Company slugs and public careers URLs are not credentials. Do not put private API keys or secrets in this file.

## Filtering

Filtering is deterministic. No LLM API is used.

The default filters prioritize:

- data science
- applied science
- machine learning
- artificial intelligence
- generative AI
- LLMs
- AI agents
- model evaluation
- retrieval
- recommendation systems
- experimentation
- causal inference
- forecasting

Default exclusions include internships, sales, recruiting, nursing, warehouse, technician, customer support, and marketing. You can override include/exclude keywords globally or per company.

Each matched row includes a short match reason.

## Deduplication

The Google Sheet is the persistent store for previously seen jobs. Existing `Deduplication Key` values are read before inserting new rows.

Key priority:

1. Company plus source job ID.
2. Normalized application URL or posting URL.
3. Company plus normalized title plus normalized location.

URL normalization removes common tracking query parameters. Text normalization handles case, punctuation, and whitespace changes.

## Google Sheet layout

The monitor creates or updates two worksheets:

- `Jobs`
- `Run Log`

`Jobs` columns:

```text
Company, Title, Location, Department, Employment Type, Date Posted, First Seen,
Match Reason, Posting URL, Application URL, Source, Source Job ID,
Deduplication Key, Status, Notes
```

After insertion, rows are sorted by company, first-seen date descending, then title. The header row is preserved.

## Add a new adapter

1. Add a file under `src/job_monitor/sources/`.
2. Implement:

   ```python
   class MySource:
       source_name = "my-source"

       def endpoint_for(self, company: CompanyConfig) -> str:
           ...

       def fetch_jobs(self, company: CompanyConfig) -> list[JobPosting]:
           ...
   ```

3. Keep all API-specific assumptions inside the adapter.
4. Register it in `src/job_monitor/sources/registry.py`.
5. Add tests and sample fixtures.
6. Only mark it supported after tests parse realistic responses.

## Tests and linting

```bash
ruff check .
ruff format --check .
pytest
```

Format if needed:

```bash
ruff format .
```

## Current limitations

- Workday and SmartRecruiters are not implemented as reliable general adapters.
- The MVP avoids browser automation, so JavaScript-only career pages need custom adapters or API discovery.
- Verify ATS identifiers before enabling additional companies.
- Google Sheets is adequate for a personal monitor, but not for high-volume analytics.
