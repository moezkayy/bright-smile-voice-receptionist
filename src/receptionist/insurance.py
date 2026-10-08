"""Deterministic insurance lookup.

Network status is a yes/no fact with consequences for the patient, so it comes
from a table, not from the LLM's memory or a fuzzy RAG hit. The one trap that
matters: "Delta Dental" PPO is in network but the DeltaCare HMO is not, so the
HMO aliases are checked first.
"""

from __future__ import annotations

import re

from . import clinic


def _tokens(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split())


def lookup(carrier: str, plan_type: str = "") -> dict:
    query = _tokens(f"{carrier} {plan_type}")
    if not query:
        return {"status": "unknown", "answer": "Which insurance company is your plan with?"}

    is_hmo = bool(re.search(r"\b(hmo|dhmo|deltacare)\b", query))
    # Most specific alias first, HMO plans before PPO plans.
    candidates = sorted(
        ((plan, alias) for plan in clinic.INSURANCE for alias in plan.aliases),
        key=lambda pa: (not ("hmo" in pa[1] or "deltacare" in pa[1]), -len(pa[1])),
    )
    for plan, alias in candidates:
        if re.search(rf"\b{re.escape(alias)}\b", query):
            if is_hmo and plan.status == "in_network" and plan.carrier.startswith("Delta"):
                continue  # "Delta HMO" must not match the PPO entry
            return _answer(plan, asked_plan_type=bool(plan_type) or is_hmo)

    return {
        "status": "unknown",
        "carrier": carrier,
        "answer": (
            f"I don't see {carrier} on our list, but the front desk can check your exact plan. "
            "You're also welcome to come in as self-pay. " + clinic.MEMBERSHIP_PLAN
        ),
    }


def _answer(plan: clinic.InsurancePlan, asked_plan_type: bool) -> dict:
    if plan.status == "in_network":
        answer = f"Yes, we're in network with {plan.carrier}."
        if plan.note:
            answer = f"Yes. {plan.note}"
        if plan.carrier.startswith("Delta") and not asked_plan_type:
            answer += " If your card says DeltaCare USA, that's their HMO, and we're not in that network."
        answer += " Bring your insurance card and photo ID to your visit."
    elif plan.status == "out_of_network":
        answer = f"We're out of network with {plan.carrier}. {plan.note}"
    else:
        answer = f"{plan.note} {clinic.MEMBERSHIP_PLAN}"
    return {"status": plan.status, "carrier": plan.carrier, "answer": answer.strip()}
