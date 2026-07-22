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
- Workday CXS job API for verified tenant/site endpoints
- SmartRecruiters public Posting API
- Eightfold public careers search endpoint
- iCIMS public career-portal HTML with JobPosting JSON-LD detail pages
- Avature public `SearchJobs` career-portal HTML with `JobDetail` / `FolderDetail` pages
- SAP SuccessFactors public XML job listing feed and server-rendered RMK search pages

Explicitly unsupported in this MVP:

- Company-specific custom sites: add a dedicated adapter before enabling them.

Workday support requires a verified `api_endpoint` ending in `/wday/cxs/{tenant}/{site}/jobs`.
Workday tenants vary, so do not assume one company URL pattern applies to every company.
SmartRecruiters support requires the company identifier used in
`https://careers.smartrecruiters.com/{companyIdentifier}`.
Eightfold support uses the public `app.eightfold.ai` careers search endpoint and requires
the Eightfold `domain`, for example `eightfold.ai`.
iCIMS support uses anonymous public career portals such as
`https://careers-example.icims.com/jobs/search?in_iframe=1`; it does not use the authenticated
iCIMS customer API.
Avature support uses anonymous public career portals such as
`https://example.avature.net/careers/SearchJobs`. Avature portals are highly configurable, so
verify each tenant path before enabling it.
SAP SuccessFactors support uses either the anonymous XML listing feed documented for Recruiting
Management / Recruiting Marketing career sites, for example
`https://career4.successfactors.com/career?company=<company-id>&career_ns=job_listing_summary&resultType=XML`.
It also supports server-rendered RMK search pages such as `https://jobs.sap.com/search/`.
It does not use authenticated SuccessFactors OData APIs.

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

Example SmartRecruiters entry:

```yaml
companies:
  - name: Example Company
    slug: example-company
    enabled: true
    source_type: smartrecruiters
    ats_identifier: verified-smartrecruiters-company-identifier
    careers_url: https://careers.smartrecruiters.com/verified-smartrecruiters-company-identifier
```

Example Eightfold entry:

```yaml
companies:
  - name: Example Company
    slug: example-company
    enabled: true
    source_type: eightfold
    ats_identifier: verified-domain.example
    careers_url: https://app.eightfold.ai/careers?domain=verified-domain.example
```

Example iCIMS entry:

```yaml
companies:
  - name: Example Company
    slug: example-company
    enabled: true
    source_type: icims
    ats_identifier: careers-example
    careers_url: https://careers-example.icims.com
```

Example Avature entry:

```yaml
companies:
  - name: Example Company
    slug: example-company
    enabled: true
    source_type: avature
    ats_identifier: example
    careers_url: https://example.avature.net/careers/SearchJobs
```

Example SAP SuccessFactors entry:

```yaml
companies:
  - name: Example Company
    slug: example-company
    enabled: true
    source_type: successfactors
    ats_identifier: verified-successfactors-company-id
    careers_url: https://career4.successfactors.com/career
    extra:
      locale: en_US
```

For SAP SuccessFactors XML feeds, `ats_identifier` is the SuccessFactors `company` query value.
For RMK search pages, set `api_endpoint` to the verified search URL. The career host varies by
tenant and datacenter, so verify the exact host before enabling a company.

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

- Workday support is limited to verified CXS endpoints and caps pagination to avoid very large runs.
- SmartRecruiters support is limited to public Posting API companies with verified identifiers.
- Eightfold support is limited to public `app.eightfold.ai` careers pages with verified domains.
- iCIMS support is limited to public career portals that expose server-rendered `/jobs/search`
  pages and JobPosting JSON-LD on detail pages.
- Avature support is limited to public `SearchJobs` portals that expose server-rendered
  `/JobDetail/.../{id}` or `/FolderDetail/.../{id}` links. It does not use private Avature APIs.
- SAP SuccessFactors support is limited to public XML job listing feeds and server-rendered RMK
  search pages. Tenant-specific XML/HTML mappings can vary, so verify title, URL, location,
  description, and date fields for each company.
- The MVP avoids browser automation, so JavaScript-only career pages need custom adapters or API discovery.
- Verify ATS identifiers before enabling additional companies.
- Google Sheets is adequate for a personal monitor, but not for high-volume analytics.
