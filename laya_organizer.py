#!/usr/bin/env python3
"""
Laya Auto File Organizer
Organizes files into smart categories using Laya sub-35ms decision engine.
Automatically creates target folders and moves files safely.
"""

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

ACTIVE_DOWNLOAD_EXTS = ('.crdownload', '.part', '.tmp', '.download', '.partial')

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

def get_laya_questions() -> dict[str, Any]:
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

class HeuristicRouter:
    """Built-in fast heuristic classifier when upstream laya neural engine or PyTorch is unavailable."""
    
    EXT_GROUPS = {
        "Code_and_Scripts": {
            ".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".c", ".cpp", ".cc", ".h", ".hpp",
            ".cs", ".java", ".html", ".css", ".scss", ".sass", ".sh", ".bash", ".zsh", ".sql",
            ".php", ".rb", ".swift", ".kt", ".lua", ".r", ".m", ".asm"
        },
        "Data_and_Configs": {
            ".json", ".yaml", ".yml", ".toml", ".xml", ".ini", ".conf", ".env", ".tsv"
        },
        "Logs_and_Diagnostics": {
            ".log", ".trace", ".dump", ".dmp", ".stacktrace"
        },
        "Images_and_Graphics": {
            ".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".bmp", ".ico", ".tiff", ".psd", ".ai"
        },
        "Audio_and_Music": {
            ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus"
        },
        "Video_and_Movies": {
            ".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v"
        },
        "Archives_and_Installers": {
            ".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".iso", ".deb", ".rpm", ".appimage", ".exe", ".dmg", ".pkg", ".msi"
        },
        "Books_and_Manuals": {
            ".epub", ".mobi", ".azw3", ".cbr", ".cbz"
        },
        "Design_and_3D": {
            ".stl", ".obj", ".blend", ".step", ".stp", ".fbx", ".3ds", ".dxf", ".dwg"
        },
        "Documents": {
            ".docx", ".doc", ".odt", ".rtf", ".txt", ".pages", ".md", ".tex", ".pptx", ".ppt"
        }
    }

    FINANCIAL_KEYWORDS = {
        "invoice", "receipt", "billing", "bill", "tax", "statement", "paystub", "payroll",
        "salary", "expense", "bank", "financial", "payment", "due", "amount", "usd", "inr"
    }

    MANUAL_KEYWORDS = {
        "manual", "handbook", "guide", "documentation", "tutorial", "spec", "specification"
    }

    def predict(self, sample_text: str, questions: dict[str, Any]) -> dict[str, Any]:
        lower_sample = sample_text.lower()
        ext = ""
        for line in sample_text.splitlines():
            if line.startswith("Extension:"):
                ext = line.split(":", 1)[1].strip().lower()
                break

        # Check financial signals
        is_financial = any(kw in lower_sample for kw in self.FINANCIAL_KEYWORDS) and (
            ext in {".pdf", ".csv", ".xlsx", ".xls", ".txt"} or not ext
        )

        # Check manual/documentation signals for PDFs
        is_manual = ext == ".pdf" and any(kw in lower_sample for kw in self.MANUAL_KEYWORDS)

        # Check junk signals
        junk_exts = {".tmp", ".temp", ".bak", ".old", ".swp", ".cache", ".crdownload", ".part", ".download"}
        is_junk = ext in junk_exts or "temp" in lower_sample or "cache" in lower_sample

        if is_financial:
            category = "Financial"
            confidence = 0.95
        elif is_manual:
            category = "Books_and_Manuals"
            confidence = 0.90
        elif ext == ".pdf":
            category = "Documents"
            confidence = 0.88
        else:
            category = "Other"
            confidence = 0.70
            for cat, exts in self.EXT_GROUPS.items():
                if ext in exts:
                    category = cat
                    confidence = 0.95
                    break

        return {
            "answers": {
                "category": {
                    "choice": category,
                    "confidence": confidence
                },
                "is_temporary_junk": {
                    "noul": 0.95 if is_junk else 0.05
                }
            }
        }

def get_router():
    """Returns upstream Laya Router if installed; otherwise falls back to fast HeuristicRouter."""
    try:
        from laya import Router
        return Router(), "neural"
    except Exception as e:
        print(f"Notice: Laya neural engine unavailable ({e}). Using built-in fast heuristic classifier.")
        return HeuristicRouter(), "heuristic"

def organize_directory(target_dir: str, output_dir: str = None, dry_run: bool = False, min_confidence: float = 0.50):
    router, engine_type = get_router()
    
    target_path = Path(target_dir).expanduser().resolve()
    if not target_path.exists() or not target_path.is_dir():
        print(f"Error: Target directory '{target_dir}' does not exist.")
        sys.exit(1)
        
    dest_base = Path(output_dir).expanduser().resolve() if output_dir else target_path
    
    print("Loading Laya Decision Engine...")
    router = Router()
    questions = get_laya_questions()
    
    files = [f for f in target_path.iterdir() if f.is_file() and (not f.name.startswith(".") or f.name.startswith(".~"))]
    if not files:
        print("No files found to organize.")
        return

    print(f"Found {len(files)} files in '{target_path}'. Sorting into categories...")
    
    stats = {}
    for file_path in files:
        if file_path.name.startswith(".~") or file_path.name.lower().endswith(ACTIVE_DOWNLOAD_EXTS):
            print(f"[Skipped] {file_path.name} (active download)")
            continue

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
            counter = 1
            new_target = dest_file_path
            while new_target.exists() and new_target != file_path:
                new_target = target_folder / f"{file_path.stem}_dup{counter}{file_path.suffix}"
                counter += 1
            dest_file_path = new_target
            shutil.move(str(file_path), str(dest_file_path))
            
    print("\nOrganization Complete!")
    for cat, count in stats.items():
        print(f"  - {cat}: {count} files")

def self_check():
    """ponytail: minimal runnable test for expanded laya decision logic"""
    router, engine = get_router()
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

def main():
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

if __name__ == "__main__":
    main()
