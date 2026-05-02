"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/shared/page-header";
import { StatCard } from "@/components/shared/stat-card";
import { McpConnectionCard } from "@/components/dashboard/mcp-connection-card";
import { RecentSourcesCard } from "@/components/dashboard/recent-sources-card";
import { SystemHealthCard } from "@/components/dashboard/system-health-card";

type DashboardStats = {
  total_sources: number;
  total_chunks: number;
  departments?: number;
  employees?: number;
};

export default function DashboardPage() {
  const { user } = useAuth();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [statsError, setStatsError] = useState(false);

  useEffect(() => {
    async function load() {
      setStatsError(false);
      try {
        const sources = await api<unknown[]>("/api/sources");
        const stats: DashboardStats = {
          total_sources: Array.isArray(sources) ? sources.length : 0,
          total_chunks: 0,
        };

        if (user?.role === "admin") {
          try {
            const depts = await api<unknown[]>("/api/departments");
            stats.departments = Array.isArray(depts) ? depts.length : 0;
          } catch {
            stats.departments = undefined;
          }
          try {
            const emps = await api<unknown[]>("/api/employees");
            stats.employees = Array.isArray(emps) ? emps.length : 0;
          } catch {
            stats.employees = undefined;
          }
        }

        setStats(stats);
      } catch {
        setStatsError(true);
        setStats({ total_sources: 0, total_chunks: 0 });
      }
    }
    load();
  }, [user]);

  return (
    <>
      <PageHeader
        title="Enterprise Overview"
        description="Monitor the health and scale of your AI knowledge ecosystem."
      />

      {statsError && (
        <div className="text-sm text-destructive bg-destructive/10 px-4 py-3 rounded-lg flex items-center gap-2">
          <span className="material-symbols-outlined text-base">warning</span>
          Could not load dashboard statistics. Check your connection or try refreshing.
        </div>
      )}

      {/* Stat Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
        <StatCard
          label="Documents"
          value={stats?.total_sources ?? "—"}
          icon="description"
          subtitle="Total knowledge sources"
        />
        {user?.role === "admin" && (
          <>
            <StatCard
              label="Departments"
              value={stats?.departments ?? "—"}
              icon="business"
              subtitle="Active departments"
            />
            <StatCard
              label="Employees"
              value={stats?.employees ?? "—"}
              icon="group"
              subtitle="Registered users"
            />
          </>
        )}
        <StatCard
          label="MCP Status"
          value="Online"
          icon="check_circle"
          subtitle="Server ready"
        />
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 flex flex-col gap-6">
          <SystemHealthCard />
          <RecentSourcesCard />
        </div>
        <div className="flex flex-col gap-6">
          <McpConnectionCard />
        </div>
      </div>
    </>
  );
}
