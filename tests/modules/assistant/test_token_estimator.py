from app.modules.assistant.application.services.token_estimator import TokenEstimator


def test_token_estimator_is_deterministic_for_unicode_text():
    estimator = TokenEstimator()

    assert estimator.estimate("") == 0
    assert estimator.estimate("áéí") == 1
    assert estimator.estimate("áéíó") == 2


def test_threshold_uses_ceiling_of_ninety_percent_for_configured_budget():
    estimator = TokenEstimator()

    assert estimator.compaction_threshold(7000) == 6300
    assert estimator.compaction_threshold(1) == 1
    assert estimator.compaction_threshold(7001) == 6301


def test_threshold_and_budget_reject_invalid_values():
    estimator = TokenEstimator()

    try:
        estimator.compaction_threshold(0)
    except ValueError:
        pass
    else:
        raise AssertionError("expected positive memory budget")
