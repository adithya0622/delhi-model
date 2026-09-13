import { cn } from "@/lib/utils";

/**
 * Skeleton — a shimmering placeholder block. Uses the ported `.skeleton` class
 * (which self-disables its animation under reduced motion via `[data-anim]`).
 * Size it with utility classes or inline style via `className`/`style`.
 */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("skeleton", className)} aria-hidden="true" {...props} />;
}
