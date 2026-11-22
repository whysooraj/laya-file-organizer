#!/usr/bin/env python3
"""
Laya Auto File Organizer
Sub-35ms local intelligent file organization engine.
Categorizes files, manages transactions with rollback, and offers interactive terminal UI.
"""

import argparse
import datetime
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Optional

DEFAULT_ACTIVE_DOWNLOAD_EXTS = ('.crdownload', '.part', '.tmp', '.download', '.partial')
ACTIVE_DOWNLOAD_EXTS = DEFAULT_ACTIVE_DOWNLOAD_EXTS
CONFIG_DIR = Path.home() / ".config" / "laya"
CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.json"

DEFAULT_FOLDER_NAMES = {
    "Financial": "Financial",
    "Documents": "Documents",
    "Code_and_Scripts": "Code_and_Scripts",
    "Data_and_Configs": "Data_and_Configs",
    "Logs_and_Diagnostics": "Logs_and_Diagnostics",
    "Images_and_Graphics": "Images_and_Graphics",
    "Audio_and_Music": "Audio_and_Music",
    "Video_and_Movies": "Video_and_Movies",
    "Archives_and_Installers": "Archives_and_Installers",
    "Books_and_Manuals": "Books_and_Manuals",
    "Design_and_3D": "Design_and_3D",
    "Other": "Other",
    "Junk_Candidates": "Junk_Candidates",
    "Uncertain": "Uncertain",
}

SHORT_FOLDER_NAMES = {
    "Financial": "Finance",
    "Documents": "Docs",
    "Code_and_Scripts": "Code",
    "Data_and_Configs": "Data",
    "Logs_and_Diagnostics": "Logs",
    "Images_and_Graphics": "Images",
    "Audio_and_Music": "Audio",
    "Video_and_Movies": "Videos",
    "Archives_and_Installers": "Archives",
    "Books_and_Manuals": "Books",
    "Design_and_3D": "3D_Design",
    "Other": "Other",
    "Junk_Candidates": "Trash_Candidates",
    "Uncertain": "Unsorted",
}


