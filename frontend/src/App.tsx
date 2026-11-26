import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  ExternalLink,
  Info,
  LoaderCircle,
  MessageCircle,
  Newspaper,
  RotateCcw,
  Send,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  X,
} from "lucide-react";
import { Children, isValidElement, useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import { Input } from "./components/ui/input";
import { Textarea } from "./components/ui/textarea";

type Profile = {
  name: string;
  ticker: string;
  currency?: string | null;
  family?: string | null;
  holdings: { name: string; symbol: string; weight: string }[];
  sector_weights: Record<string, string>;
  overview: Record<string, string>;
  gaps: string[];
};

type Failure = { stage: string; error_code: string; message: string };
type RunSnapshot = {
  id: string;
  fund: string;
  status: "queued" | "running" | "succeeded" | "failed";
  stage: string | null;
  completed_stages: string[];
  failure: Failure | null;
  report?: string;
  profile?: Profile;
};

type Evidence = {
  source_id: string;
  source_number: number | null;
  kind: "news" | "web";
  title: string;
  url: string;
  source: string | null;
  published: string | null;
  passages: string[];
};

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  evidence?: Evidence[];
  insufficient?: boolean;
};

type QAResponse = {
  answer: string;
  evidence: Evidence[];
  insufficient: boolean;
};

function formatPublishedDate(value: string | null): string | null {
  if (!value) return null;
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return value;
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(timestamp);
}

function CitationTooltip({ source }: { source: Evidence }) {
  const publishedDate = formatPublishedDate(source.published);
  return (
    <span className="chat-citation">
      <a
        className="chat-citation-number"
        href={source.url}
        target="_blank"
        rel="noreferrer"
        aria-label={`Open source ${source.source_id}: ${source.title}`}
      >
        [{source.source_id}]
      </a>
      <span className="chat-citation-card" role="tooltip">
        <a
          className="chat-citation-title"
          href={source.url}
          target="_blank"
          rel="noreferrer"
        >
          {source.title}
          <ExternalLink size={12} />
        </a>
        <span className="chat-citation-meta">
          {source.source || (source.kind === "web" ? "Web source" : "News source")}
          {publishedDate ? ` · ${publishedDate}` : ""}
        </span>
        {source.passages[0] && (
          <span className="chat-citation-excerpt">
            “{source.passages[0].slice(0, 280)}
            {source.passages[0].length > 280 ? "…" : ""}”
          </span>
        )}
        <a
          className="chat-citation-open"
          href={source.url}
          target="_blank"
          rel="noreferrer"
        >
          Open original source
          <ExternalLink size={12} />
        </a>
      </span>
    </span>
  );
}

function AnswerWithCitations({
  answer,
  evidence,
}: {
  answer: string;
  evidence: Evidence[];
}) {
  const evidenceById = new Map(
    evidence.map((source) => [source.source_id, source]),
  );
  const markdownAnswer = answer.replace(
    /\[((?:\d+|W\d+)(?:,\s*(?:\d+|W\d+))*)\]/g,
    (marker, citationList: string) => {
      const ids = citationList.split(",").map((sourceId) => sourceId.trim());
      if (ids.some((sourceId) => !evidenceById.has(sourceId))) return marker;
      return ids.map((sourceId) => `[[${sourceId}]](#invesk-cite-${sourceId})`).join(", ");
    },
  );

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ href, children }) => {
          const citationId = href?.startsWith("#invesk-cite-")
            ? href.slice("#invesk-cite-".length)
            : null;
          const source = citationId ? evidenceById.get(citationId) : undefined;
          if (source) return <CitationTooltip source={source} />;
          return (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
              <ExternalLink size={12} />
            </a>
          );
        },
      }}
    >
      {markdownAnswer}
    </ReactMarkdown>
  );
}

const stageLabels: Record<string, string> = {
  fund_extraction: "Fund data",
  news_search: "News research",
  news_dedup: "Refining results",
  synthesis: "Insights",
  report: "Report",
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: string;
    };
    throw new Error(body.detail ?? "Something went wrong. Please try again.");
  }
  return (await response.json()) as T;
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className="brand-lockup">
      <span className="brand-mark">
        <TrendingUp size={17} strokeWidth={2.5} />
      </span>
      {!compact && <span className="brand-name">invesk</span>}
    </div>
  );
}

