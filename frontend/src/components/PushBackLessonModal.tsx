import { useEffect, useState } from "react";
import { BookPlus, Check, Copy, Loader2, Sparkles, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Label, Select, Textarea } from "@/components/ui/Input";
import { api, ApiError } from "@/services/api";
import type { Foundation, ReviewThread } from "@/types";

/**
 * The beta-gated push-back lesson dialog (Settings → Beta features → Push-back lessons).
 * Step 1 asks whether to record the lesson; step 2 drafts one, lets the reviewer pick a
 * foundation and edit the wording, then applies it. Either way the push back proceeds —
 * the page sends the decision only after this modal resolves.
 */
export function PushBackLessonModal({
  reviewId,
  thread,
  uploadsEnabled,
  onResolve,
}: {
  reviewId: number;
  thread: ReviewThread;
  /** False on serverless: nothing can be written, so step 2 offers copy-to-clipboard. */
  uploadsEnabled: boolean;
  /** Called exactly once with the apply result when a lesson was applied, else with null. */
  onResolve: (applied: { path: string; foundation: string } | null) => void;
}) {
  const [step, setStep] = useState<1 | 2>(1);
  const [foundations, setFoundations] = useState<Foundation[]>([]);
  const [foundation, setFoundation] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState<{ path: string; foundation: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (step !== 2) return;
    let cancelled = false;
    setDrafting(true);
    setError(null);
    Promise.all([api.listSkills(), api.draftLesson(reviewId, thread.id)])
      .then(([skills, draft]) => {
        if (cancelled) return;
        setFoundations(skills.foundations);
        setFoundation((current) => current || skills.default);
        setTitle(draft.title);
        setBody(draft.body);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "The lesson could not be drafted.");
      })
      .finally(() => {
        if (!cancelled) setDrafting(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reviewId, thread.id, step]);

  function close(result: { path: string; foundation: string } | null) {
    onResolve(result);
  }

  async function apply() {
    setApplying(true);
    setError(null);
    try {
      const result = await api.applyLesson(reviewId, thread.id, {
        foundation_id: foundation,
        title: title.trim(),
        body: body.trim(),
      });
      setApplied({ path: result.path, foundation: result.foundation });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The lesson could not be saved.");
      setApplying(false);
    }
  }

  async function copyMarkdown() {
    try {
      await navigator.clipboard.writeText(`# ${title.trim()}\n\n${body.trim()}`);
      setCopied(true);
    } catch {
      setError("Copy failed. Select the text and copy it by hand.");
    }
  }

  const canApply = Boolean(foundation && title.trim() && body.trim()) && !applying;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <button
        type="button"
        aria-label="Close push-back lesson"
        className="absolute inset-0 bg-canvas/60 backdrop-blur-sm"
        onClick={() => close(applied)}
      />
      <div className="relative w-full max-w-lg space-y-4 rounded-xl border border-border bg-surface p-5 shadow-2xl">
        <header className="flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <h2 className="text-sm font-semibold text-ink">Push back this finding</h2>
            <p className="truncate text-xs text-inkMuted">
              {thread.file_path} · thread #{thread.id}
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={() => close(applied)} aria-label="Close" disabled={applying}>
            <X className="h-4 w-4" />
          </Button>
        </header>

        {step === 1 ? (
          <>
            <p className="text-sm text-ink">
              Record the lesson from this push back in a skill foundation, so this kind of finding
              is checked before it is raised again?
            </p>
            <footer className="flex justify-end gap-2 border-t border-border pt-4">
              <Button variant="secondary" onClick={() => close(null)}>
                No, just push back
              </Button>
              <Button onClick={() => setStep(2)}>
                <BookPlus className="h-4 w-4" /> Yes, record a lesson
              </Button>
            </footer>
          </>
        ) : applied ? (
          <>
            <p className="flex items-center gap-2 text-sm text-success">
              <Check className="h-4 w-4" /> Lesson saved to {applied.foundation} — {applied.path}
            </p>
            <footer className="flex justify-end border-t border-border pt-4">
              <Button onClick={() => close(applied)}>Done — push back</Button>
            </footer>
          </>
        ) : (
          <>
            {drafting ? (
              <p className="flex items-center gap-2 text-sm text-inkMuted">
                <Loader2 className="h-4 w-4 animate-spin" /> Drafting a rule from this finding…
              </p>
            ) : (
              <>
                <div className="space-y-2">
                  <Label htmlFor="lesson-foundation">Skill foundation</Label>
                  <Select
                    id="lesson-foundation"
                    value={foundation}
                    onChange={(event) => setFoundation(event.target.value)}
                    disabled={applying || foundations.length === 0}
                  >
                    {foundations.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.id} · {item.file_count} file(s)
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="lesson-title">Lesson title</Label>
                  <Textarea
                    id="lesson-title"
                    rows={2}
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    disabled={applying}
                  />
                </div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label htmlFor="lesson-body">Rule for future reviews</Label>
                    <span className="text-[11px] text-inkMuted">editable — the wording is yours</span>
                  </div>
                  <Textarea
                    id="lesson-body"
                    rows={6}
                    value={body}
                    onChange={(event) => setBody(event.target.value)}
                    disabled={applying}
                  />
                </div>
                {error ? <p className="text-xs text-danger">{error}</p> : null}
                <footer className="flex flex-wrap justify-end gap-2 border-t border-border pt-4">
                  {uploadsEnabled ? (
                    <>
                      <Button variant="ghost" onClick={() => close(null)} disabled={applying}>
                        Cancel, just push back
                      </Button>
                      <Button onClick={() => void apply()} disabled={!canApply}>
                        {applying ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                        Save lesson
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button variant="ghost" onClick={() => close(null)}>
                        Close
                      </Button>
                      <Button variant="secondary" onClick={() => void copyMarkdown()} disabled={copied}>
                        {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                        {copied ? "Copied" : "Copy the lesson"}
                      </Button>
                    </>
                  )}
                </footer>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
