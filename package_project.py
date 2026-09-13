"""
Project Packaging Script for Hackathon Submission / Production Archive
Excludes heavy temporary directories (node_modules, __pycache__, .pytest_cache, virtualenvs)
Produces a clean, ultra-lightweight zip archive (< 1 MB compressed).
"""

import os
import sys
import zipfile

OUTPUT_ZIP = "delhi_ncr_aqi_project.zip"

EXCLUDED_DIRS = {
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "env",
    ".git",
    ".vscode",
    ".idea",
    ".claude",
    ".gemini",
    ".npm",
    ".vite",
    ".turbo",
    ".next",
    "coverage",
    "htmlcov",
}

EXCLUDED_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".zip",
    ".log",
    ".tmp",
    ".bak",
    ".swp",
}

EXCLUDED_FILES = {
    OUTPUT_ZIP,
    "delhi_ncr_aqi_project_clean.zip",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
}

def create_package():
    root_dir = os.path.dirname(os.path.abspath(__file__))
    zip_path = os.path.join(root_dir, OUTPUT_ZIP)

    if os.path.exists(zip_path):
        try:
            os.remove(zip_path)
        except Exception:
            pass

    print(f"[PACKAGING] Processing project from: {root_dir}")
    file_count = 0

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
        for root, dirs, files in os.walk(root_dir):
            # Prune excluded directories in-place
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith(".")]

            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in EXCLUDED_EXTENSIONS or file in EXCLUDED_FILES or file.startswith(".DS_Store"):
                    continue

                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, root_dir)
                zipf.write(full_path, rel_path)
                file_count += 1

    size_bytes = os.path.getsize(zip_path)
    size_mb = size_bytes / (1024 * 1024)
    size_kb = size_bytes / 1024
    print(f"[SUCCESS] Created ultra-lightweight archive: {OUTPUT_ZIP}")
    print(f"[INFO] Total clean files included: {file_count}")
    print(f"[INFO] Final archive size: {size_mb:.2f} MB ({size_kb:.1f} KB)")

if __name__ == "__main__":
    create_package()
