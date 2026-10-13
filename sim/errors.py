class NoKey(RuntimeError):
    """A real backend was asked to run without its key. Never stubbed around."""


class NotWired(RuntimeError):
    """A real backend has a key but its call is not wired yet. Never faked."""
