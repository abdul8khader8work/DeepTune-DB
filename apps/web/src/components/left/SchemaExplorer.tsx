"use client";

import { useMemo, useState } from "react";
import {
  ChevronRight,
  Folder,
  Hash,
  KeyRound,
  Search,
  Table2,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { initiallyOpen, schema, type SchemaTable } from "@/lib/mock-schema";
import { cn } from "@/lib/utils";
import { useQueryStore } from "@/store/useQueryStore";
import { useSessionStore } from "@/store/useSessionStore";

export function SchemaExplorer() {
  const appendToken = useQueryStore((state) => state.appendToken);
  const liveTables = useSessionStore((state) => state.tables);
  const dbVersion = useSessionStore((state) => state.dbVersion);
  const [filter, setFilter] = useState("");
  const [openTables, setOpenTables] =
    useState<Record<string, boolean>>(initiallyOpen);

  const tables = useMemo<SchemaTable[]>(() => {
    if (liveTables.length === 0) return schema;
    return liveTables.map((table) => ({
      name: table.name,
      columns: table.columns.map((column) => ({
        name: column.name,
        type: column.data_type.replace(/ (without|with) time zone$/, ""),
        pk: column.is_primary_key,
        indexed: column.existing_indexes.length > 0,
      })),
    }));
  }, [liveTables]);

  const normalized = filter.trim().toLowerCase();

  const visibleTables = useMemo(() => {
    if (!normalized) return tables;
    return tables
      .map((table) => {
        const tableMatches = table.name.toLowerCase().includes(normalized);
        return {
          ...table,
          columns: tableMatches
            ? table.columns
            : table.columns.filter((column) =>
                column.name.toLowerCase().includes(normalized),
              ),
        };
      })
      .filter(
        (table) =>
          table.name.toLowerCase().includes(normalized) ||
          table.columns.length > 0,
      );
  }, [normalized, tables]);

  const toggleTable = (name: string) =>
    setOpenTables((current) => ({ ...current, [name]: !current[name] }));

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface-1">
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-subtle px-3">
        <span className="text-[11px] font-medium uppercase tracking-[0.08em] text-content-secondary">
          Schema
        </span>
        <span className="font-mono text-[10px] text-content-tertiary">
          {liveTables.length > 0
            ? `${tables.length} tables`
            : `sample · ${tables.length} tables`}
        </span>
      </div>

      <div className="relative shrink-0 px-3 py-2">
        <Search
          className="pointer-events-none absolute left-5 top-1/2 h-3 w-3 -translate-y-1/2 text-content-tertiary"
          aria-hidden
        />
        <Input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter columns…"
          aria-label="Filter schema columns"
          className="h-7 pl-7"
        />
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="px-2 pb-3 font-mono text-[11px]">
          <div className="flex items-center gap-1.5 px-1.5 py-1 text-content-tertiary">
            <Folder className="h-3 w-3" aria-hidden />
            <span>public</span>
            {dbVersion ? (
              <span
                className="ml-auto truncate text-[9px] text-content-disabled"
                title={dbVersion}
              >
                {dbVersion.split(" ").slice(0, 2).join(" ")}
              </span>
            ) : null}
          </div>

          {visibleTables.map((table) => {
            const isOpen = normalized ? true : openTables[table.name];
            return (
              <div key={table.name}>
                <button
                  type="button"
                  onClick={() => toggleTable(table.name)}
                  aria-expanded={isOpen}
                  className="flex w-full items-center gap-1.5 rounded-sm px-1.5 py-1 text-left transition-colors hover:bg-surface-2"
                >
                  <ChevronRight
                    className={cn(
                      "h-3 w-3 text-content-tertiary transition-transform",
                      isOpen && "rotate-90",
                    )}
                    aria-hidden
                  />
                  <Table2 className="h-3 w-3 text-content-tertiary" aria-hidden />
                  <span className="text-content-primary">{table.name}</span>
                  <span className="ml-auto text-[10px] text-content-disabled">
                    {table.columns.length}
                  </span>
                </button>

                {isOpen ? (
                  <ul className="ml-3 border-l border-subtle pl-1.5">
                    {table.columns.map((column) => (
                      <li key={column.name}>
                        <button
                          type="button"
                          onClick={() => appendToken(column.name)}
                          title={`Insert ${column.name} into the editor`}
                          className="group flex w-full items-center gap-1.5 rounded-sm px-1.5 py-0.5 text-left transition-colors hover:bg-surface-2"
                        >
                          {column.pk ? (
                            <KeyRound
                              className="h-2.5 w-2.5 text-warn"
                              aria-label="Primary key"
                            />
                          ) : (
                            <Hash
                              className="h-2.5 w-2.5 text-content-disabled"
                              aria-hidden
                            />
                          )}
                          <span className="text-content-secondary group-hover:text-content-primary">
                            {column.name}
                          </span>
                          {column.indexed ? (
                            <span className="rounded-xs border border-info/20 bg-info/10 px-1 text-[9px] text-info">
                              idx
                            </span>
                          ) : null}
                          <span className="ml-auto text-[10px] text-content-disabled">
                            {column.type}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            );
          })}

          {visibleTables.length === 0 ? (
            <p className="px-2 py-4 text-center font-sans text-[11px] text-content-tertiary">
              No columns match “{filter}”.
            </p>
          ) : null}
        </div>
      </ScrollArea>
    </div>
  );
}