function Welcome({
  fund,
  setFund,
  submitting,
  error,
  onStart,
}: {
  fund: string;
  setFund: (value: string) => void;
  submitting: boolean;
  error: string | null;
  onStart: (fundName: string) => void;
}) {
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [selectedSuggestion, setSelectedSuggestion] = useState(-1);
  const [chosenSuggestion, setChosenSuggestion] = useState<string | null>(null);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [suggestionsVisible, setSuggestionsVisible] = useState(false);
  const [suggestionsUnavailable, setSuggestionsUnavailable] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const requestNumber = useRef(0);
  const skipSuggestionQuery = useRef(false);

  useEffect(() => {
    const query = fund.trim();
    // Ignore a response for an older input value if a newer request has started.
    const requestId = ++requestNumber.current;
    setSelectedSuggestion(-1);
    setSuggestionsUnavailable(false);

    if (skipSuggestionQuery.current) {
      skipSuggestionQuery.current = false;
      setSuggestions([]);
      setSuggestionsLoading(false);
      return;
    }

    if (query.length < 1) {
      setSuggestions([]);
      setSuggestionsLoading(false);
      setSuggestionsVisible(false);
      return;
    }

    setSuggestions([]);
    setSuggestionsLoading(true);
    // Debounce typing so each intermediate prefix doesn't trigger a Yahoo request.
    const timer = window.setTimeout(() => {
      void api<{ suggestions: string[] }>(
        `/suggestions?query=${encodeURIComponent(query)}`,
      )
        .then((result) => {
          if (requestNumber.current !== requestId) return;
          setSuggestions(result.suggestions);
          setSuggestionsVisible(true);
        })
        .catch(() => {
          if (requestNumber.current !== requestId) return;
          setSuggestions([]);
          setSuggestionsUnavailable(true);
          setSuggestionsVisible(false);
        })
        .finally(() => {
          if (requestNumber.current === requestId) setSuggestionsLoading(false);
        });
    }, 280);

    return () => window.clearTimeout(timer);
  }, [fund]);

  useEffect(() => {
    if (!suggestionsVisible || selectedSuggestion < 0) return;
    document
      .getElementById(`fund-suggestion-${selectedSuggestion}`)
      ?.scrollIntoView({ block: "nearest" });
  }, [selectedSuggestion, suggestionsVisible]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      suggestions.length > 0 &&
      selectedSuggestion < 0 &&
      chosenSuggestion === null
    ) {
      return;
    }
    const candidate =
      selectedSuggestion >= 0
        ? suggestions[selectedSuggestion]
        : chosenSuggestion ?? fund.trim();
    if (!candidate) return;
    setFund(candidate);
    setSuggestions([]);
    setSuggestionsVisible(false);
    onStart(candidate);
  }

  function handleFundKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" && suggestionsVisible && suggestions.length > 0) {
      event.preventDefault();
      selectSuggestion(
        suggestions[selectedSuggestion >= 0 ? selectedSuggestion : 0],
      );
    } else if (event.key === "ArrowDown" && suggestionsVisible && suggestions.length > 0) {
      event.preventDefault();
      setSelectedSuggestion((selected) =>
        selected < 0 ? 0 : (selected + 1) % suggestions.length,
      );
    } else if (event.key === "ArrowUp" && suggestionsVisible && suggestions.length > 0) {
      event.preventDefault();
      setSelectedSuggestion((selected) =>
        selected <= 0 ? suggestions.length - 1 : selected - 1,
      );
    } else if (event.key === "Escape") {
      setSuggestionsVisible(false);
      setSelectedSuggestion(-1);
    }
  }

  function selectSuggestion(suggestion: string) {
    // Selecting an existing result shouldn't immediately trigger another lookup.
    skipSuggestionQuery.current = true;
    setFund(suggestion);
    setSelectedSuggestion(-1);
    setChosenSuggestion(suggestion);
    setSuggestionsVisible(false);
    inputRef.current?.focus();
  }

  return (
    <main className="welcome-page">
      <header className="topbar welcome-topbar">
        <Brand />
      </header>
      <section className="welcome-hero">
        <div className="hero-copy">
          <h1>
            Know what you
            <br />
            <span>own.</span> Understand
            <br />
            what’s changing.
          </h1>
          <p className="hero-description">
            Get a plain-language look at a fund’s holdings, financial snapshot,
            and the news shaping its companies and sectors.
          </p>
          <form className="fund-form" onSubmit={handleSubmit}>
            <label htmlFor="fund-name">Start with a fund name</label>
            <div className="fund-input-row">
              <div className="fund-field-wrap">
                <Input
                  ref={inputRef}
                  id="fund-name"
                  autoComplete="off"
                  role="combobox"
                  aria-autocomplete="list"
                  aria-expanded={suggestionsVisible && suggestions.length > 0}
                  aria-controls="fund-suggestions"
                  aria-activedescendant={
                    selectedSuggestion >= 0
                      ? `fund-suggestion-${selectedSuggestion}`
                      : undefined
                  }
                  placeholder="e.g. Vanguard S&P 500 ETF"
                  value={fund}
                  onChange={(event) => {
                    skipSuggestionQuery.current = false;
                    setFund(event.target.value);
                    setSelectedSuggestion(-1);
                    setChosenSuggestion(null);
                    setSuggestionsVisible(true);
                  }}
                  onKeyDown={handleFundKeyDown}
                  onFocus={() => {
                    if (suggestions.length > 0) setSuggestionsVisible(true);
                  }}
                  disabled={submitting}
                  required
                />
                {suggestionsLoading && (
                  <LoaderCircle className="suggestion-loader spin" size={16} aria-label="Loading fund suggestions" />
                )}
                {suggestionsVisible && (suggestions.length > 0 || (fund.trim().length >= 1 && !suggestionsLoading && !suggestionsUnavailable)) && (
                  <div className="fund-suggestions" id="fund-suggestions" role="listbox" aria-label="Yahoo Finance fund suggestions">
                    {suggestions.length > 0 ? suggestions.map((suggestion, index) => (
                      <button
                        type="button"
                        role="option"
                        aria-selected={selectedSuggestion === index}
                        id={`fund-suggestion-${index}`}
                        className={`fund-suggestion ${selectedSuggestion === index ? "fund-suggestion-active" : ""}`}
                        tabIndex={-1}
                        key={`${suggestion}-${index}`}
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => selectSuggestion(suggestion)}
                      >
                        <span className="suggestion-fund-icon"><BarChart3 size={14} /></span>
                        <span>{suggestion}</span>
                        <ArrowUpRight size={13} className="suggestion-arrow" />
                      </button>
                    )) : (
                      <div className="no-suggestions">No fund matches yet. You can still use your search.</div>
                    )}
                    {suggestions.length > 0 && <div className="suggestion-help">Use ↑ / ↓ to highlight · Enter or click to select</div>}
                  </div>
                )}
              </div>
              <Button
                type="submit"
                disabled={
                  submitting ||
                  !fund.trim() ||
                  suggestionsLoading ||
                  (suggestions.length > 0 &&
                    selectedSuggestion < 0 &&
                    chosenSuggestion === null)
                }
              >
                {submitting ? (
                  <>
                    <LoaderCircle className="spin" size={16} />
                    Starting
                  </>
                ) : (
                  <>
                    Analyze fund
                    <ArrowRight size={16} />
                  </>
                )}
              </Button>
            </div>
            {fund.trim().length >= 1 && (
              <div className="fund-suggestion-status" aria-live="polite">
                {suggestionsUnavailable
                  ? "Suggestions are temporarily unavailable; you can still enter a fund name."
                  : suggestions.length > 0 && suggestionsVisible
                    ? `${suggestions.length} matching funds from Yahoo Finance.`
                    : null}
              </div>
            )}
            {error && (
              <p className="form-error" role="alert">
                <CircleHelp size={15} />
                {error}
              </p>
            )}
            <div className="privacy-note">
              <ShieldCheck size={14} />
              Research support, not personalized financial advice.
            </div>
          </form>
        </div>
      </section>
      <section className="how-section">
        <div className="how-heading">
          <span className="eyebrow">From fund name to context</span>
        </div>
        <div className="how-grid">
          <div className="how-item">
            <span className="how-number">01</span>
            <span className="how-icon"><BarChart3 size={18} /></span>
            <div><strong>See what you own</strong><p>Holdings, sectors, and fund-level metrics in one snapshot.</p></div>
          </div>
          <div className="how-item">
            <span className="how-number">02</span>
            <span className="how-icon"><Newspaper size={18} /></span>
            <div><strong>Follow the news</strong><p>Recent stories about the companies and sectors in your fund.</p></div>
          </div>
          <div className="how-item">
            <span className="how-number">03</span>
            <span className="how-icon"><MessageCircle size={18} /></span>
            <div><strong>Ask what matters</strong><p>Explore the report and its collected sources in a grounded chat.</p></div>
          </div>
        </div>
      </section>
      <footer className="welcome-footer">
        <span>© Invesk · Understand a fund before you invest in it.</span>
      </footer>
    </main>
  );
}

