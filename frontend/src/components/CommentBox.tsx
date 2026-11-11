import { useEffect, useLayoutEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Bot, Check, Copy, Hourglass, MessageSquare, RotateCw, Send } from "lucide-react";
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
  /** Live streamed reply while this thread is being answered; undefined when not streaming. */
  streamText?: string;
  /** Resubmits this one draft; rendered when the last attempt failed. */
  onRetry?: () => void;
  submitDisabledReason?: string | null;
  disabled?: boolean;
}

/**
 * The nearest ancestor that clips the composer — the SplitPane discussion section. The picker is
 * absolutely positioned, so this is also the box it has to fit inside.
 */
function scrollableAncestor(element: HTMLElement): HTMLElement | null {
  let node = element.parentElement;
  while (node) {
    if (/(auto|scroll)/.test(window.getComputedStyle(node).overflowY)) return node;
    node = node.parentElement;
  }
  return null;
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
  streamText,
  onRetry,
  submitDisabledReason = null,
  disabled = false,
}: CommentBoxProps) {
  const ref = useRef<HTMLDivElement>(null);
  const streamRef = useRef<HTMLDivElement | null>(null);
  const composerRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  // The token Esc dismissed, so the key-up that follows does not reopen it.
  const dismissedRef = useRef<number | null>(null);
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const [mention, setMention] = useState<{ start: number; query: string; index: number } | null>(
    null,
  );
  const [menuLayout, setMenuLayout] = useState<{
    placement: "above" | "below";
    maxHeight: number;
  }>({ placement: "below", maxHeight: 224 });

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
    dismissedRef.current = null;
    onDraftChange(value);
    const caret = event.target.selectionStart ?? value.length;
    const active = activeMention(value, caret);
    setMention(active ? { ...active, index: 0 } : null);
  }

  /**
   * Re-read the token under the caret after a caret move that is not a change. Clicking elsewhere in
   * the textarea or pressing Home/End must close the picker instead of leaving it armed at a stale
   * offset, and the active row survives the key-up that follows ↑/↓.
   */
  function syncMentionToCaret() {
    const element = textareaRef.current;
    if (!element) return;
    const caret = element.selectionStart ?? element.value.length;
    const active = activeMention(element.value, caret);
    setMention((current) => {
      if (!active) return null;
      if (dismissedRef.current === active.start) return null;
      if (current && current.start === active.start && current.query === active.query) {
        return current;
      }
      return { ...active, index: 0 };
    });
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
      dismissedRef.current = mention.start;
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

  // Tail the stream unless the reviewer scrolled away from the bottom of the discussion pane.
  useEffect(() => {
    if (streamText === undefined || !streamRef.current) return;
    const pane = scrollableAncestor(streamRef.current);
    if (!pane) return;
    const distanceFromBottom = pane.scrollHeight - pane.scrollTop - pane.clientHeight;
    if (distanceFromBottom < 96) {
      streamRef.current.scrollIntoView({ block: "nearest" });
    }
  }, [streamText]);

  // Anchor the picker to the textarea and keep it inside the pane that clips it: open upwards when
  // the composer sits near the pane's bottom edge, and never grow taller than the room it has.
  useLayoutEffect(() => {
    if (!mention) return;
    const textarea = textareaRef.current;
    const menu = composerRef.current?.querySelector<HTMLElement>('[role="listbox"]');
    if (!textarea || !menu) return;
    const pane = scrollableAncestor(textarea);
    const paneRect = pane?.getBoundingClientRect();
    const paneTop = paneRect?.top ?? 0;
    const paneBottom = paneRect?.bottom ?? window.innerHeight;
    const rect = textarea.getBoundingClientRect();
    const roomBelow = paneBottom - rect.bottom - 12;
    const roomAbove = rect.top - paneTop - 12;
    const placement = roomBelow >= 140 || roomBelow >= roomAbove ? "below" : "above";
    const maxHeight = Math.max(96, Math.min(224, placement === "below" ? roomBelow : roomAbove));
    setMenuLayout((current) =>
      current.placement === placement && current.maxHeight === maxHeight
        ? current
        : { placement, maxHeight },
    );
  }, [mention?.start, mention?.query, mentionOptions.length]);

  // The pane, not the page, has to move: nudge it by exactly the overflow once the menu has its
  // final side and height.
  useLayoutEffect(() => {
    if (!mention) return;
    const textarea = textareaRef.current;
    const menu = composerRef.current?.querySelector<HTMLElement>('[role="listbox"]');
    const pane = textarea ? scrollableAncestor(textarea) : null;
    if (!pane || !menu) return;
    const paneRect = pane.getBoundingClientRect();
    const menuRect = menu.getBoundingClientRect();
    const overflowBottom = menuRect.bottom + 8 - paneRect.bottom;
    const overflowTop = paneRect.top + 8 - menuRect.top;
    if (overflowBottom > 0) pane.scrollBy({ top: overflowBottom });
    else if (overflowTop > 0) pane.scrollBy({ top: -overflowTop });
  }, [menuLayout, mention?.start, mention?.query, mentionOptions.length]);

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
        // A menu that opens downwards overlaps the next card; keep this card above its siblings.
        mention ? "relative z-30" : "",
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

        {streamText !== undefined ? (
          <div
            ref={streamRef}
            className="flex gap-2.5 rounded-lg border border-accent/40 bg-accent/5 p-2.5"
          >
            <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-accent/15 text-accent">
              <Bot className="h-3.5 w-3.5" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="mb-1 flex items-center gap-2">
                <span className="text-xs font-medium text-ink">
                  {isGithub ? "AI copilot" : "AI review"}
                </span>
                <span className="text-[11px] text-inkMuted">answering…</span>
              </div>
              <div className="md-body">
                {streamText ? (
                  renderMarkdown(streamText)
                ) : (
                  <span className="text-xs text-inkMuted">Waiting for the first tokens…</span>
                )}
                <span className="ml-1 inline-block h-3 w-1.5 animate-pulse rounded-[1px] bg-accent align-text-bottom" />
              </div>
            </div>
          </div>
        ) : null}

        <div className="space-y-2 pt-1">
          <div ref={composerRef} className="relative">
            <Textarea
              ref={textareaRef}
              rows={2}
              value={draft}
              disabled={disabled}
              onFocus={onSelect}
              onChange={handleDraftChange}
              onKeyDown={handleKeyDown}
              onKeyUp={syncMentionToCaret}
              onClick={syncMentionToCaret}
              onSelect={syncMentionToCaret}
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
                placement={menuLayout.placement}
                maxHeight={menuLayout.maxHeight}
              />
            ) : null}
          </div>
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "text-[11px]",
                  submitDisabledReason ? "text-danger" : "text-inkMuted",
                )}
              >
                {submitDisabledReason ?? "Drafts stay local until you submit them."}
              </span>
              {submitDisabledReason && onRetry ? (
                <button
                  type="button"
                  disabled={sending}
                  onClick={(event) => {
                    event.stopPropagation();
                    onRetry();
                  }}
                  className="inline-flex h-6 items-center gap-1 rounded-md border border-accent/50 bg-accent/10 px-2 text-[11px] font-medium text-accent transition-colors hover:bg-accent/15 disabled:opacity-40"
                >
                  <RotateCw className="h-3 w-3" /> Retry
                </button>
              ) : null}
            </div>
            {sending ? (
              <Badge tone="accent">
                <Hourglass className="h-3 w-3 animate-pulse" />
                {streamText !== undefined ? "Answering…" : "Thinking…"}
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
