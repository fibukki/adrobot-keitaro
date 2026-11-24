from app.errors import AppError


class KeitaroError(AppError):
    """Base class for anything that went wrong talking to Keitaro."""

    status_code = 502


class KeitaroUnavailable(KeitaroError):
    """Network error or timeout: Keitaro did not answer."""


class KeitaroAPIError(KeitaroError):
    """Keitaro answered with a 4xx/5xx."""

    def __init__(self, method: str, path: str, status: int, detail: str) -> None:
        super().__init__(f"Keitaro rejected {method} {path} (HTTP {status}): {detail}")
        self.method = method
        self.path = path
        self.status = status
        self.detail = detail


class KeitaroNotFound(KeitaroAPIError):
    status_code = 404
