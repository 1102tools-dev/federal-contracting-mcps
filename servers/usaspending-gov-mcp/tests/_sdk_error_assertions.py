"""Check unexpected failure internals without treating them as client guidance."""
from mcp.server.mcpserver import exceptions as sdk_errors


def unexpected_source_error_text(error, tool):
    """Require the SDK wrapper and retain the original provider-fault assertions.

    SDK 2.3 deliberately hides unexpected exceptions from the client. These
    injected source faults test causal status/detail/cleaning semantics, not
    promises of a visible repair hint. Intentional user-input tests still assert
    their visible message directly and never use this helper.
    """
    assert isinstance(error, sdk_errors.ToolError)
    cause = error.__cause__
    assert type(cause) is RuntimeError
    unexpected = getattr(sdk_errors, 'UnexpectedToolError', None)
    if unexpected is not None:
        assert isinstance(error, unexpected)
        assert str(error) == f'Error executing tool {tool}'
    else:
        # Retain the SDK 2.0 contract, including its original causal message.
        assert str(cause) in str(error)
    return str(cause)
