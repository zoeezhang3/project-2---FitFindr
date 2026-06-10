"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── query parsing ─────────────────────────────────────────────────────────────

# Common clothing size tokens we recognize as standalone words.
_SIZE_TOKENS = ["xxs", "xs", "s", "m", "l", "xl", "xxl"]


def _parse_query(query: str) -> dict:
    """
    Extract a description, optional size, and optional max_price from free text.

    Returns a dict: {"description": str, "size": str | None, "max_price": float | None}.
    The description is the query with the price/size phrases stripped out.
    """
    text = query.strip()
    remaining = text

    # max_price: "$30", "under 30", "under $30.50".
    max_price = None
    price_match = re.search(r"(?:under|below|less than|\$)\s*\$?\s*(\d+(?:\.\d+)?)", text, re.I)
    if price_match:
        max_price = float(price_match.group(1))
    # Strip the whole price phrase from the description text.
    remaining = re.sub(
        r"(?:under|below|less than)\s*\$?\s*\d+(?:\.\d+)?", " ", remaining, flags=re.I
    )
    remaining = re.sub(r"\$\s*\d+(?:\.\d+)?", " ", remaining)
    # Strip leftover currency words, e.g. "dollars", "bucks", "usd".
    remaining = re.sub(r"\b(?:dollars?|bucks?|usd)\b", " ", remaining, flags=re.I)

    # size: "size M", "size 8", or a standalone size token / US shoe size.
    size = None
    size_phrase = re.search(r"\bsize\s+([a-z]{1,3}|\d{1,2}(?:\.\d)?)\b", remaining, re.I)
    if size_phrase:
        size = size_phrase.group(1).upper()
        remaining = re.sub(r"\bsize\s+[a-z0-9.]{1,4}\b", " ", remaining, flags=re.I)
    else:
        # Look for a standalone size letter token (e.g. "... tee M").
        for tok in re.findall(r"\b[a-z]{1,3}\b", remaining, re.I):
            if tok.lower() in _SIZE_TOKENS:
                size = tok.upper()
                remaining = re.sub(rf"\b{re.escape(tok)}\b", " ", remaining, count=1, flags=re.I)
                break

    # description: leftover keywords, whitespace-normalized.
    description = re.sub(r"\s+", " ", remaining).strip(" ,.")

    return {"description": description, "size": size, "max_price": max_price}


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: fresh session — the single source of truth for this interaction.
    session = _new_session(query, wardrobe)

    # Step 2: parse the query into description / size / max_price.
    parsed = _parse_query(query)
    session["parsed"] = parsed

    # Branch A: nothing to search for.
    if not parsed["description"]:
        session["error"] = (
            "Tell me what you're looking for — e.g. "
            "'vintage graphic tee under $30, size M'."
        )
        return session

    # Step 3: search the listings.
    results = search_listings(
        parsed["description"], parsed["size"], parsed["max_price"]
    )
    session["search_results"] = results

    # Branch B: no matches — stop before suggest_outfit, do NOT pass empty input on.
    if not results:
        filters = []
        if parsed["max_price"] is not None:
            filters.append(f"under ${parsed['max_price']:.0f}")
        if parsed["size"] is not None:
            filters.append(f"in size {parsed['size']}")
        filter_text = " ".join(filters)
        session["error"] = (
            f"No matches for '{parsed['description']}'"
            f"{' ' + filter_text if filter_text else ''}. "
            "Want me to raise the budget, drop the size filter, or try broader keywords?"
        )
        return session

    # Step 4: select the top-scored result.
    session["selected_item"] = results[0]

    # Step 5: suggest an outfit from the user's wardrobe (LLM call).
    try:
        session["outfit_suggestion"] = suggest_outfit(
            session["selected_item"], session["wardrobe"]
        )
    except Exception:
        session["error"] = (
            "Couldn't reach the styling model — check your GROQ_API_KEY and try again."
        )
        return session

    # Step 6: write the fit card, only if we have a real outfit suggestion.
    outfit = session["outfit_suggestion"]
    if outfit and outfit.strip():
        try:
            session["fit_card"] = create_fit_card(outfit, session["selected_item"])
        except Exception:
            session["error"] = (
                "Found the item and outfit, but couldn't generate the fit card "
                "(model unavailable)."
            )
            return session

    # Step 7: done.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
