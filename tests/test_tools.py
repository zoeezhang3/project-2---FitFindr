"""
Tests for the three FitFindr tools.

The search_listings tests run offline (no LLM). The suggest_outfit and
create_fit_card tests call Groq, so they are skipped automatically when
GROQ_API_KEY is not set — the create_fit_card empty-input guard is tested
offline since it returns before any LLM call.
"""

import os

import pytest

from tools import (
    search_listings,
    suggest_outfit,
    create_fit_card,
    estimate_price_fairness,
    get_trending_styles,
    load_style_profile,
    save_style_profile,
    update_style_profile_from_query,
)
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


# ── Tool 4: estimate_price_fairness ─────────────────────────────────────────

def test_price_fairness_returns_verdict():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = estimate_price_fairness(item)
    assert result["verdict"] in {"great deal", "fair", "overpriced", "no comparables"}
    assert result["item_price"] == item["price"]
    assert isinstance(result["summary"], str) and result["summary"]


def test_price_fairness_cheap_item_is_deal():
    # A cheap top relative to its comparables should read as a good deal.
    cheap = search_listings("henley", size=None, max_price=None)[0]  # $16 henley
    result = estimate_price_fairness(cheap)
    assert result["comp_count"] > 0
    assert result["verdict"] in {"great deal", "fair"}


def test_price_fairness_no_comparables_does_not_crash():
    # Fabricate an item in a category with no other members.
    lonely = {
        "id": "fake_x",
        "title": "Mystery Object",
        "category": "spaceship",
        "style_tags": ["alien"],
        "price": 999.0,
    }
    result = estimate_price_fairness(lonely)
    assert result["verdict"] == "no comparables"
    assert result["comp_median"] is None


# ── Tool 6: get_trending_styles ─────────────────────────────────────────────

def test_trending_styles_returns_ranked_tags():
    result = get_trending_styles(size=None, top_n=5)
    assert result["sample_size"] > 0
    assert len(result["trending"]) <= 5
    counts = [count for _, count in result["trending"]]
    assert counts == sorted(counts, reverse=True)  # highest first


def test_trending_styles_unknown_size_is_empty():
    result = get_trending_styles(size="ZZZ", top_n=5)
    assert result["sample_size"] == 0
    assert result["trending"] == []
    assert "Not enough" in result["summary"]


# ── Tool 5: style profile memory ────────────────────────────────────────────

def test_style_profile_missing_file_returns_default(tmp_path):
    path = str(tmp_path / "nope.json")
    profile = load_style_profile(path)
    assert profile == {
        "preferred_styles": [],
        "sizes": [],
        "max_price": None,
        "wardrobe": {"items": []},
    }


def test_style_profile_save_and_load_roundtrip(tmp_path):
    path = str(tmp_path / "profile.json")
    save_style_profile({"sizes": ["M"], "max_price": 30.0}, path)
    loaded = load_style_profile(path)
    assert loaded["sizes"] == ["M"]
    assert loaded["max_price"] == 30.0
    # Missing keys are backfilled from the default.
    assert loaded["preferred_styles"] == []


def test_style_profile_update_persists_across_loads(tmp_path):
    path = str(tmp_path / "profile.json")
    parsed = {"description": "vintage graphic tee", "size": "M", "max_price": 30.0}
    update_style_profile_from_query(parsed, path)
    # A fresh load (simulating a new session) sees the remembered preferences.
    reloaded = load_style_profile(path)
    assert "M" in reloaded["sizes"]
    assert reloaded["max_price"] == 30.0
    assert "vintage" in reloaded["preferred_styles"]


def test_style_profile_corrupt_file_returns_default(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json")
    profile = load_style_profile(str(path))
    assert profile["sizes"] == []  # falls back to default, no crash
