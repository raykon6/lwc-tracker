"""Command line interface: validate a roster, check it from the terminal, or start the web app."""
from __future__ import annotations

import argparse
import logging
import os
import secrets
import sys
import threading
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table

from .config import ConfigError, load_settings
from .engine import Status, StudentResult, Verifier
from .export import to_csv, to_json
from .roster import RosterError, load_roster

console = Console()
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

STATUS_LABEL = {
    Status.COMPLETED: "Completed",
    Status.IN_PROGRESS: "In progress",
    Status.NOT_STARTED: "Not started",
    Status.INVALID_URL: "Invalid link",
    Status.NOT_FOUND: "Not found",
    Status.FETCH_ERROR: "Fetch error",
    Status.PARSE_ERROR: "Unreadable page",
    Status.CANCELLED: "Cancelled",
}


def _read_roster(path: str, settings):
    p = Path(path)
    if not p.is_file():
        raise RosterError(f"File not found: {path}")
    if p.stat().st_size > settings.limits.max_upload_bytes:
        raise RosterError(f"{p.name} is larger than the configured limit.")
    return load_roster(p.read_bytes(), settings.limits.max_upload_bytes, settings.limits.max_rows)


def cmd_validate(args, settings) -> int:
    roster = _read_roster(args.csv, settings)
    s = roster.summary()
    console.print(f"[bold]{s['total']}[/] rows · {s['valid']} valid · {s['invalid']} invalid · "
                  f"{s['duplicates']} duplicate · {s['unique_profiles']} unique profiles")
    console.print(f"Detected columns: {s['columns']}")
    for w in s["warnings"]:
        console.print(f"[yellow]note[/] {w}")
    for r in roster.rows:
        if r.error:
            console.print(f"  row {r.row}: {r.error}", markup=False)
        elif r.duplicate_of is not None:
            console.print(f"  row {r.row}: same profile as row {r.duplicate_of}", markup=False)
    return 0 if s["invalid"] == 0 else 1


def cmd_check(args, settings) -> int:
    roster = _read_roster(args.csv, settings)
    verifier = Verifier(settings)
    results: list[StudentResult] = []
    cancel = threading.Event()

    with Progress(TextColumn("[bold]Verifying"), BarColumn(), MofNCompleteColumn(), TimeRemainingColumn(),
                  console=console, transient=True) as progress:
        task = progress.add_task("verify", total=len(roster.rows))

        def on_result(r: StudentResult) -> None:
            results.append(r)
            progress.advance(task)

        try:
            verifier.run(roster, on_result, cancel, force_refresh=True)
        except KeyboardInterrupt:
            cancel.set()
            console.print("Cancelled.")

    req = settings.campaign.required_count
    table = Table(title=f"{settings.campaign.name}: {req} badges required", header_style="bold")
    for col in ("Row", "Name", "Badges", "Status", "Notes"):
        table.add_column(col, overflow="fold")
    for r in sorted(results, key=lambda x: x.row):
        notes = r.error or ", ".join(r.flags)
        table.add_row(str(r.row), r.name or r.display_name or "-", f"{r.badge_count}/{req}",
                      STATUS_LABEL[r.status], notes)
    console.print(table)

    counts: dict[str, int] = {}
    for r in results:
        counts[STATUS_LABEL[r.status]] = counts.get(STATUS_LABEL[r.status], 0) + 1
    console.print("  ".join(f"[bold]{v}[/] {k}" for k, v in counts.items()))

    dicts = [r.to_dict() for r in results]
    if args.out:
        Path(args.out).write_text(to_csv(dicts), encoding="utf-8", newline="")
        console.print(f"Saved CSV to {args.out}", markup=False)
    if args.json:
        Path(args.json).write_text(to_json(dicts, {"campaign": settings.campaign.name}), encoding="utf-8")
        console.print(f"Saved JSON to {args.json}", markup=False)
    failed = sum(1 for r in results if r.status in (Status.FETCH_ERROR, Status.PARSE_ERROR))
    return 3 if failed else 0


def cmd_serve(args, settings) -> int:
    import uvicorn

    from .web.app import create_app

    token = os.environ.get("VERITY_ACCESS_TOKEN") or None
    if args.host not in LOCAL_HOSTS and not token:
        token = secrets.token_urlsafe(24)
        console.print("[bold]Listening beyond localhost, so an access token is required.[/]")
        console.print(f"Access token for this session: {token}", markup=False)
    # On Render the public hostname arrives in RENDER_EXTERNAL_HOSTNAME.
    public_name = args.public_name or os.environ.get("VERITY_PUBLIC_NAME") or os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    hosts = ["127.0.0.1", "localhost", "[::1]"] + ([public_name] if public_name else [])
    if args.host not in LOCAL_HOSTS and not public_name:
        hosts.append(args.host)
    # Behind a platform proxy (Render) the real client IP is in X-Forwarded-For. Only trust it
    # when told to, because on a directly exposed server that header can be forged.
    trust_proxy = os.environ.get("VERITY_TRUST_PROXY") == "1"
    verifier = None
    if args.demo:
        from .demo import DemoTransport
        from .fetcher import ProfileFetcher

        verifier = Verifier(settings, fetcher=ProfileFetcher(settings.http, transport=DemoTransport(settings)))
        console.print("[bold]Demo mode:[/] profiles are synthetic and no requests leave this machine.")
    app = create_app(settings, access_token=token, allowed_hosts=hosts, verifier=verifier, demo=args.demo)
    shown = public_name and f"https://{public_name}" or f"http://{'127.0.0.1' if args.host in LOCAL_HOSTS else args.host}:{args.port}"
    console.print(f"Verity is running at {shown}", markup=False)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", server_header=False,
                proxy_headers=trust_proxy, forwarded_allow_ips="*" if trust_proxy else None, limit_concurrency=64, timeout_keep_alive=5)
    return 0


def cmd_demo_roster(args, settings) -> int:
    from .demo import demo_roster_csv

    Path(args.out).write_text(demo_roster_csv(), encoding="utf-8")
    console.print(f"Wrote {args.out}", markup=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="verity", description="Learn With Communities skill badge tracker")
    parser.add_argument("--config", help="Path to campaign.toml (default: project root)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show retry and warning logs")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="Check a roster CSV without contacting any website")
    p.add_argument("csv")

    p = sub.add_parser("check", help="Verify every profile in a roster CSV")
    p.add_argument("csv")
    p.add_argument("-o", "--out", help="Write results to this CSV file")
    p.add_argument("--json", help="Write results to this JSON file")

    p = sub.add_parser("serve", help="Start the web dashboard")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    p.add_argument("--public-name", help="Host name clients will use, when serving beyond localhost")
    p.add_argument("--demo", action="store_true", help="Serve synthetic profiles (offline demo, no network)")

    p = sub.add_parser("demo-roster", help="Write a sample roster that matches --demo profiles")
    p.add_argument("out")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = load_settings(args.config)
        commands = {"validate": cmd_validate, "check": cmd_check, "serve": cmd_serve, "demo-roster": cmd_demo_roster}
        return commands[args.command](args, settings)
    except (ConfigError, RosterError) as exc:
        console.print(f"[bold]Error:[/] {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
