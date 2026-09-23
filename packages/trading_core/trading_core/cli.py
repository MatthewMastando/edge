"""``trading-core`` command line: fixture generation and verification."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from trading_core.fixtures.generator import (
    DEFAULT_SEED,
    DEFAULT_SESSION_DAYS,
    DEFAULT_START_DATE,
    generate_fixtures,
    verify_fixtures,
)
from trading_core.fixtures.manifest import read_manifest
from trading_core.fixtures.spec import DEFAULT_FIXTURES_DIR

app = typer.Typer(no_args_is_help=True, help="Trading Research Workspace core tooling.")
fixtures_app = typer.Typer(no_args_is_help=True, help="Deterministic fixture data.")
app.add_typer(fixtures_app, name="fixtures")

DEFAULT_OUTPUT_DIR = DEFAULT_FIXTURES_DIR / "generated"

OutputOption = Annotated[
    Path, typer.Option("--out", help="Directory for Parquet files and manifest.json")
]
FixturesDirOption = Annotated[
    Path, typer.Option("--fixtures-dir", help="Directory holding contracts/ and session_calendars/")
]


@fixtures_app.command("generate")
def fixtures_generate(
    out: OutputOption = DEFAULT_OUTPUT_DIR,
    fixtures_dir: FixturesDirOption = DEFAULT_FIXTURES_DIR,
    seed: Annotated[int, typer.Option(min=0, help="Deterministic seed.")] = DEFAULT_SEED,
    days: Annotated[
        int, typer.Option(min=1, help="Number of session days.")
    ] = DEFAULT_SESSION_DAYS,
    start: Annotated[
        str, typer.Option(help="First session date (YYYY-MM-DD).")
    ] = DEFAULT_START_DATE.isoformat(),
) -> None:
    """Generate labeled fixture bars and trades as Parquet plus a manifest."""
    manifest = generate_fixtures(
        output_dir=out,
        fixtures_dir=fixtures_dir,
        seed=seed,
        start=date.fromisoformat(start),
        session_days=days,
    )
    typer.echo(f"data_revision: {manifest.data_revision}")
    typer.echo(f"as_of:         {manifest.as_of.isoformat()}")
    for snapshot in manifest.snapshots:
        typer.echo(
            f"  {snapshot.storage_key:<30} rows={snapshot.row_count:>7} "
            f"sha256={snapshot.content_hash[:12]}"
        )
    typer.echo(f"manifest:      {out / 'manifest.json'}")
    typer.echo("label:         FIXTURE DATA - synthetic, not market data")


@fixtures_app.command("verify")
def fixtures_verify(out: OutputOption = DEFAULT_OUTPUT_DIR) -> None:
    """Re-hash generated Parquet files against manifest.json."""
    problems = verify_fixtures(out)
    if problems:
        for problem in problems:
            typer.echo(f"FAIL {problem}", err=True)
        raise typer.Exit(code=1)
    manifest = read_manifest(out)
    typer.echo(f"OK {len(manifest.snapshots)} snapshots match {manifest.data_revision}")


@fixtures_app.command("show")
def fixtures_show(out: OutputOption = DEFAULT_OUTPUT_DIR) -> None:
    """Print the manifest summary."""
    manifest = read_manifest(out)
    typer.echo(f"data_revision: {manifest.data_revision} (seed {manifest.seed})")
    typer.echo(f"sessions:      {manifest.session_days} from {manifest.start_date}")
    typer.echo(f"as_of:         {manifest.as_of.isoformat()}")
    for contract in manifest.futures_contracts:
        typer.echo(
            f"  {contract.contract_code:<6} {contract.exchange:<6} exp {contract.expiry_date} "
            f"tick {contract.tick_size}={contract.tick_value} x{contract.point_multiplier} "
            f"{contract.settlement_type}"
        )
    for instrument in manifest.instruments:
        if instrument.asset_class != "futures":
            typer.echo(f"  {instrument.symbol:<8} {instrument.venue:<8} {instrument.asset_class}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
