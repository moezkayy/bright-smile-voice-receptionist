"""Bright Smile Dental: the single source of truth for clinic facts.

The agent prompt, the knowledge base file and the scheduling rules are all
generated from or checked against this module, so a fact can't drift between
what the receptionist says and what the scheduler enforces.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

NAME = "Bright Smile Dental"
TIMEZONE = ZoneInfo("America/Chicago")
ADDRESS = "2400 South Lamar Boulevard, Suite 210, Austin, Texas 78704"
PHONE = "(512) 555-0142"
PARKING = "Free parking in the lot behind the building"

SLOT_GRID_MINUTES = 15
MIN_LEAD_MINUTES = 120  # no bookings less than 2 hours out
MAX_DAYS_AHEAD = 45


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    role: str


PROVIDERS = {
    "hygiene": Provider("hygiene", "Lauren Kim, RDH", "Dental hygienist"),
    "doctor": Provider("doctor", "Dr. Maya Patel, DDS", "General dentist"),
}


@dataclass(frozen=True)
class Service:
    id: str
    label: str
    minutes: int
    provider: str
    self_pay: str
    notes: str = ""
    category: str = "preventive"  # preventive | restorative | emergency | cosmetic
    cdt: tuple[str, ...] = ()  # ADA CDT procedure codes typically scheduled
    fee: int = 0  # office fee, USD, used for scheduled production


SERVICES = {
    s.id: s
    for s in [
        Service("cleaning", "Cleaning and checkup", 60, "hygiene", "$145",
                "Adult cleaning, exam with Dr. Patel, and bitewing X-rays if due.",
                "preventive", ("D0120", "D1110", "D0274"), 145),
        Service("new_patient_exam", "New patient exam and cleaning", 90, "hygiene", "$210",
                "Full exam, full set of X-rays and a cleaning. For anyone not seen here before.",
                "preventive", ("D0150", "D0210", "D1110"), 210),
        Service("kids_cleaning", "Children's cleaning", 45, "hygiene", "$95",
                "Ages 3 to 12. A parent stays in the room.",
                "preventive", ("D0120", "D1120", "D1206"), 95),
        Service("filling", "Filling", 60, "doctor", "from $180",
                "Tooth-colored fillings only.",
                "restorative", ("D2391",), 180),
        Service("emergency", "Emergency visit", 30, "doctor", "$95",
                "Toothache, broken tooth, lost filling or crown. Same-day when possible.",
                "emergency", ("D0140", "D0220"), 95),
        Service("whitening_consult", "Whitening consultation", 30, "doctor", "free",
                "In-office and take-home whitening options.",
                "cosmetic", (), 0),
        Service("crown_consult", "Crown or implant consultation", 30, "doctor", "free", "",
                "restorative", ("D0140",), 0),
    ]
}

# Weekday (Mon=0) -> list of (open, close) blocks. Lunch is the gap.
HOURS: dict[int, list[tuple[time, time]]] = {
    0: [(time(8), time(12)), (time(13), time(17))],
    1: [(time(8), time(12)), (time(13), time(17))],
    2: [(time(8), time(12)), (time(13), time(17))],
    3: [(time(8), time(12)), (time(13), time(17))],
    4: [(time(8), time(14))],
}

HOURS_SPOKEN = (
    "Monday to Thursday, 8 AM to 5 PM, closed for lunch from noon to 1. "
    "Friday, 8 AM to 2 PM. Closed Saturday and Sunday."
)

# Holidays the scheduler refuses (ISO dates).
CLOSED_DATES = {"2026-11-26", "2026-11-27", "2026-12-24", "2026-12-25", "2027-01-01"}


@dataclass(frozen=True)
class InsurancePlan:
    carrier: str
    status: str  # in_network | out_of_network | not_accepted
    aliases: tuple[str, ...]
    note: str = ""


INSURANCE = [
    InsurancePlan("Delta Dental PPO", "in_network",
                  ("delta", "delta dental", "delta ppo", "delta dental ppo", "delta dental premier", "premier"),
                  "In network for Delta Dental PPO and Delta Dental Premier."),
    InsurancePlan("DeltaCare USA (Delta Dental HMO)", "not_accepted",
                  ("deltacare", "delta hmo", "delta dental hmo", "deltacare usa", "delta dhmo"),
                  "We are not in the DeltaCare USA HMO network."),
    InsurancePlan("Cigna Dental PPO", "in_network", ("cigna", "cigna ppo", "cigna dental")),
    InsurancePlan("MetLife PDP", "in_network", ("metlife", "met life", "metlife pdp", "metlife dental")),
    InsurancePlan("Aetna Dental PPO", "in_network", ("aetna", "aetna ppo", "aetna dental")),
    InsurancePlan("Guardian Dental", "in_network", ("guardian", "guardian dental")),
    InsurancePlan("United Concordia", "in_network", ("united concordia", "concordia")),
    InsurancePlan("Blue Cross Blue Shield of Texas Dental", "in_network",
                  ("blue cross", "bcbs", "blue cross blue shield", "bcbstx", "blue shield")),
    InsurancePlan("Humana Dental", "out_of_network", ("humana", "humana dental"),
                  "Out of network: we file the claim for you and Humana reimburses at its out-of-network rate."),
    InsurancePlan("Texas Medicaid and CHIP", "not_accepted",
                  ("medicaid", "chip", "texas medicaid", "dentaquest", "mcna"),
                  "We are not a Medicaid or CHIP provider."),
]

MEMBERSHIP_PLAN = (
    "No insurance? The Bright Smile membership is $29 a month and covers two cleanings, "
    "exams and X-rays each year, plus 20 percent off other treatment."
)

PAYMENT = "We take cash, all major cards, HSA and FSA cards, and CareCredit."
