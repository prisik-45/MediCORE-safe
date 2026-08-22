"use client";

import React, { useEffect, useState, use } from "react";
import { useRouter } from "next/navigation";
import Loader from "@/components/Loader";
import { getApiBaseUrl } from "@/lib/api";
import { authFetch } from "@/lib/auth";
import { 
  Users, 
  MailOpen, 
  MessageSquare, 
  Sparkles, 
  Plus, 
  RefreshCw, 
  Trash2, 
  X, 
  ShieldAlert, 
  MailCheck, 
  Database, 
  Landmark, 
  Layers, 
  HelpCircle, 
  CalendarRange,
  UserX,
  Info,
  Edit,
  LayoutDashboard,
  LogOut,
  Settings,
  Menu,
  KeyRound
} from "lucide-react";
import { supabase } from "@/lib/supabase";

interface DashboardStats {
  total_employees: number;
  total_emails_processed: number;
  ai_queries_today: number;
}

interface DBStats {
  total_suppliers: number;
  total_ingredients: number;
  database_size_mb: number;
  searches_per_day: number;
  searches_per_month: number;
}

interface Employee {
  id: string;
  name: string;
  email: string;
  status: string;
  role: string;
  last_sync: string;
}

interface AISettings {
  provider: string;
  has_api_key: boolean;
  api_key_last4?: string | null;
  vision_model: string;
  text_model: string;
}

type AdminTab = "dashboard" | "employees" | "database" | "settings";
type SettingsTab = "profile" | "api_key";

