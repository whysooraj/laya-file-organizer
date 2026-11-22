import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure parent directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from laya_organizer import (
    DEFAULT_FOLDER_NAMES,
    HeuristicRouter,
    HistoryManager,
    execute_plan,
    extract_file_sample,
    extract_pdf_snippet,
    get_compound_extension,
    get_router,
    is_junk_candidate,
    organize_directory,
    plan_organization,
    rollback_last_batch,
    split_stem_and_ext,
    validate_confidence_threshold,
)


def test_compound_extensions():
    """Verify compound extension detection, stem splitting, and correct archive categorization."""
    assert get_compound_extension("archive.tar.gz") == ".tar.gz"
    assert get_compound_extension("bundle.tar.bz2") == ".tar.bz2"
    assert get_compound_extension("system.tar.xz") == ".tar.xz"
    assert get_compound_extension("db.backup.zip") == ".backup.zip"
    assert get_compound_extension("react.d.ts") == ".d.ts"

    stem, ext = split_stem_and_ext("archive.tar.gz")
    assert stem == "archive"
    assert ext == ".tar.gz"

    stem2, ext2 = split_stem_and_ext("bundle.tar.bz2")
    assert stem2 == "bundle"
    assert ext2 == ".tar.bz2"

    stem3, ext3 = split_stem_and_ext("my.backup.zip")
    assert stem3 == "my"
    assert ext3 == ".backup.zip"

    # Test categorization via HeuristicRouter
    router = HeuristicRouter()
    q = {}
    res_gz = router.predict("Filename: archive.tar.gz\nExtension: .tar.gz\n", q)
    assert res_gz["answers"]["category"]["choice"] == "Archives_and_Installers"

    res_bz2 = router.predict("Filename: bundle.tar.bz2\nExtension: .tar.bz2\n", q)
    assert res_bz2["answers"]["category"]["choice"] == "Archives_and_Installers"

    res_dts = router.predict("Filename: index.d.ts\nExtension: .d.ts\n", q)
    assert res_dts["answers"]["category"]["choice"] == "Code_and_Scripts"


