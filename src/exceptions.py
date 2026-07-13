"""
Custom exception hierarchy for mcp-gsuite.

All exceptions are surfaced as structured MCP error responses.
Internal details (file paths, emails, credentials) are never
included in exception messages that reach the client.
"""


class MCPGSuiteError(Exception):
    """Base exception for mcp-gsuite. All tool errors derive from this."""


class AuthError(MCPGSuiteError):
    """Credential loading or token refresh failed."""


class AccessDeniedError(MCPGSuiteError):
    """
    The authenticated identity is not permitted to use this server.

    Intentionally vague — message must never reveal the authorised identity
    or any details that help an attacker enumerate valid accounts.
    """


class QuotaError(MCPGSuiteError):
    """A Google API quota limit was exceeded."""


class PermissionError(MCPGSuiteError):
    """The authenticated account lacks a required OAuth2 scope or IAM permission."""


class InvalidInputError(MCPGSuiteError):
    """Tool input failed validation (e.g. malformed email address, oversized body)."""


class DocumentNotFoundError(MCPGSuiteError):
    """The supplied Google Doc ID could not be resolved."""
