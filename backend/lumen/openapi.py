"""Print the OpenAPI document (used by ``npm run gen:api`` in desktop/)."""

from __future__ import annotations

import json
import sys

from lumen.app import create_app
from lumen.core.config import Settings


def main() -> None:
    app = create_app(Settings(log_to_file=False), token="unused")
    sys.stdout.write(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
