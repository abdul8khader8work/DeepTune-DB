"use client";

import { Command } from "cmdk";
import type { LucideIcon } from "lucide-react";

export type PaletteItemProps = {
  icon: LucideIcon;
  label: string;
  hint?: string;
  onSelect: () => void;
};

export function PaletteItem({
  icon: Icon,
  label,
  hint,
  onSelect,
}: PaletteItemProps) {
  return (
    <Command.Item
      value={label}
      onSelect={onSelect}
      className="group flex cursor-pointer items-center gap-2.5 rounded-sm px-2 py-2 text-[13px] text-content-secondary data-[selected=true]:bg-ai/10 data-[selected=true]:text-content-primary"
    >
      <Icon
        className="h-3.5 w-3.5 text-content-tertiary group-data-[selected=true]:text-ai"
        aria-hidden
      />
      <span className="flex-1">{label}</span>
      {hint ? (
        <span className="font-mono text-[10px] text-content-disabled">
          {hint}
        </span>
      ) : null}
    </Command.Item>
  );
}