function ProgressView({
  run,
  onNew,
}: {
  run: RunSnapshot;
  onNew: () => void;
}) {
  const failed = run.status === "failed";
  return (
    <div className="progress-page">
      <header className="topbar app-topbar">
        <Brand />
        <Button variant="ghost" onClick={onNew}>
          <ArrowLeft size={16} />
          New analysis
        </Button>
      </header>
      <main className="progress-main">
        {failed && (
          <div className="progress-overline">
            <span className="status-dot status-dot-red" />
            Run needs attention
          </div>
        )}
        {failed && <h1>We couldn’t finish this report.</h1>}
        {failed && (
          <p className="progress-description">
            We ran into an issue while researching {run.fund}.
          </p>
        )}
        <Card className="progress-card">
          <CardHeader className="progress-card-header">
            <div>
              <CardTitle className="progress-fund-name">{run.fund}</CardTitle>
            </div>
            <Badge>{failed ? "Needs attention" : run.status === "queued" ? "Queued" : "In progress"}</Badge>
          </CardHeader>
          <CardContent>
            <div className="stage-list">
              {STAGE_ORDER.map((stage, index) => {
                const complete = run.completed_stages.includes(stage);
                const active = stage === run.stage && !failed;
                const stageFailed = failed && stage === run.failure?.stage;
                return (
                  <div className={`stage-row ${complete ? "is-complete" : ""} ${active ? "is-active" : ""} ${stageFailed ? "is-failed" : ""}`} key={stage}>
                    <span className="stage-icon">
                      {complete ? <Check size={14} /> : active ? <LoaderCircle size={15} className="spin" /> : stageFailed ? <X size={14} /> : <span>{String(index + 1).padStart(2, "0")}</span>}
                    </span>
                    <span className="stage-label">{stageLabels[stage]}</span>
                    <span className="stage-state">{complete ? "Complete" : active ? "Working…" : stageFailed ? "Couldn’t complete" : "Waiting"}</span>
                  </div>
                );
              })}
            </div>
            {failed && run.failure && (
              <div className="failure-message" role="alert">
                <CircleHelp size={17} />
                <div><strong>{run.failure.message}</strong><span>Stage: {stageLabels[run.failure.stage] ?? run.failure.stage}</span></div>
              </div>
            )}
            {!failed && <p className="progress-footnote"><Clock3 size={14} /> You can keep this page open. Your chat will be ready as soon as the report is complete.</p>}
            {failed && <Button onClick={onNew} className="retry-button">Try another fund <ArrowRight size={15} /></Button>}
          </CardContent>
        </Card>
        <p className="progress-disclaimer"><ShieldCheck size={14} /> Invesk is an information and research aid—not personalized financial advice.</p>
      </main>
    </div>
  );
}

