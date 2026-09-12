"""Deterministic boundaries. Text heuristics are not a semantic safety guarantee."""

import hashlib
import json
import re
import time
from dataclasses import dataclass

from .config import Settings
from .models import TripFields

SECRET = re.compile(
    r"(?i)(?:\b(?:sk-ant-|sk-|ck-|lsv2_pt_|ls__)[a-z0-9_-]{12,}|bearer\s+\S+|"
    r"(?:api[_ -]?key|password|secret)\s*[=:]\s*[^\s,\"}]+)"
)
FORBIDDEN = re.compile(
    r"\b(?:ignore (?:all |previous |system )*instructions|"
    r"reveal (?:the )?system prompt)\b",
    re.I,
)


class GuardrailError(ValueError):
    pass


def redact(value):
    if isinstance(value, str):
        return SECRET.sub("[REDACTED]", value)
    if isinstance(value, dict):
        return {
            k: (
                "[REDACTED]"
                if k.lower() in {"authorization", "api_key", "password", "token", "capability"}
                else redact(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def checked_text(value: str, limit=8000) -> str:
    if len(value) > limit or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise GuardrailError("Invalid or oversized input")
    if FORBIDDEN.search(value):
        raise GuardrailError("Instruction override blocked; submit the travel request alone")
    return redact(value)


def normalize(raw: str, form: dict, facts: dict, prior: dict | None = None):
    values = dict(prior or {})
    values.update({k: v for k, v in form.items() if v is not None})
    conflicts = []
    for key, value in facts.items():
        if key not in TripFields.model_fields or not isinstance(value, str):
            continue
        if key in form and form[key] is not None:
            try:
                accepted = getattr(TripFields.model_validate({key: form[key]}), key)
                proposed = getattr(TripFields.model_validate({key: value}), key)
                if accepted != proposed:
                    conflicts.append(key)
            except ValueError:
                conflicts.append(key)
            # The explicit form is authoritative; repeated fields need no prose provenance.
            continue
        # New prose facts still require exact containment and affirmative assignment syntax.
        if value not in raw:
            conflicts.append(key)
            continue
        else:
            # Exact containment alone does not establish affirmative intent. Only a whole
            # field-assignment message is deterministic enough for this narrow prose path.
            lines = [line.strip() for line in raw.splitlines() if line.strip()]
            assignments = []
            for line in lines:
                match = re.fullmatch(r"([a-z_]+)\s*[:=]\s*([^?]+)", line)
                if not match or match[1] not in TripFields.model_fields:
                    assignments = []
                    break
                assignments.append((match[1], match[2].strip()))
            matches = [v for k, v in assignments if k == key]
            if matches != [value]:
                conflicts.append(key + " (use the structured form or explicit field: value lines)")
            else:
                values[key] = value
    try:
        trip = TripFields.model_validate(values).model_dump(mode="json", exclude_none=True)
    except ValueError:
        return {}, ["Provide unambiguous dates, destination, currency and traveler details."]
    missing = [key for key in TripFields.model_fields if key != "outbound_date" and key not in trip]
    if trip.get("origin") not in {None, "JFK", "EWR", "LHR", "LGW", "CDG", "ORY", "LIS"}:
        conflicts.append("origin (supported airports: JFK, EWR, LHR, LGW, CDG, ORY, LIS)")
    if conflicts:
        return {}, ["Confirm or correct: " + ", ".join(sorted(set(conflicts)))]
    return trip, ["Please provide: " + ", ".join(missing)] if missing else []


@dataclass
class Budget:
    settings: Settings
    started: float = 0
    calls: int = 0
    reads: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reserved_cost: float = 0

    def __post_init__(self):
        self.started = time.monotonic()

    def check(self):
        if time.monotonic() - self.started >= self.settings.deadline_seconds:
            raise GuardrailError("Request deadline exhausted")

    def model(self, text: str, max_output=4000):
        self.check()
        # UTF-8 bytes are a conservative token upper bound, not measured token usage.
        count = len(text.encode())
        if count > 16000 or self.calls >= self.settings.max_model_calls:
            raise GuardrailError("Model/context budget exhausted")
        cost = (
            count * self.settings.input_usd_per_million
            + max_output * self.settings.output_usd_per_million
        ) / 1000000
        if (
            self.input_tokens + count > 80000
            or self.output_tokens + max_output > 20000
            or self.reserved_cost + cost > self.settings.request_cost_cap
        ):
            raise GuardrailError("Token/cost reservation exhausted")
        self.calls += 1
        self.input_tokens += count
        self.output_tokens += max_output
        self.reserved_cost += cost

    def can_reserve(self, calls, inputs, outputs, seconds=30):
        return (
            self.calls + calls <= self.settings.max_model_calls
            and self.input_tokens + inputs <= 80000
            and self.output_tokens + outputs <= 20000
            and self.reserved_cost
            + (
                inputs * self.settings.input_usd_per_million
                + outputs * self.settings.output_usd_per_million
            )
            / 1000000
            <= self.settings.request_cost_cap
            and time.monotonic() - self.started + seconds < self.settings.deadline_seconds
        )

    def read(self):
        self.check()
        if self.reads >= self.settings.max_reads:
            raise GuardrailError("Tool budget exhausted")
        self.reads += 1


def validate_activities(activities, trip, evidence):
    from .models import trip_days

    accepted = []
    for a in activities:
        source = evidence.get(a.evidence_id)
        if (
            not source
            or source.get("kind") != "guide"
            or source.get("destination") != trip["destination"]
            or a.date.isoformat() not in trip_days(trip)
            or a.quote not in source["text"]
        ):
            continue
        if SECRET.search(a.claim) or FORBIDDEN.search(a.claim):
            continue
        accepted.append(a)
    return accepted
