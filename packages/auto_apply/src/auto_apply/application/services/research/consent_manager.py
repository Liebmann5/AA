# Layer: application
# Depends on: domain

"""
Consent Manager for research data collection and processing.

Handles user consent validation, policy compliance, and consent workflow orchestration.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from auto_apply.domain.exceptions import ApplicationError
from auto_apply.domain.models.profile import UserProfile


@dataclass
class ConsentRecord:
    """Record of user consent for specific research activities."""
    consent_type: str
    granted: bool
    timestamp: datetime
    expiry: datetime | None = None
    metadata: dict[str, Any] | None = None


class ConsentError(ApplicationError):
    """Raised when consent validation or processing fails."""
    pass


class ConsentManager:
    """Manages user consent for research data collection and processing."""

    def __init__(self):
        self._consent_records: dict[str, ConsentRecord] = {}
        self._required_consents = {
            'data_collection',
            'usage_analytics',
            'anonymized_research',
            'performance_monitoring'
        }

    def grant_consent(self, consent_type: str, duration_days: int | None = None) -> None:  # noqa: E501
        """Grant consent for a specific research activity type.

        Args:
            consent_type: Type of research activity requiring consent
            duration_days: Optional expiry duration in days

        Raises:
            ConsentError: If consent type is invalid
        """
        if consent_type not in self._required_consents:
            raise ConsentError(f"Unknown consent type: {consent_type}")

        expiry = None
        if duration_days:
            expiry = datetime.now() + timedelta(days=duration_days)

        self._consent_records[consent_type] = ConsentRecord(
            consent_type=consent_type,
            granted=True,
            timestamp=datetime.now(),
            expiry=expiry
        )

    def revoke_consent(self, consent_type: str) -> None:
        """Revoke previously granted consent.

        Args:
            consent_type: Type of research activity to revoke consent for

        Raises:
            ConsentError: If consent type is invalid
        """
        if consent_type not in self._required_consents:
            raise ConsentError(f"Unknown consent type: {consent_type}")

        self._consent_records[consent_type] = ConsentRecord(
            consent_type=consent_type,
            granted=False,
            timestamp=datetime.now()
        )

    def has_valid_consent(self, consent_type: str) -> bool:
        """Check if user has valid consent for a research activity.

        Args:
            consent_type: Type of research activity to check

        Returns:
            True if consent is granted and not expired
        """
        record = self._consent_records.get(consent_type)
        if not record or not record.granted:
            return False

        # Check if consent has expired
        if record.expiry and datetime.now() > record.expiry:
            return False

        return True

    def get_consent_status(self) -> dict[str, bool]:
        """Get current consent status for all research activities.

        Returns:
            Dictionary mapping consent types to their validity status
        """
        return {
            consent_type: self.has_valid_consent(consent_type)
            for consent_type in self._required_consents
        }

    def get_missing_consents(self) -> list[str]:
        """Get list of required consents that are not granted or expired.

        Returns:
            List of consent types requiring user action
        """
        return [
            consent_type for consent_type in self._required_consents
            if not self.has_valid_consent(consent_type)
        ]

    def validate_research_operation(self, required_consents: list[str]) -> None:
        """Validate that all required consents are granted for an operation.

        Args:
            required_consents: List of consent types required for the operation

        Raises:
            ConsentError: If any required consent is missing or expired
        """
        missing = []
        for consent_type in required_consents:
            if not self.has_valid_consent(consent_type):
                missing.append(consent_type)

        if missing:
            raise ConsentError(
                f"Missing required consents: {', '.join(missing)}"
            )

    def apply_user_preferences(self, profile: UserProfile) -> None:
        """Apply user consent preferences from their profile.

        Args:
            profile: User profile containing consent preferences
        """
        # Apply any consent settings from user profile
        # This would typically load from user's saved preferences
        pass

    def get_consent_summary(self) -> dict[str, Any]:
        """Get summary of all consent records for reporting.

        Returns:
            Dictionary containing consent summary information
        """
        granted_count = sum(1 for record in self._consent_records.values() if record.granted)  # noqa: E501
        expired_count = sum(
            1 for record in self._consent_records.values()
            if record.granted and record.expiry and datetime.now() > record.expiry
        )

        return {
            'total_consent_types': len(self._required_consents),
            'granted_consents': granted_count,
            'expired_consents': expired_count,
            'missing_consents': len(self.get_missing_consents()),
            'last_updated': max(
                (record.timestamp for record in self._consent_records.values()),
                default=None
            )
        }
