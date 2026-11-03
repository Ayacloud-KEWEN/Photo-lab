import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export function Input({ className, type, ...props }: ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-8 w-full min-w-0 rounded-md border border-input bg-background/60 px-2.5 text-[13px] text-foreground outline-none transition-colors placeholder:text-subtle-foreground focus-visible:border-ring/70 focus-visible:outline-none disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