const STAGE_ORDER = [
  "fund_extraction",
  "news_search",
  "news_dedup",
  "synthesis",
  "report",
];

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function isInsideMarkdownStrong(markdown: string, offset: number): boolean {
  // Count emphasis delimiters before the match so generated **...** isn't nested.
  return (markdown.slice(0, offset).match(/\*\*/g)?.length ?? 0) % 2 === 1;
}

function highlightReportEntities(
  markdown: string,
  profile: Profile,
): { markdown: string; entities: Set<string>; weights: Set<string> } {
  // Mark weights already written in report prose before highlighting profile names,
  // so the renderer can style each without introducing nested Markdown emphasis.
  const entities = new Set<string>();
  const weights = new Set<string>();
  let result = markdown.replace(
    /(^|\n)(\s*(?:[-*]\s+)?)([^\n(]+?)\s+\((\d+(?:\.\d+)?%)\s+weight\)/g,
    (_match, lineBreak: string, prefix: string, label: string, weight: string) => {
      const name = label.trim();
      entities.add(name);
      weights.add(weight);
      return `${lineBreak}${prefix}**${name}** (**${weight}** weight)`;
    },
  );

  const profileEntities = [
    ...profile.holdings.map(({ name, weight }) => ({ name, weight })),
    ...Object.entries(profile.sector_weights).map(([name, weight]) => ({
      name,
      weight,
    })),
  ].filter(({ name, weight }) => name && weight);
  const entityPattern = profileEntities
    .map(({ name }) => name)
    .sort((left, right) => right.length - left.length)
    .map(escapeRegExp)
    .join("|");

  if (entityPattern) {
    result = result.replace(
      new RegExp(`\\b(${entityPattern})\\b`, "gi"),
      (match, _entity, offset: number, source: string) => {
        entities.add(match);
        return isInsideMarkdownStrong(source, offset) ? match : `**${match}**`;
      },
    );
  }

  for (const { name, weight } of profileEntities) {
    const entityWeightPattern = new RegExp(
      `\\b${escapeRegExp(name)}\\b([^\\n]{0,240}?)(${escapeRegExp(weight)})(?![\\d.])`,
      "gi",
    );
    result = result.replace(
      entityWeightPattern,
      (
        match,
        _between: string,
        matchedWeight: string,
        offset: number,
        source: string,
      ) => {
        const weightOffset = offset + match.length - matchedWeight.length;
        weights.add(matchedWeight);
        if (isInsideMarkdownStrong(source, weightOffset)) return match;
        return `${match.slice(0, -matchedWeight.length)}**${matchedWeight}**`;
      },
    );
  }

  return { markdown: result, entities, weights };
}

function ReportPanel({ report, profile }: { report: string; profile: Profile }) {
  const reportWithoutMetadata = report.replace(
    /^#[^\r\n]*\r?\n(?:\r?\n)*Generated:[^\r\n]*\r?\n(?:\r?\n)*/,
    "",
  ).replace(/^## Financial health\s*$/im, "");
  const reportWithoutSnapshot = reportWithoutMetadata
    .split(/(?=^## )/m)
    .filter((section) => !/^## Snapshot(?:\s|$)/im.test(section))
    .join("");
  const sourcesHeading = reportWithoutSnapshot.match(/\n## Sources\s*\n/i);
  const reportBody = sourcesHeading
    ? reportWithoutSnapshot.slice(0, sourcesHeading.index)
    : reportWithoutSnapshot;
  const {
    markdown: highlightedReportBody,
    entities: highlightedEntities,
    weights: highlightedWeights,
  } = highlightReportEntities(reportBody, profile);
  const sourcesMarkdown = sourcesHeading
    ? reportWithoutSnapshot.slice(
        sourcesHeading.index! + sourcesHeading[0].length,
      )
    : "";
  const sources = Array.from(
    sourcesMarkdown.matchAll(
      /^\s*(\d+)\.\s+\[([^\]]+)\]\(([^)\s]+)\)\s*$/gm,
    ),
    ([, number, title, url]) => ({
      number: Number(number),
      title,
      url,
    }),
  );
  const sourcesByNumber = new Map(sources.map((source) => [source.number, source]));
  const linkedBody = highlightedReportBody.replace(
    /\[(\d+(?:\s*,\s*\d+)*)\]/g,
    (marker, citationList: string) => {
      const numbers = citationList.split(",").map((number) => Number(number.trim()));
      const citedSources = numbers.map((number) => sourcesByNumber.get(number));
      // Leave unknown markers untouched rather than linking them to the wrong source.
      if (citedSources.some((source) => !source)) return marker;
      return (
        "[" +
        citedSources
          .map((source) => {
            const tooltip = `${source!.title} — ${source!.url}`.replaceAll('"', '\\"');
            return `[${source!.number}](<${source!.url}> "${tooltip}")`;
          })
          .join(", ") +
        "]"
      );
    },
  );

  function plainText(node: ReactNode): string {
    if (typeof node === "string" || typeof node === "number") {
      return String(node);
    }
    if (Array.isArray(node)) return node.map(plainText).join("");
    if (isValidElement<{ children?: ReactNode }>(node)) {
      return plainText(node.props.children);
    }
    return "";
  }

  function renderMarkdown(markdown: string) {
    return (
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          strong: ({ children }) => {
            const text = Array.isArray(children)
              ? children
                  .map((child) =>
                    typeof child === "string" || typeof child === "number"
                      ? String(child)
                      : "",
                  )
                  .join("")
              : typeof children === "string" || typeof children === "number"
                ? String(children)
                : "";
            const className = highlightedEntities.has(text)
              ? "report-entity-highlight"
              : highlightedWeights.has(text)
                ? "report-weight-highlight"
                : undefined;
            return <strong className={className}>{children}</strong>;
          },
          table: ({ children }) => <div className="metric-grid">{children}</div>,
          thead: () => null,
          tbody: ({ children }) => (
            <div className="metric-card-grid">{children}</div>
          ),
          tr: ({ children }) => {
            const cells = Children.toArray(children).filter(isValidElement);
            if (cells.some((cell) => cell.type === "th")) return null;
            const values = cells.map(
              (cell) =>
                (cell.props as { children?: ReactNode }).children ?? null,
            );
            const [metric, value, definition] = values;
            const metricName = plainText(metric).trim();
            if (!metricName || value == null) return null;
            const tooltipId = `metric-definition-${metricName
              .toLocaleLowerCase()
              .replace(/[^a-z0-9]+/g, "-")}`;
            return (
              <article className="metric-card">
                <div className="metric-card-heading">
                  <strong>{metric}</strong>
                  {definition != null && (
                    <button
                      type="button"
                      className="metric-info"
                      aria-label={`Definition of ${metricName}`}
                      aria-describedby={tooltipId}
                    >
                      <Info size={14} aria-hidden="true" />
                      <span
                        id={tooltipId}
                        className="metric-tooltip"
                        role="tooltip"
                      >
                        {definition}
                      </span>
                    </button>
                  )}
                </div>
                <div className="metric-card-value">{value}</div>
              </article>
            );
          },
          a: ({ href, title, children }) => (
            <a
              href={href}
              title={title}
              target="_blank"
              rel="noreferrer"
              className={title ? "report-citation-link" : undefined}
            >
              {children}
              {!title && <ExternalLink size={12} />}
            </a>
          ),
        }}
      >
        {markdown}
      </ReactMarkdown>
    );
  }

  return (
    <>
      <article className="report-markdown report-body">{renderMarkdown(linkedBody)}</article>
      {sourcesHeading && (
        <details className="report-sources">
          <summary>Sources{sources.length > 0 ? ` (${sources.length})` : ""}</summary>
          <div className="report-markdown report-sources-content">
            {renderMarkdown(sourcesMarkdown)}
          </div>
        </details>
      )}
    </>
  );
}

function ChatPanel({ runId }: {
  runId: string;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [pendingStatus, setPendingStatus] = useState<"thinking" | "searching_web">("thinking");
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, sending]);

  async function sendQuestion(event?: FormEvent) {
    event?.preventDefault();
    const value = question.trim();
    if (!value || sending || resetting) return;
    setError(null);
    setQuestion("");
    const assistantIndex = messages.length + 1;
    setMessages((previous) => [
      ...previous,
      { role: "user", content: value },
      { role: "assistant", content: "" },
    ]);
    setSending(true);
    setPendingStatus("thinking");
    const statusPoll = window.setInterval(() => {
      void api<{ status: string | null }>(`/runs/${runId}/qa-status`)
        .then(({ status }) => {
          if (status === "thinking" || status === "searching_web") {
            setPendingStatus(status);
          }
        })
        .catch(() => {});
    }, 400);
    try {
      const response = await fetch(`/api/runs/${runId}/questions/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: value }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as {
          detail?: string;
        };
        throw new Error(body.detail ?? "Something went wrong. Please try again.");
      }
      if (!response.body) throw new Error("The answer stream could not be opened.");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let receivedResult = false;
      const handleEvent = (frame: string) => {
        const data = frame
          .split("\n")
          .find((line) => line.startsWith("data: "))
          ?.slice("data: ".length);
        if (!data) return;
        const event = JSON.parse(data) as
          | { type: "token"; text: string }
          | { type: "reset" }
          | { type: "done"; result: QAResponse }
          | { type: "error"; message: string };
        if (event.type === "token") {
          setMessages((previous) =>
            previous.map((message, index) =>
              index === assistantIndex
                ? { ...message, content: message.content + event.text }
                : message,
            ),
          );
        } else if (event.type === "reset") {
          setMessages((previous) =>
            previous.map((message, index) =>
              index === assistantIndex ? { ...message, content: "" } : message,
            ),
          );
        } else if (event.type === "done") {
          receivedResult = true;
          setMessages((previous) =>
            previous.map((message, index) =>
              index === assistantIndex
                ? {
                    ...message,
                    content: event.result.answer,
                    evidence: event.result.evidence,
                    insufficient: event.result.insufficient,
                  }
                : message,
            ),
          );
        } else {
          throw new Error(event.message);
        }
      };

      while (true) {
        const { value: chunk, done } = await reader.read();
        buffer += decoder.decode(chunk, { stream: !done });
        let frameEnd = buffer.indexOf("\n\n");
        while (frameEnd >= 0) {
          handleEvent(buffer.slice(0, frameEnd));
          buffer = buffer.slice(frameEnd + 2);
          frameEnd = buffer.indexOf("\n\n");
        }
        if (done) break;
      }
      if (buffer.trim()) {
        handleEvent(buffer);
      }
      if (!receivedResult) {
        throw new Error("The answer stream ended before the answer was complete.");
      }
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Could not get an answer.";
      setError(message);
      setMessages((previous) =>
        previous.map((item, index) =>
          index === assistantIndex
            ? {
                role: "assistant",
                content: "I couldn’t answer that just now. Your run is still here—please try again.",
              }
            : item,
        ),
      );
    } finally {
      window.clearInterval(statusPoll);
      setSending(false);
      inputRef.current?.focus();
    }
  }

  async function resetChat() {
    if (sending || resetting) return;
    setResetting(true);
    setError(null);
    try {
      await api<{ reset: boolean }>(`/runs/${runId}/chat/reset`, {
        method: "POST",
      });
      setMessages([]);
      setQuestion("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not reset the chat.");
    } finally {
      setResetting(false);
      inputRef.current?.focus();
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendQuestion();
    }
  }

  return (
    <Card className="chat-card">
      <div className="chat-header">
        <div className="chat-avatar"><Sparkles size={17} /></div>
        <div className="chat-header-copy"><strong>Ask Invesk</strong><span>Grounded in this run, with web search when needed</span></div>
        <Button
          className="chat-reset-button"
          variant="ghost"
          size="sm"
          onClick={() => void resetChat()}
          disabled={sending || resetting || messages.length === 0}
          title="Clear this conversation while keeping the report and sources"
        >
          {resetting ? <LoaderCircle size={13} className="spin" /> : <RotateCcw size={13} />}
          Reset Chat
        </Button>
        <span className="chat-online-dot" title="Ready" />
      </div>
      <div className="chat-scroll">
        {messages.map((message, index) => (
              <div className={`message-row ${message.role === "user" ? "user-row" : ""}`} key={`${index}-${message.role}`}>
                {message.role === "assistant" && <div className="message-avatar"><Sparkles size={13} /></div>}
                <div className={`message-body ${message.role === "user" ? "user-message" : "assistant-message"}`}>
                  {message.role === "assistant" && message.evidence ? (
                    <AnswerWithCitations
                      answer={message.content}
                      evidence={message.evidence}
                    />
                  ) : (
                    <p>{message.content}</p>
                  )}
                  {message.insufficient && <span className="insufficient-note"><CircleHelp size={13} /> Sources don’t cover this question.</span>}
                  {message.role === "assistant" && <span className="message-time">Invesk assistant</span>}
                </div>
              </div>
        ))}
        {sending && (
          <div className="message-row">
            <div className="message-avatar"><Sparkles size={13} /></div>
            <div className="typing-indicator" role="status" aria-live="polite">
              <LoaderCircle size={14} className="spin" aria-hidden="true" />
              <span>{pendingStatus === "searching_web" ? "Searching the Web" : "Thinking"}</span>
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>
      <div className="chat-bottom">
        {error && <div className="chat-error" role="alert">{error}</div>}
        <form className="chat-composer" onSubmit={sendQuestion}>
          <Textarea
            ref={inputRef}
            aria-label="Ask a question about this report"
            placeholder="Fire away with your question…"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={onKeyDown}
            rows={2}
            maxLength={2000}
            disabled={sending || resetting}
          />
          <Button type="submit" size="icon" aria-label="Send question" disabled={!question.trim() || sending || resetting}>
            {sending ? <LoaderCircle size={17} className="spin" /> : <Send size={16} />}
          </Button>
        </form>
        <div className="chat-footnote">AI can make mistakes. Check the cited article before relying on a claim.</div>
      </div>
    </Card>
  );
}

function Workspace({
  run,
  onNew,
}: {
  run: RunSnapshot;
  onNew: () => void;
}) {
  const profile = run.profile!;
  const generatedAt = run.report?.match(/^Generated:\s*(.+)$/m)?.[1] ?? "—";

  return (
    <div className="workspace-page">
      <header className="topbar workspace-topbar">
        <Brand />
        <div className="workspace-breadcrumb"><span>Research workspace</span><ChevronDown size={14} /><strong>{profile.name}</strong></div>
        <Button variant="outline" size="sm" onClick={onNew}><span className="plus-sign">+</span> New analysis</Button>
      </header>
      <main className="workspace-main">
        <div className="run-heading">
          <div>
            <div className="run-label"><span className="status-dot" /> Completed research <span className="run-label-divider">/</span> {profile.ticker}</div>
            <h1>{profile.name} (Currency: {profile.currency || "Unknown"})</h1>
            <p>Generated: {generatedAt}</p>
          </div>
        </div>
        <div className="workspace-grid">
          <section className="research-column">
            <div className="research-panel">
              <ReportPanel report={run.report ?? ""} profile={profile} />
            </div>
            <div className="workspace-disclaimer"><ShieldCheck size={15} /><span>For information and research only. Not personalized financial advice or a buy/sell recommendation.</span></div>
          </section>
          <aside className="chat-column">
            <ChatPanel
              key={run.id}
              runId={run.id}
            />
          </aside>
        </div>
      </main>
    </div>
  );
}

export default function App() {
  const [fund, setFund] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [run, setRun] = useState<RunSnapshot | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function startRun(fundName: string) {
    if (!fundName.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await api<{ id: string; fund: string; status: string }>(
        "/runs",
        { method: "POST", body: JSON.stringify({ fund: fundName.trim() }) },
      );
      setRunId(created.id);
      setRun({
        id: created.id,
        fund: created.fund,
        status: "queued",
        stage: null,
        completed_stages: [],
        failure: null,
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start this analysis.");
    } finally {
      setSubmitting(false);
    }
  }

  useEffect(() => {
    if (!runId || run?.status === "succeeded" || run?.status === "failed") return;
    let active = true;
    const poll = async () => {
      try {
        const result = await api<RunSnapshot>(`/runs/${runId}`);
        if (active) setRun(result);
      } catch (cause) {
        if (active) {
          setError(cause instanceof Error ? cause.message : "Could not load the run.");
        }
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1200);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [runId, run?.status]);

  function reset() {
    setRunId(null);
    setRun(null);
    setError(null);
    setFund("");
  }

  if (!run) {
    return (
      <Welcome
        fund={fund}
        setFund={setFund}
        submitting={submitting}
        error={error}
        onStart={startRun}
      />
    );
  }
  if (run.status !== "succeeded") return <ProgressView run={run} onNew={reset} />;
  return <Workspace run={run} onNew={reset} />;
}
