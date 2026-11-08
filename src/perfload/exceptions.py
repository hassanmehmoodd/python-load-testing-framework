"""Framework exceptions."""


class PerfloadError(Exception):
    """Base error for expected perfload failures."""


class ConfigError(PerfloadError):
    """The configuration file or overrides could not be loaded."""


class SafeguardError(PerfloadError):
    """A run was refused because a safety limit was not met."""


class PreflightError(PerfloadError):
    """The target did not answer a health check before the run."""


class RunError(PerfloadError):
    """Locust finished without a usable result set."""