def test_symlink_handling():
    """Verify relative and absolute symlinks are moved safely without breaking targets, and roll back cleanly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        target_file = root / "real_doc.txt"
        target_file.write_text("Secret content inside real doc")

        # Relative symlink
        rel_symlink = root / "relative_link.txt"
        os.symlink("real_doc.txt", rel_symlink)
        assert rel_symlink.is_symlink()
        assert rel_symlink.resolve() == target_file.resolve()

        # Absolute symlink
        abs_symlink = root / "absolute_link.txt"
        os.symlink(str(target_file.resolve()), abs_symlink)
        assert abs_symlink.is_symlink()
        assert abs_symlink.resolve() == target_file.resolve()

        history_file = root / "history.json"
        # Use custom_rules to ensure .txt routes to Documents deterministically across engines
        config_override = {
            "custom_rules": {".txt": "Documents"},
            "folder_names": DEFAULT_FOLDER_NAMES,
        }
        res = organize_directory(str(root), history_file=history_file, config_override=config_override)
        assert res["count"] >= 2

        # Check relative link moved to Documents and its target is intact (not broken!)
        moved_target = root / "Documents" / "real_doc.txt"
        moved_rel = root / "Documents" / "relative_link.txt"
        assert moved_rel.exists(), "Relative symlink was broken upon moving!"
        assert moved_rel.is_symlink()
        assert moved_rel.resolve() == moved_target.resolve()
        assert moved_rel.read_text() == "Secret content inside real doc"

        # Check absolute link moved to Documents and its target is intact
        moved_abs = root / "Documents" / "absolute_link.txt"
        assert moved_abs.exists(), "Absolute symlink was broken upon moving!"
        assert moved_abs.is_symlink()
        assert moved_abs.resolve() == moved_target.resolve()
        assert moved_abs.read_text() == "Secret content inside real doc"

        # Roll back and verify restoration
        rolled = rollback_last_batch(batch_id=res["batch_id"], history_file=history_file)
        assert rolled is True

        assert rel_symlink.exists()
        assert rel_symlink.is_symlink()
        assert rel_symlink.resolve() == target_file.resolve()

        assert abs_symlink.exists()
        assert abs_symlink.is_symlink()
        assert abs_symlink.resolve() == target_file.resolve()

        # Created directory should have been cleaned up
        assert not (root / "Documents").exists()


def test_junk_false_positive_prevention():
    """Verify substring words like 'temp' or 'cache' in filenames do NOT trigger junk."""
    # Substring false positives that must NOT be junk:
    assert not is_junk_candidate("template.py")
    assert not is_junk_candidate("datacache.json")
    assert not is_junk_candidate("temporary_notes.docx")
    assert not is_junk_candidate("attempt.py")
    assert not is_junk_candidate("apache.conf")

    # Explicit scrap files that MUST trigger junk:
    assert is_junk_candidate("temp_file.txt")
    assert is_junk_candidate("cache_run.bin")
    assert is_junk_candidate("build.tmp")
    assert is_junk_candidate("editor.swp")
    assert is_junk_candidate("scratch.temp")
    assert is_junk_candidate("partial.crdownload")
    assert is_junk_candidate("thumbs.db")
    assert is_junk_candidate(".DS_Store")
    assert is_junk_candidate("~lockfile.docx")

    # In action: organize directory containing template.py and datacache.json
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "template.py").write_text("class Template: pass")
        (root / "datacache.json").write_text('{"cached": true}')
        (root / "temp_scratch.log").write_text("debug log")

        moves, stats, _ = plan_organization(root)
        plan_dict = {m.source.name: m.category for m in moves}

        assert plan_dict["template.py"] == "Code_and_Scripts"
        assert plan_dict["datacache.json"] == "Data_and_Configs"
        assert plan_dict["temp_scratch.log"] == "Junk_Candidates"


def test_fallback_classifier_simulation():
    """Verify engine functions 100% reliably when neural engine is unavailable."""
    router, engine_type = get_router(force_fallback=True)
    assert engine_type == "heuristic"
    assert isinstance(router, HeuristicRouter)

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "invoice.csv").write_text("date,amount,invoice_id\n2026-01-01,100,INV-1")
        (root / "script.py").write_text("print('test')")
        (root / "picture.png").write_bytes(b"\x89PNG\r\n\x1a\n")

        res = organize_directory(str(root), router_bundle=(router, engine_type))
        assert res["count"] == 3
        assert (root / "Financial" / "invoice.csv").exists()
        assert (root / "Code_and_Scripts" / "script.py").exists()
        assert (root / "Images_and_Graphics" / "picture.png").exists()


def test_confidence_threshold_validation():
    """Verify validation of confidence threshold values."""
    assert validate_confidence_threshold(None) == 0.50
    assert validate_confidence_threshold(0.0) == 0.0
    assert validate_confidence_threshold(0.85) == 0.85
    assert validate_confidence_threshold(1.0) == 1.0
    assert validate_confidence_threshold("0.72") == 0.72

    with pytest.raises(ValueError, match="Confidence threshold must be"):
        validate_confidence_threshold(-0.01)

    with pytest.raises(ValueError, match="Confidence threshold must be"):
        validate_confidence_threshold(1.01)

    with pytest.raises(ValueError, match="Confidence threshold must be"):
        validate_confidence_threshold("not-a-number")

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "random.xyz").write_text("unknown data")

        # High threshold sends low-confidence files to Uncertain
        moves, stats, _ = plan_organization(root, min_confidence=0.99)
        assert moves[0].category == "Uncertain"


def test_rollback_successful_batch():
    """Verify end-to-end organize and rollback for a clean batch."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        history_file = root / "history.json"

        f1 = root / "test_script.py"
        f1.write_text("x = 1")
        f2 = root / "invoice_march.pdf"
        f2.write_text("Invoice total $300.00")

        res = organize_directory(str(root), history_file=history_file)
        assert res["count"] == 2
        assert not f1.exists()
        assert not f2.exists()
        assert (root / "Code_and_Scripts" / "test_script.py").exists()
        assert (root / "Financial" / "invoice_march.pdf").exists()

        success = rollback_last_batch(batch_id=res["batch_id"], history_file=history_file)
        assert success is True
        assert f1.exists()
        assert f2.exists()
        assert not (root / "Code_and_Scripts").exists()
        assert not (root / "Financial").exists()


