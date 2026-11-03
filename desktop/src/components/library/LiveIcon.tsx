import { cn } from "@/lib/utils";

/** Concentric rings, the usual mark for a Live Photo. */
export function LiveIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={cn("size-3", className)} fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.6" strokeDasharray="1.6 2.4" />
      <circle cx="12" cy="12" r="6" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="12" cy="12" r="2.6" fill="currentColor" />
    </svg>
  );
}
