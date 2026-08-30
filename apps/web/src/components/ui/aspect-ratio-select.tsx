"use client";

import { AudioLines, Check, ChevronDown } from "lucide-react";
import { Select } from "radix-ui";

import { cn } from "@/lib/utils";

type AspectRatioValue = "9:16" | "1:1" | "16:9" | "Audio";

const ASPECT_RATIO_OPTIONS: ReadonlyArray<{
  value: AspectRatioValue;
  description: string;
}> = [
  { value: "9:16", description: "Portrait" },
  { value: "1:1", description: "Square" },
  { value: "16:9", description: "Landscape" },
  { value: "Audio", description: "Audio only" },
];

function AspectRatioGlyph({ value, className }: { value: AspectRatioValue; className?: string }) {
  const frameSize = value === "9:16"
    ? "h-[25px] w-[14px]"
    : value === "1:1"
      ? "h-[22px] w-[22px]"
      : "h-[17px] w-[30px]";

  return (
    <i
      aria-hidden="true"
      className={cn("flex h-7 w-9 shrink-0 items-center justify-center text-[#7067d9]", className)}
    >
      {value === "Audio"
        ? <AudioLines size={19} strokeWidth={1.8} />
        : <i className={cn("rounded-[2px] border-[1.5px] border-current bg-[#f7f6ff] shadow-[inset_0_0_0_2px_#fff]", frameSize)} />}
    </i>
  );
}

interface AspectRatioSelectProps {
  value: AspectRatioValue;
  onValueChange: (value: AspectRatioValue) => void;
  includeAudio?: boolean;
  className?: string;
  ariaLabel?: string;
}

function AspectRatioSelect({ value, onValueChange, includeAudio = false, className, ariaLabel = "Aspect ratio" }: AspectRatioSelectProps) {
  const options = includeAudio
    ? ASPECT_RATIO_OPTIONS
    : ASPECT_RATIO_OPTIONS.filter((option) => option.value !== "Audio");

  return (
    <Select.Root value={value} onValueChange={(nextValue) => onValueChange(nextValue as AspectRatioValue)}>
      <Select.Trigger
        aria-label={`${ariaLabel}: ${value}`}
        className={cn(
          "flex h-[34px] w-full min-w-0 cursor-pointer items-center gap-1.5 rounded-[7px] border border-[var(--line)] bg-white px-1.5 text-left text-[length:var(--text-xs)] text-[#464942] outline-none transition-[border-color,box-shadow] hover:border-[#c8c5e9] focus:border-[#aaa4f6] focus:shadow-[0_0_0_3px_#f0eeff] data-[state=open]:border-[#aaa4f6] data-[state=open]:shadow-[0_0_0_3px_#f0eeff]",
          className,
        )}
      >
        <AspectRatioGlyph value={value} className="h-6 w-8" />
        <b className="min-w-0 flex-1 truncate font-[650]">{value}</b>
        <Select.Icon className="flex shrink-0 items-center text-[#777a73]">
          <ChevronDown size={15} />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content
          position="popper"
          sideOffset={6}
          align="start"
          className="z-[150] min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-[9px] border border-[var(--line)] bg-white p-1.5 text-[length:var(--text-xs)] text-[var(--ink)] shadow-[var(--shadow-md)]"
        >
          <Select.Viewport>
            {options.map((option) => (
              <Select.Item
                key={option.value}
                value={option.value}
                textValue={`${option.value} ${option.description}`}
                className="flex min-h-[48px] cursor-pointer select-none items-center gap-2 rounded-[7px] px-2 outline-none data-[highlighted]:bg-[var(--panel-muted)] data-[state=checked]:bg-[#f4f2ff]"
              >
                <AspectRatioGlyph value={option.value} />
                <div className="min-w-0 flex-1">
                  <Select.ItemText><strong className="block text-[length:var(--text-xs)] font-[680] text-[#4d5049]">{option.value}</strong></Select.ItemText>
                  <small className="mt-0.5 block text-[length:var(--text-2xs)] text-[var(--ink-faint)]">{option.description}</small>
                </div>
                <Select.ItemIndicator className="flex shrink-0 items-center text-[var(--brand)]">
                  <Check size={15} strokeWidth={2.4} />
                </Select.ItemIndicator>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  );
}

export { AspectRatioSelect, type AspectRatioValue };
