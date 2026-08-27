import * as React from "react";
import type { ReactNode } from "react";
import { Search } from "lucide-react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

function SearchField({ className, inputClassName, icon, ...props }: React.ComponentProps<typeof Input> & { inputClassName?: string; icon?: ReactNode }) {
  return (
    <label className={cn("flex h-[34px] items-center gap-2 rounded-[7px] border border-[var(--line)] bg-white px-2.5 text-[var(--ink-faint)] focus-within:border-[var(--brand)] focus-within:shadow-[0_0_0_3px_var(--brand-soft)]", className)}>
      {icon ?? <Search size={14} aria-hidden="true" />}
      <Input className={cn("h-full border-0 bg-transparent px-0 shadow-none focus:border-0 focus:bg-transparent focus:shadow-none", inputClassName)} {...props} />
    </label>
  );
}

export { SearchField };
