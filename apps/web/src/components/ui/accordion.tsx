"use client";

import * as React from "react";
import { Accordion as AccordionPrimitive } from "radix-ui";

import { cn } from "@/lib/utils";

const Accordion = AccordionPrimitive.Root;

function AccordionItem({ className, ...props }: React.ComponentProps<typeof AccordionPrimitive.Item>) {
  return <AccordionPrimitive.Item data-slot="accordion-item" className={cn(className)} {...props} />;
}

function AccordionHeader({ className, ...props }: React.ComponentProps<typeof AccordionPrimitive.Header>) {
  return <AccordionPrimitive.Header data-slot="accordion-header" className={cn("m-0", className)} {...props} />;
}

function AccordionTrigger({ className, ...props }: React.ComponentProps<typeof AccordionPrimitive.Trigger>) {
  return <AccordionPrimitive.Trigger data-slot="accordion-trigger" className={cn(className)} {...props} />;
}

function AccordionContent({ className, children, ...props }: React.ComponentProps<typeof AccordionPrimitive.Content>) {
  return (
    <AccordionPrimitive.Content
      data-slot="accordion-content"
      className={cn("overflow-hidden data-[state=closed]:animate-accordion-up data-[state=open]:animate-accordion-down", className)}
      {...props}
    >
      {children}
    </AccordionPrimitive.Content>
  );
}

export { Accordion, AccordionItem, AccordionHeader, AccordionTrigger, AccordionContent };
