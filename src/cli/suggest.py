"""FR1 input UX: fund-name suggestions backed by Yahoo search.

The suggester maps a typed prefix to fund names only (the same Yahoo search
the extraction stage uses, filtered to fund quote types and deduplicated).
Yahoo returns some fund quotes with the ticker in `shortname` (for example
`0P00017EQ6.L`), so the name is taken from `longname` first and any
symbol-shaped candidate is skipped. The interactive prompt reads the
terminal in raw mode and redraws the suggestion list on every keystroke; it
falls back to the plain line prompt whenever stdin is not a tty (tests,
pipes) so those runs never touch third-party imports or the network (P3).
Empty input still exits 2 before any Yahoo call.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable

from src.cli.config import UsageError
from src.extraction.profile import FUND_QUOTE_TYPES

#: Minimum typed characters before Yahoo is asked for suggestions.
MIN_QUERY_LEN = 2
#: Suggestions shown at once.
MAX_SUGGESTIONS = 6

Suggester = Callable[[str], list[str]]

#: Ticker charset: no whitespace, no lowercase (e.g. `0P00017EQ6.L`).
_SYMBOL_LIKE_RE = re.compile(r"[A-Z0-9][A-Z0-9.+\-^=]{0,11}\Z")


def _symbol_like(name: str, symbol: str) -> bool:
    """True when the candidate name is a ticker rather than a fund name."""
    if name == symbol:
        return True
    return bool(_SYMBOL_LIKE_RE.fullmatch(name)) and (
        any(char.isdigit() for char in name) or "." in name
    )


def _fund_name(quote: dict) -> str | None:
    """One Yahoo quote → its fund name, or None when it is not a fund.

    Candidates are tried in `longname`, `shortname` order; a candidate equal
    to the quote symbol or shaped like a ticker is skipped, so the returned
    suggestion is always a fund name (or None, which drops the quote).
    """
    if str(quote.get("quoteType") or "").upper() not in FUND_QUOTE_TYPES:
        return None
    symbol = str(quote.get("symbol") or "").strip()
    for field in ("longname", "shortname"):
        name = re.sub(r"\s+", " ", str(quote.get(field) or "")).strip()
        if name and not _symbol_like(name, symbol):
            return name
    return None


def yf_suggester(yf: object) -> Suggester:
    """Yahoo search → fund names only, in Yahoo's relevance order."""

    def suggest(query: str) -> list[str]:
        quotes = yf.Search(query, max_results=8).quotes or []  # type: ignore[attr-defined]
        names: list[str] = []
        for quote in quotes:
            name = _fund_name(quote)
            if name and name not in names:
                names.append(name)
        return names

    return suggest


def cached_suggester(upstream: Suggester) -> Suggester:
    """Memoize exact queries so editing text does not refetch prefixes."""
    cache: dict[str, list[str]] = {}

    def suggest(query: str) -> list[str]:
        if query not in cache:
            try:
                cache[query] = list(upstream(query))
            except Exception:
                cache[query] = []  # suggestions are best-effort, never fatal
        return cache[query]

    return suggest


#: ANSI light-blue for suggestion text.
LIGHT_BLUE = "\x1b[94m"
#: ANSI light-green for the typed query.
LIGHT_GREEN = "\x1b[92m"
#: Bold, for the currently selected suggestion.
BOLD = "\x1b[1m"
RESET = "\x1b[0m"


#: Dim hint shown under the suggestion list.
HINT = f"\x1b[2m  Tab: cycle suggestions · Enter: confirm{RESET}"


def _render(stdout, query: str, suggestions: list[str], selected: int) -> None:
    """Draw the prompt line plus the suggestion list and hint below it."""
    rows: list[str] = []
    if suggestions:
        for index, name in enumerate(suggestions):
            marker = "> " if index == selected else "  "
            color = f"{BOLD}{LIGHT_BLUE}" if index == selected else LIGHT_BLUE
            rows.append(f"  {marker}{color}{name}{RESET}")
    elif len(query.strip()) >= MIN_QUERY_LEN:
        rows.append("  (no suggestions)")
    rows.append(HINT)
    # Move to the prompt line, clear everything below, redraw.
    stdout.write("\r\x1b[J")
    stdout.write(f"Fund name: {LIGHT_GREEN}{query}{RESET}\n")
    stdout.write("\n".join(rows))
    stdout.write(f"\x1b[{len(rows)}A\r")
    stdout.write(f"Fund name: {LIGHT_GREEN}{query}{RESET}")
    stdout.flush()