export default function AdminWorkspacePage({ params }: { params: Promise<{ tab?: string[] }> }) {
  const resolvedParams = use(params);
  const router = useRouter();
  const [activeTab, setActiveTabState] = useState<AdminTab>("dashboard");
  const [sessionLoading, setSessionLoading] = useState(true);
  const [adminName, setAdminName] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  useEffect(() => {
    // Verify session and role on component mount
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      if (!session) {
        router.push("/login");
        return;
      }

      try {
        const response = await authFetch(`${getApiUrl()}/api/profile`);
        if (!response.ok) {
          throw new Error("Profile verification failed.");
        }
        const profile = await response.json();
        if (profile.role !== "admin") {
          router.push(profile.role === "superadmin" ? "/superadmin" : "/login");
          return;
        }
        setAdminName(profile.full_name || session.user.email?.split("@")[0] || "Admin");
        setSessionLoading(false);
      } catch {
        router.push("/login");
      }
    });
  }, [router]);

  useEffect(() => {
    // Manage sidebar-collapsed body class to align margins globally
    if (sidebarCollapsed) {
      document.body.classList.add("sidebar-collapsed");
    } else {
      document.body.classList.remove("sidebar-collapsed");
    }
    return () => {
      document.body.classList.remove("sidebar-collapsed");
    };
  }, [sidebarCollapsed]);

  async function handleLogout() {
    await supabase.auth.signOut();
    router.push("/login");
  }

  const setActiveTab = (tab: AdminTab) => {
    setActiveTabState(tab);
    if (typeof window !== "undefined") {
      const path = tab === "dashboard" ? "/admin" : `/admin/${tab}`;
      if (window.location.pathname !== path) {
        window.history.pushState({ tab }, "", path);
      }
    }
  };

  // Sync route param on initial mount / page load or popstate
  useEffect(() => {
    if (resolvedParams?.tab) {
      const tabParam = resolvedParams.tab[0] as AdminTab;
      if (tabParam && tabParam !== activeTab) {
        setActiveTabState(tabParam);
      }
    } else {
      if (activeTab !== "dashboard") {
        setActiveTabState("dashboard");
      }
    }
  }, [resolvedParams]);

  // Listen to popstate event (e.g. browser back button or custom navigation trigger)
  useEffect(() => {
    const handlePopState = () => {
      if (typeof window !== "undefined") {
        const path = window.location.pathname;
        const tab = path.split("/admin/")[1] as AdminTab;
        setActiveTabState(tab || "dashboard");
      }
    };
    handlePopState();
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const getApiUrl = getApiBaseUrl;

  // --- 1. Dashboard State & Fetching ---
  const [dashboardStats, setDashboardStats] = useState<DashboardStats | null>(null);
  const [dashboardLoading, setDashboardLoading] = useState(true);
  const [dashboardError, setDashboardError] = useState<string | null>(null);

  async function fetchDashboardStats() {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;
      const apiUrl = getApiUrl();
      const response = await authFetch(`${apiUrl}/api/admin/dashboard-stats`);
      if (!response.ok) throw new Error("Failed to load dashboard metrics.");
      const data = await response.json();
      setDashboardStats(data);
    } catch (err: any) {
      setDashboardError(err.message);
    } finally {
      setDashboardLoading(false);
    }
  }

  // --- 2. Database Stats State & Fetching ---
  const [dbStats, setDbStats] = useState<DBStats | null>(null);
  const [dbLoading, setDbLoading] = useState(true);
  const [dbError, setDbError] = useState<string | null>(null);

  async function fetchDBStats() {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;
      const apiUrl = getApiUrl();
      const response = await authFetch(`${apiUrl}/api/admin/database-stats`);
      if (!response.ok) throw new Error("Failed to load database health metrics.");
      const data = await response.json();
      setDbStats(data);
    } catch (err: any) {
      setDbError(err.message);
    } finally {
      setDbLoading(false);
    }
  }

  // --- 3. Employees State & Fetching ---
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [employeesLoading, setEmployeesLoading] = useState(true);
  const [employeesError, setEmployeesError] = useState<string | null>(null);

  // Modal & Confirmation states
  const [showAddModal, setShowAddModal] = useState(false);
  const [inviteName, setInviteName] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteLoading, setInviteLoading] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [inviteSuccess, setInviteSuccess] = useState(false);

  const [confirmRemoveId, setConfirmRemoveId] = useState<string | null>(null);
  const [removeLoading, setRemoveLoading] = useState(false);

  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  const [confirmResetId, setConfirmResetId] = useState<string | null>(null);
  const [resetLoading, setResetLoading] = useState(false);
  const [resetSuccessMsg, setResetSuccessMsg] = useState<string | null>(null);

  async function fetchEmployees() {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;
      const apiUrl = getApiUrl();
      const response = await authFetch(`${apiUrl}/api/admin/employees`);
      if (!response.ok) throw new Error("Failed to load employee list.");
      const data = await response.json();
      const sorted = data.sort((a: Employee, b: Employee) => {
        if (a.status === b.status) return a.name.localeCompare(b.name);
        if (a.status === "Active") return -1;
        if (b.status === "Active") return 1;
        if (a.status === "Pending Activation") return -1;
        return 1;
      });
      setEmployees(sorted);
    } catch (err: any) {
      setEmployeesError(err.message);
    } finally {
      setEmployeesLoading(false);
    }
  }

  // --- 4. Profile Settings State & Fetching ---
  const [profileName, setProfileName] = useState("");
  const [profileEmail, setProfileEmail] = useState("");
  const [profileOrg, setProfileOrg] = useState("");
  const [profileLoading, setProfileLoading] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Layout replication states
  const [isEditingProfile, setIsEditingProfile] = useState(false);
  const [settingsActiveTab, setSettingsActiveTab] = useState<SettingsTab>("profile");
  const [aiSettingsLoaded, setAiSettingsLoaded] = useState(false);
  const [aiSettingsLoading, setAiSettingsLoading] = useState(false);
  const [aiSettingsSaving, setAiSettingsSaving] = useState(false);
  const [aiSettingsError, setAiSettingsError] = useState<string | null>(null);
  const [aiSettingsSuccess, setAiSettingsSuccess] = useState(false);
  const [openRouterApiKey, setOpenRouterApiKey] = useState("");
  const [openRouterKeyLast4, setOpenRouterKeyLast4] = useState<string | null>(null);
  const [openRouterHasKey, setOpenRouterHasKey] = useState(false);
  const [visionModel, setVisionModel] = useState("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free");
  const [textModel, setTextModel] = useState("openai/gpt-4o-mini");
  const [visibleGuides, setVisibleGuides] = useState({
    profile_tab_desc: false,
    profile_org: false,
  });

  function userInitials(name: string, email: string) {
    if (name) {
      return name.split(" ").map((n) => n[0]).join("").toUpperCase();
    }
    if (email) {
      return email.split("@")[0].substring(0, 2).toUpperCase();
    }
    return "AD";
  }

  async function fetchProfile() {
    setProfileLoading(true);
    setSaveError(null);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;
      const apiUrl = getApiUrl();
      const response = await authFetch(`${apiUrl}/api/profile`);
      if (!response.ok) throw new Error("Failed to load profile data.");
      const data = await response.json();
      setProfileName(data.full_name || "");
      setProfileEmail(data.email || session.user.email || "");
      setProfileOrg(data.organisation || "");
    } catch (err: any) {
      setSaveError(err.message);
    } finally {
      setProfileLoading(false);
    }
  }

  async function handleSaveProfile(e: React.FormEvent) {
    e.preventDefault();
    setSaveLoading(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;
      const apiUrl = getApiUrl();
      
      const response = await authFetch(`${apiUrl}/api/profile`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ full_name: profileName.trim() })
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || "Failed to update database profile.");
      }
      
      const { error: authError } = await supabase.auth.updateUser({
        data: { full_name: profileName.trim() }
      });
      if (authError) throw authError;

      setSaveSuccess(true);
      setIsEditingProfile(false);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err: any) {
      setSaveError(err.message);
    } finally {
      setSaveLoading(false);
    }
  }

  function stripOpenRouter(text?: string | null): string {
    if (!text) return "";
    return text.replace(/OpenRouter\s*/gi, "").replace(/AI Provider API key/gi, "API key").trim();
  }

  async function fetchAISettings() {
    setAiSettingsLoading(true);
    setAiSettingsError(null);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;
      const response = await authFetch(`${getApiUrl()}/api/admin/ai-settings`);
      if (!response.ok) throw new Error("Failed to load AI settings.");
      const data: AISettings = await response.json();
      setOpenRouterHasKey(data.has_api_key);
      setOpenRouterKeyLast4(data.api_key_last4 || null);
      setVisionModel(data.vision_model || "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free");
      setTextModel(data.text_model || "openai/gpt-4o-mini");
      setOpenRouterApiKey("");
      setAiSettingsLoaded(true);
    } catch (err: any) {
      setAiSettingsError(stripOpenRouter(err.message) || "Failed to load AI settings.");
    } finally {
      setAiSettingsLoading(false);
    }
  }

  async function handleSaveAISettings(e: React.FormEvent) {
    e.preventDefault();
    setAiSettingsSaving(true);
    setAiSettingsError(null);
    setAiSettingsSuccess(false);
    try {
      const payload = {
        api_key: openRouterApiKey.trim() || null,
        vision_model: visionModel.trim(),
        text_model: textModel.trim(),
      };
      const response = await authFetch(`${getApiUrl()}/api/admin/ai-settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        const rawErr = detail.detail || "Failed to save AI settings.";
        throw new Error(stripOpenRouter(rawErr) || "Failed to save AI settings.");
      }
      const data: AISettings = await response.json();
      setOpenRouterHasKey(data.has_api_key);
      setOpenRouterKeyLast4(data.api_key_last4 || null);
      setVisionModel(data.vision_model);
      setTextModel(data.text_model);
      setOpenRouterApiKey("");
      setAiSettingsSuccess(true);
      setTimeout(() => setAiSettingsSuccess(false), 3000);
    } catch (err: any) {
      setAiSettingsError(stripOpenRouter(err.message) || "Failed to save AI settings.");
    } finally {
      setAiSettingsSaving(false);
    }
  }

  // Trigger data fetches on tab change if not already loaded
  useEffect(() => {
    if (activeTab === "dashboard" && !dashboardStats) {
      fetchDashboardStats();
    } else if (activeTab === "database" && !dbStats) {
      fetchDBStats();
    } else if (activeTab === "employees" && employees.length === 0) {
      fetchEmployees();
    } else if (activeTab === "settings" && !profileEmail) {
      fetchProfile();
    }
  }, [activeTab]);

  useEffect(() => {
    if (activeTab === "settings" && settingsActiveTab === "api_key" && !aiSettingsLoaded) {
      fetchAISettings();
    }
  }, [activeTab, settingsActiveTab, aiSettingsLoaded]);

  // Handle Invitation
  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    setInviteError(null);
    setInviteLoading(true);
    setInviteSuccess(false);

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(inviteEmail)) {
      setInviteError("Please enter a valid email address.");
      setInviteLoading(false);
      return;
    }

    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;
      const apiUrl = getApiUrl();
      const response = await authFetch(`${apiUrl}/api/admin/employees/invite`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name: inviteName.trim(),
          email: inviteEmail.trim(),
        }),
      });

      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || "Failed to invite employee.");
      }

      setInviteSuccess(true);
      setInviteName("");
      setInviteEmail("");
      fetchEmployees();
      setTimeout(() => {
        setShowAddModal(false);
        setInviteSuccess(false);
      }, 2000);
    } catch (err: any) {
      setInviteError(err.message);
    } finally {
      setInviteLoading(false);
    }
  }

  // Handle Remove Employee
  async function handleRemoveEmployee() {
    if (!confirmRemoveId) return;
    setRemoveLoading(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;
      const apiUrl = getApiUrl();
      const response = await authFetch(`${apiUrl}/api/admin/employees/${confirmRemoveId}/remove`, {
        method: "POST",
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || "Failed to remove employee.");
      }
      setConfirmRemoveId(null);
      setEmployees((current) => current.map((employee) => (
        employee.id === confirmRemoveId ? { ...employee, status: "Disabled", last_sync: "Never" } : employee
      )));
      window.setTimeout(() => fetchEmployees(), 500);
    } catch (err: any) {
      setEmployeesError(err.message);
    } finally {
      setRemoveLoading(false);
    }
  }

  // Handle Permanent Delete Employee
  async function handleDeleteEmployee() {
    if (!confirmDeleteId) return;
    setDeleteLoading(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;
      const apiUrl = getApiUrl();
      const response = await authFetch(`${apiUrl}/api/admin/employees/${confirmDeleteId}/delete`, {
        method: "POST",
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || "Failed to delete employee.");
      }
      setConfirmDeleteId(null);
      setEmployees((current) => current.filter((employee) => employee.id !== confirmDeleteId));
      window.setTimeout(() => fetchEmployees(), 500);
    } catch (err: any) {
      setEmployeesError(err.message);
    } finally {
      setDeleteLoading(false);
    }
  }

  // Handle Reset Password Link
  async function handleResetPassword() {
    if (!confirmResetId) return;
    setResetLoading(true);
    setResetSuccessMsg(null);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;
      const apiUrl = getApiUrl();
      const response = await authFetch(`${apiUrl}/api/admin/employees/${confirmResetId}/reset-password`, {
        method: "POST",
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || "Failed to request password reset.");
      }
      setResetSuccessMsg("Password reset link sent to employee email.");
      setTimeout(() => {
        setConfirmResetId(null);
        setResetSuccessMsg(null);
      }, 2500);
    } catch (err: any) {
      setEmployeesError(err.message);
    } finally {
      setResetLoading(false);
    }
  }

  function getStatusStyle(status: string) {
    switch (status) {
      case "Active":
        return { background: "rgba(16, 185, 129, 0.08)", color: "#10b981", border: "1px solid rgba(16, 185, 129, 0.15)" };
      case "Pending Activation":
        return { background: "rgba(245, 158, 11, 0.08)", color: "#f59e0b", border: "1px solid rgba(245, 158, 11, 0.15)" };
      case "Disabled":
      default:
        return { background: "rgba(239, 68, 68, 0.08)", color: "#ef4444", border: "1px solid rgba(239, 68, 68, 0.15)" };
    }
  }

  // --- RENDERING VIEWS ---

  const renderTabContent = () => {
    if (activeTab === "dashboard") {
      if (dashboardLoading) {
      return <Loader variant="tab" />;
    }
    if (dashboardError) {
      return (
        <div style={{ background: "#fdf2f2", color: "#9b1c1c", padding: "16px", borderRadius: "10px", border: "1px solid #fde8e8" }}>
          {dashboardError}
        </div>
      );
    }
    return (
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "32px" }}>
          <div>
            <h2 style={{ margin: 0, fontSize: "22px", fontWeight: 600, color: "#092f28" }}>Dashboard Overview</h2>
            <p style={{ fontSize: "14px", color: "#66736d", margin: "4px 0 0 0" }}>System metrics and operations tracking.</p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", background: "#ffffff", padding: "8px 16px", borderRadius: "10px", border: "1px solid #dce4df", fontSize: "13px", fontWeight: 500, color: "#0f7a5f" }}>
            <Sparkles size={16} />
            System Active
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "24px", marginBottom: "40px" }}>
          <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "24px", boxShadow: "0 4px 20px rgba(23, 33, 28, 0.02)", display: "flex", alignItems: "center", justifyContent: "space-between", position: "relative", overflow: "hidden" }}>
            <div>
              <span style={{ fontSize: "13px", fontWeight: 500, color: "#66736d", textTransform: "uppercase", letterSpacing: "0.5px" }}>Total Employees</span>
              <h3 style={{ fontSize: "24px", fontWeight: 500, color: "#17211c", margin: "8px 0 0 0" }}>{dashboardStats?.total_employees}</h3>
            </div>
            <div style={{ width: "48px", height: "48px", borderRadius: "12px", background: "rgba(15, 122, 95, 0.08)", color: "#0f7a5f", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Users size={24} />
            </div>
          </div>

          <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "24px", boxShadow: "0 4px 20px rgba(23, 33, 28, 0.02)", display: "flex", alignItems: "center", justifyContent: "space-between", position: "relative", overflow: "hidden" }}>
            <div>
              <span style={{ fontSize: "13px", fontWeight: 500, color: "#66736d", textTransform: "uppercase", letterSpacing: "0.5px" }}>Supplier Emails Processed</span>
              <h3 style={{ fontSize: "24px", fontWeight: 500, color: "#17211c", margin: "8px 0 0 0" }}>{dashboardStats?.total_emails_processed}</h3>
            </div>
            <div style={{ width: "48px", height: "48px", borderRadius: "12px", background: "rgba(15, 122, 95, 0.08)", color: "#0f7a5f", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <MailOpen size={24} />
            </div>
          </div>

          <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "24px", boxShadow: "0 4px 20px rgba(23, 33, 28, 0.02)", display: "flex", alignItems: "center", justifyContent: "space-between", position: "relative", overflow: "hidden" }}>
            <div>
              <span style={{ fontSize: "13px", fontWeight: 500, color: "#66736d", textTransform: "uppercase", letterSpacing: "0.5px" }}>AI Queries Today</span>
              <h3 style={{ fontSize: "24px", fontWeight: 500, color: "#17211c", margin: "8px 0 0 0" }}>{dashboardStats?.ai_queries_today}</h3>
            </div>
            <div style={{ width: "48px", height: "48px", borderRadius: "12px", background: "rgba(15, 122, 95, 0.08)", color: "#0f7a5f", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <MessageSquare size={24} />
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (activeTab === "database") {
    if (dbLoading) {
      return <Loader variant="tab" />;
    }
    if (dbError) {
      return (
        <div style={{ background: "#fdf2f2", color: "#9b1c1c", padding: "16px", borderRadius: "10px", border: "1px solid #fde8e8" }}>
          {dbError}
        </div>
      );
    }
    return (
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "32px" }}>
          <div>
            <h2 style={{ margin: 0, fontSize: "22px", fontWeight: 600, color: "#092f28" }}>Database Overview</h2>
            <p style={{ fontSize: "14px", color: "#66736d", margin: "4px 0 0 0" }}>Storage size, index health, and SQL query telemetry.</p>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "24px", marginBottom: "32px" }}>
          <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "24px", boxShadow: "0 4px 20px rgba(23, 33, 28, 0.02)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div>
              <span style={{ fontSize: "12px", fontWeight: 500, color: "#66736d", textTransform: "uppercase", letterSpacing: "0.5px" }}>Total Suppliers</span>
              <h3 style={{ fontSize: "22px", fontWeight: 500, color: "#17211c", margin: "8px 0 0 0" }}>{dbStats?.total_suppliers}</h3>
            </div>
            <div style={{ width: "44px", height: "44px", borderRadius: "10px", background: "rgba(15, 122, 95, 0.08)", color: "#0f7a5f", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Landmark size={20} />
            </div>
          </div>

          <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "24px", boxShadow: "0 4px 20px rgba(23, 33, 28, 0.02)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div>
              <span style={{ fontSize: "12px", fontWeight: 500, color: "#66736d", textTransform: "uppercase", letterSpacing: "0.5px" }}>Total Ingredients</span>
              <h3 style={{ fontSize: "22px", fontWeight: 500, color: "#17211c", margin: "8px 0 0 0" }}>{dbStats?.total_ingredients}</h3>
            </div>
            <div style={{ width: "44px", height: "44px", borderRadius: "10px", background: "rgba(15, 122, 95, 0.08)", color: "#0f7a5f", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Layers size={20} />
            </div>
          </div>

          <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "24px", boxShadow: "0 4px 20px rgba(23, 33, 28, 0.02)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div>
              <span style={{ fontSize: "12px", fontWeight: 500, color: "#66736d", textTransform: "uppercase", letterSpacing: "0.5px" }}>Database Size</span>
              <h3 style={{ fontSize: "22px", fontWeight: 500, color: "#17211c", margin: "8px 0 0 0" }}>{dbStats?.database_size_mb} MB</h3>
            </div>
            <div style={{ width: "44px", height: "44px", borderRadius: "10px", background: "rgba(15, 122, 95, 0.08)", color: "#0f7a5f", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Database size={20} />
            </div>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: "24px" }}>
          <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "24px", boxShadow: "0 4px 20px rgba(23, 33, 28, 0.02)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div>
              <span style={{ fontSize: "12px", fontWeight: 500, color: "#66736d", textTransform: "uppercase", letterSpacing: "0.5px" }}>AI Searches / Day (Avg)</span>
              <h3 style={{ fontSize: "22px", fontWeight: 500, color: "#17211c", margin: "8px 0 0 0" }}>{dbStats?.searches_per_day}</h3>
            </div>
            <div style={{ width: "44px", height: "44px", borderRadius: "10px", background: "rgba(15, 122, 95, 0.08)", color: "#0f7a5f", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <HelpCircle size={20} />
            </div>
          </div>

          <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "24px", boxShadow: "0 4px 20px rgba(23, 33, 28, 0.02)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div>
              <span style={{ fontSize: "12px", fontWeight: 500, color: "#66736d", textTransform: "uppercase", letterSpacing: "0.5px" }}>AI Searches / Month (Total)</span>
              <h3 style={{ fontSize: "22px", fontWeight: 500, color: "#17211c", margin: "8px 0 0 0" }}>{dbStats?.searches_per_month}</h3>
            </div>
            <div style={{ width: "44px", height: "44px", borderRadius: "10px", background: "rgba(15, 122, 95, 0.08)", color: "#0f7a5f", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <CalendarRange size={20} />
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (activeTab === "employees") {
    return (
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "32px" }}>
          <div>
            <h2 style={{ margin: 0, fontSize: "22px", fontWeight: 600, color: "#092f28" }}>Employee Directory</h2>
          </div>
          <button
            onClick={() => setShowAddModal(true)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              background: "#0f7a5f",
              color: "#ffffff",
              border: "none",
              borderRadius: "10px",
              padding: "12px 20px",
              fontSize: "14px",
              fontWeight: 500,
              cursor: "pointer",
              transition: "all 0.2s",
              boxShadow: "0 4px 12px rgba(15, 122, 95, 0.15)"
            }}
          >
            <Plus size={18} />
            Add Employee
          </button>
        </div>

        {employeesError && (
          <div style={{ background: "#fdf2f2", color: "#9b1c1c", padding: "16px", borderRadius: "10px", border: "1px solid #fde8e8", marginBottom: "24px" }}>
            {employeesError}
          </div>
        )}

        {employeesLoading ? (
          <Loader variant="tab" />
        ) : (
          <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", overflow: "hidden", boxShadow: "0 4px 20px rgba(23, 33, 28, 0.02)" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
              <thead>
                <tr style={{ background: "#fafcfb", borderBottom: "1px solid #dce4df" }}>
                  <th style={{ padding: "18px 24px", fontSize: "12px", fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.5px", width: "64px" }}>#</th>
                  <th style={{ padding: "18px 24px", fontSize: "12px", fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.5px" }}>Employee Name</th>
                  <th style={{ padding: "18px 24px", fontSize: "12px", fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.5px" }}>Connected Email</th>
                  <th style={{ padding: "18px 24px", fontSize: "12px", fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.5px" }}>Status</th>
                  <th style={{ padding: "18px 24px", fontSize: "12px", fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.5px" }}>Last Sync</th>
                  <th style={{ padding: "18px 24px", fontSize: "12px", fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.5px", textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {employees.length === 0 ? (
                  <tr>
                    <td colSpan={6} style={{ padding: "40px", textAlign: "center", color: "var(--muted)", fontSize: "13px" }}>
                      No employees found. Invite your first employee by clicking "Add Employee".
                    </td>
                  </tr>
                ) : (
                  employees.map((emp, index) => (
                    <tr key={emp.id} style={{ borderBottom: "1px solid #f4f7f5", transition: "background 0.2s" }}>
                      <td style={{ padding: "16px 24px", fontSize: "12.5px", color: "var(--muted)" }}>{index + 1}</td>
                      <td style={{ padding: "16px 24px" }}>
                        <div style={{ fontWeight: 400, color: "var(--ink)", fontSize: "13px" }}>{emp.name}</div>
                      </td>
                      <td style={{ padding: "16px 24px", fontSize: "13px", color: "var(--ink)" }}>{emp.email}</td>
                      <td style={{ padding: "16px 24px" }}>
                        <span style={{
                          padding: "3px 8px",
                          borderRadius: "20px",
                          fontSize: "10.5px",
                          fontWeight: 500,
                          display: "inline-block",
                          ...getStatusStyle(emp.status)
                        }}>
                          {emp.status}
                        </span>
                      </td>
                      <td style={{ padding: "16px 24px", fontSize: "12.5px", color: "var(--muted)" }}>{emp.last_sync}</td>
                      <td style={{ padding: "16px 24px", textAlign: "right" }}>
                        {emp.role !== "admin" && (
                          <div style={{ display: "inline-flex", gap: "8px" }}>
                            {emp.status !== "Disabled" ? (
                              <>
                                <button
                                  onClick={() => setConfirmResetId(emp.id)}
                                  title="Reset Password"
                                  style={{ background: "none", border: "none", color: "#66736d", padding: "6px", cursor: "pointer", borderRadius: "6px", transition: "all 0.2s" }}
                                >
                                  <RefreshCw size={16} />
                                </button>
                                <button
                                  onClick={() => setConfirmRemoveId(emp.id)}
                                  title="Deactivate Account"
                                  style={{ background: "none", border: "none", color: "#e11d48", padding: "6px", cursor: "pointer", borderRadius: "6px", transition: "all 0.2s" }}
                                >
                                  <Trash2 size={16} />
                                </button>
                              </>
                            ) : (
                              <button
                                onClick={() => setConfirmDeleteId(emp.id)}
                                title="Delete Account Permanently"
                                style={{ background: "none", border: "none", color: "#ef4444", padding: "6px", cursor: "pointer", borderRadius: "6px", transition: "all 0.2s", fontSize: "12px", fontWeight: 600 }}
                              >
                                Delete
                              </button>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Action Confirmation Modals (Remove & Reset Password) */}
        {confirmRemoveId && (
          <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(15, 33, 28, 0.4)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1100 }}>
            <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "32px", width: "440px", boxShadow: "0 20px 40px rgba(0,0,0,0.1)", textAlign: "center" }}>
              <div style={{ background: "#fef2f2", color: "#ef4444", width: "48px", height: "48px", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 20px auto" }}>
                <ShieldAlert size={24} />
              </div>
              <h3 style={{ fontSize: "18px", fontWeight: 700, color: "#17211c", margin: "0 0 10px 0" }}>Deactivate Employee</h3>
              <p style={{ fontSize: "14px", color: "#66736d", margin: "0 0 24px 0", lineHeight: 1.5 }}>
                Are you sure you want to deactivate this employee? They will immediately lose workspace access, and their sync integrations will be removed.
              </p>
              <div style={{ display: "flex", gap: "12px" }}>
                <button
                  onClick={() => setConfirmRemoveId(null)}
                  disabled={removeLoading}
                  style={{ flex: 1, padding: "12px", borderRadius: "10px", border: "1px solid #dce4df", background: "none", color: "#66736d", fontSize: "14px", fontWeight: 600, cursor: "pointer" }}
                >
                  Cancel
                </button>
                <button
                  onClick={handleRemoveEmployee}
                  disabled={removeLoading}
                  style={{ flex: 1, padding: "12px", borderRadius: "10px", border: "none", background: "#e11d48", color: "#ffffff", fontSize: "14px", fontWeight: 600, cursor: "pointer" }}
                >
                  {removeLoading ? "Deactivating..." : "Deactivate"}
                </button>
              </div>
            </div>
          </div>
        )}

        {confirmDeleteId && (
          <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(15, 33, 28, 0.4)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1100 }}>
            <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "32px", width: "440px", boxShadow: "0 20px 40px rgba(0,0,0,0.1)", textAlign: "center" }}>
              <div style={{ background: "#fef2f2", color: "#ef4444", width: "48px", height: "48px", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 20px auto" }}>
                <ShieldAlert size={24} />
              </div>
              <h3 style={{ fontSize: "18px", fontWeight: 700, color: "#17211c", margin: "0 0 10px 0" }}>Delete Employee Account</h3>
              <p style={{ fontSize: "14px", color: "#66736d", margin: "0 0 24px 0", lineHeight: 1.5 }}>
                Are you sure you want to permanently delete this employee? Their profile, history, and connected settings will be destroyed. This action is irreversible.
              </p>
              <div style={{ display: "flex", gap: "12px" }}>
                <button
                  onClick={() => setConfirmDeleteId(null)}
                  disabled={deleteLoading}
                  style={{ flex: 1, padding: "12px", borderRadius: "10px", border: "1px solid #dce4df", background: "none", color: "#66736d", fontSize: "14px", fontWeight: 600, cursor: "pointer" }}
                >
                  Cancel
                </button>
                <button
                  onClick={handleDeleteEmployee}
                  disabled={deleteLoading}
                  style={{ flex: 1, padding: "12px", borderRadius: "10px", border: "none", background: "#ef4444", color: "#ffffff", fontSize: "14px", fontWeight: 600, cursor: "pointer" }}
                >
                  {deleteLoading ? "Deleting..." : "Delete Permanently"}
                </button>
              </div>
            </div>
          </div>
        )}

        {confirmResetId && (
          <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(15, 33, 28, 0.4)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1100 }}>
            <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "32px", width: "440px", boxShadow: "0 20px 40px rgba(0,0,0,0.1)", textAlign: "center" }}>
              <div style={{ background: "#f0fdf4", color: "#16a34a", width: "48px", height: "48px", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 20px auto" }}>
                <MailCheck size={24} />
              </div>
              <h3 style={{ fontSize: "18px", fontWeight: 700, color: "#17211c", margin: "0 0 10px 0" }}>Reset Password</h3>
              <p style={{ fontSize: "14px", color: "#66736d", margin: "0 0 24px 0", lineHeight: 1.5 }}>
                Send a password reset link to this employee's email?
              </p>
              {resetSuccessMsg ? (
                <div style={{ background: "#f0fdf4", color: "#16a34a", padding: "12px", borderRadius: "8px", fontSize: "13px", marginBottom: "20px" }}>
                  {resetSuccessMsg}
                </div>
              ) : (
                <div style={{ display: "flex", gap: "12px" }}>
                  <button
                    onClick={() => setConfirmResetId(null)}
                    disabled={resetLoading}
                    style={{ flex: 1, padding: "12px", borderRadius: "10px", border: "1px solid #dce4df", background: "none", color: "#66736d", fontSize: "14px", fontWeight: 600, cursor: "pointer" }}
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleResetPassword}
                    disabled={resetLoading}
                    style={{ flex: 1, padding: "12px", borderRadius: "10px", border: "none", background: "#0f7a5f", color: "#ffffff", fontSize: "14px", fontWeight: 600, cursor: "pointer" }}
                  >
                    {resetLoading ? "Sending..." : "Send Reset Link"}
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Add Employee Modal */}
        {showAddModal && (
          <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(15, 33, 28, 0.4)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1100 }}>
            <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "32px", width: "460px", boxShadow: "0 20px 40px rgba(0,0,0,0.1)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "24px" }}>
                <h3 style={{ fontSize: "18px", fontWeight: 700, color: "#17211c", margin: 0 }}>Invite Employee</h3>
                <button onClick={() => setShowAddModal(false)} style={{ background: "none", border: "none", color: "#66736d", cursor: "pointer" }}>
                  <X size={20} />
                </button>
              </div>

              {inviteError && (
                <div style={{ background: "#fdf2f2", color: "#9b1c1c", padding: "12px", borderRadius: "8px", fontSize: "13px", marginBottom: "16px" }}>
                  {inviteError}
                </div>
              )}

              {inviteSuccess ? (
                <div style={{ background: "#f0fdf4", color: "#16a34a", padding: "16px", borderRadius: "8px", fontSize: "14px", textAlign: "center" }}>
                  Employee invitation sent successfully!
                </div>
              ) : (
                <form onSubmit={handleInvite} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                  <div className="input-group">
                    <label>Employee Name</label>
                    <input
                      type="text"
                      required
                      placeholder="e.g. John Doe"
                      value={inviteName}
                      onChange={(e) => setInviteName(e.target.value)}
                      style={{ width: "100%", padding: "12px", border: "1px solid #dce4df", borderRadius: "8px", fontSize: "14px" }}
                    />
                  </div>
                  <div className="input-group">
                    <label>Work Email</label>
                    <input
                      type="email"
                      required
                      placeholder="e.g. john@company.com"
                      value={inviteEmail}
                      onChange={(e) => setInviteEmail(e.target.value)}
                      style={{ width: "100%", padding: "12px", border: "1px solid #dce4df", borderRadius: "8px", fontSize: "14px" }}
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={inviteLoading}
                    style={{ background: "#0f7a5f", color: "#ffffff", padding: "12px", border: "none", borderRadius: "8px", fontSize: "14px", fontWeight: 600, cursor: "pointer", marginTop: "10px" }}
                  >
                    {inviteLoading ? "Sending Invite..." : "Send Invitation"}
                  </button>
                </form>
              )}
            </div>
          </div>
        )}
      </div>
    );
  }

  if (activeTab === "settings") {
    if (profileLoading) {
      return <Loader variant="tab" />;
    }
    return (
      <div className="settings-container" style={{
        display: "flex",
        flexDirection: "row",
        height: "calc(100vh - 180px)",
        alignItems: "stretch",
        overflow: "hidden",
        background: "#fff",
        border: "1px solid var(--line)",
        borderRadius: "16px",
        boxShadow: "0 4px 24px rgba(0, 0, 0, 0.025)",
      }}>
        {/* 1. LEFT SIDEBAR PANEL */}
        <aside className="settings-sidebar" style={{
          width: "250px",
          background: "#fcfcfc",
          borderRight: "1px solid var(--line)",
          padding: "32px 16px",
          display: "flex",
          flexDirection: "column",
          gap: "6px",
          flexShrink: 0,
        }}>
          <div style={{ padding: "0 12px 20px 12px", borderBottom: "1px solid var(--line)", marginBottom: "20px" }}>
            <h2 style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: "#092f28", letterSpacing: "-0.2px" }}>Workspace Settings</h2>
            <span style={{ fontSize: "12px", color: "var(--muted)", marginTop: "2px", display: "block" }}>Configure defaults & preferences</span>
          </div>

          {[
            { id: "profile", label: "Profile & Preferences", icon: <Users size={16} /> },
            { id: "api_key", label: "API Key", icon: <KeyRound size={16} /> },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setSettingsActiveTab(tab.id as any)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "10px",
                padding: "10px 14px",
                borderRadius: "8px",
                border: "none",
                background: settingsActiveTab === tab.id ? "rgba(15, 122, 95, 0.08)" : "transparent",
                color: settingsActiveTab === tab.id ? "var(--accent)" : "var(--ink)",
                fontWeight: settingsActiveTab === tab.id ? 600 : 500,
                cursor: "pointer",
                transition: "all 0.15s ease",
                textAlign: "left",
                width: "100%",
              }}
              className="settings-tab-btn"
            >
              {tab.icon}
              <span style={{ fontSize: "13.5px" }}>{tab.label}</span>
            </button>
          ))}
        </aside>

        {/* 2. RIGHT CONTENT PANEL */}
        <main className="settings-content" style={{
          background: "#fff",
          padding: "40px",
          display: "flex",
          flexDirection: "column",
          flex: "1 1 0%",
          overflowY: "auto",
          gap: "32px"
        }}>
          {settingsActiveTab === "profile" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "32px" }}>
              <div style={{ borderBottom: "1px solid var(--line)", paddingBottom: "24px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <h2 style={{ margin: 0, fontSize: "22px", fontWeight: 600, color: "#092f28", letterSpacing: "-0.3px" }}>Profile & Preferences</h2>
                  <span
                    onMouseEnter={() => setVisibleGuides(p => ({ ...p, profile_tab_desc: true }))}
                    onMouseLeave={() => setVisibleGuides(p => ({ ...p, profile_tab_desc: false }))}
                    style={{ position: "relative", display: "inline-flex", alignItems: "center", color: "var(--muted)", cursor: "default", marginTop: "4px" }}
                  >
                    <Info size={16} />
                    {visibleGuides.profile_tab_desc && (
                      <span className="settings-tooltip centered" style={{ width: "220px" }}>
                        Manage your administrative profile, workspace details, and system localization preferences.
                      </span>
                    )}
                  </span>
                </div>
              </div>

              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
                  <h3 style={{ margin: 0, fontSize: "12px", fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>User Identity</h3>
                  {!isEditingProfile ? (
                    <button
                      onClick={() => {
                        setIsEditingProfile(true);
                        setSaveError(null);
                      }}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "6px",
                        background: "transparent",
                        border: "none",
                        color: "var(--accent)",
                        fontSize: "13px",
                        fontWeight: 600,
                        cursor: "pointer",
                        padding: "4px 8px",
                        borderRadius: "4px",
                        transition: "all 0.15s ease",
                      }}
                      className="profile-edit-btn"
                    >
                      <Edit size={14} />
                      Edit Profile
                    </button>
                  ) : (
                    <div style={{ display: "flex", gap: "8px" }}>
                      <button
                        onClick={handleSaveProfile}
                        disabled={saveLoading}
                        style={{
                          background: "var(--accent)",
                          color: "#fff",
                          border: "none",
                          padding: "4px 12px",
                          borderRadius: "6px",
                          fontSize: "12px",
                          fontWeight: 600,
                          cursor: saveLoading ? "not-allowed" : "pointer",
                          opacity: saveLoading ? 0.7 : 1,
                        }}
                      >
                        {saveLoading ? "Saving..." : "Save"}
                      </button>
                      <button
                        onClick={() => {
                          setIsEditingProfile(false);
                          setSaveError(null);
                        }}
                        disabled={saveLoading}
                        style={{
                          background: "transparent",
                          color: "var(--muted)",
                          border: "1px solid var(--line)",
                          padding: "4px 12px",
                          borderRadius: "6px",
                          fontSize: "12px",
                          fontWeight: 600,
                          cursor: saveLoading ? "not-allowed" : "pointer",
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  )}
                </div>

                {saveError && (
                  <div style={{
                    background: "#fdf2f2",
                    border: "1px solid #fde8e8",
                    borderRadius: "8px",
                    padding: "10px 14px",
                    marginBottom: "16px",
                    color: "#9b1c1c",
                    fontSize: "13px",
                  }}>
                    {saveError}
                  </div>
                )}

                {saveSuccess && (
                  <div style={{
                    background: "#f0fdf4",
                    border: "1px solid #dcfce7",
                    borderRadius: "8px",
                    padding: "10px 14px",
                    marginBottom: "16px",
                    color: "#16a34a",
                    fontSize: "13px",
                  }}>
                    Settings updated successfully!
                  </div>
                )}

                <div style={{ background: "#fff", border: "1px solid var(--line)", borderRadius: "10px", padding: "0 20px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 0", borderBottom: "1px solid var(--line)" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "16px", minWidth: 0, flex: 1 }}>
                      <div className="user-avatar" style={{ width: "48px", height: "48px", fontSize: "18px", flexShrink: 0, boxShadow: "none" }}>
                        {userInitials(profileName, profileEmail)}
                      </div>
                      <div style={{ minWidth: 0, flex: 1, maxWidth: "400px" }}>
                        {!isEditingProfile ? (
                          <>
                            <strong style={{ display: "block", fontSize: "15px", color: "var(--ink)" }}>{profileName}</strong>
                            <span style={{ fontSize: "13.0px", color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", display: "block", marginTop: "2px" }}>{profileEmail}</span>
                          </>
                        ) : (
                          <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                            <input
                              type="text"
                              value={profileName}
                              onChange={(e) => setProfileName(e.target.value)}
                              style={{
                                padding: "6px 12px",
                                borderRadius: "6px",
                                border: "1px solid var(--line)",
                                fontSize: "14px",
                                color: "var(--ink)",
                                outline: "none",
                                width: "100%",
                                maxWidth: "280px",
                              }}
                              placeholder="Full Name"
                              disabled={saveLoading}
                            />
                            <span style={{ fontSize: "12.0px", color: "var(--muted)", display: "block" }}>{profileEmail}</span>
                          </div>
                        )}
                      </div>
                    </div>
                    <span style={{
                      padding: "4px 12px",
                      background: "rgba(15, 122, 95, 0.08)",
                      color: "var(--accent)",
                      borderRadius: "20px",
                      fontSize: "11px",
                      fontWeight: 700,
                      letterSpacing: "0.05em",
                      textTransform: "uppercase"
                    }}>
                      admin
                    </span>
                  </div>

                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 0" }}>
                    <div style={{ paddingRight: "24px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        <strong style={{ display: "block", fontSize: "14px", color: "var(--ink)" }}>Workplace Organisation</strong>
                        <span
                          onMouseEnter={() => setVisibleGuides(p => ({ ...p, profile_org: true }))}
                          onMouseLeave={() => setVisibleGuides(p => ({ ...p, profile_org: false }))}
                          style={{ position: "relative", display: "inline-flex", alignItems: "center", color: "var(--muted)", cursor: "default" }}
                        >
                          <Info size={14} />
                          {visibleGuides.profile_org && (
                            <span className="settings-tooltip centered" style={{ width: "200px" }}>
                              The workspace name displayed across generated reports and analytics.
                            </span>
                          )}
                        </span>
                      </div>
                    </div>
                    <span style={{ fontSize: "13.5px", fontWeight: 600, color: "var(--muted)", background: "#f9fafb", padding: "6px 12px", borderRadius: "6px", border: "1px solid var(--line)" }}>
                      {profileOrg || "MediCORE Central"}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {settingsActiveTab === "api_key" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "28px" }}>
              <div style={{ borderBottom: "1px solid var(--line)", paddingBottom: "24px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <h2 style={{ margin: 0, fontSize: "22px", fontWeight: 600, color: "#092f28", letterSpacing: "-0.3px" }}>API Key</h2>
                </div>
              </div>

              {aiSettingsLoading ? (
                <Loader variant="tab" />
              ) : (
                <form onSubmit={handleSaveAISettings} style={{ display: "flex", flexDirection: "column", gap: "18px", maxWidth: "720px" }}>
                  {aiSettingsError && (
                    <div style={{
                      background: "#fdf2f2",
                      border: "1px solid #fde8e8",
                      borderRadius: "8px",
                      padding: "10px 14px",
                      color: "#9b1c1c",
                      fontSize: "13px",
                    }}>
                      {aiSettingsError}
                    </div>
                  )}

                  {aiSettingsSuccess && (
                    <div style={{
                      background: "#f0fdf4",
                      border: "1px solid #dcfce7",
                      borderRadius: "8px",
                      padding: "10px 14px",
                      color: "#16a34a",
                      fontSize: "13px",
                    }}>
                      AI settings saved.
                    </div>
                  )}

                  <div style={{ background: "#fff", border: "1px solid var(--line)", borderRadius: "10px", padding: "20px", display: "flex", flexDirection: "column", gap: "18px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "16px", paddingBottom: "12px", borderBottom: "1px solid var(--line)" }}>
                      <div>
                        <strong style={{ display: "block", fontSize: "14px", color: "var(--ink)" }}>Provider</strong>
                        <span style={{ fontSize: "12.5px", color: "var(--muted)" }}>AI Provider</span>
                      </div>
                      <span style={{
                        padding: "4px 12px",
                        background: openRouterHasKey ? "rgba(15, 122, 95, 0.08)" : "#f9fafb",
                        color: openRouterHasKey ? "var(--accent)" : "var(--muted)",
                        borderRadius: "20px",
                        fontSize: "11px",
                        fontWeight: 700,
                        letterSpacing: "0.05em",
                        textTransform: "uppercase"
                      }}>
                        {openRouterHasKey && openRouterKeyLast4 ? `saved ****${openRouterKeyLast4}` : "not saved"}
                      </span>
                    </div>

                    <label style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                      <span style={{ fontSize: "13px", fontWeight: 600, color: "var(--ink)" }}>API Key</span>
                      <input
                        type="password"
                        value={openRouterApiKey}
                        onChange={(e) => setOpenRouterApiKey(e.target.value)}
                        placeholder={openRouterHasKey ? "Leave blank to keep existing key" : "API key"}
                        autoComplete="off"
                        disabled={aiSettingsSaving}
                        style={{
                          padding: "10px 12px",
                          borderRadius: "6px",
                          border: "1px solid var(--line)",
                          fontSize: "14px",
                          color: "var(--ink)",
                          outline: "none",
                          width: "100%",
                        }}
                      />
                    </label>

                    <label style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                      <span style={{ fontSize: "13px", fontWeight: 600, color: "var(--ink)" }}>Vision Model</span>
                      <input
                        type="text"
                        value={visionModel}
                        onChange={(e) => setVisionModel(e.target.value)}
                        disabled={aiSettingsSaving}
                        style={{
                          padding: "10px 12px",
                          borderRadius: "6px",
                          border: "1px solid var(--line)",
                          fontSize: "14px",
                          color: "var(--ink)",
                          outline: "none",
                          width: "100%",
                        }}
                      />
                    </label>

                    <label style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                      <span style={{ fontSize: "13px", fontWeight: 600, color: "var(--ink)" }}>Text Model</span>
                      <input
                        type="text"
                        value={textModel}
                        onChange={(e) => setTextModel(e.target.value)}
                        disabled={aiSettingsSaving}
                        style={{
                          padding: "10px 12px",
                          borderRadius: "6px",
                          border: "1px solid var(--line)",
                          fontSize: "14px",
                          color: "var(--ink)",
                          outline: "none",
                          width: "100%",
                        }}
                      />
                    </label>

                    <div style={{ display: "flex", justifyContent: "flex-end", paddingTop: "4px" }}>
                      <button
                        type="submit"
                        disabled={aiSettingsSaving}
                        style={{
                          background: "var(--accent)",
                          color: "#fff",
                          border: "none",
                          padding: "9px 16px",
                          borderRadius: "6px",
                          fontSize: "13px",
                          fontWeight: 600,
                          cursor: aiSettingsSaving ? "not-allowed" : "pointer",
                          opacity: aiSettingsSaving ? 0.7 : 1,
                        }}
                      >
                        {aiSettingsSaving ? "Saving..." : "Save"}
                      </button>
                    </div>
                  </div>
                </form>
              )}
            </div>
          )}
        </main>
      </div>
    );
  }

    return null;
  };

  if (sessionLoading) {
    return <Loader variant="card" title="Verifying Admin Session" subtitle="Loading dashboard metrics..." />;
  }

  return (
    <>
      {/* Navbar */}
      <nav className="navbar">
        <div className="navbar-brand" style={{ display: "flex", alignItems: "center", gap: "14px" }}>
          <h1>MediCORE</h1>
          <span style={{ fontSize: "12.5px", color: "var(--muted)", fontWeight: 500, letterSpacing: "0.02em", borderLeft: "1px solid var(--line)", paddingLeft: "14px" }}>
            Admin Portal
          </span>
        </div>
        <div className="navbar-actions">
          <div className="user-menu" style={{ cursor: "default" }}>
            <div className="user-avatar">
              {adminName ? adminName.split(" ").map((n: string) => n[0]).join("").toUpperCase() : "AD"}
            </div>
            <div className="user-info">
              <p>{adminName}</p>
              <span>Admin</span>
            </div>
          </div>
        </div>
      </nav>

      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-content">
          <div className="sidebar-top">
            <span className="sidebar-top-label"><h2>Admin</h2></span>
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
                  onClick={() => setActiveTab("employees")}
                  className={`sidebar-nav-link ${activeTab === "employees" ? "active" : ""}`}
                >
                  <Users size={18} />
                  <span>Employees</span>
                </button>
              </li>
              <li className="sidebar-nav-item">
                <button
                  onClick={() => setActiveTab("database")}
                  className={`sidebar-nav-link ${activeTab === "database" ? "active" : ""}`}
                >
                  <Database size={18} />
                  <span>Database</span>
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
        <section className="dashboard">
          {renderTabContent()}
        </section>
      </main>
    </>
  );
}
