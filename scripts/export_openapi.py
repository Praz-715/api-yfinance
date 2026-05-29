"""Generate the OpenAPI specification to ``docs/openapi.json``.

Run from the project root:

    python scripts/export_openapi.py

The schema is produced from the live FastAPI application, so it always reflects
the current routes, parameters, and response models. ``ENVIRONMENT`` is forced to
``development`` for generation so the full route set is described (production
disables the interactive docs endpoints, but the schema content is identical).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Ensure the project root is importable and configure a generation-safe env.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("API_KEYS", "generation-only-key")
os.environ.setdefault("JWT_SECRET", "generation-only-secret-0123456789abcdef0123456789")

from app.main import create_app  # noqa: E402


def main() -> None:
    app = create_app()
    schema = app.openapi()

    docs_dir = ROOT / "docs"
    docs_dir.mkdir(exist_ok=True)
    output = docs_dir / "openapi.json"
    output.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    paths = schema.get("paths", {})
    operations = sum(len(methods) for methods in paths.values())
    print(f"Wrote {output.relative_to(ROOT)}")
    print(f"  OpenAPI version: {schema.get('openapi')}")
    print(f"  Title:           {schema['info']['title']} v{schema['info']['version']}")
    print(f"  Paths:           {len(paths)}")
    print(f"  Operations:      {operations}")


if __name__ == "__main__":
    main()
