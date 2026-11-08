import { useEffect, useState, type ReactNode } from "react";
import {
  Bot,
  Check,
  ChevronDown,
  ChevronRight,
  Github,
  Hourglass,
  User,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Textarea } from "@/components/ui/Input";
import { cn, formatAbsolute } from "@/lib/utils";
import type { ReviewThread, RoundDecision, ThreadMessage, ThreadRound } from "@/types";

const ROUND_LABEL: Record<string, string> = {
  drafting: "Not decided",
  pending_apply: "Accepted",
  published: "Published",
  resolved_no_reply: "Pushed back",
};

function roundTone(status: string): "neutral" | "accent" | "success" | "warning" {
  if (status === "published") return "success";
  if (status === "pending_apply") return "warning";
  if (status === "drafting") return "accent";
  return "neutral";
}

function MessageRow({
  message,
  thread,
  round,
  renderMarkdown,
}: {
  message: ThreadMessage;
  thread: ReviewThread;
  round: ThreadRound;
  renderMarkdown: (content: string) => ReactNode;
}) {
  const external = message.is_external;
  const author = external
    ? `@${message.author ?? round.inbound_author ?? thread.original_author ?? "GitHub"}`
    : message.role === "user"
      ? "You"
      : thread.origin === "GITHUB_EXISTING"
        ? "AI copilot"
        : "AI review";

  return (
    <div
      className={cn(
        "flex gap-2.5 rounded-lg border p-2.5",
        external
          ? "border-borderStrong/70 bg-surfaceMuted"
          : message.role === "user"
            ? "border-success/25 bg-success/5"
            : "border-border bg-surfaceMuted/40",
      )}
    >
      <span
        className={cn(
          "mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full",
          external
            ? "bg-borderStrong/60 text-ink"
            : message.role === "user"
              ? "bg-success/15 text-success"
              : "bg-accent/15 text-accent",
        )}
      >
        {external ? (
          <Github className="h-3.5 w-3.5" />
        ) : message.role === "user" ? (
          <User className="h-3.5 w-3.5" />
        ) : (
          <Bot className="h-3.5 w-3.5" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-center gap-2">
          <span className="text-xs font-medium text-ink">{author}</span>
          <span className="text-[11px] text-inkMuted">{formatAbsolute(message.created_at)}</span>
        </div>
        <div className="md-body">{renderMarkdown(message.content)}</div>
      </div>
    </div>
  );
}

export function RoundPanel({
  thread,
  round,
  messages,
  active,
  expanded,
  onToggle,
  onDecide,
  onSaveSummary,
  deciding,
  renderMarkdown,
}: {
  thread: ReviewThread;
  round: ThreadRound;
  messages: ThreadMessage[];
  active: boolean;
  expanded: boolean;
  onToggle: () => void;
  onDecide?: (decision: RoundDecision) => void;
  onSaveSummary?: (text: string) => void;
  deciding: boolean;
  renderMarkdown: (content: string) => ReactNode;
}) {
  const open = active || expanded;
  const isInitialFinding = thread.origin === "AI_GENERATED" && round.round_number === 1;
  const inbound = round.inbound_body?.trim();
  const [edited, setEdited] = useState(round.final_summary ?? "");

  useEffect(() => {
    setEdited(round.final_summary ?? "");
  }, [round.final_summary]);

  const saved = (round.final_summary ?? "").trim();
  const dirty = edited.trim() !== saved;

  return (
    <div
      className={cn(
        "rounded-xl border",
        active ? "border-borderStrong/80 bg-surfaceMuted/30" : "border-border/70 bg-surface/40",
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-inkMuted" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-inkMuted" />
        )}
        <span className="text-xs font-medium text-ink">Round {round.round_number}</span>
        <Badge tone={roundTone(round.status)}>{ROUND_LABEL[round.status] ?? round.status}</Badge>
        {inbound ? (
          <span className="truncate text-[11px] text-inkMuted">
            {round.inbound_author ? `@${round.inbound_author} · ` : ""}
            {inbound.replace(/\s+/g, " ").slice(0, 70)}
          </span>
        ) : null}
      </button>

      {open ? (
        <div className="space-y-2.5 px-3 pb-3">
          {messages.map((message) => (
            <MessageRow
              key={message.id}
              message={message}
              thread={thread}
              round={round}
              renderMarkdown={renderMarkdown}
            />
          ))}

          {round.status === "pending_apply" && round.final_summary ? (
            <div className="space-y-1.5 rounded-lg border border-warning/40 bg-warning/5 p-2.5">
              <div className="flex items-center gap-1.5 text-[11px] font-medium text-warning">
                <Hourglass className="h-3 w-3" /> This is what will be posted
              </div>
              <Textarea
                rows={5}
                value={edited}
                disabled={!onSaveSummary || deciding}
                onChange={(event) => setEdited(event.target.value)}
                className="text-[12px] leading-relaxed"
              />
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={!onSaveSummary || deciding || !dirty || !edited.trim()}
                  onClick={() => onSaveSummary?.(edited.trim())}
                  className="h-7 rounded-md border border-accent/50 bg-accent/10 px-2 text-[11px] font-medium text-accent transition-colors hover:bg-accent/15 disabled:opacity-40"
                >
                  Save changes
                </button>
                <span className="text-[11px] text-inkMuted">
                  {dirty ? "Edited — not saved yet" : "Accepted; edit the wording if you like"}
                </span>
              </div>
            </div>
          ) : null}

          {round.status === "resolved_no_reply" ? (
            <p className="flex items-center gap-1.5 text-[11px] text-inkMuted">
              <Check className="h-3 w-3 text-success" /> Agreed — nothing will be posted for this
              round.
            </p>
          ) : null}

          {active && !isInitialFinding && round.status === "published" ? (
            <p className="text-[11px] text-inkMuted">
              Already on GitHub. Discuss below to open a new round.
            </p>
          ) : null}

          {active && round.status !== "published" ? (
            <div className="space-y-1.5 pt-0.5">
              <div className="flex flex-wrap items-center gap-1.5">
                <button
                  type="button"
                  disabled={
                    !onDecide ||
                    deciding ||
                    round.status === "pending_apply" ||
                    messages.length === 0
                  }
                  onClick={() => onDecide?.("accept")}
                  title={
                    messages.length === 0
                      ? "Ask the copilot for a reply first"
                      : "Publish this round on the next apply"
                  }
                  className={cn(
                    "h-7 rounded-md border px-2 text-[11px] font-medium transition-colors",
                    round.status === "pending_apply"
                      ? "cursor-default border-success/50 bg-success/10 text-success"
                      : "border-warning/50 bg-warning/10 text-warning hover:bg-warning/15",
                    "disabled:opacity-50",
                  )}
                >
                  {round.status === "pending_apply" ? "Accepted" : "Accept"}
                </button>
                <button
                  type="button"
                  disabled={!onDecide || deciding || round.status === "resolved_no_reply"}
                  onClick={() => onDecide?.("push_back")}
                  title="Do not publish this round to GitHub"
                  className="h-7 rounded-md border border-border px-2 text-[11px] text-inkMuted transition-colors hover:border-danger/50 hover:text-danger disabled:opacity-50"
                >
                  {round.status === "resolved_no_reply" ? "Pushed back" : "Push back"}
                </button>
              </div>
              <p className="text-[11px] text-inkMuted">
                {isInitialFinding
                  ? "Not decided yet — Accept writes the comment that will be posted."
                  : "Accept writes the reply comment for this round. Push back posts nothing."}
              </p>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
