import json
import gzip
import sys
from pathlib import Path

def build_snapshot(report_path: str, output_path: str, base_dir: str = "."):
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    warnings = report.get("warnings", report if isinstance(report, list) else [])
    file_paths = set()

    for w in warnings:
        # Modern format
        for pos in w.get("positions", []):
            fp = pos.get("file", "")
            if fp and not fp.startswith("__analysis__"):
                file_paths.add(fp)
        # Legacy fallback
        fp = w.get("fileName", "")
        if fp:
            file_paths.add(fp)

    snapshot = {}
    base = Path(base_dir).resolve()

    for rel_path in file_paths:
        full_path = base / rel_path
        if full_path.exists() and full_path.is_file():
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
                snapshot[rel_path.replace("\\", "/")] = content
            except Exception as e:
                print(f"⚠️ Failed to read {rel_path}: {e}", file=sys.stderr)

    with gzip.open(output_path, "wt", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False)

    print(f"✅ Snapshot created: {output_path} ({len(snapshot)} files)")

if __name__ == "__main__":
    # Usage: python pvs_snapshot.py report.json snapshot.json.gz C:\workspace\src
    if len(sys.argv) < 3:
        print("Usage: python pvs_snapshot.py <report.json> <output.json.gz> [base_dir]")
        sys.exit(1)
    build_snapshot(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ".")
