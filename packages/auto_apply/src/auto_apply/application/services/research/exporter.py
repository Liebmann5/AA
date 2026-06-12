"""Research data export service for generating reports and data extracts."""

# Layer: application
# Depends on: domain

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from auto_apply.domain.models.research import ResearchSignal

from auto_apply.domain.models.job import Job
from auto_apply.domain.models.session_report import SessionReport
from auto_apply.domain.ports.repository_port import JobRepositoryPort


class ResearchExporter:
    """Service for exporting research data in various formats."""

    def __init__(self, job_repository: JobRepositoryPort):
        self._job_repository = job_repository

    def export_jobs_to_json(self, jobs: list[Job], output_path: Path) -> bool:
        """Export job data to JSON format.

        Args:
            jobs: List of jobs to export
            output_path: Path where JSON file will be written

        Returns:
            True if export successful, False otherwise
        """
        try:
            job_data = [
                {
                    'title': job.title,
                    'company': job.company,
                    'location': job.location,
                    'url': job.url,
                    'description': job.description,
                    'posted_date': job.posted_date.isoformat() if job.posted_date else None,  # noqa: E501
                    'salary_range': job.salary_range,
                    'remote_ok': job.remote_ok,
                    'created_at': job.created_at.isoformat(),
                    'updated_at': job.updated_at.isoformat()
                }
                for job in jobs
            ]

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(job_data, f, indent=2, ensure_ascii=False)

            return True

        except Exception:
            return False

    def export_jobs_to_csv(self, jobs: list[Job], output_path: Path) -> bool:
        """Export job data to CSV format.

        Args:
            jobs: List of jobs to export
            output_path: Path where CSV file will be written

        Returns:
            True if export successful, False otherwise
        """
        if not jobs:
            return True

        try:
            fieldnames = [
                'title', 'company', 'location', 'url', 'description',
                'posted_date', 'salary_range', 'remote_ok', 'created_at', 'updated_at'
            ]

            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()

                for job in jobs:
                    writer.writerow({
                        'title': job.title,
                        'company': job.company,
                        'location': job.location,
                        'url': job.url,
                        'description': job.description,
                        'posted_date': job.posted_date.isoformat() if job.posted_date else '',  # noqa: E501
                        'salary_range': job.salary_range or '',
                        'remote_ok': job.remote_ok,
                        'created_at': job.created_at.isoformat(),
                        'updated_at': job.updated_at.isoformat()
                    })

            return True

        except Exception:
            return False

    def export_session_report(self, report: SessionReport, output_path: Path) -> bool:
        """Export session report to JSON format.

        Args:
            report: Session report to export
            output_path: Path where report will be written

        Returns:
            True if export successful, False otherwise
        """
        try:
            report_data = {
                'session_id': report.session_id,
                'start_time': report.start_time.isoformat(),
                'end_time': report.end_time.isoformat() if report.end_time else None,
                'jobs_discovered': report.jobs_discovered,
                'jobs_vetted': report.jobs_vetted,
                'jobs_applied': report.jobs_applied,
                'errors_encountered': report.errors_encountered,
                'success_rate': report.success_rate,
                'metadata': report.metadata or {}
            }

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, indent=2, ensure_ascii=False)

            return True

        except Exception:
            return False

    def export_research_signals(self, signals: list[ResearchSignal], output_path: Path) -> bool:  # noqa: E501
        """Export research signals to JSON format.

        Args:
            signals: List of research signals to export
            output_path: Path where signals will be written

        Returns:
            True if export successful, False otherwise
        """
        try:
            signal_data = [
                {
                    'signal_type': signal.signal_type,
                    'confidence': signal.confidence,
                    'data': signal.data,
                    'timestamp': signal.timestamp.isoformat(),
                    'source': signal.source
                }
                for signal in signals
            ]

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(signal_data, f, indent=2, ensure_ascii=False)

            return True

        except Exception:
            return False

    def generate_summary_report(self, jobs: list[Job]) -> dict[str, Any]:
        """Generate summary statistics from job data.

        Args:
            jobs: List of jobs to analyze

        Returns:
            Dictionary containing summary statistics
        """
        if not jobs:
            return {
                'total_jobs': 0,
                'companies': [],
                'locations': [],
                'remote_jobs': 0,
                'salary_info': {}
            }

        companies = set()
        locations = set()
        remote_count = 0
        salaries = []

        for job in jobs:
            if job.company:
                companies.add(job.company)
            if job.location:
                locations.add(job.location)
            if job.remote_ok:
                remote_count += 1
            if job.salary_range:
                salaries.append(job.salary_range)

        return {
            'total_jobs': len(jobs),
            'unique_companies': len(companies),
            'unique_locations': len(locations),
            'remote_jobs': remote_count,
            'remote_percentage': (remote_count / len(jobs)) * 100,
            'top_companies': sorted(companies)[:10],
            'top_locations': sorted(locations)[:10],
            'generated_at': datetime.now().isoformat()
        }
