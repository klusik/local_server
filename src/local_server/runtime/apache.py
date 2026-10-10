"""Reserved Apache adapter boundary for platform-specific HTTPD builds."""


class ApacheAdapter:
    """Pending implementation of Apache config generation and foreground startup."""

    def start(self) -> None:
        """Do not claim platform-specific HTTPD support before it is implemented."""
        raise NotImplementedError(
            "Apache integration will be implemented with verified Windows/macOS builds"
        )
