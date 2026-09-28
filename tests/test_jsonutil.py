from dutext.jsonutil import parse_json_object


def test_parse_json_object_from_fence() -> None:
    data = parse_json_object("```json\n{\"kind\": \"emphasize\", \"text\": \"hello\"}\n```")
    assert data["kind"] == "emphasize"
    assert data["text"] == "hello"


def test_parse_json_object_with_preamble() -> None:
    data = parse_json_object("here you go\n{\"tex\": \"\\\\textbf{x}\"}\n")
    assert "textbf" in data["tex"]
