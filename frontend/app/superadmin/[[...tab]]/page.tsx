"use client";

import React, { useEffect, useState, use } from "react";
import { useRouter } from "next/navigation";
import Loader from "@/components/Loader";
import { getApiBaseUrl } from "@/lib/api";
import {
  LayoutDashboard,
  Users,
  Database,
  LogOut,
  Menu,
  X,
  Settings,
  ShieldCheck,
  Activity,
  CheckCircle2,
  XCircle,
  Sparkles,
  Server,
  TrendingUp,
  Search,
  Info,
  UserX,
  Mail,
  Lock,
  Eye,
  EyeOff,
  Loader2,
  ArrowRight
} from "lucide-react";
import { supabase } from "@/lib/supabase";

type SuperadminTab = "dashboard" | "approvals" | "directory" | "settings";

interface PendingWorkspace {
  id: string;
  name: string;
  email: string;
  organisation: string;
  created_at: string;
}

interface Workspace {
  id: string;
  owner_name: string;
  owner_email: string;
  organisation: string;
  status: string;
  employee_count: number;
  email_count: number;
  created_at: string;
}

interface GlobalAnalytics {
  metrics: {
    total_tenants: number;
    total_employees: number;
    total_parsed_catalogs: number;
    total_ai_queries: number;
  };
  trends: {
    labels: string[];
    catalogs: number[];
    queries: number[];
  };
}

interface Telemetry {
  valkey_status?: string;
  redis_status: string;
  celery_status: string;
  queue_backlog: number;
  avg_processing_speed: string;
  engine_version: string;
}

