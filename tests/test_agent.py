"""
Tests for the planning loop, including Feature 7 (retry with fallback).

These tests stub out the two LLM tools so they run offline — they exercise
the loop's branching and state flow, not the live models.
"""

import os

import pytest

import agent
from agent import run_agent, _search_with_fallback, _new_session
from utils.data_loader import get_example_wardrobe


@pytest.fixture(autouse=True)
def stub_llm(monkeypatch):
    """Replace the LLM-backed tools with deterministic stubs."""
    monkeypatch.setattr(agent, "suggest_outfit", lambda item, wardrobe: "stub outfit")
    monkeypatch.setattr(agent, "create_fit_card", lambda outfit, item: "stub fit card")


def test_happy_path_no_adjustments():
    session = run_agent("vintage graphic tee under $30", get_example_wardrobe())
    assert session["error"] is None
    assert session["selected_item"] is not None
    assert session["adjustments"] == []  # exact match, nothing loosened
    assert session["fit_card"] == "stub fit card"


def test_retry_drops_size_filter():
    # A real graphic tee exists, but not in size XXS — loop should drop size.
    session = run_agent("vintage graphic tee size XXS", get_example_wardrobe())
    assert session["error"] is None
    assert session["selected_item"] is not None
    assert any("size XXS" in note for note in session["adjustments"])


def test_retry_drops_price_filter():
    # Real boots exist but none under $1 — loop should drop the budget.
    session = run_agent("leather bomber jacket under $1", get_example_wardrobe())
    assert session["error"] is None
    assert session["selected_item"] is not None
    assert any("budget" in note for note in session["adjustments"])


def test_impossible_query_sets_error_and_no_downstream():
    session = run_agent("designer ballgown size XXS under 5 dollars", get_example_wardrobe())
    assert session["error"] is not None
    assert session["search_results"] == []
    assert session["selected_item"] is None
    assert session["outfit_suggestion"] is None
    assert session["fit_card"] is None


def test_fallback_records_note_only_when_loosening_helps():
    session = _new_session("q", get_example_wardrobe())
    parsed = {"description": "vintage graphic tee", "size": "XXS", "max_price": None}
    results = _search_with_fallback(parsed, session)
    assert results  # found after dropping size
    assert session["adjustments"] == ["ignored the size XXS filter"]
