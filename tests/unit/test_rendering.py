"""Row WY8: :func:`weightroom.web.rendering.canonical_name`, the one place a model table recovers
a provider name out of a canonical ID rather than showing the whole identity string.
"""

from __future__ import annotations

from weightroom.web.rendering import canonical_name


def test_a_name_with_no_special_characters_comes_back_unchanged() -> None:
    assert canonical_name("ollama/smollm2:135m@sha256:9077fe9d2ae1") == "smollm2:135m"


def test_a_name_that_itself_contains_a_slash_survives_the_parse() -> None:
    # provider_model_name may legitimately contain "/" (baseaicore.ModelIdentity's own docstring,
    # e.g. "hf.co/user/repo:q4"); only the first "/" is the provider_kind separator.
    canonical = (
        "ollama/fredrezones55/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive:IQ2_M"
        "@sha256:423c4a0ed6fb"
    )
    assert canonical_name(canonical) == (
        "fredrezones55/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive:IQ2_M"
    )


def test_an_unknown_digest_is_still_stripped() -> None:
    assert canonical_name("ollama/gemma3:latest@unknown") == "gemma3:latest"


def test_a_value_with_no_slash_does_not_parse_and_comes_back_unchanged() -> None:
    """ADR-0016: a canonical ID that does not fit the grammar renders truncated, never raises."""
    assert canonical_name("not-a-canonical-id") == "not-a-canonical-id"


def test_none_comes_back_as_the_empty_string() -> None:
    assert canonical_name(None) == ""
