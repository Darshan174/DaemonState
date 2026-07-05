from app.evals.extraction import DEFAULT_EXTRACTION_EVAL_CASES, run_extraction_eval


def test_default_extraction_eval_is_not_toy_sized():
    assert len(DEFAULT_EXTRACTION_EVAL_CASES) >= 100


def test_default_extraction_eval_passes_current_contract():
    report = run_extraction_eval()

    assert report.case_count >= 100
    assert report.failed_count == 0
    assert report.pass_rate == 1.0