def test_rollback_partial_batch():
    """Verify that if a batch fails midway, already-moved records are preserved in journal and can roll back."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        history_file = root / "history.json"

        f1 = root / "file1.py"
        f1.write_text("file 1")
        f2 = root / "file2.py"
        f2.write_text("file 2")
        f3 = root / "file3.py"
        f3.write_text("file 3")

        moves, _, _ = plan_organization(root)
        assert len(moves) == 3

        orig_move = shutil.move
        move_counter = 0

        def failing_move(src, dst):
            nonlocal move_counter
            move_counter += 1
            if move_counter >= 3:
                raise OSError("Simulated disk error on 3rd file move!")
            return orig_move(src, dst)

        batch_id = "partial_test_batch"
        with patch("shutil.move", side_effect=failing_move):
            with pytest.raises(OSError, match="Simulated disk error"):
                execute_plan(moves, batch_id=batch_id, target_dir=root, history_file=history_file)

        # Confirm 2 files were moved before the error
        assert (root / "Code_and_Scripts" / "file1.py").exists()
        assert (root / "Code_and_Scripts" / "file2.py").exists()
        assert f3.exists()  # 3rd file stayed in place

        # Verify journal preserved the 2 partial moves!
        batches = HistoryManager.load(history_file=history_file)
        assert len(batches) == 1
        assert batches[0]["batch_id"] == batch_id
        assert batches[0]["count"] == 2

        # Roll back the partial batch
        rollback_success = rollback_last_batch(batch_id=batch_id, history_file=history_file)
        assert rollback_success is True

        # Both moved files are restored to their original location
        assert f1.exists()
        assert f2.exists()
        assert f3.exists()
        assert not (root / "Code_and_Scripts").exists()


def test_safe_collision_resolution():
    """Verify collision resolution with _dup1, _dup2 for regular and compound extensions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        code_dir = root / "Code_and_Scripts"
        code_dir.mkdir(parents=True)
        existing_code = code_dir / "app.py"
        existing_code.write_text("Original app script")

        archive_dir = root / "Archives_and_Installers"
        archive_dir.mkdir(parents=True)
        existing_tar = archive_dir / "archive.tar.gz"
        existing_tar.write_text("Original archive")

        new_code = root / "app.py"
        new_code.write_text("New app script")

        new_tar = root / "archive.tar.gz"
        new_tar.write_text("New archive content")

        history_file = root / "history.json"
        organize_directory(str(root), history_file=history_file)

        # Existing files must be untouched
        assert existing_code.read_text() == "Original app script"
        assert existing_tar.read_text() == "Original archive"

        # Collided files renamed with _dup1, preserving compound extensions!
        dup_code = code_dir / "app_dup1.py"
        assert dup_code.exists()
        assert dup_code.read_text() == "New app script"

        dup_tar = archive_dir / "archive_dup1.tar.gz"
        assert dup_tar.exists(), "Compound extension duplicate renaming failed!"
        assert dup_tar.read_text() == "New archive content"


def test_pdf_extractor():
    """Verify pure-Python PDF metadata and text extraction without external dependencies."""
    with tempfile.NamedTemporaryFile("wb+", suffix=".pdf", delete=False) as f:
        # Minimal synthetic PDF content with /Title and Tj text operator
        pdf_bytes = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Title (Invoice 2026 March) /Subject (Billing Statement) >>\nendobj\n"
            b"2 0 obj\nstream\nBT /F1 12 Tf (Total amount due: $750.00) Tj ET\nendstream\nendobj\n"
            b"%%EOF"
        )
        f.write(pdf_bytes)
        pdf_path = Path(f.name)

    try:
        snippet = extract_pdf_snippet(pdf_path)
        assert "Invoice 2026 March" in snippet
        assert "Total amount due: $750.00" in snippet

        sample = extract_file_sample(pdf_path)
        assert "Extension: .pdf" in sample
        assert "Invoice 2026 March" in sample

        # Classifier recognizes as Financial due to invoice snippet
        router = HeuristicRouter()
        res = router.predict(sample, {})
        assert res["answers"]["category"]["choice"] == "Financial"
    finally:
        pdf_path.unlink()
