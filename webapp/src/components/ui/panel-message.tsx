import { cn } from "@/lib/utils";

/**
 * PanelMessage — the honest degraded state. When a feed is unreachable or empty,
 * a panel renders one of these instead of fabricating data. `tone="warn"` tints
 * it toward the caution amber for live-feed failures.
 */
export function PanelMessage({
  className,
  tone = "muted",
  children,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement> & { tone?: "muted" | "warn" }) {
  return (
    <p
      role="status"
      className={cn("panel-msg", tone === "warn" && "panel-msg--warn", className)}
      {...props}
    >
      {children}
    </p>
  );
}
