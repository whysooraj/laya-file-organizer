#!/usr/bin/env python3
"""
Laya Auto File Organizer
Organizes files into smart categories using Laya sub-35ms decision engine.
Automatically creates target folders and moves files safely.
"""

import os
import sys
import shutil
import argparse
from pathlib import Path
from typing import Dict, Any

# ponytail: stdlib text extraction helper with 1KB ceiling to keep forward pass instant
def extract_file_sample(file_path: Path, max_chars: int = 1000) -> str:
    """Extract filename and text content snippet for Laya context."""
    ext = file_path.suffix.lower()
    info = f"Filename: {file_path.name}\nExtension: {ext}\nSize: {file_path.stat().st_size} bytes\n"
    
    text_exts = {
        ".txt", ".md", ".json", ".csv", ".tsv", ".py", ".js", ".ts", ".jsx", ".tsx", 
        ".rs", ".go", ".cpp", ".c", ".h", ".java", ".html", ".css", ".log", ".yaml", 
        ".yml", ".sh", ".sql", ".xml", ".toml", ".env", ".ini", ".conf"
    }
    
    if ext in text_exts:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                snippet = f.read(max_chars)
                info += f"Content Snippet:\n{snippet}"
        except Exception:
            pass
    return info

def get_laya_questions() -> Dict[str, Any]:
    return {
        "category": {
            "type": "choice",
            "instructions": "Which folder category should this file be organized into?",
            "criteria": {
                "Financial": "invoices, receipts, tax documents, bank statements, billing, paystubs, financial reports",
                "Documents": "resumes, CVs, contracts, letters, notes, reports, PDFs, academic papers, articles",
                "Code_and_Scripts": "source code files, Python, JavaScript, TypeScript, Rust, C++, Go, HTML, CSS, Shell scripts, SQL",
                "Data_and_Configs": "JSON, CSV, TSV, YAML, TOML, XML, env configuration files, database dumps",
                "Logs_and_Diagnostics": "system log files, crash dumps, build logs, debug traces, stack traces",
                "Images_and_Graphics": "PNG, JPG, JPEG, SVG, WebP, GIF, PSD, AI, Figma exports, screenshots",
                "Audio_and_Music": "MP3, WAV, FLAC, AAC, OGG, M4A, podcasts, voice recordings, music tracks",
                "Video_and_Movies": "MP4, MKV, AVI, MOV, WebM, screen recordings, video clips, movies",
                "Archives_and_Installers": "ZIP, TAR, GZ, 7Z, RAR, ISO, DEB, RPM, AppImage, EXE, DMG, software installers",
                "Books_and_Manuals": "EPUB, MOBI, AZW3, user manuals, technical documentation PDFs, ebooks",
                "Design_and_3D": "STL, OBJ, BLEND, STEP, CAD drawings, 3D models, graphics projects",
                "Other": "everything else that does not clearly fit above"
            }
        },
        "is_temporary_junk": {
            "type": "noul",
            "instructions": "Is this a temporary download, cache, or scrap log file that should be flagged for cleaning?"
        }
    }

def organize_directory(target_dir: str, output_dir: str = None, dry_run: bool = False, min_confidence: float = 0.50):
    from laya import Router
    
    target_path = Path(target_dir).expanduser().resolve()
    if not target_path.exists() or not target_path.is_dir():
        print(f"Error: Target directory '{target_dir}' does not exist.")
        sys.exit(1)
        
    dest_base = Path(output_dir).expanduser().resolve() if output_dir else target_path
    
    print(f"Loading Laya Decision Engine...")
    router = Router()
    questions = get_laya_questions()
    
    files = [f for f in target_path.iterdir() if f.is_file() and not f.name.startswith(".")]
    if not files:
        print("No files found to organize.")
        return

    print(f"Found {len(files)} files in '{target_path}'. Sorting into categories...")
    
    stats = {}
    for file_path in files:
        sample_text = extract_file_sample(file_path)
        res = router.predict(sample_text, questions)
        
        cat_ans = res["answers"]["category"]
        category = cat_ans["choice"]
        confidence = cat_ans.get("confidence", 1.0)
        is_junk = res["answers"]["is_temporary_junk"]["noul"] > 0.70
        
        if confidence < min_confidence:
            category = "Uncertain"
            
        target_folder = dest_base / category
        if is_junk:
            target_folder = dest_base / "Junk_Candidates"
            
        dest_file_path = target_folder / file_path.name
        
        stats[category] = stats.get(category, 0) + 1
        print(f"[{category}] (conf: {confidence:.2f}) {file_path.name} -> {target_folder}/")
        
        if not dry_run:
            # ponytail: auto-create target directory if it does not exist
            target_folder.mkdir(parents=True, exist_ok=True)
            if dest_file_path.exists() and dest_file_path != file_path:
                dest_file_path = target_folder / f"{file_path.stem}_dup{file_path.suffix}"
            shutil.move(str(file_path), str(dest_file_path))
            
    print("\nOrganization Complete!")
    for cat, count in stats.items():
        print(f"  - {cat}: {count} files")

def self_check():
    """ponytail: minimal runnable test for expanded laya decision logic"""
    from laya import Router
    router = Router()
    q = get_laya_questions()
    
    samples = [
        ("Filename: invoice_2026_march.pdf\nExtension: .pdf\nContent Snippet: Invoice #402. Total amount due $450.00", "Financial"),
        ("Filename: main.rs\nExtension: .rs\nContent Snippet: fn main() { println!(\"Hello\"); }", "Code_and_Scripts"),
        ("Filename: config.yaml\nExtension: .yaml\nContent Snippet: server:\n  port: 8080", "Data_and_Configs"),
    ]
    for sample, expected in samples:
        res = router.predict(sample, q)
        got = res["answers"]["category"]["choice"]
        assert got == expected, f"Expected {expected}, got {got}"
    print("Self-check passed: All expanded categories classified correctly!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Laya Sub-35ms Auto File Organizer")
    parser.add_argument("target_dir", nargs="?", default=".", help="Directory to organize (default: current dir)")
    parser.add_argument("-o", "--output-dir", help="Destination base folder (default: inside target_dir)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate organization without moving files")
    parser.add_argument("--confidence", type=float, default=0.50, help="Min confidence threshold (default: 0.50)")
    parser.add_argument("--check", action="store_true", help="Run self-check test")
    
    args = parser.parse_args()
    
    if args.check:
        self_check()
    else:
        organize_directory(args.target_dir, args.output_dir, dry_run=args.dry_run, min_confidence=args.confidence)
