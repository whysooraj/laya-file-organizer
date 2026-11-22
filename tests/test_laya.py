import sys
import tempfile
from pathlib import Path

# Ensure parent directory is in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from laya_organizer import (
    ACTIVE_DOWNLOAD_EXTS,
    HeuristicRouter,
    extract_file_sample,
    get_laya_questions,
    load_config,
    organize_directory,
    rollback_last_batch,
)


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

def test_heuristic_router_categories():
    router = HeuristicRouter()
    q = get_laya_questions()
    
    samples = [
        ("Filename: invoice_2026.pdf\nExtension: .pdf\nContent Snippet: Invoice total $500", "Financial"),
        ("Filename: script.py\nExtension: .py\nContent Snippet: print('hello')", "Code_and_Scripts"),
        ("Filename: settings.json\nExtension: .json\nContent Snippet: {\"debug\": true}", "Data_and_Configs"),
        ("Filename: photo.png\nExtension: .png\n", "Images_and_Graphics"),
        ("Filename: track.mp3\nExtension: .mp3\n", "Audio_and_Music"),
        ("Filename: movie.mp4\nExtension: .mp4\n", "Video_and_Movies"),
        ("Filename: archive.zip\nExtension: .zip\n", "Archives_and_Installers"),
        ("Filename: doc.pdf\nExtension: .pdf\nContent Snippet: Regular project report", "Documents"),
    ]
    for text, expected in samples:
        res = router.predict(text, q)
        assert res["answers"]["category"]["choice"] == expected
        assert res["answers"]["category"]["confidence"] >= 0.70

def test_heuristic_router_junk():
    router = HeuristicRouter()
    q = get_laya_questions()
    res = router.predict("Filename: temp_scrap.tmp\nExtension: .tmp\n", q)
    assert res["answers"]["is_temporary_junk"]["noul"] > 0.70

def test_organize_and_rollback():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir)
        file1 = test_dir / "invoice_march.pdf"
        file1.write_text("Invoice total $300.00")
        file2 = test_dir / "app.py"
        file2.write_text("print('hello')")

        # Live run
        res = organize_directory(str(test_dir), dry_run=False)
        assert res["count"] == 2
        assert not file1.exists()
        assert not file2.exists()
        assert (test_dir / "Financial" / "invoice_march.pdf").exists()
        assert (test_dir / "Code_and_Scripts" / "app.py").exists()

        # Rollback
        success = rollback_last_batch(res["batch_id"])
        assert success is True
        assert file1.exists()
        assert file2.exists()
        assert not (test_dir / "Financial").exists()
        assert not (test_dir / "Code_and_Scripts").exists()

def test_config_roundtrip():
    cfg = load_config()
    assert "folder_names" in cfg
    assert "ignored_extensions" in cfg
    assert "default_confidence" in cfg
