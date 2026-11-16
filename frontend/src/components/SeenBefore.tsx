import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { History } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { api, ApiError } from "@/services/api";
import type { FindingHit } from "@/types";

/** Prior findings in this repository with the same normalised key. Evidence, not a duplicate claim. */
export function SeenBefore({ reviewId, threadId }: { reviewId: number; threadId: number }) {
  const [hits, setHits] = useState<FindingHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setHits(null);
    setError(null);
    api
      .similarFindings(reviewId, threadId)
      .then((response) => {
        if (!cancelled) setHits(response.items);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Could not check the history");
      });
    return () => {
      cancelled = true;
    };
  }, [reviewId, threadId]);

  if (error) return null;
  if (hits === null || hits.length === 0) return null;

  return (
    <div className="rounded-xl border border-border bg-surfaceMuted/40 px-3 py-2.5 text-xs">
      <p className="flex items-center gap-1.5 font-medium text-ink">
        <History className="h-3.5 w-3.5 text-accent" /> Seen before in this repository
      </p>
      <ul className="mt-1.5 space-y-1">
        {hits.map((hit) => (
          <li key={hit.thread_id} className="flex flex-wrap items-center gap-2 text-inkMuted">
            <Link
              to={`/reviews/${hit.review_id}`}
              className="text-accent transition-colors hover:text-accentStrong"
            >
              Review #{hit.review_id} · {hit.file_path}:{hit.line_number}
            </Link>
            <Badge tone={hit.accepted ? "success" : "neutral"}>
              {hit.accepted ? "Accepted then" : "Not accepted"}
            </Badge>
          </li>
        ))}
      </ul>
      <p className="mt-1 text-[11px] text-inkMuted">
        Similar wording in the same repository — not proof that it is the same defect.
      </p>
    </div>
  );
}
