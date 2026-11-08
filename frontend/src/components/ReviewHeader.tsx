import { ArrowLeft, ExternalLink, GitBranch, GitCommitHorizontal, Cpu } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/Badge";
import { relativeTime, shortSha } from "@/lib/utils";
import type { CodeReviewDetail } from "@/types";

const statusTone = (status: CodeReviewDetail["status"]) =>
  status === "applied"
    ? ("success" as const)
    : status === "failed"
      ? ("danger" as const)
      : status === "running"
        ? ("warning" as const)
        : status === "in_discussion"
          ? ("warning" as const)
          : ("accent" as const);

const statusLabel = (status: CodeReviewDetail["status"]) =>
  status === "applied"
    ? "Applied to GitHub"
    : status === "failed"
      ? "Failed"
      : status === "running"
        ? "Running"
        : status === "in_discussion"
          ? "In discussion"
          : "Draft";

export function ReviewHeader({ review }: { review: CodeReviewDetail }) {
  return (
    <header className="space-y-3">
      <Link
        to="/"
        className="inline-flex items-center gap-1.5 text-xs text-inkMuted transition-colors hover:text-ink"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> All reviews
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex min-w-0 items-center gap-2">
            <h1 className="truncate text-xl font-semibold tracking-tight">
              {review.pr_title ?? `Review #${review.id}`}
            </h1>
            <a
              href={review.pr_url}
              target="_blank"
              rel="noreferrer"
              title="Open the pull request on GitHub"
              aria-label="Open the pull request on GitHub"
              className="shrink-0 rounded-md p-1 text-inkMuted transition-colors hover:bg-surfaceMuted hover:text-accent"
            >
              <ExternalLink className="h-4 w-4" />
            </a>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-inkMuted">
            <span className="inline-flex items-center gap-1 font-mono">
              <GitBranch className="h-3.5 w-3.5" />
              {review.vcs === "gitlab" ? "GitLab" : "GitHub"} · {review.repo_full_name ?? "unknown repo"}
              {review.pr_number ? `#${review.pr_number}` : ""}
            </span>
            {review.commit_id ? (
              <span className="inline-flex items-center gap-1 font-mono">
                <GitCommitHorizontal className="h-3.5 w-3.5" />
                {shortSha(review.commit_id)}
              </span>
            ) : null}
            {review.model_used ? (
              <span className="inline-flex items-center gap-1">
                <Cpu className="h-3.5 w-3.5" /> {review.model_used}
              </span>
            ) : null}
            <span>· {relativeTime(review.created_at)}</span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {review.suggested_verdict ? (
            <Badge tone="accent">
              AI suggests {review.suggested_verdict}
              {review.confidence_percentage !== null ? ` · ${review.confidence_percentage}%` : ""}
            </Badge>
          ) : null}
          {review.verdict ? <Badge tone="neutral">{review.verdict}</Badge> : null}
          {review.github_review_url ? (
            <a href={review.github_review_url} target="_blank" rel="noreferrer">
              <Badge tone="success">
                <ExternalLink className="h-3 w-3" />{" "}
                {review.vcs === "gitlab" ? "View on GitLab" : "View on GitHub"}
              </Badge>
            </a>
          ) : null}
          <Badge tone={statusTone(review.status)}>{statusLabel(review.status)}</Badge>
        </div>
      </div>
    </header>
  );
}
