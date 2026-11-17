from app.config import REPO_ROOT, Settings


def test_env_example_loads_with_empty_values():
    s = Settings(_env_file=REPO_ROOT / ".env.example")
    assert s.aws_region == "ap-south-1" and s.bedrock_llm_id is None and s.max_rows is None
    assert s.llm_extra_request_fields is None and s.slice_hours == 24
    assert s.chroma_path.is_absolute() and s.id_pattern == r"\b[0-9A-F]{8,12}\b"


def test_extra_request_fields_json(monkeypatch):
    monkeypatch.setenv("LLM_EXTRA_REQUEST_FIELDS", '{"reasoning_effort": "low"}')
    assert Settings(_env_file=None).llm_extra_request_fields == {"reasoning_effort": "low"}


def test_env_example_selects_gemini_without_a_key():
    s = Settings(_env_file=REPO_ROOT / ".env.example")
    assert s.llm_provider == "gemini" and s.gemini_api_key is None and s.gemini_thinking_budget == 0
    assert s.llm_model_id == s.gemini_llm_id and s.embed_model_id == s.gemini_embed_id


def test_bedrock_provider_ids(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("BEDROCK_LLM_ID", "some.model-v1")
    s = Settings(_env_file=None)
    assert s.llm_model_id == "some.model-v1" and s.embed_model_id == "amazon.titan-embed-text-v2:0"
