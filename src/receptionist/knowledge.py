"""Render the agent's knowledge base from clinic.py, so the two can't disagree."""

from . import clinic


def render() -> str:
    services = "\n".join(
        f"- {s.label}: {s.minutes} minutes with {clinic.PROVIDERS[s.provider].name}. "
        f"Self-pay price {s.self_pay}. {s.notes}".rstrip()
        for s in clinic.SERVICES.values()
    )
    in_net = ", ".join(p.carrier for p in clinic.INSURANCE if p.status == "in_network")
    other = "\n".join(f"- {p.carrier}: {p.note}" for p in clinic.INSURANCE if p.status != "in_network")
    return f"""# {clinic.NAME}: front desk facts

## Location and contact
- Address: {clinic.ADDRESS}
- Phone: {clinic.PHONE}
- Parking: {clinic.PARKING}
- Wheelchair accessible, with an elevator to Suite 210.

## Hours
{clinic.HOURS_SPOKEN}
Closed Thanksgiving Day and the day after, Christmas Eve, Christmas Day and New Year's Day.

## Team
- Dr. Maya Patel, DDS: general and cosmetic dentistry, 12 years in practice.
- Lauren Kim, RDH: dental hygienist. Does cleanings, X-rays and kids' visits.

## Services
{services}

## Insurance
In network: {in_net}.
{other}
Price questions with insurance: the front desk checks your exact benefits before the visit.
{clinic.MEMBERSHIP_PLAN}

## Payment
{clinic.PAYMENT}

## Policies
- New patients: arrive 15 minutes early. Bring photo ID and your insurance card. Forms are texted to you after booking.
- Existing patients: arrive 5 minutes early.
- Cancellations: please give 24 hours notice. Missed appointments without notice have a $50 fee.
- Children under 18 need a parent or guardian at the first visit.
- Nitrous oxide (laughing gas) is available for anxious patients at $45 per visit.
- We don't offer IV sedation, orthodontics, or wisdom tooth extractions; we refer to trusted specialists nearby.
"""
