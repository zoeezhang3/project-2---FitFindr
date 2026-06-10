"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    # Keywords from the description, lowercased for case-insensitive matching.
    keywords = [w for w in description.lower().split() if w]

    scored: list[tuple[int, dict]] = []
    for item in listings:
        # Filter: price ceiling (inclusive).
        if max_price is not None and item["price"] > max_price:
            continue

        # Filter: size, case-insensitive substring match so "M" matches "S/M".
        if size is not None and size.strip().lower() not in item["size"].lower():
            continue

        # Score: keyword overlap across title, description, and style_tags.
        haystack = " ".join(
            [item["title"], item["description"], " ".join(item["style_tags"])]
        ).lower()
        score = sum(1 for kw in keywords if kw in haystack)

        # Drop listings with no relevant keyword match.
        if score == 0:
            continue

        scored.append((score, item))

    # Sort by score, highest first. Stable sort preserves dataset order on ties.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    client = _get_groq_client()

    # Describe the new item compactly for the prompt.
    item_desc = (
        f"{new_item['title']} "
        f"(category: {new_item['category']}, "
        f"colors: {', '.join(new_item['colors'])}, "
        f"style: {', '.join(new_item['style_tags'])}, "
        f"condition: {new_item['condition']})"
    )

    items = wardrobe.get("items", [])

    if not items:
        # Empty wardrobe: give general styling advice, never reference owned pieces.
        prompt = (
            f"A shopper is considering buying this secondhand item:\n{item_desc}\n\n"
            "They haven't told us what's in their wardrobe yet. In 2-3 sentences, "
            "give general styling advice for this piece: what categories, colors, "
            "and kinds of pieces pair well with it, and what overall vibe it suits. "
            "Do not invent specific items they own."
        )
    else:
        # Format the wardrobe so the LLM can name real pieces.
        wardrobe_lines = []
        for w in items:
            note = f" — {w['notes']}" if w.get("notes") else ""
            wardrobe_lines.append(
                f"- {w['name']} ({w['category']}, "
                f"{', '.join(w['colors'])}, {', '.join(w['style_tags'])}){note}"
            )
        wardrobe_text = "\n".join(wardrobe_lines)
        prompt = (
            f"A shopper is considering buying this secondhand item:\n{item_desc}\n\n"
            f"Here is their existing wardrobe:\n{wardrobe_text}\n\n"
            "Suggest 1-2 complete, wearable outfits that pair the new item with "
            "specific pieces from their wardrobe (name the pieces). Keep it casual "
            "and concrete, 2-4 sentences total. Only use items listed above."
        )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": "You are a thoughtful personal stylist who gives "
                "practical, specific secondhand-fashion advice.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
    )

    return response.choices[0].message.content.strip()


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # Guard: no outfit to describe.
    if not outfit or not outfit.strip():
        return (
            "Can't write a fit card without an outfit to describe — "
            "try the search again."
        )

    client = _get_groq_client()

    prompt = (
        f"Item: {new_item['title']}\n"
        f"Price: ${new_item['price']:.0f}\n"
        f"Platform: {new_item['platform']}\n"
        f"Outfit: {outfit}\n\n"
        "Write a short, casual social-media caption (2-4 sentences) for this "
        "thrifted find, like a real OOTD post — not a product description. "
        "Mention the item name, price, and platform naturally, once each. "
        "Capture the outfit's vibe in specific terms. Keep it authentic."
    )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": "You write fun, authentic-sounding OOTD captions for "
                "secondhand-fashion finds.",
            },
            {"role": "user", "content": prompt},
        ],
        # Higher temperature so the caption varies between identical inputs.
        temperature=1.0,
    )

    return response.choices[0].message.content.strip()
