class ServiceError(Exception):
    def __init__(self, status: int, message: str, code: str, param: str | None = None):
        self.status = status
        self.message = message
        self.code = code
        self.param = param
        super().__init__(message)

    def body(self) -> dict:
        kind = "invalid_request_error" if self.status in {400, 401} else "server_error"
        if self.status == 429:
            kind = "rate_limit_error"
        return {
            "error": {"message": self.message, "type": kind, "param": self.param, "code": self.code}
        }
