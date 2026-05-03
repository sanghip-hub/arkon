"use client";

import { useState, useRef, useMemo } from "react";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { 
  Dialog, 
  DialogContent, 
  DialogDescription, 
  DialogFooter, 
  DialogHeader, 
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import { Skill } from "./skill-card";

type BulkChangeTagsDialogProps = {
  selectedSkills: Skill[];
  allTags: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
};

export function BulkChangeTagsDialog({ 
  selectedSkills, 
  allTags,
  open, 
  onOpenChange, 
  onSuccess 
}: BulkChangeTagsDialogProps) {
  const [loading, setLoading] = useState(false);
  const [tagsToAdd, setTagsToAdd] = useState<string[]>([]);
  const [tagsToRemove, setTagsToRemove] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Get unique tags from selected skills to show in "Remove" section
  const currentTags = useMemo(() => {
    const tags = new Set<string>();
    selectedSkills.forEach(skill => {
      skill.tags.forEach(tag => tags.add(tag));
    });
    return Array.from(tags).sort();
  }, [selectedSkills]);

  const handleSave = async () => {
    if (selectedSkills.length === 0) return;
    if (tagsToAdd.length === 0 && tagsToRemove.length === 0) {
      onOpenChange(false);
      return;
    }

    try {
      setLoading(true);
      
      await api("/api/skills/bulk/tags/update", {
        method: "POST",
        body: { 
          skill_ids: selectedSkills.map(s => s.id),
          add_tags: tagsToAdd,
          remove_tags: tagsToRemove
        }
      });

      setTagsToAdd([]);
      setTagsToRemove([]);
      setTagInput("");
      onSuccess();
      onOpenChange(false);
    } catch (error) {
      const msg = error instanceof ApiError ? (error.data as any)?.detail || error.message : "Unknown error";
      alert("Failed to update tags: " + msg);
    } finally {
      setLoading(false);
    }
  };

  const toggleAddTag = (t: string) => {
    if (tagsToAdd.includes(t)) {
      setTagsToAdd(tagsToAdd.filter(item => item !== t));
    } else {
      setTagsToAdd([...tagsToAdd, t]);
      setTagInput("");
    }
  };

  const toggleRemoveTag = (t: string) => {
    if (tagsToRemove.includes(t)) {
      setTagsToRemove(tagsToRemove.filter(item => item !== t));
    } else {
      setTagsToRemove([...tagsToRemove, t]);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      const val = tagInput.trim().toLowerCase();
      if (val && !tagsToAdd.includes(val)) {
        setTagsToAdd([...tagsToAdd, val]);
        setTagInput("");
      }
    }
  };

  const filteredSuggestions = useMemo(() => {
    if (!tagInput) return [];
    return allTags.filter(t => 
      t.toLowerCase().includes(tagInput.toLowerCase()) && 
      !tagsToAdd.includes(t)
    ).slice(0, 5);
  }, [allTags, tagInput, tagsToAdd]);

  return (
    <Dialog open={open} onOpenChange={(o) => {
      onOpenChange(o);
      if (!o) {
        setTagsToAdd([]);
        setTagsToRemove([]);
        setTagInput("");
      }
    }}>
      <DialogContent className="sm:max-w-[500px] max-h-[90vh] flex flex-col p-0 overflow-hidden">
        <DialogHeader className="p-6 pb-2">
          <DialogTitle>Change Tags for {selectedSkills.length} Skills</DialogTitle>
          <DialogDescription>
            Add new tags and select existing tags to remove.
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto p-6 pt-2 space-y-6">
          {/* Section 1: Add Tags */}
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-primary">
              <span className="material-symbols-outlined text-base">add_circle</span>
              Add Tags
            </div>
            <div className="grid gap-2 relative">
              <div 
                className={cn(
                  "flex flex-wrap gap-1.5 p-2 min-h-[42px] border border-border rounded-md bg-secondary/5 transition-all cursor-text",
                  "focus-within:border-primary focus-within:ring-1 focus-within:ring-primary/20 focus-within:bg-background"
                )}
                onClick={() => inputRef.current?.focus()}
              >
                {tagsToAdd.map(t => (
                  <Badge 
                    key={t}
                    variant="secondary" 
                    className="pl-2 pr-1.5 py-0.5 h-7 text-[12px] font-medium border-primary/30 bg-primary/5 text-primary rounded-full flex items-center gap-1"
                  >
                    {t}
                    <button 
                      type="button" 
                      onClick={(e) => { e.stopPropagation(); toggleAddTag(t); }}
                      className="w-4 h-4 rounded-full bg-primary/10 hover:bg-destructive hover:text-white transition-all flex items-center justify-center ml-0.5"
                    >
                      <span className="material-symbols-outlined" style={{ fontSize: '8px' }}>close</span>
                    </button>
                  </Badge>
                ))}
                <input
                  ref={inputRef}
                  type="text"
                  className="flex-1 bg-transparent border-none outline-none text-sm min-w-[120px] py-0.5"
                  placeholder={tagsToAdd.length === 0 ? "Type to add..." : ""}
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                />
              </div>

              {/* Suggestions */}
              {filteredSuggestions.length > 0 && (
                <div className="absolute top-full left-0 right-0 mt-1 border border-border rounded-md bg-card shadow-xl z-20 overflow-hidden">
                  {filteredSuggestions.map(t => (
                    <div 
                      key={t}
                      onClick={() => toggleAddTag(t)}
                      className="px-3 py-2 text-sm hover:bg-primary/10 hover:text-primary cursor-pointer transition-colors"
                    >
                      {t}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="h-px bg-border/50" />

          {/* Section 2: Remove Tags */}
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-sm font-semibold text-destructive">
              <span className="material-symbols-outlined text-base">remove_circle</span>
              Remove Existing Tags
            </div>
            
            {currentTags.length > 0 ? (
              <div className="grid grid-cols-2 gap-2 p-3 border border-border rounded-md bg-secondary/5">
                {currentTags.map(tag => (
                  <div key={tag} className="flex items-center space-x-2 group">
                    <Checkbox 
                      id={`tag-${tag}`} 
                      checked={tagsToRemove.includes(tag)}
                      onCheckedChange={() => toggleRemoveTag(tag)}
                      className="data-[state=checked]:bg-destructive data-[state=checked]:border-destructive"
                    />
                    <label 
                      htmlFor={`tag-${tag}`}
                      className={cn(
                        "text-xs font-medium cursor-pointer transition-colors",
                        tagsToRemove.includes(tag) ? "text-destructive" : "text-muted-foreground group-hover:text-foreground"
                      )}
                    >
                      {tag}
                    </label>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-4 border border-dashed border-border rounded-md text-xs text-muted-foreground">
                Selected skills have no tags.
              </div>
            )}
          </div>
        </div>

        <DialogFooter className="p-6 bg-secondary/10 border-t border-border">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button 
            disabled={loading || (tagsToAdd.length === 0 && tagsToRemove.length === 0)} 
            onClick={handleSave}
            className="shadow-sm"
          >
            {loading ? "Updating..." : "Save Changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
