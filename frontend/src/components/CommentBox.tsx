import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy, Hourglass, MessageSquare, Send } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Textarea } from "@/components/ui/Input";
import { MentionMenu, activeMention, filterOptions, insertMention } from "@/components/MentionMenu";
import { RoundPanel } from "@/components/RoundPanel";
import { cn, formatAbsolute, linkThreadRefs } from "@/lib/utils";
import type {
  ReviewThread,
  RoundDecision,
  ThreadMessage,
  ThreadOption,
  ThreadRound,
} from "@/types";

export interface CommentBoxProps {
  index: number;
  thread: ReviewThread;
  selected: boolean;
  draft: string;
  threadCount?: number;
  threadOptions?: ThreadOption[];
  onSelect: () => void;
  onDraftChange: (value: string) => void;
  onJumpToOrdinal?: (ordinal: number) => void;
  onDecide?: (roundId: number, decision: RoundDecision) => void;
  onSaveSummary?: (roundId: number, text: string) => void;
  decidingRoundId?: number | null;
  sending?: boolean;
  submitDisabledReason?: string | null;
  disabled?: boolean;
}

function fallbackRound(): ThreadRound {
  return {
    id: -1,
    round_number: 1,
    inbound_github_comment_id: null,
    inbound_author: null,
    inbound_body: null,
    final_summary: null,
    status: "drafting",
    published_github_comment_id: null,
    created_at: null,
    updated_at: null,
  };
}

