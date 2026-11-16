import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Modal } from "@/components/ui/Modal";
import { api, ApiError } from "@/services/api";
import { relativeTime } from "@/lib/utils";
import type { FindingHit } from "@/types";

/**
 * The dialog behind the reviews page's magnifier button. Cross-review finding search: results are
 * evidence — "similar to", never "duplicate of". Closing it unmounts the state, so reopening starts
 * from an empty field rather than a stale result set.
 */
export function FindingSearchModal({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<FindingHit[] | null>(null);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const term = query.trim();
    if (!term) {
      setError("Type a few words from the finding you remember.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await api.searchFindings({ q: term, limit: 50 });
      setHits(response.items);
      setTotal(response.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not search findings");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Search findings"
      description="Look across every review for a pattern you remember. Matches are similar, not identical."
      onClose={onClose}
      width="max-w-2xl"
    >
      <div className="space-y-3">
        <form onSubmit={(event) => void submit(event)} className="flex gap-2">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="e.g. unbounded query"
            aria-label="Search findings"
            autoFocus
          />
          <Button type="submit" variant="secondary" disabled={busy}>
            {busy ? "Searching…" : "Search"}
          </Button>
        </form>

        {error ? <p className="text-xs text-danger">{error}</p> : null}

        {hits !== null ? (
          hits.length === 0 ? (
            <p className="text-xs text-inkMuted">No earlier findings match that phrase.</p>
          ) : (
            <div className="space-y-1.5">
              <p className="text-[11px] text-inkMuted">
                {total} match{total === 1 ? "" : "es"}
                {total > hits.length ? ` · showing the ${hits.length} most recent` : ""}
              </p>
              <ul className="divide-y divide-border rounded-xl border border-border">
                {hits.map((hit) => (
                  <li key={hit.thread_id} className="space-y-1 px-3 py-2">
                    <Link
                      to={`/reviews/${hit.review_id}`}
                      className="text-xs font-medium text-accent hover:text-accentStrong"
                    >
                      Review #{hit.review_id} · {hit.file_path}:{hit.line_number}
                    </Link>
                    <p className="text-xs text-inkMuted">{hit.snippet}</p>
                    <p className="flex flex-wrap items-center gap-2 text-[11px] text-inkMuted">
                      <span>{hit.repo_full_name ?? "unknown repo"}</span>
                      <span>{relativeTime(hit.created_at)}</span>
                      <Badge tone={hit.accepted ? "success" : "neutral"}>
                        {hit.accepted ? "Accepted then" : "Not accepted"}
                      </Badge>
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )
        ) : (
          <p className="text-xs text-inkMuted">
            Search runs over every finding this account has kept, newest first.
          </p>
        )}
      </div>
    </Modal>
  );
}
