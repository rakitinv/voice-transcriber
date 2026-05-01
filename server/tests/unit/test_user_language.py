from core.user_language import llm_summary_output_language


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
