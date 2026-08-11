"""Explicit, structured failure taxonomy for Phase D Differential Explorer.

This taxonomy replaces fragile substring-matching with 10 explicit, programmatic
disposition categories.
"""

from enum import Enum, auto


class Disposition(str, Enum):
    PARSE_FAILED = "parse_failed"
    SAFETY_REJECTED = "safety_rejected"
    COLLECTION_IMPORT_FAILED = "collection_import_failed"
    SETUP_RUNTIME_ERROR = "setup_runtime_error"
    BASE_ASSERTION_FAILED = "base_assertion_failed"
    HEAD_PASSED = "head_passed"
    HEAD_FAILED_WRONG_REASON = "head_failed_wrong_reason"
    STABLE_TECHNICAL_WEAK_CATCH = "stable_technical_weak_catch"
    ASSESSOR_REJECTED = "assessor_rejected"
    ACCEPTED_STRONG_CATCH = "accepted_strong_catch"

    def is_disqualified(self) -> bool:
        return self in {
            Disposition.PARSE_FAILED,
            Disposition.SAFETY_REJECTED,
            Disposition.COLLECTION_IMPORT_FAILED,
            Disposition.SETUP_RUNTIME_ERROR,
            Disposition.BASE_ASSERTION_FAILED,
            Disposition.HEAD_PASSED,
            Disposition.HEAD_FAILED_WRONG_REASON,
            Disposition.ASSESSOR_REJECTED,
        }

    def is_catch(self) -> bool:
        return self in {
            Disposition.STABLE_TECHNICAL_WEAK_CATCH,
            Disposition.ACCEPTED_STRONG_CATCH,
        }
