from __future__ import annotations

from src.topics import (
    EPIC_GAMES_STORE_KEY,
    STEAM_STORE_KEY,
    StorefrontDisambiguator,
    StorefrontExtractor,
)


def test_extracts_both_storefronts_from_comparative_text() -> None:
    extractor = StorefrontExtractor()

    results = extractor.extract("I went back to Steam because Epic can't compare.")

    assert {result.symbol for result in results} == {
        EPIC_GAMES_STORE_KEY,
        STEAM_STORE_KEY,
    }


def test_extracts_steam_store_from_store_context() -> None:
    extractor = StorefrontExtractor()

    results = extractor.extract("The Steam client UI is better than the launcher.")

    assert [result.symbol for result in results] == [STEAM_STORE_KEY]


def test_steam_deck_alone_does_not_match_store() -> None:
    extractor = StorefrontExtractor()

    assert extractor.extract("The Steam Deck battery life is solid.") == []


def test_storefront_disambiguator_keeps_supported_entities() -> None:
    extractor = StorefrontExtractor()
    disambiguator = StorefrontDisambiguator()

    candidates = extractor.extract("Prefer the Epic Store to Steam for pricing.")

    assert set(disambiguator.filter(candidates)) == {
        EPIC_GAMES_STORE_KEY,
        STEAM_STORE_KEY,
    }
