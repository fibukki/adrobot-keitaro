class AppError(Exception):
    """An error whose message is safe and meaningful to show to the user."""

    status_code: int = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ValidationFailed(AppError):
    status_code = 422


class NotFound(AppError):
    status_code = 404


class Conflict(AppError):
    status_code = 409
