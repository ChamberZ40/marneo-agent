# tests/tools/test_files.py
import json
import pytest
from marneo.tools.core.files import (
    read_file, write_file, edit_file, glob_files, grep_files
)


def test_read_file_returns_content_with_line_numbers(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("line1\nline2\nline3")
    result = json.loads(read_file({"path": str(f)}))
    assert "line1" in result["content"]
    assert "1\t" in result["content"]   # line numbers
    assert result["lines"] == 3


def test_read_file_with_offset_and_limit(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("\n".join(f"line{i}" for i in range(1, 11)))
    result = json.loads(read_file({"path": str(f), "offset": 3, "limit": 3}))
    assert "line3" in result["content"]
    assert "line6" in result["content"]
    assert "line7" not in result["content"]


def test_read_file_missing_returns_error(tmp_path):
    result = json.loads(read_file({"path": str(tmp_path / "no.txt")}))
    assert "error" in result


def test_write_file_creates_file(tmp_path):
    f = tmp_path / "new.txt"
    result = json.loads(write_file({"path": str(f), "content": "hello"}))
    assert result.get("ok") is True
    assert f.read_text() == "hello"


def test_write_file_creates_parent_dirs(tmp_path):
    f = tmp_path / "a" / "b" / "c.txt"
    result = json.loads(write_file({"path": str(f), "content": "x"}))
    assert result.get("ok") is True
    assert f.read_text() == "x"


def test_edit_file_replaces_string(tmp_path):
    f = tmp_path / "edit.txt"
    f.write_text("hello world\nhello again")
    result = json.loads(edit_file({"path": str(f), "old_string": "hello world", "new_string": "hi world"}))
    assert result.get("ok") is True
    assert f.read_text() == "hi world\nhello again"


def test_edit_file_fails_if_old_string_not_found(tmp_path):
    f = tmp_path / "edit.txt"
    f.write_text("hello world")
    result = json.loads(edit_file({"path": str(f), "old_string": "not there", "new_string": "x"}))
    assert "error" in result


def test_glob_files(tmp_path):
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    (tmp_path / "c.txt").write_text("")
    result = json.loads(glob_files({"pattern": "*.py", "path": str(tmp_path)}))
    files = result["files"]
    assert len(files) == 2
    assert all(f.endswith(".py") for f in files)


def test_grep_files(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    return 42\n")
    (tmp_path / "b.py").write_text("def bar():\n    pass\n")
    result = json.loads(grep_files({"pattern": "def foo", "path": str(tmp_path)}))
    assert len(result["matches"]) == 1
    assert "a.py" in result["matches"][0]["file"]
