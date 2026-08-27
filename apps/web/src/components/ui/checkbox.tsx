"use client";

import * as React from "react";
import { Checkbox as CheckboxPrimitive } from "radix-ui";
import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

function Checkbox({ className, ...props }: React.ComponentProps<typeof CheckboxPrimitive.Root>) {
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      className={cn("grid size-4 shrink-0 place-items-center rounded-[4px] border border-[var(--line-strong)] bg-white text-white outline-none transition-colors data-[state=checked]:border-[var(--brand)] data-[state=checked]:bg-[var(--brand)] focus-visible:ring-2 focus-visible:ring-[var(--brand-soft)] disabled:cursor-not-allowed disabled:opacity-55", className)}
      {...props}
    >
      <CheckboxPrimitive.Indicator data-slot="checkbox-indicator"><Check size={12} strokeWidth={3} /></CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
}

export { Checkbox };
