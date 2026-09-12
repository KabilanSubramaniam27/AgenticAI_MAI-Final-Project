from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CITIES = {
    "Lisbon": (38.7223, -9.1393, "Europe/Lisbon", "lisbon"),
    "Paris": (48.8566, 2.3522, "Europe/Paris", "paris"),
    "London": (51.5074, -0.1278, "Europe/London", "london"),
    "New York City": (40.7128, -74.0060, "America/New_York", "new_york_city"),
}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TripFields(Strict):
    destination: Literal["Lisbon", "Paris", "London", "New York City"] | None = None
    start_date: date | None = None
    outbound_date: date | None = None
    end_date: date | None = None
    budget: Decimal | None = Field(default=None, gt=0, le=1000000, allow_inf_nan=False)
    currency: Literal["USD", "EUR", "GBP"] | None = None
    origin: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    adults: int | None = Field(default=None, ge=1, le=8)
    rooms: int | None = Field(default=None, ge=1, le=4)

    @field_validator("adults", "rooms", mode="before")
    @classmethod
    def reject_boolean_counts(cls, value):
        if isinstance(value, bool):
            raise ValueError("Traveler and room counts must be integers")
        return value

    @model_validator(mode="after")
    def dates(self):
        if (
            self.outbound_date
            and self.start_date
            and not 0 <= (self.start_date - self.outbound_date).days <= 2
        ):
            raise ValueError(
                "Outbound date must be on or within two days before the first destination day"
            )
        if self.start_date and self.end_date:
            days = (self.end_date - self.start_date).days + 1
            if not 2 <= days <= 14:
                raise ValueError("This slice supports trips of 2–14 inclusive days")
        if self.adults and self.rooms and self.rooms > self.adults:
            raise ValueError("Rooms cannot exceed adults in this slice")
        return self


class ChatRequest(Strict):
    thread_id: str = Field(min_length=1, max_length=64)
    client_message_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=8000)
    trip_fields: TripFields = Field(default_factory=TripFields)
    clear_allowances: bool = False
    allowances: dict[
        Literal["food", "local_transport", "activities", "mandatory_fees"], Decimal
    ] = Field(default_factory=dict)

    @field_validator("allowances")
    @classmethod
    def allowance_amounts(cls, values):
        if any(not v.is_finite() or v < 0 or v > 1000000 for v in values.values()):
            raise ValueError("Invalid whole-trip allowance")
        return values


class Proposal(Strict):
    # Values are copied from raw text; no model-generated provenance is trusted.
    facts: dict[str, str] = Field(default_factory=dict)

    @field_validator("facts", mode="before")
    @classmethod
    def numeric_proposals(cls, value):
        # JSON numbers are valid representations of numeric proposals, not proof of intent.
        # Bool/null/objects and numeric city/currency values remain schema errors.
        if not isinstance(value, dict):
            return value
        return {
            key: str(item)
            if key in {"budget", "adults", "rooms"} and type(item) in (int, float)
            else item
            for key, item in value.items()
        }


class Activity(Strict):
    date: date
    claim: str = Field(min_length=1, max_length=600)
    evidence_id: str
    quote: str = Field(min_length=1, max_length=1400)
    exposure: Literal["indoor", "outdoor", "unknown"] = "unknown"


class Itinerary(Strict):
    activities: list[Activity] = Field(default_factory=list, max_length=28)


class Selection(Strict):
    evidence_ids: list[str] = Field(default_factory=list, max_length=5)


class Support(Strict):
    supported: list[int] = Field(default_factory=list, max_length=28)


def trip_days(trip: dict) -> list[str]:
    start = date.fromisoformat(trip["start_date"])
    end = date.fromisoformat(trip["end_date"])
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


class ClaimDecision(Strict):
    claim_id: str
    claim_hash: str
    source_hash: str
    status: Literal["supported", "contradicted", "insufficient_evidence"]
    quote: str = Field(max_length=1400)
    reason: str = Field(min_length=1, max_length=600)


class GroundingResult(Strict):
    results: list[ClaimDecision] = Field(max_length=28)


class PlanningDone(Strict):
    done: Literal[True]
