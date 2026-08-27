"use client";

import * as React from "react";
import { Switch as SwitchPrimitive } from "radix-ui";

import { cn } from "@/lib/utils";

function Switch({ className, ...props }: React.ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn("inline-flex h-[19px] w-[34px] shrink-0 cursor-pointer items-center rounded-full bg-[var(--control-off)] p-0.5 outline-none transition-colors data-[state=checked]:bg-[var(--brand)] focus-visible:ring-2 focus-visible:ring-[var(--brand-soft)] disabled:cursor-not-allowed disabled:opacity-55", className)}
      {...props}
    >
      <SwitchPrimitive.Thumb data-slot="switch-thumb" className="block size-[15px] rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,.18)] transition-transform data-[state=checked]:translate-x-[15px]" />
    </SwitchPrimitive.Root>
  );
}

export { Switch };
