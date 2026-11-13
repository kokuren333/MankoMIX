"""Error types and process exit codes shared by every face (SPEC 10.1)."""

from __future__ import annotations

EXIT_OK = 0
EXIT_VERIFY_FAILED = 1   # ran fine, but a verification/gate failed
EXIT_INPUT_ERROR = 2     # bad arguments, bad project, bad input files
EXIT_ENV_ERROR = 3       # missing ffmpeg, missing dependency, I/O environment


class MankoError(Exception):
    exit_code = EXIT_INPUT_ERROR
    code = "error"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"error": self.code, "message": self.message, "details": self.details}


class InputError(MankoError):
    exit_code = EXIT_INPUT_ERROR
    code = "input_error"


class ValidationError(MankoError):
    exit_code = EXIT_INPUT_ERROR
    code = "validation_error"


class EnvironmentProblem(MankoError):
    exit_code = EXIT_ENV_ERROR
    code = "environment_error"


class VerifyFailed(MankoError):
    exit_code = EXIT_VERIFY_FAILED
    code = "verify_failed"