export default function SuperadminWorkspacePage({ params }: { params: Promise<{ tab?: string[] }> }) {
  const resolvedParams = use(params);
  const router = useRouter();

  // Navigation and Layout states
  const [activeTab, setActiveTabState] = useState<SuperadminTab>("dashboard");
  const [sessionLoading, setSessionLoading] = useState(true);
  const [superadminName, setSuperadminName] = useState("");
  const [superadminEmail, setSuperadminEmail] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [isAuthorized, setIsAuthorized] = useState(false);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loginLoading, setLoginLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  // Feature states
  const [pendingWorkspaces, setPendingWorkspaces] = useState<PendingWorkspace[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [analytics, setAnalytics] = useState<GlobalAnalytics | null>(null);
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);

  // Loading/Error states
  const [pendingLoading, setPendingLoading] = useState(false);
  const [workspacesLoading, setWorkspacesLoading] = useState(false);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [telemetryLoading, setTelemetryLoading] = useState(false);

  const [actionLoadingId, setActionLoadingId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Search states
  const [approvalsSearch, setApprovalsSearch] = useState("");
  const [directorySearch, setDirectorySearch] = useState("");

  const getQueueStatus = () => telemetry?.valkey_status || telemetry?.redis_status || "Offline";

  const getApiUrl = getApiBaseUrl;

  const verifySuperadminProfile = async () => {
    const response = await fetch(`${getApiUrl()}/api/profile`, {
      credentials: "include",
    });
    if (!response.ok) {
      throw new Error("Unable to verify superadmin profile.");
    }
    const profile = await response.json();
    if (profile.role !== "superadmin") {
      throw new Error("Access denied. Superadmin credentials required.");
    }
    return profile;
  };

  // Sync route param on initial mount / page load or popstate
  useEffect(() => {
    if (resolvedParams?.tab) {
      const tabParam = resolvedParams.tab[0] as SuperadminTab;
      if (tabParam && tabParam !== activeTab) {
        setActiveTabState(tabParam);
      }
    } else {
      if (activeTab !== "dashboard") {
        setActiveTabState("dashboard");
      }
    }
  }, [resolvedParams]);

  // Listen to popstate event (browser back/forward button)
  useEffect(() => {
    const handlePopState = () => {
      if (typeof window !== "undefined") {
        const path = window.location.pathname;
        const tab = path.split("/superadmin/")[1] as SuperadminTab;
        setActiveTabState(tab || "dashboard");
      }
    };
    handlePopState();
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  // Verify Session & Role
  useEffect(() => {
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      if (!session) {
        setIsAuthorized(false);
        setSessionLoading(false);
        return;
      }

      try {
        const profile = await verifySuperadminProfile();
        setSuperadminName(profile.full_name || session.user.email?.split("@")[0] || "Superadmin");
        setSuperadminEmail(profile.email || session.user.email || "");
        setIsAuthorized(true);
      } catch {
        setIsAuthorized(false);
      } finally {
        setSessionLoading(false);
      }
    });
  }, [router]);

  const handleSuperadminLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginError(null);
    setLoginLoading(true);

    try {
      const { data, error: authError } = await supabase.auth.signInWithPassword({
        email: loginEmail.trim(),
        password: loginPassword,
      });

      if (authError) {
        setLoginError(authError.message);
        setLoginLoading(false);
        return;
      }

      try {
        const profile = await verifySuperadminProfile();
        setSuperadminName(profile.full_name || data.user?.email?.split("@")[0] || "Superadmin");
        setSuperadminEmail(profile.email || data.user?.email || "");
        setIsAuthorized(true);
      } catch {
        await supabase.auth.signOut();
        setLoginError("Access denied. Superadmin credentials required.");
        setLoginLoading(false);
        return;
      }
    } catch (err: any) {
      setLoginError(err.message || "An unexpected error occurred.");
    } finally {
      setLoginLoading(false);
    }
  };

  // Manage sidebar margin global body classes
  useEffect(() => {
    if (sidebarCollapsed) {
      document.body.classList.add("sidebar-collapsed");
    } else {
      document.body.classList.remove("sidebar-collapsed");
    }
    return () => {
      document.body.classList.remove("sidebar-collapsed");
    };
  }, [sidebarCollapsed]);

  // Fetch Logic
  const fetchWithAuth = async (endpoint: string, options: RequestInit = {}) => {
    const { data: { session } } = await supabase.auth.getSession();
    if (!session) throw new Error("No active session found.");

    const headers = {
      ...options.headers,
      "Content-Type": "application/json",
    };

    const res = await fetch(`${getApiUrl()}/api/superadmin${endpoint}`, { ...options, headers, credentials: "include" });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || "API request failed.");
    }
    return res.json();
  };

  const fetchPending = async () => {
    setPendingLoading(true);
    setErrorMsg(null);
    try {
      const data = await fetchWithAuth("/pending");
      setPendingWorkspaces(data);
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setPendingLoading(false);
    }
  };

  const fetchWorkspaces = async () => {
    setWorkspacesLoading(true);
    setErrorMsg(null);
    try {
      const data = await fetchWithAuth("/workspaces");
      setWorkspaces(data);
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setWorkspacesLoading(false);
    }
  };

  const fetchAnalytics = async () => {
    setAnalyticsLoading(true);
    try {
      const data = await fetchWithAuth("/global-analytics");
      setAnalytics(data);
    } catch (err: any) {
      console.error("Failed to load global analytics:", err);
    } finally {
      setAnalyticsLoading(false);
    }
  };

  const fetchTelemetry = async () => {
    setTelemetryLoading(true);
    try {
      const data = await fetchWithAuth("/telemetry");
      setTelemetry(data);
    } catch (err: any) {
      console.error("Failed to load telemetry:", err);
    } finally {
      setTelemetryLoading(false);
    }
  };

  // Trigger loads on tab change
  useEffect(() => {
    if (sessionLoading || !isAuthorized) return;
    if (activeTab === "dashboard") {
      fetchAnalytics();
      fetchTelemetry();
    } else if (activeTab === "approvals") {
      fetchPending();
    } else if (activeTab === "directory") {
      fetchWorkspaces();
    }
  }, [activeTab, sessionLoading, isAuthorized]);

  // Auto-clear success messages after 5 seconds
  useEffect(() => {
    if (successMsg) {
      const timer = setTimeout(() => {
        setSuccessMsg(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [successMsg]);

  // Actions
  const handleApprove = async (id: string, orgName: string) => {
    setActionLoadingId(id);
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      await fetchWithAuth(`/workspaces/${id}/approve`, { method: "POST" });
      setSuccessMsg(`Workspace "${orgName}" approved successfully! Notification email sent.`);
      fetchPending();
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleReject = async (id: string, orgName: string) => {
    if (!confirm(`Are you sure you want to reject and delete the workspace registration for "${orgName}"?`)) return;
    setActionLoadingId(id);
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      await fetchWithAuth(`/workspaces/${id}/reject`, { method: "POST" });
      setSuccessMsg(`Workspace "${orgName}" rejected and registration deleted.`);
      fetchPending();
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleToggleWorkspaceStatus = async (id: string, orgName: string) => {
    setActionLoadingId(id);
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      const data = await fetchWithAuth(`/workspaces/${id}/toggle-status`, { method: "POST" });
      setSuccessMsg(`Workspace "${orgName}" status toggled to ${data.status}.`);
      fetchWorkspaces();
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleLogout = async () => {
    await supabase.auth.signOut();
    router.push("/login");
  };

  const setActiveTab = (tab: SuperadminTab) => {
    setActiveTabState(tab);
    if (typeof window !== "undefined") {
      const path = tab === "dashboard" ? "/superadmin" : `/superadmin/${tab}`;
      if (window.location.pathname !== path) {
        window.history.pushState({ tab }, "", path);
      }
    }
  };

  // Rendering Helper
  const renderTabContent = () => {
    if (activeTab === "dashboard") {
      return (
        <div>
          {/* Header */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "32px" }}>
            <div>
              <h2 style={{ margin: 0, fontSize: "22px", fontWeight: 600, color: "#092f28" }}>Global Telemetry & Stats</h2>
              <p style={{ fontSize: "14px", color: "#66736d", margin: "4px 0 0 0" }}>System-wide resource tracking and background worker health.</p>
            </div>
            <button
              onClick={() => { fetchAnalytics(); fetchTelemetry(); }}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                padding: "8px 16px",
                background: "#ffffff",
                border: "1px solid #dce4df",
                borderRadius: "10px",
                fontSize: "13px",
                fontWeight: 600,
                color: "#0f7a5f",
                cursor: "pointer"
              }}
            >
              <Activity size={16} />
              Refresh System Metrics
            </button>
          </div>

          {/* Metric Tiles */}
          {analyticsLoading ? (
            <Loader variant="tab" />
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "20px", marginBottom: "40px" }}>
              <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "24px", boxShadow: "0 4px 20px rgba(23, 33, 28, 0.02)" }}>
                <span style={{ fontSize: "11.5px", fontWeight: 600, color: "#66736d", textTransform: "uppercase", letterSpacing: "0.05em" }}>Active Workspaces</span>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginTop: "12px" }}>
                  <h3 style={{ fontSize: "28px", fontWeight: 600, color: "#17211c", margin: 0 }}>{analytics?.metrics.total_tenants || 0}</h3>
                  <span style={{ fontSize: "12px", color: "#10b981", fontWeight: 600, display: "flex", alignItems: "center", gap: "2px" }}><TrendingUp size={14} /> +100%</span>
                </div>
              </div>

              <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "24px", boxShadow: "0 4px 20px rgba(23, 33, 28, 0.02)" }}>
                <span style={{ fontSize: "11.5px", fontWeight: 600, color: "#66736d", textTransform: "uppercase", letterSpacing: "0.05em" }}>Total Employees</span>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginTop: "12px" }}>
                  <h3 style={{ fontSize: "28px", fontWeight: 600, color: "#17211c", margin: 0 }}>{analytics?.metrics.total_employees || 0}</h3>
                  <span style={{ fontSize: "12px", color: "#66736d" }}>Registered</span>
                </div>
              </div>

              <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "24px", boxShadow: "0 4px 20px rgba(23, 33, 28, 0.02)" }}>
                <span style={{ fontSize: "11.5px", fontWeight: 600, color: "#66736d", textTransform: "uppercase", letterSpacing: "0.05em" }}>Processed Catalogs</span>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginTop: "12px" }}>
                  <h3 style={{ fontSize: "28px", fontWeight: 600, color: "#17211c", margin: 0 }}>{analytics?.metrics.total_parsed_catalogs || 0}</h3>
                  <span style={{ fontSize: "12px", color: "#0f7a5f", fontWeight: 600 }}>Total</span>
                </div>
              </div>

              <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "24px", boxShadow: "0 4px 20px rgba(23, 33, 28, 0.02)" }}>
                <span style={{ fontSize: "11.5px", fontWeight: 600, color: "#66736d", textTransform: "uppercase", letterSpacing: "0.05em" }}>Global AI Queries</span>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginTop: "12px" }}>
                  <h3 style={{ fontSize: "28px", fontWeight: 600, color: "#17211c", margin: 0 }}>{analytics?.metrics.total_ai_queries || 0}</h3>
                  <span style={{ fontSize: "12px", color: "#0f7a5f", fontWeight: 600 }}>Queries</span>
                </div>
              </div>
            </div>
          )}

          {/* Telemetry and Queue Health */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px" }}>
            <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "28px", boxShadow: "0 4px 20px rgba(23, 33, 28, 0.02)" }}>
              <h4 style={{ margin: "0 0 18px 0", fontSize: "15px", fontWeight: 600, color: "#092f28", display: "flex", alignItems: "center", gap: "8px" }}>
                <Server size={18} />
                Background Engine Telemetry
              </h4>

              {telemetryLoading ? (
                <div style={{ padding: "20px 0" }}><Loader variant="inline" /></div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", paddingBottom: "12px", borderBottom: "1px solid var(--line)" }}>
                    <span style={{ fontSize: "13.5px", color: "var(--muted)" }}>Valkey Broker Connection</span>
                    <span style={{
                      fontSize: "12px",
                      fontWeight: 700,
                      padding: "4px 12px",
                      borderRadius: "12px",
                      background: getQueueStatus() === "Online" ? "rgba(16, 185, 129, 0.08)" : "rgba(239, 68, 68, 0.08)",
                      color: getQueueStatus() === "Online" ? "#10b981" : "#ef4444",
                      display: "inline-flex",
                      alignItems: "center"
                    }}>
                      <span className={getQueueStatus() === "Online" ? "pulse-dot-green" : "pulse-dot-red"}></span>
                      {getQueueStatus()}
                    </span>
                  </div>

                  <div style={{ display: "flex", justifyContent: "space-between", paddingBottom: "12px", borderBottom: "1px solid var(--line)" }}>
                    <span style={{ fontSize: "13.5px", color: "var(--muted)" }}>Celery Worker Status</span>
                    <span style={{
                      fontSize: "12px",
                      fontWeight: 700,
                      padding: "4px 12px",
                      borderRadius: "12px",
                      background: telemetry?.celery_status === "Active" ? "rgba(16, 185, 129, 0.08)" : "rgba(239, 68, 68, 0.08)",
                      color: telemetry?.celery_status === "Active" ? "#10b981" : "#ef4444",
                      display: "inline-flex",
                      alignItems: "center"
                    }}>
                      <span className={telemetry?.celery_status === "Active" ? "pulse-dot-green" : "pulse-dot-red"}></span>
                      {telemetry?.celery_status || "Inactive"}
                    </span>
                  </div>

                  <div style={{ display: "flex", justifyContent: "space-between", paddingBottom: "12px", borderBottom: "1px solid var(--line)" }}>
                    <span style={{ fontSize: "13.5px", color: "var(--muted)" }}>Celery Task Queue Backlog</span>
                    <span style={{ fontSize: "14px", fontWeight: 600, color: "var(--ink)" }}>
                      {telemetry?.queue_backlog || 0} tasks
                    </span>
                  </div>

                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ fontSize: "13.5px", color: "var(--muted)" }}>Average Processing Speed</span>
                    <span style={{ fontSize: "14px", fontWeight: 600, color: "#0f7a5f" }}>
                      {telemetry?.avg_processing_speed || "4.2s / catalog"}
                    </span>
                  </div>
                </div>
              )}
            </div>

            <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "28px", boxShadow: "0 4px 20px rgba(23, 33, 28, 0.02)", display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", textAlign: "center" }}>
              <div style={{ width: "64px", height: "64px", borderRadius: "50%", background: "rgba(15, 122, 95, 0.08)", color: "#0f7a5f", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: "16px" }}>
                <Sparkles size={32} />
              </div>
              <h4 style={{ margin: "0 0 8px 0", fontSize: "16px", fontWeight: 600, color: "#092f28" }}>MediCORE AI Cluster</h4>
              <p style={{ fontSize: "13.5px", color: "var(--muted)", maxWidth: "340px", margin: 0, lineHeight: 1.6 }}>
                Global services running optimally. NLP translation engines, parsing models, and Supabase SQL query engines are verified operational.
              </p>
            </div>
          </div>
        </div>
      );
    }

    if (activeTab === "approvals") {
      const filteredApprovals = pendingWorkspaces.filter(item =>
        item.organisation.toLowerCase().includes(approvalsSearch.toLowerCase()) ||
        item.name.toLowerCase().includes(approvalsSearch.toLowerCase()) ||
        item.email.toLowerCase().includes(approvalsSearch.toLowerCase())
      );

      return (
        <div>
          {/* Header */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "28px" }}>
            <div>
              <h2 style={{ margin: 0, fontSize: "22px", fontWeight: 600, color: "#092f28" }}>Workspace Approvals</h2>
              <p style={{ fontSize: "14px", color: "#66736d", margin: "4px 0 0 0" }}>Approve new Workspace Administrator registration requests to grant login credentials.</p>
            </div>
          </div>

          {/* Search bar */}
          <div style={{ position: "relative", marginBottom: "20px", maxWidth: "400px" }}>
            <Search style={{ position: "absolute", left: "14px", top: "50%", transform: "translateY(-50%)", color: "var(--muted)" }} size={16} />
            <input
              type="text"
              value={approvalsSearch}
              onChange={(e) => setApprovalsSearch(e.target.value)}
              placeholder="Search by organisation, name or email..."
              style={{
                width: "100%",
                padding: "10px 16px 10px 40px",
                borderRadius: "10px",
                border: "1px solid #dce4df",
                fontSize: "13.5px",
                outline: "none"
              }}
            />
          </div>

          {/* Table */}
          {pendingLoading ? (
            <Loader variant="tab" />
          ) : filteredApprovals.length === 0 ? (
            <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "48px", textAlign: "center", color: "var(--muted)" }}>
              No pending workspace registration requests found.
            </div>
          ) : (
            <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", overflow: "hidden", boxShadow: "0 4px 20px rgba(23, 33, 28, 0.02)" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "13.5px" }}>
                <thead>
                  <tr style={{ background: "#fafcfb", borderBottom: "1px solid #dce4df" }}>
                    <th style={{ padding: "16px 24px", color: "#092f28", fontWeight: 600, width: "64px" }}>#</th>
                    <th style={{ padding: "16px 24px", color: "#092f28", fontWeight: 600 }}>Organisation</th>
                    <th style={{ padding: "16px 24px", color: "#092f28", fontWeight: 600 }}>Admin Owner</th>
                    <th style={{ padding: "16px 24px", color: "#092f28", fontWeight: 600 }}>Email Address</th>
                    <th style={{ padding: "16px 24px", color: "#092f28", fontWeight: 600 }}>Request Date</th>
                    <th style={{ padding: "16px 24px", color: "#092f28", fontWeight: 600, textAlign: "right" }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredApprovals.map((req, index) => (
                    <tr key={req.id} style={{ borderBottom: "1px solid #dce4df" }}>
                      <td style={{ padding: "16px 24px", color: "var(--muted)" }}>{index + 1}</td>
                      <td style={{ padding: "16px 24px", fontWeight: 600, color: "var(--ink)" }}>{req.organisation}</td>
                      <td style={{ padding: "16px 24px", color: "var(--ink)" }}>{req.name}</td>
                      <td style={{ padding: "16px 24px", color: "var(--muted)" }}>{req.email}</td>
                      <td style={{ padding: "16px 24px", color: "var(--muted)" }}>
                        {req.created_at ? new Date(req.created_at).toLocaleDateString(undefined, { dateStyle: "medium" }) : "N/A"}
                      </td>
                      <td style={{ padding: "16px 24px", textAlign: "right" }}>
                        <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
                          <button
                            onClick={() => handleApprove(req.id, req.organisation)}
                            disabled={actionLoadingId === req.id}
                            style={{
                              padding: "6px 12px",
                              borderRadius: "6px",
                              background: "var(--accent)",
                              color: "#ffffff",
                              border: "none",
                              fontWeight: 600,
                              fontSize: "12px",
                              cursor: "pointer",
                            }}
                          >
                            {actionLoadingId === req.id ? "Approve..." : "Approve"}
                          </button>
                          <button
                            onClick={() => handleReject(req.id, req.organisation)}
                            disabled={actionLoadingId === req.id}
                            style={{
                              padding: "6px 12px",
                              borderRadius: "6px",
                              background: "#ffffff",
                              color: "#ef4444",
                              border: "1px solid #fde8e8",
                              fontWeight: 600,
                              fontSize: "12px",
                              cursor: "pointer",
                            }}
                          >
                            Reject
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      );
    }

    if (activeTab === "directory") {
      const filteredWorkspaces = workspaces.filter(item =>
        item.organisation.toLowerCase().includes(directorySearch.toLowerCase()) ||
        item.owner_name.toLowerCase().includes(directorySearch.toLowerCase()) ||
        item.owner_email.toLowerCase().includes(directorySearch.toLowerCase())
      );

      return (
        <div>
          {/* Header */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "28px" }}>
            <div>
              <h2 style={{ margin: 0, fontSize: "22px", fontWeight: 600, color: "#092f28" }}>Workspace Directory</h2>
              <p style={{ fontSize: "14px", color: "#66736d", margin: "4px 0 0 0" }}>System-wide directory of all active workspace tenants. Suspend or reactivate admin controls.</p>
            </div>
          </div>

          {/* Search bar */}
          <div style={{ position: "relative", marginBottom: "20px", maxWidth: "400px" }}>
            <Search style={{ position: "absolute", left: "14px", top: "50%", transform: "translateY(-50%)", color: "var(--muted)" }} size={16} />
            <input
              type="text"
              value={directorySearch}
              onChange={(e) => setDirectorySearch(e.target.value)}
              placeholder="Search workspaces..."
              style={{
                width: "100%",
                padding: "10px 16px 10px 40px",
                borderRadius: "10px",
                border: "1px solid #dce4df",
                fontSize: "13.5px",
                outline: "none"
              }}
            />
          </div>

          {/* Table */}
          {workspacesLoading ? (
            <Loader variant="tab" />
          ) : filteredWorkspaces.length === 0 ? (
            <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "48px", textAlign: "center", color: "var(--muted)" }}>
              No workspaces found.
            </div>
          ) : (
            <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", overflow: "hidden", boxShadow: "0 4px 20px rgba(23, 33, 28, 0.02)" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left", fontSize: "13.5px" }}>
                <thead>
                  <tr style={{ background: "#fafcfb", borderBottom: "1px solid #dce4df" }}>
                    <th style={{ padding: "16px 24px", color: "#092f28", fontWeight: 600, width: "64px" }}>#</th>
                    <th style={{ padding: "16px 24px", color: "#092f28", fontWeight: 600 }}>Organisation</th>
                    <th style={{ padding: "16px 24px", color: "#092f28", fontWeight: 600 }}>Owner Name</th>
                    <th style={{ padding: "16px 24px", color: "#092f28", fontWeight: 600 }}>Email Address</th>
                    <th style={{ padding: "16px 24px", color: "#092f28", fontWeight: 600 }}>Employees</th>
                    <th style={{ padding: "16px 24px", color: "#092f28", fontWeight: 600 }}>Catalogs</th>
                    <th style={{ padding: "16px 24px", color: "#092f28", fontWeight: 600 }}>Status</th>
                    <th style={{ padding: "16px 24px", color: "#092f28", fontWeight: 600, textAlign: "right" }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredWorkspaces.map((ws, index) => (
                    <tr key={ws.id} style={{ borderBottom: "1px solid #dce4df" }}>
                      <td style={{ padding: "16px 24px", color: "var(--muted)" }}>{index + 1}</td>
                      <td style={{ padding: "16px 24px", fontWeight: 600, color: "var(--ink)" }}>{ws.organisation}</td>
                      <td style={{ padding: "16px 24px", color: "var(--ink)" }}>{ws.owner_name}</td>
                      <td style={{ padding: "16px 24px", color: "var(--muted)" }}>{ws.owner_email}</td>
                      <td style={{ padding: "16px 24px", color: "var(--ink)" }}>{ws.employee_count}</td>
                      <td style={{ padding: "16px 24px", color: "var(--ink)" }}>{ws.email_count}</td>
                      <td style={{ padding: "16px 24px" }}>
                        <span style={{
                          fontSize: "11px",
                          fontWeight: 700,
                          padding: "3px 8px",
                          borderRadius: "10px",
                          background: ws.status === "Active" ? "rgba(16, 185, 129, 0.08)" : "rgba(239, 68, 68, 0.08)",
                          color: ws.status === "Active" ? "#10b981" : "#ef4444"
                        }}>
                          {ws.status}
                        </span>
                      </td>
                      <td style={{ padding: "16px 24px", textAlign: "right" }}>
                        <button
                          onClick={() => handleToggleWorkspaceStatus(ws.id, ws.organisation)}
                          disabled={actionLoadingId === ws.id}
                          style={{
                            padding: "6px 12px",
                            borderRadius: "6px",
                            background: "#ffffff",
                            color: ws.status === "Active" ? "#ef4444" : "var(--accent)",
                            border: `1px solid ${ws.status === "Active" ? "#fde8e8" : "rgba(15, 122, 95, 0.2)"}`,
                            fontWeight: 600,
                            fontSize: "12px",
                            cursor: "pointer",
                          }}
                        >
                          {actionLoadingId === ws.id ? "Updating..." : ws.status === "Active" ? "Suspend" : "Activate"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      );
    }

    if (activeTab === "settings") {
      return (
        <div>
          {/* Header */}
          <div style={{ borderBottom: "1px solid var(--line)", paddingBottom: "20px", marginBottom: "28px" }}>
            <h2 style={{ margin: 0, fontSize: "22px", fontWeight: 600, color: "#092f28" }}>Profile Preferences</h2>
            <p style={{ fontSize: "14px", color: "#66736d", margin: "4px 0 0 0" }}>Manage your administrative settings.</p>
          </div>

          <div style={{ background: "#ffffff", border: "1px solid var(--line)", borderRadius: "14px", padding: "0 24px", maxWidth: "600px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "20px 0", borderBottom: "1px solid var(--line)" }}>
              <span style={{ fontSize: "14px", fontWeight: 600, color: "var(--ink)" }}>Superadmin Name</span>
              <span style={{ fontSize: "14px", color: "var(--muted)" }}>{superadminName}</span>
            </div>

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "20px 0", borderBottom: "1px solid var(--line)" }}>
              <span style={{ fontSize: "14px", fontWeight: 600, color: "var(--ink)" }}>Email Address</span>
              <span style={{ fontSize: "14px", color: "var(--muted)" }}>{superadminEmail}</span>
            </div>

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "20px 0" }}>
              <span style={{ fontSize: "14px", fontWeight: 600, color: "var(--ink)" }}>System Role</span>
              <span style={{
                padding: "4px 12px",
                background: "rgba(15, 122, 95, 0.08)",
                color: "var(--accent)",
                borderRadius: "20px",
                fontSize: "11px",
                fontWeight: 700,
                textTransform: "uppercase"
              }}>
                superadmin
              </span>
            </div>
          </div>
        </div>
      );
    }

    return null;
  };

  if (sessionLoading) {
    return <Loader variant="card" title="Verifying Superadmin Session" subtitle="Loading metrics telemetry..." />;
  }

  if (!isAuthorized) {
    return (
      <main className="auth-page">
        <div className="auth-card-wrapper">
          <div className="auth-card-glow"></div>
          <form className="auth-card" onSubmit={handleSuperadminLogin}>
            <div className="auth-brand">
              <div className="brand-logo" style={{ background: "transparent", width: "64px", height: "64px", padding: 0, display: "inline-flex", justifyContent: "center", alignItems: "center", marginBottom: "12px" }}>
                <img src="/Tarkshy.png" alt="Tarkshy Logo" style={{ width: "100%", height: "100%", objectFit: "contain" }} />
              </div>
              <h1>MediCORE</h1>
              <p className="brand-tagline" style={{ margin: "2px 0 16px 0" }}>
                <span style={{ fontSize: "12px", opacity: 0.8 }}>By Tarkshy Consultancy Services</span>
              </p>
            </div>

            <div className="auth-header-text" style={{ textAlign: "center", marginBottom: "20px" }}>
              <h2>Superadmin Console</h2>
              <p style={{ fontSize: "13px", color: "#66736d", marginTop: "4px" }}>
                Enter superadmin credentials to access global administration.
              </p>
            </div>

            {loginError && (
              <div className="auth-error-box" style={{ marginBottom: "20px" }}>
                <XCircle className="error-icon" />
                <span>{loginError}</span>
              </div>
            )}

            <div className="input-group">
              <label htmlFor="email">
                <span>Email Address</span>
                <div className="input-with-icon">
                  <Mail className="field-icon" />
                  <input
                    id="email"
                    type="email"
                    value={loginEmail}
                    onChange={(e) => setLoginEmail(e.target.value)}
                    placeholder="name@example.com"
                    required
                  />
                </div>
              </label>
            </div>

            <div className="input-group" style={{ marginTop: "16px" }}>
              <label htmlFor="password">
                <span>Password</span>
                <div className="input-with-icon">
                  <Lock className="field-icon" />
                  <input
                    id="password"
                    type={showPassword ? "text" : "password"}
                    value={loginPassword}
                    onChange={(e) => setLoginPassword(e.target.value)}
                    placeholder="••••••••"
                    required
                  />
                  <button
                    type="button"
                    className="password-toggle-btn"
                    onClick={() => setShowPassword(!showPassword)}
                    aria-label={showPassword ? "Hide password" : "Show password"}
                  >
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </label>
            </div>

            <button type="submit" className="submit-btn" style={{ marginTop: "24px", width: "100%", display: "flex", justifyContent: "center", alignItems: "center" }} disabled={loginLoading}>
              {loginLoading ? (
                <>
                  <Loader2 className="spinner" size={16} style={{ display: "inline-block", marginRight: "8px", verticalAlign: "middle" }} />
                  Authenticating...
                </>
              ) : (
                <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
                  Sign In to Console
                  <ArrowRight size={16} style={{ marginLeft: "8px" }} />
                </span>
              )}
            </button>
          </form>
        </div>
        <style jsx global>{`
          .auth-page {
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background: radial-gradient(circle at 10% 20%, rgba(244, 247, 245, 1) 0%, rgba(220, 228, 223, 0.4) 90%);
            padding: 24px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          }

          .auth-card-wrapper {
            position: relative;
            width: 100%;
            max-width: 440px;
          }

          .auth-card-glow {
            position: absolute;
            top: -20px;
            left: -20px;
            right: -20px;
            bottom: -20px;
            background: radial-gradient(circle, rgba(15, 122, 95, 0.08) 0%, transparent 70%);
            filter: blur(10px);
            z-index: 0;
            pointer-events: none;
          }

          .auth-card {
            position: relative;
            background: #ffffff;
            border: 1px solid #dce4df;
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 10px 30px rgba(23, 33, 28, 0.06), 0 1px 3px rgba(23, 33, 28, 0.02);
            z-index: 1;
          }

          .auth-brand {
            text-align: center;
            margin-bottom: 32px;
          }

          .brand-logo {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 48px;
            height: 48px;
            background: rgba(15, 122, 95, 0.1);
            color: #0f7a5f;
            border-radius: 12px;
            margin-bottom: 12px;
          }

          .auth-brand h1 {
            margin: 0;
            font-size: 26px;
            font-weight: 800;
            color: #0f7a5f;
            letter-spacing: -0.5px;
          }

          .brand-tagline {
            margin: 4px 0 0;
            font-size: 12px;
            color: #66736d;
            font-weight: 500;
            letter-spacing: 0.5px;
            text-transform: uppercase;
          }

          .auth-header-text {
            margin-bottom: 24px;
          }

          .auth-header-text h2 {
            margin: 0;
            font-size: 20px;
            font-weight: 700;
            color: #17211c;
          }

          .auth-header-text p {
            margin: 4px 0 0;
            font-size: 14px;
            color: #66736d;
          }

          .auth-error-box {
            background: #fdf2f2;
            border: 1px solid #fde8e8;
            border-radius: 8px;
            padding: 12px 16px;
            display: flex;
            align-items: flex-start;
            gap: 10px;
            margin-bottom: 24px;
            color: #9b1c1c;
            font-size: 14px;
          }

          .error-icon {
            flex-shrink: 0;
            margin-top: 2px;
            width: 16px;
            height: 16px;
            transform: rotate(180deg);
          }

          .input-group {
            margin-bottom: 20px;
            text-align: left;
          }

          .input-group label span {
            display: block;
            font-size: 13px;
            font-weight: 600;
            color: #17211c;
            margin-bottom: 8px;
            text-align: left;
          }

          .input-with-icon {
            position: relative;
          }

          .field-icon {
            position: absolute;
            left: 14px;
            top: 50%;
            transform: translateY(-50%);
            color: #66736d;
            width: 18px;
            height: 18px;
          }

          .input-with-icon input {
            width: 100%;
            height: 48px;
            padding: 0 16px 0 44px;
            border: 1px solid #dce4df;
            border-radius: 10px;
            font-size: 14px;
            color: #17211c;
            background: #fafcfb;
            outline: none;
            transition: all 0.2s;
          }

          .input-with-icon input:focus {
            border-color: #0f7a5f;
            background: #ffffff;
            box-shadow: 0 0 0 3px rgba(15, 122, 95, 0.08);
          }

          .password-toggle-btn {
            position: absolute;
            right: 14px;
            top: 50%;
            transform: translateY(-50%);
            background: none !important;
            border: none !important;
            padding: 0 !important;
            color: #66736d !important;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: color 0.2s;
            width: auto !important;
            min-height: unset !important;
            box-shadow: none !important;
          }

          .password-toggle-btn:hover {
            color: #17211c;
          }

          .submit-btn {
            width: 100%;
            height: 48px;
            background: #0f7a5f;
            color: #ffffff;
            border: none;
            border-radius: 10px;
            font-size: 15px;
            font-weight: 600;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            cursor: pointer;
            transition: all 0.2s;
            margin-top: 8px;
          }

          .submit-btn:hover {
            background: #0d6a50;
            box-shadow: 0 4px 12px rgba(15, 122, 95, 0.2);
          }

          .submit-btn:disabled {
            background: #80bfae;
            cursor: not-allowed;
            box-shadow: none;
          }
        `}</style>
      </main>
    );
  }

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes pulse-green {
          0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.4); }
          70% { box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }
          100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
        }
        @keyframes pulse-red {
          0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
          70% { box-shadow: 0 0 0 8px rgba(239, 68, 68, 0); }
          100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
        }
        .pulse-dot-green {
          display: inline-block;
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: #10b981;
          animation: pulse-green 2s infinite;
          vertical-align: middle;
          margin-right: 6px;
        }
        .pulse-dot-red {
          display: inline-block;
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: #ef4444;
          animation: pulse-red 2s infinite;
          vertical-align: middle;
          margin-right: 6px;
        }
      ` }} />
      {/* Navbar */}
      <nav className="navbar">
        <div className="navbar-brand" style={{ display: "flex", alignItems: "center", gap: "14px" }}>
          <h1>MediCORE</h1>
          <span style={{ fontSize: "12.5px", color: "var(--muted)", fontWeight: 500, letterSpacing: "0.02em", borderLeft: "1px solid var(--line)", paddingLeft: "14px" }}>
            Superadmin Panel
          </span>
        </div>
        <div className="navbar-actions">
          <div className="user-menu" style={{ cursor: "default" }}>
            <div className="user-avatar" style={{ background: "rgba(15, 122, 95, 0.12)", color: "var(--accent)" }}>
              {superadminName ? superadminName.split(" ").map((n) => n[0]).join("").toUpperCase() : "SA"}
            </div>
            <div className="user-info">
              <p>{superadminName}</p>
              <span>Superadmin</span>
            </div>
          </div>
        </div>
      </nav>

      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-content">
          <div className="sidebar-top">
            <span className="sidebar-top-label"><h2>Menu</h2></span>
            <button
              className="sidebar-toggle"
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
              aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              {sidebarCollapsed ? <Menu size={20} /> : <X size={20} />}
            </button>
          </div>

          <div className="sidebar-section">
            <ul className="sidebar-nav">
              <li className="sidebar-nav-item">
                <button
                  onClick={() => setActiveTab("dashboard")}
                  className={`sidebar-nav-link ${activeTab === "dashboard" ? "active" : ""}`}
                >
                  <LayoutDashboard size={18} />
                  <span>Dashboard</span>
                </button>
              </li>
              <li className="sidebar-nav-item">
                <button
                  onClick={() => setActiveTab("approvals")}
                  className={`sidebar-nav-link ${activeTab === "approvals" ? "active" : ""}`}
                >
                  <div className="sidebar-icon-wrapper">
                    <ShieldCheck size={18} />
                    {pendingWorkspaces.length > 0 && <span className="notification-dot" />}
                  </div>
                  <span>Approvals</span>
                </button>
              </li>
              <li className="sidebar-nav-item">
                <button
                  onClick={() => setActiveTab("directory")}
                  className={`sidebar-nav-link ${activeTab === "directory" ? "active" : ""}`}
                >
                  <Users size={18} />
                  <span>Directory</span>
                </button>
              </li>
            </ul>
          </div>

          <div className="sidebar-settings-section" style={{ marginTop: "auto" }}>
            <div className="sidebar-section-title">Settings</div>
            <ul className="sidebar-nav">
              <li className="sidebar-nav-item">
                <button
                  onClick={() => setActiveTab("settings")}
                  className={`sidebar-nav-link ${activeTab === "settings" ? "active" : ""}`}
                >
                  <Settings size={18} />
                  <span>Settings</span>
                </button>
              </li>
            </ul>
          </div>

          <div className="sidebar-footer">
            <button type="button" onClick={handleLogout}>
              <LogOut size={16} />
              <span>Logout</span>
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="app-shell">
        {/* Success/Error Alerts */}
        {successMsg && (
          <div style={{
            background: "#f0fdf4",
            border: "1px solid #dcfce7",
            borderRadius: "10px",
            padding: "12px 18px",
            marginBottom: "20px",
            color: "#16a34a",
            fontSize: "13.5px",
            display: "flex",
            alignItems: "center",
            gap: "8px",
            boxShadow: "0 2px 10px rgba(16, 185, 129, 0.05)"
          }}>
            <CheckCircle2 size={16} />
            <span>{successMsg}</span>
          </div>
        )}
        {errorMsg && (
          <div style={{
            background: "#fdf2f2",
            border: "1px solid #fde8e8",
            borderRadius: "10px",
            padding: "12px 18px",
            marginBottom: "20px",
            color: "#9b1c1c",
            fontSize: "13.5px",
            display: "flex",
            alignItems: "center",
            gap: "8px",
            boxShadow: "0 2px 10px rgba(239, 68, 68, 0.05)"
          }}>
            <XCircle size={16} />
            <span>{errorMsg}</span>
          </div>
        )}

        <section className="dashboard">
          {renderTabContent()}
        </section>
      </main>
    </>
  );
}
