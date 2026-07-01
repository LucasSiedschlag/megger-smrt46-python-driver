class Smrt46Error(Exception):
    """Base exception for SMRT46 operations."""


class Smrt46ConnectionError(Smrt46Error):
    """Raised when a TCP connection cannot be established or used."""


class Smrt46TimeoutError(Smrt46Error):
    """Raised when the device does not answer in time."""


class Smrt46ProtocolError(Smrt46Error):
    """Raised when a protocol-level expectation is not met."""


class Smrt46SessionBusyError(Smrt46ProtocolError):
    """Raised when the SMRT46 refuses a new TCP client because another one is active."""
