"""Reserved PHP FastCGI adapter boundary for simultaneous PHP versions."""


class PhpFastCgiAdapter:
    """Pending per-project php-cgi (Windows) / php-fpm (macOS) orchestration."""

    def start(self) -> None:
        """Require a real verified binary and configured project-specific port."""
        raise NotImplementedError(
            "PHP FastCGI lifecycle and hot switching are not implemented yet"
        )
