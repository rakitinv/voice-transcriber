from core.user_language import (
    default_asr_language_hint_from_preferences,
    llm_summary_output_language,
)


def test_asr_hint_auto_is_none():
    assert default_asr_language_hint_from_preferences(None) is None
    assert default_asr_language_hint_from_preferences({}) is None
    assert default_asr_language_hint_from_preferences({"default_language": "auto"}) is None


def test_asr_hint_explicit():
    assert default_asr_language_hint_from_preferences({"default_language": "en"}) == "en"


def test_llm_summary_auto_maps_to_russian():
    assert llm_summary_output_language(None) == "ru"
    assert llm_summary_output_language({}) == "ru"
    assert llm_summary_output_language({"default_language": ""}) == "ru"
    assert llm_summary_output_language({"default_language": "auto"}) == "ru"
    assert llm_summary_output_language({"default_language": "AUTO"}) == "ru"
    assert llm_summary_output_language({"default_language": "—"}) == "ru"


def test_llm_summary_explicit_language():
    assert llm_summary_output_language({"default_language": "en"}) == "en"
    assert llm_summary_output_language({"default_language": "DE"}) == "de"
