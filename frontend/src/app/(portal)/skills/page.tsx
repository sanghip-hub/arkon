"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/shared/empty-state";
import { Skill, SkillCard } from "@/components/skills/skill-card";
import { SkillFilters } from "@/components/skills/skill-filters";
import { UploadSkillDialog } from "@/components/skills/upload-skill-dialog";
import { BulkChangeTagsDialog } from "@/components/skills/bulk-change-tags-dialog";
import { BulkChangeDeptDialog } from "@/components/skills/bulk-change-dept-dialog";
import { TagsManagerDialog } from "@/components/skills/tags-manager-dialog";
import { cn } from "@/lib/utils";

type SkillListResponse = {
  items: Skill[];
  total: number;
};

type Department = {
  id: string;
  name: string;
};

const LIMIT = 12;

export default function SkillsPage() {
  const router = useRouter();
  const [skills, setSkills] = useState<Skill[]>([]);
  const [total, setTotal] = useState(0);
  const [allTags, setAllTags] = useState<string[]>([]);
  const [allDepartments, setAllDepartments] = useState<Department[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  
  // Selection state
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [isBulkTagDialogOpen, setIsBulkTagDialogOpen] = useState(false);
  const [isBulkDeptDialogOpen, setIsBulkDeptDialogOpen] = useState(false);

  // Filters state
  const [search, setSearch] = useState("");
  const [activeTags, setActiveTags] = useState<string[]>([]);
  const [offset, setOffset] = useState(0);

  const loadSkills = useCallback(async (isNextPage = false) => {
    if (isNextPage) setLoadingMore(true);
    else setLoading(true);

    try {
      const currentOffset = isNextPage ? offset + LIMIT : 0;
      const params = new URLSearchParams();
      if (search) params.set("q", search);
      activeTags.forEach(t => params.append("tag", t));
      params.set("limit", String(LIMIT));
      params.set("offset", String(currentOffset));

      const data = await api<SkillListResponse>(`/api/skills?${params.toString()}`);
      
      if (isNextPage) {
        setSkills(prev => [...prev, ...data.items]);
        setOffset(currentOffset);
      } else {
        setSkills(data.items);
        setOffset(0);
        setSelectedIds([]); 
      }
      setTotal(data.total);
    } catch {
      if (!isNextPage) setSkills([]);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [search, activeTags, offset]);

  const loadAllTags = useCallback(async () => {
    try {
      const data = await api<{ items: string[], total: number }>("/api/tags");
      setAllTags(data.items);
      // Clean up active tags that might have been deleted
      setActiveTags(prev => prev.filter(t => data.items.includes(t)));
    } catch {
      setAllTags([]);
    }
  }, []);

  const loadAllDepartments = useCallback(async () => {
    try {
      const data = await api<Department[]>("/api/departments");
      setAllDepartments(data);
    } catch {
      setAllDepartments([]);
    }
  }, []);

  // Initial load
  useEffect(() => {
    loadAllTags();
    loadAllDepartments();
  }, [loadAllTags, loadAllDepartments]);

  // Load skills when filters change (debounced search)
  useEffect(() => {
    const timer = setTimeout(() => {
      loadSkills(false);
    }, 300);
    return () => clearTimeout(timer);
  }, [search, activeTags]);

  // Polling for processing skills
  useEffect(() => {
    const hasProcessing = skills.some(s => s.status === "processing" || s.status === "deleting");
    if (!hasProcessing) return;

    const interval = setInterval(() => {
      const params = new URLSearchParams();
      if (search) params.set("q", search);
      activeTags.forEach(t => params.append("tag", t));
      params.set("limit", String(skills.length)); 
      params.set("offset", "0");

      api<SkillListResponse>(`/api/skills?${params.toString()}`)
        .then(data => setSkills(data.items))
        .catch(err => console.error("Polling error:", err));
    }, 3000);

    return () => clearInterval(interval);
  }, [skills, search, activeTags]);

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`Are you sure you want to delete Skill "${name}"?`)) return;
    try {
      await api(`/api/skills/${id}`, { method: "DELETE" });
      loadSkills(false);
    } catch (error) {
      alert("Delete failed: " + (error instanceof Error ? error.message : "Unknown error"));
    }
  };

  const handleBulkDelete = async () => {
    if (selectedIds.length === 0) return;
    if (!confirm(`Are you sure you want to delete ${selectedIds.length} skills?`)) return;

    try {
      await api("/api/skills/bulk", {
        method: "DELETE",
        body: { ids: selectedIds }
      });
      setSelectedIds([]);
      loadSkills(false);
    } catch (error) {
      alert("Bulk delete failed: " + (error instanceof Error ? error.message : "Unknown error"));
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      if (prev.includes(id)) {
        return prev.filter(i => i !== id);
      } else {
        return [...prev, id];
      }
    });
  };

  const handleSelectAll = () => {
    if (selectedIds.length === skills.length && skills.length > 0) {
      setSelectedIds([]);
    } else {
      setSelectedIds(skills.map(s => s.id));
    }
  };

  const toggleFilterTag = (t: string) => {
    if (activeTags.includes(t)) {
      setActiveTags(activeTags.filter(item => item !== t));
    } else {
      setActiveTags([...activeTags, t]);
    }
  };

  const isAllSelected = skills.length > 0 && selectedIds.length === skills.length;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="AI Skills"
        description="Manage and deploy skill packages for your AI system."
        action={
          <div className="flex flex-wrap gap-2 sm:flex-nowrap">
            <TagsManagerDialog onUpdate={loadAllTags} />
            <UploadSkillDialog 
              allTags={allTags} 
              allDepartments={allDepartments}
              onUploaded={() => loadSkills(false)} 
              onRefreshTags={loadAllTags}
            />
          </div>
        }
      />

      <SkillFilters 
        search={search}
        onSearchChange={setSearch}
        allTags={allTags}
        activeTags={activeTags}
        onToggleTag={toggleFilterTag}
        onClearTags={() => setActiveTags([])}
      />

      {/* Bulk Actions Bar */}
      {skills.length > 0 && (
        <div className="flex flex-col sm:flex-row sm:items-center justify-between bg-secondary/20 p-3 sm:p-2 rounded-lg border border-border shadow-sm animate-in fade-in slide-in-from-top-1 duration-300 gap-3 sm:gap-0">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 px-3 py-1.5 bg-background rounded-md border border-border shadow-sm hover:border-primary/50 transition-all cursor-pointer" onClick={handleSelectAll}>
              <input 
                type="checkbox" 
                checked={isAllSelected} 
                onChange={handleSelectAll}
                className="w-4 h-4 cursor-pointer accent-primary"
                onClick={(e) => e.stopPropagation()}
              />
              <span className="text-xs font-bold text-foreground uppercase tracking-tight">
                {isAllSelected ? "Unselect All" : "Select All"}
              </span>
            </div>
            {selectedIds.length > 0 && (
              <span className="text-sm font-semibold text-primary animate-in fade-in slide-in-from-left-1">
                {selectedIds.length} skills selected
              </span>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            <Button 
              variant="outline" 
              size="sm" 
              disabled={selectedIds.length === 0}
              onClick={() => setIsBulkTagDialogOpen(true)}
              className="h-9 px-4 font-semibold shadow-sm hover:bg-secondary transition-colors"
            >
              <span className="material-symbols-outlined text-sm mr-1">label</span>
              Change Tags
            </Button>
            <Button 
              variant="outline" 
              size="sm" 
              disabled={selectedIds.length === 0}
              onClick={() => setIsBulkDeptDialogOpen(true)}
              className="h-9 px-4 font-semibold shadow-sm hover:bg-secondary transition-colors"
            >
              <span className="material-symbols-outlined text-sm mr-1">corporate_fare</span>
              Change Dept
            </Button>
            <Button 
              variant="destructive" 
              size="sm" 
              disabled={selectedIds.length === 0}
              onClick={handleBulkDelete}
              className="h-9 px-4 font-semibold shadow-sahara"
            >
              <span className="material-symbols-outlined text-sm mr-1">delete_sweep</span>
              Delete ({selectedIds.length})
            </Button>
            {selectedIds.length > 0 && (
              <Button 
                variant="ghost" 
                size="sm" 
                onClick={() => setSelectedIds([])}
                className="h-9 px-3 text-xs"
              >
                Cancel
              </Button>
            )}
          </div>
        </div>
      )}

      <div className="flex flex-col gap-8">
        {loading ? (
          <div className="flex items-center justify-center py-24">
            <span className="material-symbols-outlined text-4xl text-muted-foreground animate-spin">
              progress_activity
            </span>
          </div>
        ) : skills.length === 0 ? (
          <EmptyState
            icon="bolt"
            title="No skills found"
            description={search || activeTags.length > 0 ? "Try changing filters or search keywords." : "Upload ZIP packages to get started."}
          />
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
              {skills.map((skill) => (
                <SkillCard 
                  key={skill.id}
                  skill={skill}
                  isSelected={selectedIds.includes(skill.id)}
                  onToggleSelect={toggleSelect}
                  onDelete={handleDelete}
                  onEdit={(slug) => router.push(`/skills/${slug}/edit`)}
                  onClick={(slug) => router.push(`/skills/${slug}`)}
                />
              ))}
            </div>

            {skills.length < total && (
              <div className="flex flex-col items-center gap-4 py-8">
                <p className="text-sm text-muted-foreground italic">
                  Showing {skills.length} of {total} skills
                </p>
                <Button 
                  variant="outline" 
                  disabled={loadingMore} 
                  onClick={() => loadSkills(true)}
                  className="w-40 shadow-sahara"
                >
                  {loadingMore ? (
                    <span className="material-symbols-outlined animate-spin text-base">progress_activity</span>
                  ) : (
                    "Load More"
                  )}
                </Button>
              </div>
            )}
          </>
        )}
      </div>
      <BulkChangeTagsDialog 
        selectedSkills={skills.filter(s => selectedIds.includes(s.id))}
        allTags={allTags}
        open={isBulkTagDialogOpen}
        onOpenChange={setIsBulkTagDialogOpen}
        onSuccess={() => {
          setSelectedIds([]);
          loadSkills(false);
          loadAllTags();
        }}
      />

      <BulkChangeDeptDialog 
        skillIds={selectedIds}
        departments={allDepartments}
        open={isBulkDeptDialogOpen}
        onOpenChange={setIsBulkDeptDialogOpen}
        onSuccess={() => {
          setSelectedIds([]);
          loadSkills(false);
        }}
      />
    </div>
  );
}
