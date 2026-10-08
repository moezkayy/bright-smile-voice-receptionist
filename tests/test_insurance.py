import pytest

from receptionist.insurance import lookup


@pytest.mark.parametrize("carrier,plan,status", [
    ("Delta Dental", "", "in_network"),
    ("delta", "PPO", "in_network"),
    ("Delta Dental Premier", "", "in_network"),
    ("Delta Dental", "HMO", "not_accepted"),
    ("DeltaCare USA", "", "not_accepted"),
    ("Cigna", "", "in_network"),
    ("Met Life", "", "in_network"),
    ("BCBS", "", "in_network"),
    ("Blue Cross Blue Shield", "", "in_network"),
    ("Humana", "", "out_of_network"),
    ("Texas Medicaid", "", "not_accepted"),
    ("Acme Mutual", "", "unknown"),
    ("", "", "unknown"),
])
def test_status(carrier, plan, status):
    assert lookup(carrier, plan)["status"] == status


def test_delta_answer_warns_about_hmo_only_when_plan_unknown():
    assert "DeltaCare" in lookup("Delta Dental")["answer"]
    assert "DeltaCare" not in lookup("Delta Dental", "PPO")["answer"]


def test_unknown_offers_membership():
    assert "membership" in lookup("Acme Mutual")["answer"]
