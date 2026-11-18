import { useEffect, useRef, useState } from "react";
import { CheckCircle2, ChevronDown, MessageSquare, ShieldX } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import type { QuickReviewEvent } from "@/types";

const ACTIONS: {
  event: QuickReviewEvent;
  label: string;
  icon: typeof CheckCircle2;
  iconClass: string;
}[] = [
  { event: "APPROVE", label: "Approve", icon: CheckCircle2, iconClass: "text-success" },
  {
    event: "REQUEST_CHANGES",
    label: "Request changes",
    icon: ShieldX,
    iconClass: "text-danger",
  },
  { event: "COMMENT", label: "Comment", icon: MessageSquare, iconClass: "text-accent" },
];

/**
 * The compact quick-review actions for one inbox card. Selecting an item closes the menu and
 * hands the event to the page, which opens the existing QuickReviewPanel.
 */
export function InboxActionsMenu({
  onSelect,
}: {
  onSelect: (event: QuickReviewEvent) => void;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    menuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  function choose(event: QuickReviewEvent) {
    setOpen(false);
    onSelect(event);
  }

  return (
    <div ref={containerRef} className="relative">
      <Button
        ref={triggerRef}
        variant="secondary"
        size="sm"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        Actions
        <ChevronDown
          className={cn("h-3.5 w-3.5 transition-transform", open ? "rotate-180" : "")}
        />
      </Button>
      {open ? (
        <div
          ref={menuRef}
          role="menu"
          aria-label="Review actions"
          className="absolute right-0 z-20 mt-1 w-44 rounded-lg border border-borderStrong bg-surface p-1 shadow-[0_18px_40px_-20px_rgba(0,0,0,0.9)]"
        >
          {ACTIONS.map(({ event, label, icon: Icon, iconClass }) => (
            <button
              key={event}
              type="button"
              role="menuitem"
              className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-xs text-ink transition-colors hover:bg-surfaceMuted/60 focus:bg-surfaceMuted/60 focus:outline-none"
              onClick={() => choose(event)}
            >
              <Icon className={cn("h-3.5 w-3.5", iconClass)} />
              {label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
