"""Shared, deliberately small exception taxonomy for PAVE-Rec."""


class PaveRecError(Exception):
    """Base class for declared PAVE-Rec failures."""


class ContractError(PaveRecError):
    """A public schema, identity, coverage, or state invariant was violated."""


class ResourceResolutionError(PaveRecError):
    """A required versioned resource could not be resolved safely."""


class ComponentExecutionError(PaveRecError):
    """A component failed outside its normal result contract."""


class ConfigurationError(ContractError):
    """Configuration loading, merging, or validation failed before a run started."""


class FixtureValidationError(ContractError):
    """A versioned fixture is missing or violates its declared contract."""


class RunInputError(ContractError):
    """A CLI or runner input is invalid before controller execution."""
