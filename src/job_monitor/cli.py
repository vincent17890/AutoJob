from __future__ import annotations

import argparse
import os

from job_monitor.config import load_config
from job_monitor.logging_config import configure_logging
from job_monitor.runner import run_monitor
from job_monitor.sheets import GoogleSheetStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="job-monitor")
    parser.add_argument(
        "--config",
        default=os.environ.get("JOB_MONITOR_CONFIG", "config/companies.yml"),
        help="Path to YAML company configuration.",
    )
    parser.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))

    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Fetch, filter, deduplicate, and write jobs.")
    run_parser.add_argument("--company", help="Run a single enabled company by slug or name.")
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch/filter without writing Sheets.",
    )
    subparsers.add_parser("validate-config", help="Validate the YAML configuration and exit.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    try:
        config = load_config(args.config)
        if args.command == "validate-config":
            print(f"configuration valid: {args.config} ({len(config.companies)} companies)")
            return 0

        sheet_store = None if args.dry_run else GoogleSheetStore.from_environment()
        summary = run_monitor(
            config,
            sheet_store=sheet_store,
            dry_run=args.dry_run,
            company_key=args.company,
        )
        print(
            "run complete: "
            f"checked={summary.companies_checked} "
            f"fetched={summary.jobs_fetched} "
            f"matched={summary.jobs_matched} "
            f"new={summary.new_jobs_inserted} "
            f"duplicates={summary.duplicates_skipped} "
            f"failures={len(summary.failures)}"
        )
        return 0
    except Exception as exc:
        print(f"system failure: {type(exc).__name__}: {exc}")
        return 1
