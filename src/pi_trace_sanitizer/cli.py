"""CLI entry point for pi-trace-sanitizer."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import click
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from .config import DEFAULT_MODEL_PATH, DEFAULT_SERVER_PORT
from .detector import ServerDetector
from .entity_map import EntityMap
from .sanitizer import (
    Detection,
    EventDone,
    EventStart,
    FieldDone,
    FieldStart,
    ProgressEvent,
    ReplaceStart,
    SessionDone,
    SessionStart,
    sanitize_session,
)

console = Console(stderr=True)

MAX_ENTITY_DISPLAY_LEN = 48


def _truncate(s: str, max_len: int = MAX_ENTITY_DISPLAY_LEN) -> str:
    return s if len(s) <= max_len else s[:max_len - 3] + "..."


def _server_healthy(port: int = DEFAULT_SERVER_PORT) -> bool:
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/v1/models", timeout=3) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


# ── Rich TUI display ─────────────────────────────────────────────────────────

class LiveDisplay:
    """Rich Live display that reacts to sanitizer progress events."""

    def __init__(self, live: Live) -> None:
        self._live = live
        self._file = ""
        self._total_events = 0
        self._event_idx = 0
        self._event_id = ""
        self._event_type = ""
        self._field_path = ""
        self._field_status = ""
        self._detections: list[tuple[str, str, str]] = []
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=30),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        )
        self._event_task = self._progress.add_task("Events", total=1)

    def _build(self) -> Group:
        status_parts = []
        if self._event_type:
            status_parts.append(
                f"Event [bold]{self._event_idx + 1}[/]/{self._total_events}  "
                f"[dim]{self._event_id}[/] ([cyan]{self._event_type}[/])"
            )
        if self._field_path:
            status_parts.append(f"Field: [yellow]{self._field_path}[/]  {self._field_status}")

        status_text = "\n".join(status_parts) if status_parts else "[dim]Starting...[/]"
        status_panel = Panel(
            status_text,
            title=f"[bold]{self._file}[/]",
            border_style="blue",
            padding=(0, 1),
        )

        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1), expand=True)
        table.add_column("Type", style="green", width=14)
        table.add_column("Entity", style="white", ratio=2)
        table.add_column("Placeholder", style="cyan", ratio=1)

        for etype, etext, placeholder in self._detections[-15:]:
            table.add_row(etype, _truncate(etext), placeholder)
        if len(self._detections) > 15:
            table.add_row("", f"[dim]... {len(self._detections) - 15} more above[/]", "")

        detection_panel = Panel(
            table if self._detections else Text("No detections yet", style="dim"),
            title=f"[bold]Detections ({len(self._detections)})[/]",
            border_style="green" if self._detections else "dim",
            padding=(0, 0),
        )

        return Group(status_panel, detection_panel, self._progress)

    def handle(self, event: ProgressEvent) -> None:
        if isinstance(event, SessionStart):
            self._file = event.file
            self._total_events = event.total_events
            self._progress.update(self._event_task, total=event.total_events, description="Events")
        elif isinstance(event, EventStart):
            self._event_idx = event.index
            self._event_id = event.event_id
            self._event_type = event.event_type
            self._field_path = ""
            self._field_status = "[dim]skip[/]" if event.scannable_fields == 0 else ""
        elif isinstance(event, FieldStart):
            self._field_path = event.json_path
            chunks = f" ({event.chunks} chunks)" if event.chunks > 1 else ""
            self._field_status = f"[dim]{event.text_length} chars{chunks}[/]  ⠋ scanning..."
        elif isinstance(event, Detection):
            self._detections.append((event.entity_type, event.entity_text, event.placeholder))
        elif isinstance(event, FieldDone):
            self._field_status = f"[dim]{event.elapsed:.1f}s  {event.detections} found[/]"
        elif isinstance(event, EventDone):
            self._progress.update(self._event_task, completed=event.index + 1)
        elif isinstance(event, ReplaceStart):
            self._field_path = ""
            self._field_status = (
                f"[bold]Replacing {event.unique_entities} entities "
                f"across {event.total_events} events[/]"
            )
        elif isinstance(event, SessionDone):
            self._progress.update(self._event_task, completed=self._total_events)

        self._live.update(self._build())


class QuietDisplay:
    """Minimal output — only print detections as they happen."""

    def handle(self, event: ProgressEvent) -> None:
        if isinstance(event, Detection):
            console.print(
                f"  [green]{event.entity_type}[/]: {_truncate(event.entity_text)!r} → "
                f"[cyan]{event.placeholder}[/]"
            )


# ── CLI ───────────────────────────────────────────────────────────────────────

class SanitizerCLI(click.Group):
    """Treats the first non-option arg as a path if it's not a known command."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if args and not args[0].startswith("-") and args[0] not in self.commands:
            args = ["sanitize"] + args
        return super().parse_args(ctx, args)


@click.group(cls=SanitizerCLI)
def main() -> None:
    """Sanitize pi coding agent session traces using local LLM PII detection.

    \b
    Start the server:
      pi-trace-sanitizer server --model models/NVFP4

    \b
    Sanitize traces:
      pi-trace-sanitizer <session-dir>
      pi-trace-sanitizer path/to/file.jsonl
    """