def _read_key(fd: int) -> str:
    """One keypress as a logical key: 'CHAR', 'ENTER', 'UP', 'DOWN', 'CTRL_D'."""
    while True:
        char = os.read(fd, 1).decode("utf-8", errors="replace")
        if char == "\r" or char == "\n":
            return "ENTER"
        if char == "\x04":
            return "CTRL_D"
        if char == "\t":
            return "TAB"
        if char == "\x1b":  # escape sequence: ignore (only Tab cycles)
            if _pending(fd):
                os.read(fd, 2)
            continue
        if char.isprintable():
            return char
        if char in ("\x7f", "\b"):
            return "\x7f"


def _pending(fd: int) -> bool:
    """True when more input is already buffered (bare ESC vs arrow keys)."""
    import select

    ready, _, _ = select.select([fd], [], [], 0.05)
    return bool(ready)


def _confirm_analysis(stdout, query: str) -> str:
    """Ask whether to start; returns 'go', 'edit' (keep typing), or 'abort'.

    Read in cooked mode (terminal back to normal), so Enter answers the
    default `Y`.
    """
    import sys

    print(
        f"Start analysis for {query!r}? [Y/n] ",
        end="",
        flush=True,
        file=stdout,
    )
    answer = sys.stdin.readline()
    if answer == "":  # EOF at the confirm prompt
        return "abort"
    reply = answer.strip().lower()
    if reply in ("", "y", "yes"):
        return "go"
    return "edit"


def prompt_with_suggestions(suggest: Suggester, stdout) -> str:
    """Interactive fund-name prompt with live suggestions; POSIX tty only.

    Type to filter, Tab to cycle through suggestions, Enter to accept.
    Enter asks for confirmation before the run starts; `n` returns to
    editing, Ctrl-D there aborts. Raises UsageError on Ctrl-D with no
    input (FR1: empty input is a usage error).
    """
    import sys
    import termios
    import tty

    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)
    query = ""
    suggestions: list[str] = []
    selected = -1
    confirmed = False
    tty.setcbreak(fd)
    try:
        while True:
            _render(stdout, query, suggestions, selected)
            key = _read_key(fd)
            if key == "ENTER":
                if not query.strip():
                    raise UsageError("no fund name provided")
                if 0 <= selected < len(suggestions):
                    query = suggestions[selected]
                # Confirm in cooked mode (normal terminal line editing).
                termios.tcsetattr(fd, termios.TCSADRAIN, original)
                stdout.write("\r\x1b[J")
                stdout.write(f"Fund name: {LIGHT_GREEN}{query}{RESET}\n")
                decision = _confirm_analysis(stdout, query)
                if decision == "go":
                    confirmed = True
                    stdout.write("\n")
                    stdout.flush()
                    break
                if decision == "abort":
                    stdout.write("\n")
                    stdout.flush()
                    raise UsageError("analysis cancelled")
                # 'edit': back to raw mode and keep typing. The cursor is
                # two lines below the prompt line (confirm line + the
                # Enter that answered it), so clear from the prompt line.
                tty.setcbreak(fd)
                stdout.write("\x1b[2A\r\x1b[J")
                selected = -1
                continue
            if key == "CTRL_D":
                if not query.strip():
                    raise UsageError("no fund name provided")
                break
            if key == "TAB" and suggestions:
                selected = (
                    0 if selected == -1 else (selected + 1) % len(suggestions)
                )
                continue
            if key == "\x7f":
                query = query[:-1]
            else:
                query += key
            selected = -1  # query changed: drop any suggestion highlight
            if len(query.strip()) >= MIN_QUERY_LEN:
                suggestions = suggest(query.strip())[:MAX_SUGGESTIONS]
            else:
                suggestions = []
        if not confirmed:  # submitted without confirm (Ctrl-D with text)
            stdout.write("\r\x1b[J")
            stdout.write(f"Fund name: {LIGHT_GREEN}{query}{RESET}\n")
            stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original)
    return query.strip()
