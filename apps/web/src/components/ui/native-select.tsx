import * as React from "react";

import { cn } from "@/lib/utils";

function NativeSelect({ className, ...props }: React.ComponentProps<"select">) {
  return (
    <select
      data-slot="native-select"
      className={cn("h-[34px] cursor-pointer rounded-[7px] border border-[var(--line)] bg-[var(--surface-white)] py-0 pl-2.5 pr-7 text-[length:var(--text-md)] text-[var(--control-muted-foreground)] outline-none transition-[border-color,box-shadow] focus:border-[var(--brand)] focus:shadow-[0_0_0_3px_var(--brand-soft)] disabled:cursor-not-allowed disabled:opacity-55", className)}
      {...props}
    />
  );
}

export { NativeSelect };
