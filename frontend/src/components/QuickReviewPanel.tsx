import { useState } from "react";
import { Loader2, Sparkles, X } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Label, Textarea } from "@/components/ui/Input";
import { api, ApiError } from "@/services/api";
import type { CachedPR, QuickReviewEvent } from "@/types";

const EVENT_META: Record<
  QuickReviewEvent,
  { label: string; tone: "success" | "danger" | "accent"; bodyRequired: boolean; hint: string }
> = {
  APPROVE: {
    label: "Approve",
    tone: "success",
    bodyRequired: false,
    hint: "An optional note goes with the approval.",
  },
  REQUEST_CHANGES: {
    label: "Request changes",
    tone: "danger",
    bodyRequired: true,
    hint: "Tell the author what must change.",
  },
  COMMENT: {
    label: "Comment",
    tone: "accent",
    bodyRequired: true,
    hint: "A general comment on the pull request.",
  },
};

/**
 * The slide-over for one quick action on an inbox item. Owns the quick-review and polish calls;
 * the page owns the list and re-renders the card from `onDone`.
 */
export function QuickReviewPanel({
  pr,
  event,
  onClose,
  onDone,
}: {
  pr: CachedPR;
  event: QuickReviewEvent;
  onClose: () => void;
  onDone: (updated: CachedPR) => void;
}) {
  const meta = EVENT_META[event];
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState<"submit" | "polish" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setBusy("submit");
    setError(null);
    try {
      onDone(await api.quickReview(pr.id, event, body.trim() || undefined));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The review could not be posted.");
      setBusy(null);
    }
  }

  async function polish() {
    setBusy("polish");
    setError(null);
    try {
      const result = await api.polishComment(body.trim());
      setBody(result.text);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The draft could not be polished.");
    } finally {
      setBusy(null);
    }
  }

  const blocked = meta.bodyRequired && !body.trim();

  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true">
      <button
        type="button"
        aria-label="Close quick review"
        className="absolute inset-0 bg-canvas/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <aside className="relative flex h-full w-full max-w-md flex-col border-l border-border bg-surface shadow-2xl">
        <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0 space-y-1.5">
            <Badge tone={meta.tone}>{meta.label}</Badge>
            <h2 className="text-sm font-semibold text-ink">
              {pr.title} <span className="text-inkMuted">#{pr.pr_number}</span>
            </h2>
            <p className="text-xs text-inkMuted">
              {pr.repo_owner}/{pr.repo_name} · by {pr.author_username}
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </header>

        <div className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="quick-review-body">Review comment</Label>
              <Button
                variant="ghost"
                size="sm"
                disabled={busy !== null || !body.trim()}
                onClick={() => void polish()}
                title="Rewrite the draft for clarity with the active model"
              >
                {busy === "polish" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Sparkles className="h-3.5 w-3.5" />
                )}
                Polish
              </Button>
            </div>
            <Textarea
              id="quick-review-body"
              rows={8}
              value={body}
              onChange={(event) => setBody(event.target.value)}
              placeholder={meta.hint}
            />
            <p className="text-[11px] text-inkMuted">
              Markdown is rendered on GitHub. {meta.hint}
            </p>
          </div>
          {error ? <p className="text-xs text-danger">{error}</p> : null}
        </div>

        <footer className="border-t border-border px-5 py-4">
          <Button
            className="w-full"
            variant={meta.tone === "danger" ? "danger" : meta.tone === "success" ? "success" : "primary"}
            disabled={busy !== null || blocked}
            onClick={() => void submit()}
          >
            {busy === "submit" ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {meta.label} on GitHub
          </Button>
          {blocked ? (
            <p className="mt-2 text-center text-[11px] text-inkMuted">
              A comment body is required for this action.
            </p>
          ) : null}
        </footer>
      </aside>
    </div>
  );
}
