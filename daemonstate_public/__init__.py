"""Safe public demonstration surface for DaemonState."""

from .cli import SCHEMA_VERSION, BundleValidationError, load_bundle, validate_bundle

__all__ = [
    "SCHEMA_VERSION",
    "BundleValidationError",
    "load_bundle",
    "validate_bundle",
]

__version__ = "0.1.0"
