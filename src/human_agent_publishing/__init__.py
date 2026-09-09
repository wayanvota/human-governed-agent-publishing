"""Human-governed multi-agent publishing release gates."""

from .gate import GateError, verify_packet

__all__ = ["GateError", "verify_packet"]
__version__ = "0.1.0"

