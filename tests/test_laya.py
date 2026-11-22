import sys
import tempfile
from pathlib import Path

# Ensure parent directory is in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from laya_organizer import ACTIVE_DOWNLOAD_EXTS, extract_file_sample, get_laya_questions


def test_active_download_exts():
    assert ".crdownload" in ACTIVE_DOWNLOAD_EXTS
    assert ".part" in ACTIVE_DOWNLOAD_EXTS
    assert ".download" in ACTIVE_DOWNLOAD_EXTS

def test_get_laya_questions():
    questions = get_laya_questions()
    assert "category" in questions
    assert questions["category"]["type"] == "choice"
    criteria = questions["category"]["criteria"]
    assert "Financial" in criteria
    assert "Code_and_Scripts" in criteria
    assert "Images_and_Graphics" in criteria

def test_extract_file_sample_text():
    with tempfile.NamedTemporaryFile("w+", suffix=".py", delete=False) as f:
        f.write("def hello():\n    return 'world'\n")
        temp_path = Path(f.name)
    try:
        sample = extract_file_sample(temp_path)
        assert f"Filename: {temp_path.name}" in sample
        assert "Extension: .py" in sample
        assert "Content Snippet:" in sample
        assert "hello()" in sample
    finally:
        temp_path.unlink()

def test_extract_file_sample_binary():
    with tempfile.NamedTemporaryFile("wb+", suffix=".bin", delete=False) as f:
        f.write(b"\x00\x01\x02\x03\x04")
        temp_path = Path(f.name)
    try:
        sample = extract_file_sample(temp_path)
        assert f"Filename: {temp_path.name}" in sample
        assert "Extension: .bin" in sample
        assert "Content Snippet:" not in sample
    finally:
        temp_path.unlink()
