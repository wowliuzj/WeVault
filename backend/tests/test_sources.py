from app.services.sources import match_weread_source_candidate


def test_match_weread_source_candidate_ignores_spacing_and_case() -> None:
    candidate = {"bookId": "MP_WXS_123", "title": "MIR 睿工业"}

    assert match_weread_source_candidate([candidate], "mir睿工业") == candidate


def test_match_weread_source_candidate_rejects_ambiguous_exact_matches() -> None:
    candidates = [
        {"bookId": "MP_WXS_123", "title": "同名公众号"},
        {"bookId": "MP_WXS_456", "name": "同名公众号"},
    ]

    assert match_weread_source_candidate(candidates, "同名公众号") is None
