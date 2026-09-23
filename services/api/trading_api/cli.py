"""``trading-api`` command line: serve the API or export the OpenAPI document."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from trading_api.main import create_app
from trading_api.openapi_schema import openapi_json
from trading_api.settings import get_settings


def export_openapi(out: Path | None) -> str:
    document = openapi_json(create_app())
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(document, encoding="utf-8")
    return document


def serve(reload: bool) -> None:
    import uvicorn  # noqa: PLC0415 - keep server deps out of the export path

    settings = get_settings()
    uvicorn.run(
        "trading_api.main:app",
        host=settings.host,
        port=settings.port,
        reload=reload,
        log_level=settings.log_level.lower(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trading-api")
    sub = parser.add_subparsers(dest="command", required=True)
    serve_parser = sub.add_parser("serve", help="run the API with uvicorn")
    serve_parser.add_argument("--reload", action="store_true")
    export_parser = sub.add_parser("export-openapi", help="write openapi.json")
    export_parser.add_argument(
        "--out", type=Path, default=None, help="file path; stdout if omitted"
    )
    args = parser.parse_args(argv)

    if args.command == "serve":
        serve(reload=bool(args.reload))
        return 0
    document = export_openapi(args.out)
    if args.out is None:
        sys.stdout.write(document)
    else:
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
