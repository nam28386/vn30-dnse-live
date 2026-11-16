"""Tạo gói source cục bộ, không kèm .env, dữ liệu, cache hoặc .git."""

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED = {
    ".git",
    ".venv",
    ".data",
    "artifacts",
    "node_modules",
    "dist",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".cache",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT.parent / "vn30-dnse-live-local.zip")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Tệp đích đã tồn tại; chọn --output khác để tránh ghi đè.")
    files = [
        ROOT / ".env.example",
        ROOT / ".gitignore",
        ROOT / "AGENTS.md",
        ROOT / "NOTICE",
        ROOT / "README.md",
        ROOT / "LOCAL_RUN_VI.md",
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
    ]
    for folder in ("backend", "frontend", "docs", "scripts"):
        files.extend((ROOT / folder).rglob("*"))
    with zipfile.ZipFile(args.output, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            relative = path.relative_to(ROOT)
            if (
                not path.is_file()
                or path.is_symlink()
                or any(part in EXCLUDED for part in relative.parts)
                or path.name == ".env"
                or path.name.startswith(".env.")
                and path.name != ".env.example"
                or path.suffix in {".pyc", ".tsbuildinfo"}
            ):
                continue
            archive.write(path, Path("vn30-dnse-live") / relative)
    print("Đã tạo gói source cục bộ:", args.output)


if __name__ == "__main__":
    main()
