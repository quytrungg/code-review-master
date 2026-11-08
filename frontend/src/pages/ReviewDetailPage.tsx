import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { FileSearch, Loader2, RefreshCw, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { CodeSnippetBox } from "@/components/CodeSnippetBox";
import { CommentBox } from "@/components/CommentBox";
import { IngestProgress } from "@/components/IngestProgress";
import { ReviewHeader } from "@/components/ReviewHeader";
import { SplitPane } from "@/components/SplitPane";
import { StickyActionBar } from "@/components/StickyActionBar";
import { ThreadFilterBar, type FilterCounts, type ThreadFilter } from "@/components/ThreadFilterBar";
import { WarningsBanner } from "@/components/WarningsBanner";
import { useReviewDrafts } from "@/hooks/useReviewDrafts";
import { applyButtonLabel, pendingApplyCount } from "@/lib/utils";
import { api, ApiError } from "@/services/api";
import type { CodeReviewDetail, ReviewVerdict, RoundDecision } from "@/types";

export function ReviewDetailPage() {
  const { id } = useParams();
  const reviewId = Number(id);

  const [review, setReview] = useState<CodeReviewDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [verdict, setVerdict] = useState<ReviewVerdict>("COMMENT");

  const [filter, setFilter] = useState<ThreadFilter>("all");
  const [syncing, setSyncing] = useState(false);
  const [decidingRoundId, setDecidingRoundId] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [applying, setApplying] = useState(false);
  const [sendingIds, setSendingIds] = useState<number[]>([]);
  const [threadErrors, setThreadErrors] = useState<Record<number, string>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [applyWarnings, setApplyWarnings] = useState<string[]>([]);

  const { drafts, setDraft, clearDrafts, pendingIds, pendingCount } = useReviewDrafts();
  const codeRefs = useRef<Record<number, HTMLDivElement | null>>({});

  const load = useCallback(async () => {
    if (!Number.isFinite(reviewId)) {
      setNotFound(true);
      setLoading(false);
      return;
    }
    setLoading(true);
    setLoadError(null);
    setNotFound(false);
    try {
      const data = await api.getReview(reviewId);
      setReview(data);
      setVerdict(data.verdict ?? "COMMENT");
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) setNotFound(true);
      else setLoadError(error instanceof ApiError ? error.message : "Failed to load the review");
    } finally {
      setLoading(false);
    }
  }, [reviewId]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleIngestFinished = useCallback(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedId(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function select(threadId: number) {
    setSelectedId((current) => (current === threadId ? null : threadId));
    const node = codeRefs.current[threadId];
    if (node && selectedId !== threadId) {
      node.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }

  function jumpToOrdinal(ordinal: number) {
    const thread = review?.threads[ordinal - 1];
    if (!thread) return;
    setSelectedId(thread.id);
    codeRefs.current[thread.id]?.scrollIntoView({ block: "center", behavior: "smooth" });
    document
      .getElementById(`thread-${thread.id}`)
      ?.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  async function applyToGithub() {
    if (!review) return;
    setApplying(true);
    setActionError(null);
    setNotice(null);
    setApplyWarnings([]);
    try {
      const response = await api.applyReview(review.id, { event: verdict });
      setReview(response.review);
      setApplyWarnings(response.warnings);
      const parts: string[] = [];
      if (response.comments_posted > 0) {
        parts.push(
          `${response.comments_posted} inline comment${response.comments_posted === 1 ? "" : "s"}`,
        );
      }
      if (response.replies_posted > 0) {
        parts.push(
          `${response.replies_posted} repl${response.replies_posted === 1 ? "y" : "ies"}`,
        );
      }
      setNotice(
        `Published${parts.length > 0 ? ` · ${parts.join(" · ")}` : ""}` +
          (response.dropped.length > 0
            ? ` · ${response.dropped.length} withdrawn thread(s) excluded`
            : "") +
          (response.summarised || response.comments_posted === 0
            ? ""
            : " · summariser unavailable, used last messages") +
          (response.github_review_url ? " · link in the header" : ""),
      );
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : "Failed to apply the review");
    } finally {
      setApplying(false);
    }
  }

  async function submitDrafts() {
    if (!review || pendingIds.length === 0) return;
    setSubmitting(true);
    setSendingIds(pendingIds);
    setActionError(null);
    setNotice(null);
    setThreadErrors({});
    try {
      const response = await api.discuss(
        review.id,
        pendingIds.map((threadId) => ({
          thread_id: threadId,
          message: (drafts[threadId] ?? "").trim(),
        })),
      );
      setReview(response.review);
      const succeeded = response.results.filter((result) => result.ok).map((result) => result.thread_id);
      const failed = response.results.filter((result) => !result.ok);
      clearDrafts(succeeded);
      if (failed.length > 0) {
        setThreadErrors(
          Object.fromEntries(
            failed.map((result) => [result.thread_id, result.error ?? "The model did not reply."]),
          ),
        );
      }
      setNotice(
        `${succeeded.length} repl${succeeded.length === 1 ? "y" : "ies"} added` +
          (failed.length > 0 ? ` · ${failed.length} failed (draft kept)` : "") +
          (response.opinion_refreshed
            ? ` · AI opinion updated to ${response.review.suggested_verdict ?? "unknown"}` +
              (response.review.confidence_percentage !== null
                ? ` (${response.review.confidence_percentage}%)`
                : "")
            : response.warnings.length > 0
              ? ` · ${response.warnings[0]}`
              : ""),
      );
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : "Failed to submit responses");
    } finally {
      setSubmitting(false);
      setSendingIds([]);
    }
  }

  async function syncFromGithub() {
    if (!review) return;
    setSyncing(true);
    setActionError(null);
    setNotice(null);
    setApplyWarnings([]);
    try {
      const response = await api.syncReview(review.id);
      setReview(response.review);
      setApplyWarnings(response.warnings);
      setNotice(
        response.new_rounds === 0 && response.new_threads === 0
          ? "No new comments on GitHub."
          : `Fetched ${response.new_rounds} new repl${
              response.new_rounds === 1 ? "y" : "ies"
            } and ${response.new_threads} new thread${response.new_threads === 1 ? "" : "s"}.`,
      );
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  }

  async function decideRound(roundId: number, decision: RoundDecision, summary?: string) {
    if (!review) return;
    setDecidingRoundId(roundId);
    setActionError(null);
    setNotice(null);
    try {
      const response = await api.decideRound(review.id, roundId, decision, summary);
      setReview(response.review);
      const base =
        decision === "push_back"
          ? "Round pushed back — nothing will be posted for it."
          : summary
            ? "Comment saved — apply when you are ready."
            : "Comment drafted from the thread — edit the wording if you like, then apply.";
      setNotice(response.warnings.length > 0 ? `${base} ${response.warnings.join(" ")}` : base);
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : "Could not update the round");
    } finally {
      setDecidingRoundId(null);
    }
  }

  if (loading) {
    return (
      <p className="flex items-center gap-2 text-sm text-inkMuted">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading review…
      </p>
    );
  }

  if (notFound) {
    return (
      <Card className="p-6">
        <h1 className="text-lg font-semibold">Review not found</h1>
        <p className="mt-1 text-sm text-inkMuted">This review does not exist or was deleted.</p>
        <Link to="/">
          <Button className="mt-4" variant="secondary">
            Back to reviews
          </Button>
        </Link>
      </Card>
    );
  }

  if (loadError || !review) {
    return (
      <Card className="p-6">
        <p className="text-sm text-danger">{loadError ?? "Review unavailable"}</p>
        <Button className="mt-3" variant="secondary" onClick={() => void load()}>
          <RefreshCw className="h-4 w-4" /> Retry
        </Button>
      </Card>
    );
  }

  const threads = review.threads;
  const counts: FilterCounts = {
    all: threads.length,
    ai: threads.filter((thread) => thread.origin === "AI_GENERATED").length,
    github: threads.filter((thread) => thread.origin === "GITHUB_EXISTING").length,
    needs: threads.filter((thread) => thread.thread_status === "needs_response").length,
  };
  const visibleThreads = threads.filter((thread) => {
    if (filter === "ai") return thread.origin === "AI_GENERATED";
    if (filter === "github") return thread.origin === "GITHUB_EXISTING";
    if (filter === "needs") return thread.thread_status === "needs_response";
    return true;
  });
  const pending = pendingApplyCount(threads);
  const threadOptions = threads.map((thread) => ({
    ordinal: thread.ordinal,
    file_path: thread.file_path,
    line_number: thread.line_number,
    excerpt: (thread.messages[0]?.content ?? "").replace(/\s+/g, " ").slice(0, 90),
  }));

  return (
    <div className="flex flex-col gap-4 pb-44">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <ReviewHeader review={review} />
        <div className="flex items-center gap-1.5">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void syncFromGithub()}
            disabled={syncing || review.vcs !== "github" || review.status === "running"}
            title={
              review.vcs !== "github"
                ? "Syncing inbound comments is available for GitHub reviews"
                : "Fetch comments and replies added on GitHub"
            }
          >
            <RotateCw className={syncing ? "h-3.5 w-3.5 animate-spin" : "h-3.5 w-3.5"} />
            {syncing ? "Syncing…" : "Sync GitHub"}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </Button>
        </div>
      </div>

      <WarningsBanner
        error={review.error}
        notes={[review.notes, ...applyWarnings].filter(Boolean).join("\n")}
      />

      {review.status === "running" ? (
        <IngestProgress reviewId={review.id} onFinished={handleIngestFinished} />
      ) : threads.length === 0 ? (
        <Card className="flex flex-col items-center gap-2 p-10 text-center">
          <FileSearch className="h-6 w-6 text-inkMuted" />
          <p className="text-sm text-ink">No findings for this pull request</p>
          <p className="max-w-sm text-xs text-inkMuted">
            {review.error
              ? "The model call failed, so there is nothing to discuss. Retry the review from the dashboard."
              : "The model reviewed the diff against your skill files and had nothing to flag."}
          </p>
        </Card>
      ) : (
        <>
          <ThreadFilterBar value={filter} counts={counts} onChange={setFilter} />
          {visibleThreads.length === 0 ? (
            <Card className="p-6 text-center text-sm text-inkMuted">
              No threads match this filter.
            </Card>
          ) : null}
          <SplitPane
          left={visibleThreads.map((thread, index) => (
            <CodeSnippetBox
              key={thread.id}
              ref={(node) => {
                codeRefs.current[thread.id] = node;
              }}
              index={index}
              thread={thread}
              selected={selectedId === thread.id}
              onSelect={() => select(thread.id)}
            />
          ))}
          right={visibleThreads.map((thread, index) => (
            <CommentBox
              key={thread.id}
              index={index}
              thread={thread}
              selected={selectedId === thread.id}
              draft={drafts[thread.id] ?? ""}
              threadCount={threads.length}
              threadOptions={threadOptions}
              onSelect={() => setSelectedId(thread.id)}
              onDraftChange={(value) => setDraft(thread.id, value)}
              onJumpToOrdinal={jumpToOrdinal}
              onDecide={(roundId, decision) => void decideRound(roundId, decision)}
              onSaveSummary={(roundId, text) => void decideRound(roundId, "accept", text)}
              decidingRoundId={decidingRoundId}
              sending={sendingIds.includes(thread.id)}
              submitDisabledReason={threadErrors[thread.id] ?? null}
            />
          ))}
          />
        </>
      )}

      {review.status !== "running" ? (
        <StickyActionBar
          pendingCount={pendingCount}
          verdict={verdict}
          onVerdict={setVerdict}
          aiVerdict={review.suggested_verdict}
          aiConfidence={review.confidence_percentage}
          aiNote={review.suggested_verdict_note}
          onUseAiVerdict={
            review.suggested_verdict ? () => setVerdict(review.suggested_verdict!) : undefined
          }
          onSubmit={() => void submitDrafts()}
          onApply={() => void applyToGithub()}
          submitting={submitting}
          applying={applying}
          applyLabel={applyButtonLabel(pending)}
          applyCount={pending.total}
          submitDisabledReason="Type a reply in any thread to enable bulk submit."
          error={actionError}
          notice={notice}
        />
      ) : null}
    </div>
  );
}
