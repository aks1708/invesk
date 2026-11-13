"""Terminal-only report colors; report artifacts remain plain Markdown."""

from __future__ import annotations

from typing import TextIO

from colorama import AnsiToWin32, Fore, Style

_SECTION_COLORS = {
    "Company insights": Fore.RED,
    "Sector insights": Fore.BLUE,
    "Snapshot": Fore.LIGHTMAGENTA_EX,
    "Financial health": Fore.LIGHTMAGENTA_EX,
    "Sources": Fore.YELLOW,
}


def colorize_report(report: str) -> str:
    """Apply section colors to report lines, preserving Markdown and newlines."""
    colored_lines: list[str] = []
    active_color: str | None = None

    for line in report.splitlines(keepends=True):
        heading = line.rstrip("\r\n")
        if heading.startswith("## "):
            active_color = _SECTION_COLORS.get(heading[3:])

        if active_color and heading:
            colored_lines.append(f"{active_color}{line}{Style.RESET_ALL}")
        else:
            colored_lines.append(line)

    return "".join(colored_lines)


def write_terminal_report(report: str, stream: TextIO) -> None:
    """Write colors only to an interactive terminal; otherwise write plain text."""
    is_terminal = getattr(stream, "isatty", lambda: False)()
    if not is_terminal:
        stream.write(report)
        return

    # AnsiToWin32 converts Colorama's ANSI sequences on Windows and passes them
    # through on terminals that already understand ANSI.
    terminal_stream = AnsiToWin32(stream, strip=False).stream
    terminal_stream.write(colorize_report(report))
