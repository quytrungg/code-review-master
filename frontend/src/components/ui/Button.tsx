import * as React from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success";
type Size = "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary:
    "bg-accentStrong text-white hover:bg-accent border border-accentStrong/60 shadow-[0_6px_20px_-12px_rgba(91,107,250,0.9)]",
  secondary: "bg-surfaceMuted text-ink hover:bg-border border border-border",
  ghost: "bg-transparent text-inkMuted hover:text-ink hover:bg-surfaceMuted border border-transparent",
  danger: "bg-danger/10 text-danger hover:bg-danger/20 border border-danger/40",
  success: "bg-success/10 text-success hover:bg-success/20 border border-success/40",
};

const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
  lg: "h-11 px-5 text-sm gap-2",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "md", ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center rounded-lg font-medium transition-colors transition-shadow disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  ),
);
Button.displayName = "Button";
