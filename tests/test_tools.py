"""
Tests for the three FitFindr tools.

The search_listings tests run offline (no LLM). The suggest_outfit and
create_fit_card tests call Groq, so they are skipped automatically when
GROQ_API_KEY is not set — the create_fit_card empty-input guard is tested
offline since it returns before any LLM call.
"""

import os

import pytest

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

needs_groq = pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set — skipping live LLM test",
)


# ── search_listings ─────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []  # empty list, no exception


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter_case_insensitive():
    # "m" should match listings whose size contains M, e.g. "M", "S/M", "M/L".
    results = search_listings("vintage", size="m", max_price=None)
    assert len(results) > 0
    assert all("m" in item["size"].lower() for item in results)


def test_search_sorted_by_relevance():
    # More keyword overlap should rank first; result must be non-increasing score.
    results = search_listings("vintage band graphic tee", size=None, max_price=None)
    assert len(results) > 0

    def score(item):
        hay = " ".join(
            [item["title"], item["description"], " ".join(item["style_tags"])]
        ).lower()
        return sum(1 for kw in "vintage band graphic tee".split() if kw in hay)

    scores = [score(item) for item in results]
    assert scores == sorted(scores, reverse=True)


# ── suggest_outfit ──────────────────────────────────────────────────────────

@needs_groq
def test_suggest_outfit_with_wardrobe():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    out = suggest_outfit(item, get_example_wardrobe())
    assert isinstance(out, str)
    assert out.strip() != ""


@needs_groq
def test_suggest_outfit_empty_wardrobe_does_not_crash():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    out = suggest_outfit(item, get_empty_wardrobe())
    assert isinstance(out, str)
    assert out.strip() != ""  # general advice, never empty


# ── create_fit_card ─────────────────────────────────────────────────────────

def test_create_fit_card_empty_outfit_returns_error_string():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    # Empty / whitespace outfit must return a string, not raise.
    assert isinstance(create_fit_card("", item), str)
    assert create_fit_card("", item).strip() != ""
    assert isinstance(create_fit_card("   ", item), str)


@needs_groq
def test_create_fit_card_varies_on_repeat():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    outfit = "Pair it with baggy dark-wash jeans and chunky white sneakers."
    cards = {create_fit_card(outfit, item) for _ in range(3)}
    # Higher temperature should produce at least 2 distinct captions out of 3.
    assert len(cards) >= 2
