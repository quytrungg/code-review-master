import { useState } from "react";

export function useReviewDrafts() {
  const [drafts, setDrafts] = useState<Record<number, string>>({});

  function setDraft(threadId: number, value: string) {
    setDrafts((current) => ({ ...current, [threadId]: value }));
  }

  function clearDrafts(threadIds: number[]) {
    setDrafts((current) => {
      const next = { ...current };
      for (const id of threadIds) delete next[id];
      return next;
    });
  }

  const pendingIds = Object.keys(drafts)
    .map(Number)
    .filter((id) => (drafts[id] ?? "").trim().length > 0);

  return { drafts, setDraft, clearDrafts, pendingIds, pendingCount: pendingIds.length };
}
