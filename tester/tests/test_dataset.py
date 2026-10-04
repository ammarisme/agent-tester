import pytest

from agent_tester.dataset import DatasetParseError, load_dataset, parse_cases
from agent_tester.models import DatasetRef


def test_jsonl_with_comments_and_blank_lines():
    text = (
        '{"id": "a", "input": {"m": 1}}\n\n// comment\n{"id": 2, "input": "x", "tags": "t1, t2"}\n'
    )
    cases = parse_cases(text, "set.jsonl")
    assert [c.id for c in cases] == ["a", "2"]
    assert cases[1].tags == ["t1", "t2"]


def test_json_array_and_wrapper_and_auto_ids():
    assert [c.id for c in parse_cases('[{"input": 1}, {"input": 2}]')] == ["case-1", "case-2"]
    assert parse_cases('{"name": "x", "cases": [{"id": "z"}]}')[0].id == "z"
    assert parse_cases('[{"case_id": "legacy"}]')[0].id == "legacy"


def test_errors_are_collected_with_line_numbers():
    text = '{"id": "a"}\n{broken\n{"id": "a"}\n{"id": "b", "expected": {"contain": "x"}}\n'
    with pytest.raises(DatasetParseError) as exc:
        parse_cases(text, "x.jsonl")
    lines = [(e["line"], e["message"]) for e in exc.value.errors]
    assert lines[0][0] == 2 and "invalid JSON" in lines[0][1]
    assert lines[1][0] == 3 and "duplicate id 'a'" in lines[1][1]
    assert lines[2][0] == 4 and "unknown check 'contain'" in lines[2][1]


def test_csv_columns_become_input_fields():
    text = 'id,message,locale,expected,tags\nc1,Hello,en,Hi,smoke\nc2,Hallo,de,"{""regex"": ""Hallo""}",\n'
    cases = parse_cases(text, "cases.csv")
    assert cases[0].input == {"message": "Hello", "locale": "en"}
    assert cases[0].expected.contains == ["Hi"]
    assert cases[0].tags == ["smoke"]
    assert cases[1].expected.regex == "Hallo"


def test_csv_input_column():
    cases = parse_cases('id,input\na,"{""q"": 1}"\nb,plain text\n', "c.csv")
    assert cases[0].input == {"q": 1}
    assert cases[1].input == {"message": "plain text"}


def test_empty_text_is_empty_dataset():
    assert parse_cases("   \n") == []


async def test_file_uris_can_be_disabled(tmp_path):
    path = tmp_path / "d.jsonl"
    path.write_text('{"id": "a"}\n')
    assert len(await load_dataset(DatasetRef(uri=str(path)))) == 1
    with pytest.raises(ValueError, match="http"):
        await load_dataset(DatasetRef(uri=str(path)), allow_files=False)