export function CommentBox({
  index,
  thread,
  selected,
  draft,
  threadCount = 0,
  threadOptions = [],
  onSelect,
  onDraftChange,
  onJumpToOrdinal,
  onDecide,
  onSaveSummary,
  decidingRoundId = null,
  sending = false,
  submitDisabledReason = null,
  disabled = false,
}: CommentBoxProps) {
  const ref = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const [mention, setMention] = useState<{ start: number; query: string; index: number } | null>(
    null,
  );

  // The badge keeps the review-wide ordinal: filtering must never renumber a thread.
  const displayOrdinal = thread.ordinal || index + 1;
  const rounds = thread.rounds.length > 0 ? thread.rounds : [fallbackRound()];
  const activeNumber = thread.current_round || rounds[rounds.length - 1].round_number;
  const messagesByRound = thread.messages.reduce<Record<number, ThreadMessage[]>>(
    (groups, message) => {
      const key = message.round_number || 1;
      (groups[key] ??= []).push(message);
      return groups;
    },
    {},
  );
  const mentionOptions = mention
    ? filterOptions(threadOptions, mention.query, displayOrdinal)
    : [];
  const isGithub = thread.origin === "GITHUB_EXISTING";

  function handleDraftChange(event: React.ChangeEvent<HTMLTextAreaElement>) {
    const value = event.target.value;
    onDraftChange(value);
    const caret = event.target.selectionStart ?? value.length;
    const active = activeMention(value, caret);
    setMention(active ? { ...active, index: 0 } : null);
  }

  function pickOrdinal(ordinal: number) {
    if (!mention) return;
    const element = textareaRef.current;
    const caret = element?.selectionStart ?? draft.length;
    const { value, caret: nextCaret } = insertMention(draft, mention.start, caret, ordinal);
    onDraftChange(value);
    setMention(null);
    window.requestAnimationFrame(() => {
      element?.focus();
      element?.setSelectionRange(nextCaret, nextCaret);
    });
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (!mention) return;
    if (event.key === "Escape") {
      event.preventDefault();
      setMention(null);
      return;
    }
    if (mentionOptions.length === 0) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      const next = (mention.index + step + mentionOptions.length) % mentionOptions.length;
      setMention({ ...mention, index: next });
      return;
    }
    if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      const option = mentionOptions[Math.min(mention.index, mentionOptions.length - 1)];
      if (option) pickOrdinal(option.ordinal);
    }
  }

  function renderMarkdown(content: string) {
    return (
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            if (href?.startsWith("#thread-ref-")) {
              const ordinal = Number(href.slice("#thread-ref-".length));
              return (
                <a
                  href={href}
                  title={`Jump to thread #${ordinal}`}
                  className="rounded bg-accent/15 px-1 font-medium text-accent no-underline hover:bg-accent/25"
                  onClick={(event) => {
                    event.preventDefault();
                    onJumpToOrdinal?.(ordinal);
                  }}
                >
                  {children}
                </a>
              );
            }
            return (
              <a href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            );
          },
        }}
      >
        {linkThreadRefs(content, threadCount)}
      </ReactMarkdown>
    );
  }

  async function copyContext() {
    const text = `${thread.file_path}:${thread.line_number}\n\n${thread.diff_hunk}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  useEffect(() => {
    if (selected && ref.current) {
      ref.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [selected]);

  return (
    <div
      ref={ref}
      id={`thread-${thread.id}`}
      onClick={onSelect}
      className={cn(
        "surface-card border-l-2 transition-all",
        isGithub ? "border-l-accentStrong" : "border-l-accent",
        isGithub ? "border-borderStrong" : "border-accent/45",
        selected ? "ring-2 ring-accent/40" : "",
      )}
    >
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
        <Badge tone={isGithub ? "neutral" : "accent"}>
          {isGithub ? "🐙 GitHub Discussion" : "🤖 AI Finding"} #{displayOrdinal}
        </Badge>
        <span className="truncate font-mono text-xs text-inkMuted" title={thread.file_path}>
          {thread.file_path}:{thread.line_number}
        </span>
        {isGithub && thread.original_author ? (
          <span className="text-[11px] text-inkMuted">by @{thread.original_author}</span>
        ) : null}
        <div className="ml-auto flex items-center gap-1.5">
          {thread.thread_status === "needs_response" ? (
            <Badge tone="warning">⚠️ Needs response</Badge>
          ) : null}
          {thread.thread_status === "resolved" ? <Badge tone="neutral">resolved</Badge> : null}
          {thread.dropped ? <Badge tone="danger">withdrawn</Badge> : null}
          {draft.trim() ? <Badge tone="warning">unsent</Badge> : null}
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              void copyContext();
            }}
            title="Copy the file path, line and diff context"
            className="inline-flex items-center gap-1 rounded-md border border-border px-1.5 py-0.5 text-[11px] text-inkMuted transition-colors hover:border-borderStrong hover:text-ink"
          >
            {copied ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
            {copied ? "Copied" : "Copy context"}
          </button>
          <Badge tone="accent">
            <MessageSquare className="h-3 w-3" /> {thread.messages.length}
          </Badge>
        </div>
      </div>

      <div className="space-y-2.5 p-4">
        {rounds.map((round) => {
          const messages = messagesByRound[round.round_number] ?? [];
          const active = round.round_number === activeNumber;
          const open = active || Boolean(expanded[round.id]);
          return (
            <RoundPanel
              key={round.id}
              thread={thread}
              round={round}
              messages={messages}
              active={active}
              expanded={open}
              onToggle={() =>
                setExpanded((current) => ({ ...current, [round.id]: !open }))
              }
              onDecide={
                onDecide && round.id > 0
                  ? (decision) => onDecide(round.id, decision)
                  : undefined
              }
              onSaveSummary={
                onSaveSummary && round.id > 0
                  ? (text) => onSaveSummary(round.id, text)
                  : undefined
              }
              deciding={decidingRoundId === round.id}
              renderMarkdown={renderMarkdown}
            />
          );
        })}

        <div className="relative space-y-2 pt-1">
          <Textarea
            ref={textareaRef}
            rows={2}
            value={draft}
            disabled={disabled}
            onFocus={onSelect}
            onChange={handleDraftChange}
            onKeyDown={handleKeyDown}
            onBlur={() => window.setTimeout(() => setMention(null), 120)}
            placeholder={
              isGithub
                ? "Ask the copilot: “Is this reviewer right about the race condition?” · # references another thread"
                : "Ask the model, push back, or reference another thread with #"
            }
            className="min-h-[68px] text-[13px]"
          />
          {mention ? (
            <MentionMenu
              options={mentionOptions}
              activeIndex={Math.min(mention.index, Math.max(mentionOptions.length - 1, 0))}
              query={mention.query}
              onPick={pickOrdinal}
            />
          ) : null}
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] text-inkMuted">
              {submitDisabledReason ?? "Drafts stay local until you submit them."}
            </span>
            {sending ? (
              <Badge tone="accent">
                <Hourglass className="h-3 w-3 animate-pulse" /> Thinking…
              </Badge>
            ) : draft.trim() ? (
              <Badge tone="warning">
                <Send className="h-3 w-3" /> Queued — submit in the footer
              </Badge>
            ) : (
              <span className="text-[11px] text-inkMuted">
                {formatAbsolute(thread.created_at)}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
