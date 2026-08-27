"use client";

import * as React from "react";
import { Label as LabelPrimitive } from "radix-ui";

import { cn } from "@/lib/utils";

function Label({ className, ...props }: React.ComponentProps<typeof LabelPrimitive.Root>) {
  return (
    <LabelPrimitive.Root
      data-slot="label"
      className={cn("flex items-center gap-2 text-[length:var(--text-xs)] font-semibold text-[#4e504a]", className)}
      {...props}
    />
  );
}

export { Label };
