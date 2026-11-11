import { useCallback, useRef, useState } from "react";
import { api, ApiError } from "@/services/api";
import type { DiscussionDone } from "@/types";

export interface ThreadStreamState {
  status: "sending" | "done" | "error" | "stopped";
  text: string;
  error: string | null;
}

export interface DiscussionStreamState {
  active: boolean;
  total: number;
  answered: number;
  threads: Record<number, ThreadStreamState>;
  /** Set when the server sent its terminal `done`; cleared on the next start. */
  doneInfo: DiscussionDone | null;
}

const IDLE: DiscussionStreamState = {
  active: false,
  total: 0,
  answered: 0,
  threads: {},
  doneInfo: null,
};

/**
 * Owns one streaming discussion submit at a time: per-thread deltas, terminal states, and
 * cancel. The page reacts to `doneInfo` (refetch, clear drafts, notices); on Stop or a dead
 * connection, threads still marked `sending` are reported as stopped/failed without touching
 * what the server already persisted.
 */
export function useDiscussionStream() {
  const [state, setState] = useState<DiscussionStreamState>(IDLE);
  const controllerRef = useRef<AbortController | null>(null);
  const stoppedRef = useRef(false);

  const patchThread = useCallback((threadId: number, patch: Partial<ThreadStreamState>) => {
    setState((current) => {
      const existing = current.threads[threadId];
      if (!existing) return current;
      return {
        ...current,
        threads: { ...current.threads, [threadId]: { ...existing, ...patch } },
      };
    });
  }, []);

  const stop = useCallback(() => {
    if (!controllerRef.current) return;
    stoppedRef.current = true;
    controllerRef.current.abort();
  }, []);

  const start = useCallback(
    (reviewId: number, threads: { thread_id: number; message: string }[]) => {
      if (controllerRef.current || threads.length === 0) return;
      const controller = new AbortController();
      controllerRef.current = controller;
      stoppedRef.current = false;
      setState({
        active: true,
        total: threads.length,
        answered: 0,
        threads: Object.fromEntries(
          threads.map(({ thread_id }) => [thread_id, { status: "sending" as const, text: "", error: null }]),
        ),
        doneInfo: null,
      });

      api
        .streamDiscussion(
          reviewId,
          threads,
          (event) => {
            if (event.type === "delta") {
              setState((current) => {
                const existing = current.threads[event.thread_id];
                if (!existing) return current;
                return {
                  ...current,
                  threads: {
                    ...current.threads,
                    [event.thread_id]: { ...existing, text: existing.text + event.text },
                  },
                };
              });
            } else if (event.type === "thread_done") {
              patchThread(event.thread_id, { status: "done" });
              setState((current) => ({ ...current, answered: current.answered + 1 }));
            } else if (event.type === "thread_error") {
              patchThread(event.thread_id, { status: "error", error: event.error });
            } else if (event.type === "done") {
              setState((current) => ({
                ...current,
                active: false,
                doneInfo: {
                  answered: event.answered,
                  failed: event.failed,
                  opinion_refreshed: event.opinion_refreshed,
                  warnings: event.warnings,
                },
              }));
            }
          },
          controller.signal,
        )
        .catch((error) => {
          const aborted =
            stoppedRef.current ||
            (error instanceof DOMException && error.name === "AbortError");
          const message = aborted
            ? null
            : error instanceof ApiError
              ? error.message
              : "The discussion stream ended unexpectedly. Reload to see what was answered.";
          // Threads that never reached a terminal event keep nothing on the server.
          setState((current) => {
            const threads = Object.fromEntries(
              Object.entries(current.threads).map(([id, thread]) => [
                id,
                thread.status === "sending"
                  ? {
                      ...thread,
                      status: (aborted ? "stopped" : "error") as "stopped" | "error",
                      error: aborted ? null : message,
                    }
                  : thread,
              ]),
            );
            const terminal = Object.values(threads);
            return {
              ...current,
              threads,
              active: false,
              doneInfo: {
                answered: terminal.filter((thread) => thread.status === "done").length,
                failed: terminal.filter((thread) => thread.status !== "done").length,
                opinion_refreshed: false,
                warnings: aborted ? ["Stopped — completed threads were saved."] : [],
              },
            };
          });
        })
        .finally(() => {
          controllerRef.current = null;
        });
    },
    [patchThread],
  );

  return { ...state, start, stop };
}
