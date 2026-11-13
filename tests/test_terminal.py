"""Terminal-only report transformations (colors, hidden link URLs)."""

from colorama import Fore, Style

from src.reporting.terminal import colorize_report


def test_colorize_report_shows_only_the_title_of_source_links():
    report = (
        "## Sources\n\n"
        "26. [Deloitte outlook](https://www.example.com/outlooks.html)\n"
    )
    colored = colorize_report(report)
    link_line = next(line for line in colored.splitlines() if "Deloitte" in line)
    # The title is underlined and wrapped in the OSC 8 hyperlink; the URL
    # appears exactly once — embedded in the wrapper, never as visible text.
    assert (
        "\x1b]8;;https://www.example.com/outlooks.html\x1b\\"
        "\x1b[4mDeloitte outlook\x1b[24m"
        "\x1b]8;;\x1b\\" in link_line
    )
    assert link_line.count("https://www.example.com/outlooks.html") == 1


def test_colorize_report_leaves_citation_markers_alone():
    report = "## Company insights\n\nCompany text. [1]\n"
    colored = colorize_report(report)
    assert "[1]" in colored  # a bare [n] marker is not a markdown link


def test_colorize_report_still_colors_the_sources_heading():
    colored = colorize_report("## Sources\n")
    assert colored.startswith(f"{Fore.YELLOW}## Sources\n")


def test_colorize_report_colors_linked_lines_inside_a_section():
    report = "## Sources\n\n1. [A news item](https://example.com/a)\n"
    colored = colorize_report(report)
    lines = colored.splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines) if "A news item" in line)
    assert lines[index].startswith(Fore.YELLOW)
    # colorama wraps the line's newline, so the reset lands on the next line.
    assert lines[index + 1].startswith(Style.RESET_ALL)
