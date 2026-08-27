import * as React from "react";

import { cn } from "@/lib/utils";

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "min-h-20 w-full resize-y rounded-[7px] border border-[var(--line)] bg-white px-[9px] py-2 text-[length:var(--text-sm)] text-[var(--ink)] outline-none transition-[border-color,box-shadow] placeholder:text-[var(--ink-faint)] focus:border-[var(--brand)] focus:shadow-[0_0_0_3px_var(--brand-soft)] disabled:cursor-not-allowed disabled:opacity-55",
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
