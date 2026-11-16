import { useEffect } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

/**
 * The one dialog shell. Owns the overlay, escape handling and the close button; the caller owns the
 * open/close state and unmounts the content, which is also how a form resets itself.
 */
export function Modal({
  title,
  description,
  onClose,
  children,
  footer,
  width = "max-w-lg",
}: {
  title: string;
  description?: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: string;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <button
        type="button"
        aria-label={`Close ${title}`}
        className="absolute inset-0 bg-canvas/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div
        className={cn(
          "relative flex max-h-[calc(100vh-2rem)] w-full flex-col rounded-xl border border-border bg-surface shadow-2xl",
          width,
        )}
      >
        <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0 space-y-0.5">
            <h2 className="text-sm font-semibold text-ink">{title}</h2>
            {description ? <p className="text-xs text-inkMuted">{description}</p> : null}
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer ? (
          <footer className="flex justify-end gap-2 border-t border-border px-5 py-4">{footer}</footer>
        ) : null}
      </div>
    </div>
  );
}
