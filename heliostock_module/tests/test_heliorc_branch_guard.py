from heliostock.heliorc.engine import decentralized_branch_guard


def test_decentralized_branch_need_must_be_strictly_lower_than_total() -> None:
    total = [100.0] * 12

    equal_branch = [100.0] * 12
    messages = decentralized_branch_guard(total, equal_branch)
    assert any("strictement" in message for message in messages)

    lower_branch = [80.0] * 12
    assert decentralized_branch_guard(total, lower_branch) == []


def test_decentralized_branch_need_cannot_exceed_total_monthly() -> None:
    total = [100.0] * 12
    branch = [80.0] * 12
    branch[0] = 110.0

    messages = decentralized_branch_guard(total, branch)

    assert any("mois par mois" in message for message in messages)
    assert any("Janvier" in message for message in messages)
