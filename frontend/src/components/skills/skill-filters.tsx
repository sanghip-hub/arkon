"use client";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type SkillFiltersProps = {
  search: string;
  onSearchChange: (val: string) => void;
  allTags: string[];
  activeTags: string[];
  onToggleTag: (tag: string) => void;
  onClearTags: () => void;
};

export function SkillFilters({
  search,
  onSearchChange,
  allTags,
  activeTags,
  onToggleTag,
  onClearTags
}: SkillFiltersProps) {
  return (
    <div className="flex flex-col gap-4 bg-card p-4 rounded-xl border border-border shadow-sahara">
      <div className="relative">
        <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground">search</span>
        <Input 
          placeholder="Search skills by name or description..." 
          className="pl-10 bg-background"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </div>
      
      {allTags.length > 0 && (
        <div className="flex flex-wrap gap-2 items-center">
          <span className="text-xs font-medium text-muted-foreground mr-2 flex items-center gap-1">
            <span className="material-symbols-outlined text-sm">filter_list</span>
            Tags:
          </span>
          {allTags.map(t => (
            <button
              key={t}
              onClick={() => onToggleTag(t)}
              className={cn(
                "px-3 py-1 rounded-full text-xs transition-all",
                activeTags.includes(t)
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "bg-secondary text-secondary-foreground hover:bg-secondary/80"
              )}
            >
              {t}
            </button>
          ))}
          {activeTags.length > 0 && (
            <button 
              onClick={onClearTags}
              className="text-xs text-muted-foreground hover:text-primary transition-colors ml-2 underline underline-offset-4"
            >
              Clear all
            </button>
          )}
        </div>
      )}
    </div>
  );
}
