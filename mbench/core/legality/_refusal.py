from dataclasses import dataclass
from enum import Enum


class Reason(Enum):
    """Why a command was refused, a stable code the refusals are counted by."""

    REFERENT_MISSING = "referent_missing"
    REFERENT_WRONG_TYPE = "referent_wrong_type"
    GATE_FAILED = "gate_failed"
    NOT_LIVE = "not_live"
    ENDPOINT_MISSING = "endpoint_missing"
    ENDPOINT_WRONG_TYPE = "endpoint_wrong_type"
    ENDPOINT_GATE_FAILED = "endpoint_gate_failed"
    ENDPOINT_FILTER_FAILED = "endpoint_filter_failed"
    PAIR_ALREADY_WRITTEN = "pair_already_written"
    INVALID_VALUE = "invalid_value"
    UNTRUE_DISCLOSURE = "untrue_disclosure"
    UNEQUAL_AUTHORITY = "unequal_authority"
    SPEAKER_TWICE = "speaker_twice"
    CONTESTED_VALUES_EQUAL = "contested_values_equal"
    CONTESTED_VALUE_IS_CURRENT = "contested_value_is_current"
    NO_WRITER = "no_writer"
    WRITER_GATE_FAILED = "writer_gate_failed"
    NO_CONTESTABLE_FRAMING = "no_contestable_framing"
    INITIATOR_NOT_SHARED = "initiator_not_shared"
    PAIR_SEALED = "pair_sealed"
    ENTITY_SEALED = "entity_sealed"
    ANCHOR_SAME_ZONE = "anchor_same_zone"
    UNCHANGED_VALUE = "unchanged_value"
    IDENTIFIER_TAKEN = "identifier_taken"


@dataclass(frozen=True)
class Refusal:
    """Why a command was refused: the reason its first failing clause gives."""

    reason: Reason
