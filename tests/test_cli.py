from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from laya_organizer import (
    config_subcommand,
    find_duplicates,
    format_size,
    format_table,
    inspect_directory,
    load_history,
    organize_directory,
    rollback_last_batch,
    scan_directory,
    self_check,
)


def test_format_size():
    assert format_size(100) == "100 B"
    assert format_size(2048) == "2.0 KB"
    assert format_size(1048576) == "1.0 MB"
    assert format_size(1073741824) == "1.0 GB"


def test_format_table():
    headers = ["Name", "Age"]
    rows = [["Alice", "30"], ["Bob", "25"]]
    table = format_table(headers, rows)
    assert "Alice" in table
    assert "Bob" in table
    assert "┌" in table
    assert "└" in table


def test_self_check():
    assert self_check() is True


def test_scan_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        (td / "test_app.py").write_text("print('test app')")
        (td / "test_doc.md").write_text("# Test Document")
        (td / "invoice_99.pdf").write_text("Invoice total $100.00")

        report = scan_directory(td, json_output=False)
        assert report["total_files"] == 3
        assert "breakdown" in report
        assert len(report["files"]) == 3

        # Verify no files were moved or directories created
        assert (td / "test_app.py").exists()
        assert (td / "test_doc.md").exists()
        assert (td / "invoice_99.pdf").exists()


def test_scan_directory_json(capsys):
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        (td / "data.json").write_text('{"name": "test"}')

        _ = scan_directory(td, json_output=True)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["total_files"] == 1
        assert "Data_and_Configs" in data["breakdown"]


def test_inspect_directory():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        (td / "file1.txt").write_text("sample content")
        (td / "file2.py").write_text("x = 1\n")
        (td / "subdir").mkdir()

        report = inspect_directory(td, json_output=False)
        assert report["total_files"] == 2
        assert report["total_subdirectories"] == 1
        assert report["total_size_bytes"] > 0
        assert "< 10 KB" in report["size_distribution"]
        assert report["size_distribution"]["< 10 KB"] == 2


def test_find_duplicates():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        content = "exact duplicate binary or text content"
        (td / "file_orig.txt").write_text(content)
        (td / "file_copy.txt").write_text(content)
        (td / "unique.txt").write_text("different content")

        report = find_duplicates(td, json_output=False)
        assert report["total_duplicate_groups"] == 1
        assert report["total_duplicate_files"] == 1
        assert report["total_wasted_bytes"] == len(content.encode("utf-8"))

        group = report["duplicate_groups"][0]
        assert len(group["files"]) == 2
        assert group["count"] == 2


def test_organize_dry_run():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        (td / "main.rs").write_text("fn main() {}")

        res = organize_directory(str(td), dry_run=True)
        assert res["dry_run"] is True
        assert res["count"] == 1
        assert res["batch_id"] is None
        # File should still be at original path
        assert (td / "main.rs").exists()


def test_organize_apply_and_undo():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        history_file = td / ".history.json"
        f1 = td / "app.py"
        f1.write_text("print('hello')")
        f2 = td / "metrics.csv"
        f2.write_text("a,b,c\n1,2,3\n")

        # Live sort
        res = organize_directory(
            target_dir=str(td),
            apply=True,
            auto_confirm=True,
            history_file=history_file,
        )
        assert res["applied"] is True
        assert res["count"] == 2
        assert res["batch_id"] is not None
        assert not f1.exists()
        assert not f2.exists()

        # Check history recorded
        batches = load_history(history_file=history_file)
        assert len(batches) >= 1
        assert batches[-1]["batch_id"] == res["batch_id"]

        # Undo via rollback_last_batch
        success = rollback_last_batch(batch_id=res["batch_id"], history_file=history_file)
        assert success is True
        assert f1.exists()
        assert f2.exists()


def test_config_subcommand():
    cfg = config_subcommand(show=True, json_output=False)
    assert "default_confidence" in cfg

    updated = config_subcommand(set_confidence=0.75, json_output=False)
    assert updated["default_confidence"] == 0.75

    # Reset
    reset_cfg = config_subcommand(reset=True, json_output=False)
    assert reset_cfg["default_confidence"] == 0.50


def test_cli_subcommand_invocations():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        (td / "test.py").write_text("print('test')")
        (td / "copy.py").write_text("print('test')")

        # Test scan
        p_scan = subprocess.run(
            [sys.executable, "laya_organizer.py", "scan", str(td), "--json"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(p_scan.stdout)
        assert data["total_files"] == 2

        # Test duplicates
        p_dup = subprocess.run(
            [sys.executable, "laya_organizer.py", "duplicates", str(td), "--json"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        dup_data = json.loads(p_dup.stdout)
        assert dup_data["total_duplicate_files"] == 1

        # Test inspect
        p_insp = subprocess.run(
            [sys.executable, "laya_organizer.py", "inspect", str(td), "--json"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        insp_data = json.loads(p_insp.stdout)
        assert insp_data["total_files"] == 2

        # Test organize dry run
        p_org = subprocess.run(
            [sys.executable, "laya_organizer.py", "organize", str(td), "--dry-run", "--json"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        org_data = json.loads(p_org.stdout)
        assert org_data["dry_run"] is True


def test_benchmark_script_run():
    # Run benchmark on small synthetic sample set
    p = subprocess.run(
        [sys.executable, "benchmarks/benchmark.py", "--samples", "20", "--skip-neural", "--json"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(p.stdout)
    assert report["total_samples"] == 20
    assert "extension_baseline" in report["classifiers"]
    assert "laya_heuristic" in report["classifiers"]
    assert report["classifiers"]["extension_baseline"]["throughput_fps"] > 0
    assert report["classifiers"]["laya_heuristic"]["throughput_fps"] > 0
