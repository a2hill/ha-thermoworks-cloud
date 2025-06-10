"""Exceptions for the Thermoworks Cloud integration."""


class MissingRequiredAttributeError(Exception):
    """Exception raised when a required attribute is missing."""

    def __init__(self, missing_attributes: list[str], object_type: type):
        """Initialize the exception."""
        self.missing_attributes = missing_attributes
        self.object_type = object_type
        message = f"Missing required attribute(s) for {object_type}: {', '.join(missing_attributes)}"
        super().__init__(message)
