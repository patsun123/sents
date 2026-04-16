from __future__ import annotations

from src.topics import (
    EPIC_GAMES_STORE_KEY,
    EpicGamesStoreDisambiguator,
    EpicGamesStoreExtractor,
)


def test_strong_phrase_matches_epic_games_store() -> None:
    extractor = EpicGamesStoreExtractor()

    results = extractor.extract("The Epic Games Store weekly freebies are live.")

    assert [result.symbol for result in results] == [EPIC_GAMES_STORE_KEY]


def test_contextual_match_requires_store_context() -> None:
    extractor = EpicGamesStoreExtractor()

    results = extractor.extract("Epic has another launcher exclusive this month.")

    assert [result.symbol for result in results] == [EPIC_GAMES_STORE_KEY]


def test_prepositional_phrase_on_epic_matches() -> None:
    extractor = EpicGamesStoreExtractor()

    results = extractor.extract("Control is free on Epic right now.")

    assert [result.symbol for result in results] == [EPIC_GAMES_STORE_KEY]


def test_epic_exclusive_phrase_matches() -> None:
    extractor = EpicGamesStoreExtractor()

    results = extractor.extract("Another Epic exclusive is coming to PC.")

    assert [result.symbol for result in results] == [EPIC_GAMES_STORE_KEY]


def test_generic_epic_usage_does_not_match() -> None:
    extractor = EpicGamesStoreExtractor()

    assert extractor.extract("That trailer was epic.") == []


def test_disambiguator_only_keeps_epic_entity() -> None:
    extractor = EpicGamesStoreExtractor()
    disambiguator = EpicGamesStoreDisambiguator()

    candidates = extractor.extract("EGS coupon stacking is back.")

    assert disambiguator.filter(candidates) == [EPIC_GAMES_STORE_KEY]
