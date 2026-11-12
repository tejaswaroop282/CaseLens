from app.config import REPO_ROOT, Settings


def test_env_example_loads_with_empty_values():
    s = Settings(_env_file=REPO_ROOT / ".env.example")
    assert s.aws_region == "ap-south-1" and s.bedrock_llm_id is None and s.max_rows is None
    assert s.llm_extra_request_fields is None and s.slice_hours == 24
    assert s.chroma_path.is_absolute() and s.id_pattern == r"\b[0-9A-F]{8,12}\b"


def test_extra_request_fields_json(monkeypatch):
    monkeypatch.setenv("LLM_EXTRA_REQUEST_FIELDS", '{"reasoning_effort": "low"}')
    assert Settings(_env_file=None).llm_extra_request_fields == {"reasoning_effort": "low"}
