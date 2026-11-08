import { useEffect, useState } from "react";
import { Check, Loader2, XCircle } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { api } from "@/services/api";
import { cn } from "@/lib/utils";
import type { ProgressEvent } from "@/types";

type ConnectionState = "connecting" | "live" | "done" | "failed";

/**
 * Subscribes to the review's Server-Sent Events stream and renders the live pipeline.
 * The stream replays history, so mounting after the job started still shows every step.
 */
export function IngestProgress({
  reviewId,
  onFinished,
}: {
  reviewId: number;
  onFinished: () => void;
}) {
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [state, setState] = useState<ConnectionState>("connecting");
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    let finished = false;
    const source = new EventSource(api.eventsUrl(reviewId));

    const push = (event: ProgressEvent) =>
      setEvents((current) =>
        current.some((item) => item.seq === event.seq) ? current : [...current, event],
      );

    const finish = (next: ConnectionState) => {
      if (finished) return;
      finished = true;
      setState(next);
      source.close();
      onFinished();
    };

    source.addEventListener("open", () => setState("live"));
    source.addEventListener("progress", (event) => {
      setState("live");
      push(JSON.parse((event as MessageEvent).data));
    });
    source.addEventListener("done", (event) => {
      push(JSON.parse((event as MessageEvent).data));
      finish("done");
    });
    source.addEventListener("failed", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as ProgressEvent;
      push(payload);
      setFailure(payload.detail ?? "The review failed.");
      finish("failed");
    });
    source.onerror = () => {
      // The browser retries on its own; surface it only if the stream never opened.
      setState((current) => (current === "connecting" ? "connecting" : current));
    };

    return () => source.close();
  }, [reviewId, onFinished]);

  const latest = events[events.length - 1];
  const progress = latest?.progress ?? 0;
  const steps = events.filter((event) => event.stage !== "done" && event.stage !== "error");

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-3">
        <span
          className={cn(
            "grid h-6 w-6 place-items-center rounded-full",
            state === "failed" ? "bg-danger/15 text-danger" : "bg-accent/15 text-accent",
          )}
        >
          {state === "failed" ? (
            <XCircle className="h-3.5 w-3.5" />
          ) : state === "done" ? (
            <Check className="h-3.5 w-3.5 text-success" />
          ) : (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          )}
        </span>
        <div className="min-w-0">
          <p className="text-sm font-medium text-ink">
            {failure ?? (state === "done" ? "Review ready" : latest?.label ?? "Connecting to the review job…")}
          </p>
          <p className="truncate text-xs text-inkMuted">
            {failure ?? latest?.detail ?? "Streaming progress from the backend."}
          </p>
        </div>
        <span className="ml-auto font-mono text-xs text-inkMuted">{progress}%</span>
      </div>

      <div className="h-1 w-full bg-surfaceMuted">
        <div
          className={cn(
            "h-full transition-all duration-500",
            state === "failed" ? "bg-danger" : "bg-accent",
          )}
          style={{ width: `${Math.min(100, Math.max(2, progress))}%` }}
        />
      </div>

      <ol className="max-h-64 space-y-2 overflow-y-auto px-5 py-4">
        {steps.map((event) => (
          <li key={`${event.seq}-${event.stage}`} className="flex items-start gap-2 text-xs">
            <span
              className={cn(
                "mt-1 h-1.5 w-1.5 shrink-0 rounded-full",
                event.level === "error"
                  ? "bg-danger"
                  : event.level === "warn"
                    ? "bg-warning"
                    : "bg-accent/70",
              )}
            />
            <div>
              <span className="text-ink">{event.label}</span>
              {event.detail ? <span className="text-inkMuted"> — {event.detail}</span> : null}
            </div>
          </li>
        ))}
        {steps.length === 0 ? (
          <li className="text-xs text-inkMuted">Waiting for the first step…</li>
        ) : null}
      </ol>
    </Card>
  );
}