def load_config() -> dict[str, Any]:
    """Loads configuration from ~/.config/laya/config.json with default fallback."""
    config = {
        "folder_names": dict(DEFAULT_FOLDER_NAMES),
        "ignored_extensions": list(DEFAULT_ACTIVE_DOWNLOAD_EXTS),
        "custom_rules": {},  # ext -> folder_name, e.g. ".torrent": "Torrents"
        "default_confidence": 0.50,
        "auto_confirm": False,
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_conf = json.load(f)
                if isinstance(user_conf, dict):
                    if "folder_names" in user_conf and isinstance(user_conf["folder_names"], dict):
                        config["folder_names"].update(user_conf["folder_names"])
                    if "ignored_extensions" in user_conf and isinstance(user_conf["ignored_extensions"], list):
                        config["ignored_extensions"] = user_conf["ignored_extensions"]
                    if "custom_rules" in user_conf and isinstance(user_conf["custom_rules"], dict):
                        config["custom_rules"].update(user_conf["custom_rules"])
                    if "default_confidence" in user_conf and isinstance(user_conf["default_confidence"], (int, float)):
                        config["default_confidence"] = float(user_conf["default_confidence"])
                    if "auto_confirm" in user_conf:
                        config["auto_confirm"] = bool(user_conf["auto_confirm"])
        except Exception:
            pass
    return config


def save_config(config: dict[str, Any]) -> None:
    """Persists config to ~/.config/laya/config.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def load_history() -> list[dict[str, Any]]:
    """Loads move journal history from ~/.config/laya/history.json."""
    if not HISTORY_FILE.exists():
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("batches", [])
    except Exception:
        return []


def save_history(batches: list[dict[str, Any]]) -> None:
    """Saves move journal history."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump({"batches": batches[-50:]}, f, indent=2)  # retain last 50 batches


def record_batch_moves(batch_id: str, target_dir: str, moves: list[dict[str, str]]) -> None:
    """Appends an executed sorting batch to history for rollback."""
    if not moves:
        return
    batches = load_history()
    batches.append({
        "batch_id": batch_id,
        "timestamp": datetime.datetime.now().isoformat(),
        "target_dir": str(target_dir),
        "count": len(moves),
        "moves": moves,
    })
    save_history(batches)


def rollback_last_batch(batch_id: Optional[str] = None) -> bool:
    """Reverts the last (or specified) sorting transaction batch."""
    batches = load_history()
    if not batches:
        print("No organization history found to roll back.")
        return False

    target_batch = None
    target_idx = -1
    if batch_id:
        for idx, b in enumerate(reversed(batches)):
            if b.get("batch_id") == batch_id:
                target_batch = b
                target_idx = len(batches) - 1 - idx
                break
    else:
        target_batch = batches[-1]
        target_idx = len(batches) - 1

    if not target_batch:
        print(f"Error: Batch '{batch_id}' not found in history.")
        return False

    moves = target_batch.get("moves", [])
    print(f"\nRolling back batch {target_batch.get('batch_id')} ({len(moves)} files)...")

    reverted = 0
    folders_to_clean = set()

    for item in reversed(moves):
        src = Path(item["source"])
        dst = Path(item["dest"])

        if dst.exists():
            try:
                src.parent.mkdir(parents=True, exist_ok=True)
                # If target already exists, resolve collision
                final_src = src
                counter = 1
                while final_src.exists() and final_src != dst:
                    final_src = src.parent / f"{src.stem}_restored{counter}{src.suffix}"
                    counter += 1

                shutil.move(str(dst), str(final_src))
                print(f"  [Restored] {dst.name} -> {final_src.parent}/")
                reverted += 1
                folders_to_clean.add(dst.parent)
            except Exception as e:
                print(f"  [Failed] Could not restore {dst.name}: {e}")
        else:
            print(f"  [Skipped] {dst} no longer exists.")

    # Clean empty category folders if left empty
    for folder in folders_to_clean:
        try:
            if folder.exists() and folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
                print(f"  [Cleaned empty folder] {folder.name}/")
        except Exception:
            pass

    # Remove reverted batch from history
    batches.pop(target_idx)
    save_history(batches)
    print(f"\nRollback complete. Successfully restored {reverted}/{len(moves)} files.")
    return True


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
        return HeuristicRouter(), "heuristic"


def organize_directory(
    target_dir: str,
    output_dir: Optional[str] = None,
    dry_run: bool = False,
    min_confidence: Optional[float] = None,
    config_override: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Organizes files in target_dir into categorized subdirectories with rollback journaling."""
    config = config_override or load_config()
    folder_mapping = config.get("folder_names", DEFAULT_FOLDER_NAMES)
    ignored_exts = tuple(config.get("ignored_extensions", DEFAULT_ACTIVE_DOWNLOAD_EXTS))
    custom_rules = config.get("custom_rules", {})
    confidence_threshold = min_confidence if min_confidence is not None else config.get("default_confidence", 0.50)

    target_path = Path(target_dir).expanduser().resolve()
    if not target_path.exists() or not target_path.is_dir():
        print(f"Error: Target directory '{target_dir}' does not exist.")
        sys.exit(1)

    dest_base = Path(output_dir).expanduser().resolve() if output_dir else target_path

    router, engine_type = get_router()
    questions = get_laya_questions()

    files = [
        f for f in target_path.iterdir()
        if f.is_file() and (not f.name.startswith(".") or f.name.startswith(".~"))
    ]
    if not files:
        print("No files found to organize.")
        return {"count": 0, "stats": {}, "batch_id": None}

    print(f"\nEngine: {engine_type.upper()} | Target: {target_path} | Files: {len(files)}")
    if dry_run:
        print("[MODE: DRY RUN - Simulation only, no files will be moved]\n")
    else:
        print("[MODE: LIVE SORT - Changes tracked for undo/rollback]\n")

    batch_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    stats = {}
    moves_journal = []

    for file_path in files:
        # Check ignored download extensions
        if file_path.name.startswith(".~") or file_path.name.lower().endswith(ignored_exts):
            print(f"  [Skipped] {file_path.name} (active or ignored download)")
            continue

        ext = file_path.suffix.lower()

        # Check user custom extension overrides first
        if ext in custom_rules:
            category_key = custom_rules[ext]
            category_folder = category_key
            confidence = 1.0
            is_junk = False
        else:
            sample_text = extract_file_sample(file_path)
            res = router.predict(sample_text, questions)

            cat_ans = res["answers"]["category"]
            category_key = cat_ans["choice"]
            confidence = cat_ans.get("confidence", 1.0)
            is_junk = res["answers"]["is_temporary_junk"]["noul"] > 0.70

            if confidence < confidence_threshold:
                category_key = "Uncertain"
            if is_junk:
                category_key = "Junk_Candidates"

            category_folder = folder_mapping.get(category_key, category_key)

        target_folder = dest_base / category_folder
        dest_file_path = target_folder / file_path.name

        stats[category_folder] = stats.get(category_folder, 0) + 1
        conf_str = f"conf: {confidence:.2f}" if confidence is not None else "custom rule"
        print(f"  -> [{category_folder}] ({conf_str}) {file_path.name}")

        if not dry_run:
            target_folder.mkdir(parents=True, exist_ok=True)
            counter = 1
            new_target = dest_file_path
            while new_target.exists() and new_target != file_path:
                new_target = target_folder / f"{file_path.stem}_dup{counter}{file_path.suffix}"
                counter += 1
            dest_file_path = new_target

            shutil.move(str(file_path), str(dest_file_path))
            moves_journal.append({
                "source": str(file_path),
                "dest": str(dest_file_path)
            })

    if not dry_run and moves_journal:
        record_batch_moves(batch_id, str(target_path), moves_journal)

    print("\nOrganization Complete:")
    for cat, count in sorted(stats.items()):
        print(f"  * {cat}: {count} file(s)")

    if not dry_run and moves_journal:
        print(f"\nAudit Log: Saved batch ID '{batch_id}'. Run 'laya --undo' anytime to reverse.")

    return {
        "batch_id": batch_id if not dry_run else None,
        "count": len(moves_journal) if not dry_run else len(files),
        "stats": stats,
    }


def get_top_directories() -> list[tuple[str, Path, int]]:
    """Discovers top user directories (Downloads, Desktop, etc.) with file counts."""
    home = Path.home()
    candidates = [
        ("Downloads", home / "Downloads"),
        ("Desktop", home / "Desktop"),
        ("Documents", home / "Documents"),
        ("Pictures", home / "Pictures"),
        ("Videos", home / "Videos"),
        ("Current Directory", Path.cwd()),
    ]
    results = []
    for label, p in candidates:
        if p.exists() and p.is_dir():
            try:
                count = sum(1 for item in p.iterdir() if item.is_file() and not item.name.startswith("."))
            except Exception:
                count = 0
            results.append((label, p, count))
    return results


def interactive_menu():
    """Friendly terminal interface allowing user to choose directory, settings, and undo."""
    config = load_config()

    while True:
        print("\n" + "=" * 54)
        print("          LAYA AUTO FILE ORGANIZER")
        print("       Sub-35ms Local Decision Engine")
        print("=" * 54)
        print(" [1] Sort a Directory (Downloads, Desktop, etc.)")
        print(" [2] Preview Sorting (Dry Run Simulation)")
        print(" [3] Undo / Rollback Last Organization")
        print(" [4] Folder Naming & File Rules Settings")
        print(" [5] View Organization History")
        print(" [6] Exit")
        print("=" * 54)

        try:
            choice = input("Select an option [1-6]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            sys.exit(0)

        if choice in ("1", "2"):
            dry_run = (choice == "2")
            print("\nChoose Target Directory:")
            top_dirs = get_top_directories()
            for idx, (label, p, count) in enumerate(top_dirs, 1):
                print(f" [{idx}] {label:18} ({p}) — {count} file(s)")
            print(f" [{len(top_dirs) + 1}] Custom Path...")
            print(" [0] Back to Main Menu")

            try:
                dir_choice = input(f"Select directory [0-{len(top_dirs) + 1}]: ").strip()
            except (KeyboardInterrupt, EOFError):
                continue

            if dir_choice == "0" or not dir_choice:
                continue

            target_path = None
            if dir_choice.isdigit():
                val = int(dir_choice)
                if 1 <= val <= len(top_dirs):
                    target_path = str(top_dirs[val - 1][1])
                elif val == len(top_dirs) + 1:
                    raw_custom = input("Enter custom folder path: ").strip()
                    if raw_custom:
                        target_path = raw_custom

            if not target_path:
                print("Invalid selection.")
                continue

            organize_directory(target_path, dry_run=dry_run, config_override=config)

        elif choice == "3":
            batches = load_history()
            if not batches:
                print("\nNo previous sorting history found.")
                continue
            last = batches[-1]
            print(f"\nLast batch: {last['batch_id']} ({last['timestamp']})")
            print(f"Directory : {last['target_dir']}")
            print(f"Files     : {last['count']} files moved")
            confirm = input("\nRoll back and restore all files? [y/N]: ").strip().lower()
            if confirm in ("y", "yes"):
                rollback_last_batch()
            else:
                print("Rollback cancelled.")

        elif choice == "4":
            settings_menu(config)

        elif choice == "5":
            batches = load_history()
            if not batches:
                print("\nNo history recorded yet.")
            else:
                print("\nOrganization History (Recent Batches):")
                print("-" * 54)
                for b in reversed(batches[-10:]):
                    print(f" Batch: {b.get('batch_id')} | Time: {b.get('timestamp')}")
                    print(f" Folder: {b.get('target_dir')} | Files: {b.get('count')}")
                    print("-" * 54)

        elif choice == "6":
            print("\nGoodbye!")
            break
        else:
            print("Invalid option. Please choose 1-6.")


def settings_menu(config: dict[str, Any]):
    """Settings submenu to customize folder names, custom extension rules, and ignore lists."""
    while True:
        print("\n" + "=" * 54)
        print("              LAYA SETTINGS")
        print("=" * 54)
        print(" [1] View Current Folder Naming")
        print(" [2] Switch to Short/Clean Folder Names (Docs, Code, Media...)")
        print(" [3] Reset to Standard Folder Names (Documents, Code_and_Scripts...)")
        print(" [4] Add Custom Extension Rule (e.g. .torrent -> Torrents)")
        print(" [5] Adjust Confidence Threshold (Currently: {:.2f})".format(config.get("default_confidence", 0.50)))
        print(" [0] Save & Return to Main Menu")
        print("=" * 54)

        try:
            choice = input("Select setting option [0-5]: ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if choice == "0":
            save_config(config)
            print("Settings saved.")
            break
        elif choice == "1":
            print("\nCurrent Folder Mappings:")
            for k, v in config.get("folder_names", {}).items():
                print(f"  {k:24} -> {v}")
            if config.get("custom_rules"):
                print("\nCustom Extension Rules:")
                for ext, folder in config["custom_rules"].items():
                    print(f"  {ext} -> {folder}")
        elif choice == "2":
            config["folder_names"] = dict(SHORT_FOLDER_NAMES)
            save_config(config)
            print("Switched to clean/short folder naming style.")
        elif choice == "3":
            config["folder_names"] = dict(DEFAULT_FOLDER_NAMES)
            save_config(config)
            print("Reset to standard folder naming style.")
        elif choice == "4":
            ext = input("Enter file extension with dot (e.g. .torrent): ").strip().lower()
            if not ext.startswith("."):
                ext = "." + ext
            target_f = input(f"Enter target folder name for '{ext}': ").strip()
            if target_f:
                config.setdefault("custom_rules", {})[ext] = target_f
                save_config(config)
                print(f"Added rule: {ext} -> {target_f}")
        elif choice == "5":
            try:
                val = float(input("Enter min confidence (0.10 to 0.95): ").strip())
                if 0.05 <= val <= 0.99:
                    config["default_confidence"] = val
                    save_config(config)
                    print(f"Confidence threshold set to {val:.2f}")
                else:
                    print("Value out of valid range.")
            except ValueError:
                print("Invalid number.")


def self_check():
    """Minimal runnable check for Laya organizer and fallback router."""
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
    print(f"Self-check passed: All test samples classified correctly using {engine.upper()} engine!")


def main():
    parser = argparse.ArgumentParser(
        description="Laya Sub-35ms Local File Organizer with Rollback and Interactive Controls"
    )
    parser.add_argument("target_dir", nargs="?", default=None, help="Directory to organize (default: interactive menu or current dir)")
    parser.add_argument("-o", "--output-dir", help="Destination base folder (default: inside target_dir)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate organization without moving files")
    parser.add_argument("--confidence", type=float, default=None, help="Min confidence threshold (default: 0.50)")
    parser.add_argument("--undo", "--rollback", dest="rollback", action="store_true", help="Undo last file organization batch")
    parser.add_argument("--batch-id", help="Specific batch ID to undo (used with --undo)")
    parser.add_argument("--history", action="store_true", help="Show recent organization history")
    parser.add_argument("--config", action="store_true", help="Open interactive settings menu")
    parser.add_argument("--check", action="store_true", help="Run self-check validation")

    args = parser.parse_args()

    if args.check:
        self_check()
    elif args.rollback:
        rollback_last_batch(args.batch_id)
    elif args.history:
        batches = load_history()
        if not batches:
            print("No organization history recorded.")
        else:
            print("\nRecent Organization Batches:")
            for b in reversed(batches[-10:]):
                print(f"  [{b.get('batch_id')}] {b.get('timestamp')} - {b.get('count')} file(s) in {b.get('target_dir')}")
    elif args.config:
        settings_menu(load_config())
    elif args.target_dir is not None:
        organize_directory(args.target_dir, args.output_dir, dry_run=args.dry_run, min_confidence=args.confidence)
    else:
        # If run with no arguments in a terminal, launch interactive menu
        if sys.stdin.isatty():
            interactive_menu()
        else:
            organize_directory(".", args.output_dir, dry_run=args.dry_run, min_confidence=args.confidence)


if __name__ == "__main__":
    main()
