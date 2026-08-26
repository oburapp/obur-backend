"""Custom exceptions for the reporting domain."""


class ReportError(Exception):
    """Base class for report-domain errors."""


class ContentReportNotFoundError(ReportError):
    """Raised when a content report id doesn't match any row."""


class VenueReportNotFoundError(ReportError):
    """Raised when a venue report id doesn't match any row."""
