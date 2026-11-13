"""Terminal-only report colors; report artifacts remain plain Markdown."""

from __future__ import annotations

import re
from typing import TextIO

from colorama import AnsiToWin32, Fore, Style

_SECTION_COLORS = {
    "Company insights": Fore.RED,
    "Sector insights": Fore.BLUE,
    "Snapshot": Fore.LIGHTMAGENTA_EX,
    "Financial health": Fore.LIGHTMAGENTA_EX,
    "Sources": Fore.YELLOW,
}

#: Markdown links in the report, e.g. the Sources entries `[title](url)`.
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")

#: OSC 8 hyperlink wrappers: only the title shows, the URL stays embedded.
_OSC8_OPEN = "\x1b]8;;{url}\x1b\\"
_OSC8_CLOSE = "\x1b]8;;\x1b\\"
#: Underline the link title so it reads as clickable text.
_UNDERLINE = "\x1b[4m"
_UNDERLINE_OFF = "\x1b[24m"


def _hide_link_urls(line: str) -> str:
    """Markdown link → terminal hyperlink showing only the underlined title.

    Terminals that understand OSC 8 render the title as a clickable, underlined
    link without printing the URL; unsupported terminals ignore the sequence.
    """
    return _MD_LINK_RE.sub(
        lambda match: f"{_OSC8_OPEN.format(url=match.group(2))}"
        f"{_UNDERLINE}{match.group(1)}{_UNDERLINE_OFF}{_OSC8_CLOSE}",
        line,
    )


def colorize_report(report: str) -> str:
    """Apply section colors to report lines, preserving Markdown and newlines."""
    colored_lines: list[str] = []
    active_color: str | None = None

    for line in report.splitlines(keepends=True):
        heading = line.rstrip("\r\n")
        if heading.startswith("## "):
            active_color = _SECTION_COLORS.get(heading[3:])

        content = _hide_link_urls(line)
        if active_color and heading:
            colored_lines.append(f"{active_color}{content}{Style.RESET_ALL}")
        else:
            colored_lines.append(content)

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
