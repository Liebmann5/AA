# Layer: application
# Depends on: domain

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from auto_apply.domain.exceptions import ApplicationError
from auto_apply.domain.models.profile import UserProfile


@dataclass
class AnonymizationRule:
    """Configuration for how to anonymize a specific field type."""
    field_pattern: str
    replacement_strategy: str  # 'hash', 'mask', 'remove', 'generic'
    preserve_format: bool = False


class DataAnonymizer:
    """Application service for anonymizing sensitive data in research contexts.

    This service provides PII protection capabilities for job application
    research data, ensuring sensitive information is scrubbed while
    preserving data utility for analysis.
    """

    def __init__(self):
        self._rules = self._get_default_rules()
        self._salt = "autoapply_anonymization_salt_v1"

    def anonymize_profile(self, profile: UserProfile) -> dict[str, Any]:
        """Create an anonymized version of a user profile for research.

        Args:
            profile: The user profile to anonymize

        Returns:
            Dictionary with anonymized profile data

        Raises:
            ApplicationError: If anonymization fails
        """
        try:
            return {
                'id': self._hash_value(profile.email),  # Use email hash as stable ID
                'experience_level': profile.experience_level,
                'preferred_locations': self._anonymize_locations(profile.preferred_locations),  # noqa: E501
                'skills': profile.skills,  # Skills are generally not PII
                'job_titles': profile.preferred_job_titles,
                'salary_range': profile.salary_expectations,
                'work_preferences': {
                    'remote_ok': getattr(profile.work_preferences, 'remote_ok', None),
                    'full_time': getattr(profile.work_preferences, 'full_time', None),
                    'contract_ok': getattr(profile.work_preferences, 'contract_ok', None),  # noqa: E501
                },
                'created_at': profile.created_at.isoformat() if profile.created_at else None,  # noqa: E501
            }
        except Exception as e:
            raise ApplicationError(f"Failed to anonymize profile: {e}")

    def anonymize_job_data(self, job_data: dict[str, Any]) -> dict[str, Any]:
        """Anonymize job listing data for research purposes.

        Args:
            job_data: Raw job data dictionary

        Returns:
            Anonymized job data dictionary
        """
        anonymized = {}

        for key, value in job_data.items():
            if key in ['company_name', 'job_title', 'location', 'description']:
                anonymized[key] = self._apply_anonymization_rules(key, value)
            elif key == 'url':
                anonymized[key] = self._anonymize_url(value)
            elif key == 'salary':
                anonymized[key] = self._anonymize_salary(value)
            else:
                # Preserve non-sensitive metadata
                anonymized[key] = value

        return anonymized

    def anonymize_application_data(self, app_data: dict[str, Any]) -> dict[str, Any]:
        """Anonymize application interaction data.

        Args:
            app_data: Application attempt data

        Returns:
            Anonymized application data
        """
        return {
            'job_id': self._hash_value(str(app_data.get('job_url', ''))),
            'platform': app_data.get('platform'),
            'attempt_timestamp': app_data.get('timestamp'),
            'success': app_data.get('success'),
            'error_type': app_data.get('error_type'),
            'form_fields_detected': app_data.get('form_fields_count', 0),
            'completion_time_seconds': app_data.get('completion_time'),
            'retry_count': app_data.get('retry_count', 0),
        }

    def _get_default_rules(self) -> list[AnonymizationRule]:
        """Get default anonymization rules for common field types."""
        return [
            AnonymizationRule(
                field_pattern=r'email',
                replacement_strategy='hash'
            ),
            AnonymizationRule(
                field_pattern=r'name',
                replacement_strategy='generic'
            ),
            AnonymizationRule(
                field_pattern=r'phone',
                replacement_strategy='mask',
                preserve_format=True
            ),
            AnonymizationRule(
                field_pattern=r'address',
                replacement_strategy='generic'
            ),
        ]

    def _apply_anonymization_rules(self, field_name: str, value: Any) -> Any:
        """Apply appropriate anonymization rule based on field name."""
        if not isinstance(value, str) or not value.strip():
            return value

        field_lower = field_name.lower()

        # Apply matching rules
        for rule in self._rules:
            if re.search(rule.field_pattern.lower(), field_lower):
                if rule.replacement_strategy == 'hash':
                    return self._hash_value(value)
                elif rule.replacement_strategy == 'mask':
                    return self._mask_value(value, rule.preserve_format)
                elif rule.replacement_strategy == 'generic':
                    return self._genericize_value(field_name, value)
                elif rule.replacement_strategy == 'remove':
                    return '[REMOVED]'

        # Default: return as-is for non-sensitive fields
        return value

    def _hash_value(self, value: str) -> str:
        """Create a stable hash of the value for anonymization."""
        if not value:
            return value

        hasher = hashlib.sha256()
        hasher.update(f"{self._salt}{value}".encode())
        return f"hash_{hasher.hexdigest()[:16]}"

    def _mask_value(self, value: str, preserve_format: bool = False) -> str:
        """Mask a value while optionally preserving format."""
        if not value:
            return value

        if preserve_format:
            # Preserve structure (e.g., phone: XXX-XXX-XXXX)
            masked = ''
            for char in value:
                if char.isalnum():
                    masked += 'X'
                else:
                    masked += char
            return masked
        else:
            return 'X' * min(len(value), 10)

    def _genericize_value(self, field_name: str, value: str) -> str:
        """Replace with a generic placeholder."""
        field_lower = field_name.lower()

        if 'name' in field_lower:
            return '[GENERIC_NAME]'
        elif 'company' in field_lower:
            return '[GENERIC_COMPANY]'
        elif 'address' in field_lower or 'location' in field_lower:
            return '[GENERIC_LOCATION]'
        else:
            return '[GENERIC_VALUE]'

    def _anonymize_locations(self, locations: list[str] | None) -> list[str]:
        """Anonymize location data while preserving geographic utility."""
        if not locations:
            return []

        anonymized = []
        for location in locations:
            # Keep general geographic regions, remove specific addresses
            if ',' in location:
                parts = [p.strip() for p in location.split(',')]
                # Keep state/country, anonymize city/specific location
                if len(parts) >= 2:
                    anonymized.append(f"[CITY], {parts[-1]}")
                else:
                    anonymized.append('[GENERIC_LOCATION]')
            # Single location - genericize if it looks specific
            elif any(keyword in location.lower() for keyword in ['street', 'avenue', 'road', 'apt', 'suite']):  # noqa: E501
                anonymized.append('[GENERIC_LOCATION]')
            else:
                anonymized.append(location)  # Probably just a city/state

        return anonymized

    def _anonymize_url(self, url: str) -> str:
        """Anonymize URLs while preserving domain structure for analysis."""
        if not url:
            return url

        try:
            from urllib.parse import urlparse  # noqa: PLC0415
            parsed = urlparse(url)

            # Keep domain and basic structure, hash specific paths/params
            domain = parsed.netloc
            if parsed.path and len(parsed.path) > 1:
                path_hash = self._hash_value(parsed.path)[:8]
                return f"{parsed.scheme}://{domain}/anonymized_path_{path_hash}"
            else:
                return f"{parsed.scheme}://{domain}/"

        except Exception:
            return '[ANONYMIZED_URL]'

    def _anonymize_salary(self, salary: Any) -> Any:
        """Anonymize salary data while preserving range information."""
        if not salary:
            return salary

        if isinstance(salary, dict):
            return {
                'min_range': self._generalize_salary(salary.get('min')),
                'max_range': self._generalize_salary(salary.get('max')),
                'currency': salary.get('currency'),
                'period': salary.get('period')
            }
        elif isinstance(salary, (int, float)):
            return self._generalize_salary(salary)
        else:
            return str(salary)  # Keep as-is if string format

    def _generalize_salary(self, amount: float | None) -> str | None:
        """Generalize salary amount to ranges for anonymization."""
        if not amount:
            return None

        # Round to broad ranges
        if amount < 50000:
            return "<50k"
        elif amount < 75000:
            return "50k-75k"
        elif amount < 100000:
            return "75k-100k"
        elif amount < 150000:
            return "100k-150k"
        elif amount < 200000:
            return "150k-200k"
        else:
            return ">200k"