@main.command()
@click.option("--model", default=DEFAULT_MODEL_PATH, help="Path or HF repo ID of the MLX model.")
@click.option("--port", default=DEFAULT_SERVER_PORT, type=int, help=f"Port (default: {DEFAULT_SERVER_PORT}).")
def server(model: str, port: int) -> None:
    """Start the MLX model server (or report health if already running)."""
    if _server_healthy(port):
        console.print(f"[bold green]Server already running[/] at http://localhost:{port}")
        return

    console.print(f"Starting model server on port {port}...")
    console.print(f"Model: [bold]{model}[/]")

    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "mlx_lm", "server", "--model", model, "--port", str(port)],
            stdout=sys.stderr,
            stderr=sys.stderr,
        )
    except FileNotFoundError:
        console.print("[red]mlx_lm not found. Install it: pip install mlx-lm[/]")
        raise SystemExit(1)

    for _ in range(120):
        time.sleep(1)
        if _server_healthy(port):
            console.print(f"\n[bold green]Server ready[/] at http://localhost:{port}  (pid {proc.pid})")
            console.print("[dim]Leave this running. In another terminal:[/]")
            console.print(f"  [bold]pi-trace-sanitizer <session-dir>[/]")
            try:
                proc.wait()
            except KeyboardInterrupt:
                console.print("\n[dim]Shutting down...[/]")
                proc.terminate()
                proc.wait(timeout=5)
            return

        if proc.poll() is not None:
            console.print(f"[red]Server exited with code {proc.returncode}[/]")
            raise SystemExit(1)

    console.print("[red]Server failed to start within 120s[/]")
    proc.terminate()
    raise SystemExit(1)


@main.command(name="sanitize", hidden=True)
@click.argument("session_dir", type=click.Path(exists=True))
@click.option("-o", "--output-dir", default=None, type=click.Path(), help="Output directory.")
@click.option("--port", default=DEFAULT_SERVER_PORT, type=int, help=f"Server port (default: {DEFAULT_SERVER_PORT}).")
@click.option("--entity-map", "entity_map_path", default=None, type=click.Path(), help="Persist entity map.")
@click.option("--dry-run", is_flag=True, help="Report entities without writing output.")
@click.option("--no-thinking", is_flag=True, help="Disable thinking mode (faster, lower quality).")
@click.option("-q", "--quiet", is_flag=True, help="Minimal output.")
def sanitize_cmd(
    session_dir: str,
    output_dir: str | None,
    port: int,
    entity_map_path: str | None,
    dry_run: bool,
    no_thinking: bool,
    quiet: bool,
) -> None:
    """Sanitize session traces."""
    session_path = Path(session_dir)
    if session_path.is_dir():
        inputs = sorted(session_path.glob("*.jsonl"))
        if not inputs:
            console.print(f"[red]No .jsonl files found in {session_dir}[/]")
            raise SystemExit(1)
    else:
        inputs = [session_path]

    if output_dir is None:
        parent = session_path if session_path.is_dir() else session_path.parent
        output_dir = str(parent / "sanitized")

    if not _server_healthy(port):
        console.print(
            f"[red]Server not running at http://localhost:{port}[/]\n"
            f"Start it first:  [bold]pi-trace-sanitizer server[/]"
        )
        raise SystemExit(1)

    server_url = f"http://localhost:{port}"
    entity_map = EntityMap()
    if entity_map_path and Path(entity_map_path).exists():
        entity_map = EntityMap.load(entity_map_path)
        console.print(f"Loaded entity map with {len(entity_map)} entries", style="dim")

    detector = ServerDetector(server_url, thinking=not no_thinking)
    detector.load()

    summaries = []
    for input_path in inputs:
        name = input_path.name
        output_path = Path(output_dir) / name

        if quiet:
            display = QuietDisplay()
            console.print(f"\n[bold]Processing:[/] {name}")
            summary = sanitize_session(
                input_path, output_path, detector, entity_map,
                dry_run=dry_run, on_progress=display.handle,
            )
        else:
            with Live(console=console, refresh_per_second=8, transient=False) as live:
                display = LiveDisplay(live)
                summary = sanitize_session(
                    input_path, output_path, detector, entity_map,
                    dry_run=dry_run, on_progress=display.handle,
                )

        summaries.append(summary)
        console.print(
            f"  [bold]{summary['events']}[/] events, "
            f"[bold]{summary['fields_scanned']}[/] fields, "
            f"[bold]{summary['entities_found']}[/] entities "
            f"([bold]{summary['unique_entities']}[/] unique)"
        )

    if entity_map_path:
        entity_map.save(entity_map_path)
        console.print(f"\nSaved entity map ({len(entity_map)} entries) → {entity_map_path}", style="dim")

    if not dry_run:
        console.print(f"\nSanitized files → [bold]{output_dir}/[/]")

    total = sum(s["entities_found"] for s in summaries)
    console.print(f"\n[bold green]Done.[/] Total entities: {total}")


if __name__ == "__main__":
    main()
