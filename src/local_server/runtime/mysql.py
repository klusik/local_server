"""Reserved MySQL adapter boundary for private data directories."""


class MysqlAdapter:
    """Pending secure initialisation, secrets handling and process supervision."""

    def start(self) -> None:
        """Never initialize an unsecured database or global machine service."""
        raise NotImplementedError(
            "Local MySQL datadir initialization and lifecycle are not implemented yet"
        )
