"use client";

import Loader from "@/components/Loader";
import { getApiBaseUrl, getChatWsUrl } from "@/lib/api";
import {
  BarChart3,
  Bell,
  ChevronDown,
  FileText,
  GitCompare,
  Inbox,
  Loader2,
  LogOut,
  Mail,
  Menu,
  Plus,
  Search,
  Send,
  Settings,
  Shield,
  Sparkles,
  TrendingUp,
  Users,
  X,
  Sliders,
  Check,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Trash2,
  Edit,
  ArrowRight,
  Info,
  Eye,
  EyeOff,
  ShieldAlert,
} from "lucide-react";
import React, { useEffect, useMemo, useRef, useState, use } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";

type ChatMessage = {
  role: "user" | "assistant" | "status";
  text: string;
};

type CertificatePdf = {
  name: string;
  url: string;
  storage_path?: string | null;
  type?: string | null;
};

type SupplierItem = {
  ingredient_name: string;
  supplier_name?: string;
  email_domain?: string | null;
  country?: string | null;
  specification?: string | null;
  price_per_unit: number | null;
  currency: string;
  available_qty: number | null;
  unit: string | null;
  valid_until?: string;
  lead_time_days?: number | null;
  lead_time_text?: string | null;
  moq?: number | null;
  pack_size?: string | null;
  price_display?: string | null;
  quantity_display?: string | null;
  moq_display?: string | null;
  source_document?: string | null;
  certificate_pdfs?: CertificatePdf[];
  catalog_email_id?: string | null;
  received_at?: string | null;
  is_updated?: boolean;
};

type SupplierApiRow = {
  name: string;
  email_domain: string;
  country?: string | null;
  last_email_date: string | null;
  certifications: string | null;
  item_count?: number;
};

type CatalogEmailRow = {
  id: string;
  supplier_name: string;
  email_domain?: string | null;
  received_at: string;
  subject: string | null;
  pdf_url: string | null;
  body_preview?: string | null;
  processing_status: string;
  item_count?: number;
  duplicate_count?: number;
};

type SupplierTableRow = SupplierItem & {
  supplier_name: string;
  email_domain: string;
  country?: string | null;
  certifications?: string | null;
};

type SidebarTab = "dashboard" | "inbox" | "catalogs" | "analysis" | "compare" | "assistant" | "suppliers" | "settings";

type CompareSort = "best-value" | "lowest-price" | "highest-qty";
type SupplierSort = "name" | "items" | "latest";

type InboxThread = {
  id: string;
  supplier_name: string;
  email_domain: string;
  country?: string | null;
  item_count: number;
  duplicate_count: number;
  latest_item: string;
  received_at: string | null;
  latest_price: number;
  latest_currency: string;
  latest_qty: number;
  latest_unit: string;
  status_label: string;
  status_tone: "processed" | "pending" | "review" | "failed" | "skipped";
  items: SupplierTableRow[];
  pdf_url?: string | null;
  body_preview?: string | null;
  subject?: string | null;
};

const FULL_CATALOG_LIMIT = 10000;
const FULL_INBOX_LIMIT = 10000;

function supplierKey(name: string | null | undefined, email: string | null | undefined): string {
  return `${String(name || "").trim().toLowerCase()}|${String(email || "").trim().toLowerCase()}`;
}

type AuthUser = {
  email: string;
  name: string;
  role: string;
  organisation?: string;
};

type EmailFilter = {
  id?: string;
  require_attachment: boolean;
  sender_keywords: string | null;
  subject_keywords: string | null;
  skip_promotions_tab: boolean;
};

type ConnectedEmailAccount = {
  id: string;
  user_id: string;
  provider: string;
  email_address: string;
  imap_host: string;
  imap_port: number;
  sync_status: string;
  sync_error_msg?: string | null;
  last_synced_at?: string | null;
  created_at: string;
  filters: EmailFilter[];
};

type EmailSyncSetting = {
  id: string;
  user_id: string;
  poll_interval_minutes: number;
  auto_extract_catalog: boolean;
  notify_on_new_catalog: boolean;
  ingestion_approach?: string;
  trusted_suppliers?: string;
  pending_approvals?: string;
};

type SyncActivityEvent = {
  id: string;
  emailId?: string;
  tone: "info" | "processing" | "success" | "skipped" | "failed";
  supplier: string;
  message: string;
  detail?: string;
  timestamp: number;
};

type SyncActivityJob = {
  id: string;
  status: "idle" | "running" | "completed" | "failed";
  startedAt: number;
  completedAt?: number;
  accountIds: string[];
  total: number;
  processed: number;
  skipped: number;
  failed: number;
  events: SyncActivityEvent[];
};


const exampleQuestions = [
  "Which supplier has the best price for ascorbic acid with 20,000+ units available?",
  "Find the most reliable supplier for paracetamol 500mg",
  "Compare supplier prices for citric acid"
];

function formatRelativeTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }

  const diffMinutes = Math.max(1, Math.round((Date.now() - date.getTime()) / 60000));
  if (diffMinutes < 60) {
    return `${diffMinutes}m ago`;
  }

  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) {
    return `${diffHours}h ago`;
  }

  const diffDays = Math.round(diffHours / 24);
  return `${diffDays}d ago`;
}

function formatInboxDate(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }

  return date.toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const RUPEE_SYMBOL = "₹";

function normalizedProcessingStatus(status: string | null | undefined): string {
  return String(status || "").trim().toLowerCase();
}

function inboxStatusTone(status: string | null | undefined, itemCount: number): InboxThread["status_tone"] {
  const normalized = normalizedProcessingStatus(status);
  if (normalized.startsWith("failed") || normalized.startsWith("error")) {
    return "failed";
  }
  if (normalized === "partial" || normalized === "partially_processed") {
    return "review";
  }
  if (normalized === "empty" || normalized.startsWith("skipped") || normalized.startsWith("ignored")) {
    return "skipped";
  }
  if (normalized === "completed" || normalized === "certificate" || itemCount > 0) {
    return "processed";
  }
  return "pending";
}

function inboxStatusLabel(status: string | null | undefined, itemCount: number): string {
  const normalized = normalizedProcessingStatus(status);
  if (normalized.startsWith("failed") || normalized.startsWith("error")) {
    return "Failed";
  }
  if (normalized === "partial" || normalized === "partially_processed") {
    return "Partially Processed";
  }
  if (normalized === "empty" || normalized.startsWith("skipped") || normalized.startsWith("ignored")) {
    return "Skipped";
  }
  if (normalized === "processing" || normalized === "queued") {
    return "Processing";
  }
  if (normalized === "certificate") {
    return "Certificate Processed";
  }
  if (normalized === "completed" || itemCount > 0) {
    return "Processed";
  }
  return "Processing";
}

function syncActivityReason(status: string | null | undefined): string {
  const raw = String(status || "").trim();
  const isFailure = /^(failed|error):/i.test(raw);
  const cleaned = raw
    .replace(/^(failed|error|skipped|ignored):\s*/i, "")
    .trim();
  if (!cleaned || ["failed", "error", "skipped", "ignored", "empty"].includes(cleaned.toLowerCase())) {
    return "";
  }
  if (isFailure) {
    if (/timeout|timed out/i.test(cleaned)) {
      return "Processing timed out. Please retry.";
    }
    if (/attachment|document|file/i.test(cleaned)) {
      return "The email attachment could not be processed.";
    }
    return "Processing could not be completed for this email.";
  }
  if (/traceback|sqlalchemy|psycopg|invalidsql|programmingerror|operationalerror|prepared statement|select\s+|insert\s+|update\s+|ocr|debug|exception/i.test(cleaned)) {
    return "Processing could not be completed for this email.";
  }
  return cleaned.length > 120 ? `${cleaned.slice(0, 117)}...` : cleaned;
}

function trustedSupplierMatches(sender: unknown, trustedSuppliers: string | null | undefined): boolean {
  const rawSender = String(sender || "").trim().toLowerCase();
  const address = rawSender.match(/<([^>]+)>/)?.[1]?.trim() || rawSender;
  const domain = address.includes("@") ? address.split("@").pop() || address : address;
  const terms = String(trustedSuppliers || "")
    .split(",")
    .map((term) => term.trim().toLowerCase())
    .filter(Boolean);
  return terms.includes(address) || terms.includes(domain);
}

function syncEmailSignature(email: CatalogEmailRow): string {
  return `${normalizedProcessingStatus(email.processing_status)}|${Number(email.item_count || 0)}`;
}

function syncEventFromEmail(email: CatalogEmailRow, observedAt?: number): SyncActivityEvent {
  const itemCount = Number(email.item_count || 0);
  const status = normalizedProcessingStatus(email.processing_status);
  const supplier = email.supplier_name || email.email_domain || "Supplier";
  const receivedTimestamp = new Date(email.received_at || Date.now()).getTime();
  const timestamp = observedAt ?? (receivedTimestamp || Date.now());
  if (status.startsWith("failed") || status.startsWith("error")) {
    return {
      id: `email-${email.id}`,
      emailId: email.id,
      tone: "failed",
      supplier,
      message: "Processing failed",
      detail: syncActivityReason(email.processing_status) || "Review the email attachment and retry sync.",
      timestamp,
    };
  }
  if (status === "empty" || status.startsWith("skipped") || status.startsWith("ignored")) {
    const reason = syncActivityReason(email.processing_status);
    return {
      id: `email-${email.id}`,
      emailId: email.id,
      tone: "skipped",
      supplier,
      message: reason && /promo|newsletter|marketing/i.test(reason) ? "Promotional email skipped" : "Email skipped",
      detail: reason || "No procurement catalogue data was detected.",
      timestamp,
    };
  }
  if (status === "completed" || status === "partial" || status === "certificate" || itemCount > 0) {
    return {
      id: `email-${email.id}`,
      emailId: email.id,
      tone: status === "partial" ? "skipped" : "success",
      supplier,
      message: itemCount > 0 ? `${itemCount} item${itemCount === 1 ? "" : "s"} extracted` : "Processed",
      detail: status === "partial" ? "Some fields or attachments need review." : undefined,
      timestamp,
    };
  }
  return {
    id: `email-${email.id}`,
    emailId: email.id,
    tone: "processing",
    supplier,
    message: itemCount > 0 ? "Updating catalogue..." : "Processing catalogue...",
    timestamp,
  };
}

function isProcurementCatalogEmail(email: CatalogEmailRow): boolean {
  const status = normalizedProcessingStatus(email.processing_status);
  if (status === "certificate") {
    return false;
  }
  const hasUsableItems = Number(email.item_count || 0) > 0;
  const isSuccessfulProcurementStatus =
    status === "completed" || status === "partial" || status === "partially_processed";
  return isSuccessfulProcurementStatus || hasUsableItems;
}

function getBasePrice(price: number, currency: string): number {
  const curr = (currency || "INR").toUpperCase();
  if (curr === "USD") return price * 83;
  if (curr === "CAD") return price * 61;
  if (curr === "AUD") return price * 55;
  return price;
}

function formatMoney(value: number, currency = "INR"): string {
  const curr = (currency || "INR").toUpperCase();

  let symbol = curr;
  if (curr === "INR") symbol = "₹";
  else if (curr === "USD") symbol = "$";
  else if (curr === "CAD") symbol = "C$";
  else if (curr === "AUD") symbol = "A$";
  else if (curr === "EUR") symbol = "€";
  else if (curr === "GBP") symbol = "£";

  const separator = (symbol === "₹" || symbol === "$" || symbol === "€" || symbol === "£") ? "" : " ";
  return `${symbol}${separator}${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })}`;
}

function formatCompactCurrency(value: number): string {
  let pref = "INR";
  if (typeof window !== "undefined") {
    pref = localStorage.getItem("mediCORE_currency_pref") || "INR";
  }

  if (!Number.isFinite(value) || value <= 0) {
    const defaultSymbol = pref === "USD" ? "$" : pref === "CAD" ? "C$" : pref === "AUD" ? "A$" : "₹";
    return `${defaultSymbol}0`;
  }

  // Convert base value (assumed INR) to preferred currency
  let finalVal = value;
  if (pref === "USD") {
    finalVal = value / 83;
  } else if (pref === "CAD") {
    finalVal = value / 61;
  } else if (pref === "AUD") {
    finalVal = value / 55;
  }

  let symbol = "₹";
  if (pref === "USD") symbol = "$";
  else if (pref === "CAD") symbol = "C$";
  else if (pref === "AUD") symbol = "A$";

  if (finalVal >= 100000) {
    return `${symbol}${(finalVal / 100000).toFixed(1)}L`;
  }

  if (finalVal >= 1000) {
    return `${symbol}${(finalVal / 1000).toFixed(1)}K`;
  }

  return `${symbol}${finalVal.toFixed(0)}`;
}

function formatQuantity(value: number): string {
  return new Intl.NumberFormat("en-IN", { maximumFractionDigits: 4 }).format(value);
}

function safePrice(value: number | null | undefined, currency?: string): number {
  return value == null ? Number.POSITIVE_INFINITY : getBasePrice(value, currency || "INR");
}

function safeQty(value: number | null | undefined): number {
  return value == null ? 0 : value;
}

function isMissingDisplayValue(value: unknown): boolean {
  if (value == null) return true;
  return ["", "na", "n/a", "none", "null", "-", "--"].includes(String(value).trim().toLowerCase());
}

function displayText(value: unknown): string {
  return isMissingDisplayValue(value) ? "-" : String(value);
}

function displayItemName(item: Pick<SupplierItem, "ingredient_name" | "is_updated"> | Record<string, unknown>): string {
  const rawName = (item as any).ingredient_name;
  const name = displayText(rawName);
  return name !== "-" && (item as any).is_updated ? `${name} (U)` : name;
}

function renderItemName(item: Pick<SupplierItem, "ingredient_name" | "is_updated"> | Record<string, unknown>) {
  const rawName = (item as any).ingredient_name;
  const name = displayText(rawName);
  if (name === "-") return name;
  return (
    <span className="item-name-with-badge">
      <span>{name}</span>
      {(item as any).is_updated ? (
        <span className="updated-item-marker" title="Updated from latest supplier communication.">(U)</span>
      ) : null}
    </span>
  );
}

function canonicalSearchText(value: unknown): string {
  return String(value ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

function searchTokens(value: unknown): string[] {
  return canonicalSearchText(value)
    .split(" ")
    .filter((token) => token.length >= 2 && !["price", "qty", "item", "supplier", "find", "show", "best", "for", "the", "and"].includes(token));
}

function searchRelevance(row: Pick<SupplierItem, "ingredient_name" | "specification"> | string, query: string): number {
  const name = typeof row === "string" ? canonicalSearchText(row) : canonicalSearchText(row.ingredient_name);
  const needle = canonicalSearchText(query);
  if (!needle || !name) return 0;

  let score = 0;
  if (name === needle) score += 1000;
  if (name.includes(needle)) score += 750;

  const tokens = searchTokens(query);
  if (tokens.length > 0) {
    const nameTokens = name.split(" ");
    const matched = tokens.filter((token) => nameTokens.some((nameToken) => nameToken === token || nameToken.includes(token))).length;
    score += (matched / tokens.length) * 300;
    if (matched === tokens.length) score += 150;
  }
  return score;
}

function matchesSearch(row: Pick<SupplierItem, "ingredient_name" | "specification"> | string, query: string): boolean {
  if (!query.trim()) return true;
  const name = typeof row === "string" ? canonicalSearchText(row) : canonicalSearchText(row.ingredient_name);
  const needle = canonicalSearchText(query);
  if (!needle || !name) return false;
  if (name.includes(needle)) return true;
  const tokens = searchTokens(query);
  return tokens.length > 0 && tokens.every((token) => name.split(" ").some((part) => part === token || part.includes(token)));
}

function compareSearchMatches(row: Pick<SupplierItem, "ingredient_name" | "specification"> | string, query: string): boolean {
  const tokens = searchTokens(query);
  if (tokens.length === 0) return false;
  const name = typeof row === "string" ? canonicalSearchText(row) : canonicalSearchText(row.ingredient_name);
  const spec = typeof row === "string" ? "" : canonicalSearchText(row.specification);
  const haystack = `${name} ${spec}`.trim();
  const alphaTokens = tokens.filter((token) => /[a-z]/.test(token));
  const requiredTokens = alphaTokens.length ? alphaTokens : tokens;
  return requiredTokens.every((token) => haystack.split(" ").some((part) => part === token || part.includes(token)));
}

function compareSearchRelevance(row: Pick<SupplierItem, "ingredient_name" | "specification"> | string, query: string): number {
  if (!compareSearchMatches(row, query)) return 0;
  const base = searchRelevance(row, query);
  const tokens = searchTokens(query);
  const name = typeof row === "string" ? canonicalSearchText(row) : canonicalSearchText(row.ingredient_name);
  const spec = typeof row === "string" ? "" : canonicalSearchText(row.specification);
  const haystack = `${name} ${spec}`.trim();
  const numericMatches = tokens.filter((token) => /^\d+$/.test(token) && haystack.includes(token)).length;
  return base + numericMatches * 250;
}

function displaySpecification(item: Pick<SupplierItem, "specification"> | Record<string, unknown>): string {
  return displayText((item as any).specification);
}

function isNumericOnlyDisplay(value: unknown): boolean {
  if (isMissingDisplayValue(value)) return false;
  return /^[+-]?\d+(?:\.\d+)?$/.test(String(value).trim());
}

function displayPrice(item: Pick<SupplierItem, "price_display" | "price_per_unit" | "currency" | "unit">): string {
  if (!isMissingDisplayValue(item.price_display) && !isNumericOnlyDisplay(item.price_display)) return String(item.price_display);
  if (item.price_per_unit == null) return "-";
  return `${formatMoney(item.price_per_unit, item.currency)}/${item.unit || "unit"}`;
}

function displayQuantity(item: Pick<SupplierItem, "quantity_display" | "available_qty" | "unit">): string {
  if (!isMissingDisplayValue(item.quantity_display) && !isNumericOnlyDisplay(item.quantity_display)) return String(item.quantity_display);
  if (item.available_qty == null) return "-";
  return `${formatQuantity(item.available_qty)} ${item.unit || ""}`.trim();
}

function displayRichness(row: Record<string, unknown>): number {
  const value = `${row.price_display ?? ""} ${row.quantity_display ?? ""}`;
  let score = value.length;
  if (/(USD|INR|EUR|GBP|\$|₹|€|£)/i.test(value)) score += 30;
  if (/\/|\b(kg|g|mg|bag|drum)\b/i.test(value)) score += 20;
  return score;
}

function shouldPreferAssistantRow(next: Record<string, unknown>, current: Record<string, unknown>): boolean {
  if (Boolean(next.is_updated) !== Boolean(current.is_updated)) return Boolean(next.is_updated);
  const nextTime = new Date(String(next.received_at ?? 0)).getTime();
  const currentTime = new Date(String(current.received_at ?? 0)).getTime();
  if (Number.isFinite(nextTime) && Number.isFinite(currentTime) && nextTime !== currentTime) return nextTime > currentTime;
  return displayRichness(next) > displayRichness(current);
}

function displayLeadTime(item: Pick<SupplierItem, "lead_time_text" | "lead_time_days">): string {
  return !isMissingDisplayValue(item.lead_time_text) ? String(item.lead_time_text) : (item.lead_time_days != null ? `${item.lead_time_days} days` : "-");
}

function displayMoq(item: Pick<SupplierItem, "moq_display" | "moq" | "unit">): string {
  return !isMissingDisplayValue(item.moq_display) ? String(item.moq_display) : (item.moq != null ? `${formatQuantity(Number(item.moq))} ${item.unit || ""}`.trim() : "-");
}

function certificatePdfs(row: Pick<SupplierItem, "certificate_pdfs"> | Record<string, unknown>): CertificatePdf[] {
  const values = (row as { certificate_pdfs?: unknown }).certificate_pdfs;
  if (!Array.isArray(values)) return [];
  return values
    .filter((item): item is CertificatePdf => Boolean(
      item
      && typeof item === "object"
      && (
        (typeof (item as CertificatePdf).url === "string" && (item as CertificatePdf).url)
        || (typeof (item as CertificatePdf).storage_path === "string" && (item as CertificatePdf).storage_path)
      )
    ))
    .map((item) => ({
      name: item.name || "Certificate PDF",
      url: item.url || "",
      storage_path: item.storage_path || null,
      type: item.type || "Certificate",
    }));
}

function comparisonRowKey(row: Record<string, unknown>, index: number): string {
  return [
    row.id,
    row.catalog_email_id,
    row.email_domain,
    row.supplier_name,
    row.ingredient_name,
    row.specification,
    row.available_qty,
    row.unit,
    row.moq,
    row.received_at,
    index,
  ].map((value) => String(value ?? "")).join("|");
}

function formatShortDate(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

function formatDDMMYY(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const year = String(date.getFullYear()).slice(-2);
  return `${day}/${month}/${year}`;
}

function supplierInitials(name: string): string {
  return name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("") || "S";
}

function userInitials(name: string, email: string): string {
  const source = name.trim() || email.split("@")[0] || "U";
  return source
    .split(/[.\s_-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("") || "U";
}

function ToggleSwitch({ checked, onChange, disabled }: { checked: boolean; onChange: (checked: boolean) => void; disabled?: boolean }) {
  return (
    <div
      onClick={() => !disabled && onChange(!checked)}
      style={{
        width: "44px",
        height: "24px",
        borderRadius: "12px",
        background: checked ? "var(--accent)" : "rgba(0, 0, 0, 0.12)",
        position: "relative",
        cursor: disabled ? "not-allowed" : "pointer",
        transition: "background 0.2s ease",
        opacity: disabled ? 0.6 : 1,
        flexShrink: 0,
      }}
    >
      <div
        style={{
          width: "18px",
          height: "18px",
          borderRadius: "50%",
          background: "#fff",
          position: "absolute",
          top: "3px",
          left: checked ? "23px" : "3px",
          transition: "left 0.2s cubic-bezier(0.25, 0.8, 0.25, 1)",
          boxShadow: "0 1px 3px rgba(0, 0, 0, 0.15)",
        }}
      />
    </div>
  );
}

export default function Home({ params }: { params: Promise<{ tab?: string[] }> }) {
  const router = useRouter();
  const resolvedParams = use(params);
  
  // Local state to keep transitions instant and preserve chat history
  const [activeTab, setActiveTabState] = useState<SidebarTab>("dashboard");

  useEffect(() => {
    if (resolvedParams?.tab) {
      const tabParam = resolvedParams.tab[0] as SidebarTab;
      if (tabParam && tabParam !== activeTab) {
        setActiveTabState(tabParam);
      }
    } else {
      if (activeTab !== "dashboard") {
        setActiveTabState("dashboard");
      }
    }
  }, [resolvedParams]);

  useEffect(() => {
    const handlePopState = () => {
      const segment = window.location.pathname.split("/").filter(Boolean)[1] as SidebarTab | undefined;
      setActiveTabState(segment || "dashboard");
    };
    handlePopState();
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const setActiveTab = (tab: SidebarTab) => {
    setActiveTabState(tab);
    if (typeof window !== "undefined") {
      const path = tab === "dashboard" ? "/employee" : `/employee/${tab}`;
      if (window.location.pathname !== path) {
        window.history.pushState({ tab }, "", path);
      }
    }
  };

  // Confirmation Modal states
  const [deleteEmailConfirmId, setDeleteEmailConfirmId] = useState<string | null>(null);
  const [deleteEmailLoading, setDeleteEmailLoading] = useState(false);
  const [disconnectAccountConfirmId, setDisconnectAccountConfirmId] = useState<string | null>(null);
  const [disconnectAccountLoading, setDisconnectAccountLoading] = useState(false);

  // Real-time email sync states
  const [isSyncingEmails, setIsSyncingEmails] = useState(false);
  const [syncSuccess, setSyncSuccess] = useState(false);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);
  const [syncActivityJob, setSyncActivityJob] = useState<SyncActivityJob | null>(null);

  useEffect(() => {
    if (!syncNotice) return;
    const timer = window.setTimeout(() => setSyncNotice(null), 3000);
    return () => window.clearTimeout(timer);
  }, [syncNotice]);

  async function handleSyncRealtimeEmails() {
    setIsSyncingEmails(true);
    setSyncSuccess(false);
    const startedAt = Date.now();
    syncEmailBaselineRef.current = new Map(
      catalogEmails.map((email) => [email.id, syncEmailSignature(email)])
    );
    syncEmailObservedRef.current = new Map();
    setUserMenuOpen(true);
    setSyncActivityJob({
      id: `sync-${startedAt}`,
      status: "running",
      startedAt,
      accountIds: [],
      total: 0,
      processed: 0,
      skipped: 0,
      failed: 0,
      events: [],
    });
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 30000);
    try {
      const response = await authFetch(`${apiBaseUrl}/api/ingestion/poll-now-sync-user`, {
        method: "POST",
        signal: controller.signal,
      });
      if (response.ok) {
        const result = await response.json().catch(() => null);
        setSyncSuccess(true);
        const processed = Number(result?.processed || 0);
        const pending = Number(result?.pending_approvals || 0);
        const queuedAccounts = Number(result?.queued_accounts || 0);
        const failedAccounts = Number(result?.failed_accounts || 0);
        const newCandidates = Number(result?.new_candidate_messages || 0);
        const accountIds: string[] = Array.from(new Set<string>(
          (Array.isArray(result?.previews) ? result.previews : [])
            .map((preview: { account_id?: unknown }) => String(preview?.account_id || ""))
            .filter(Boolean)
        ));
        const apiEvents: SyncActivityEvent[] = [];
        if (failedAccounts > 0) {
          apiEvents.push({
            id: `sync-${startedAt}-queue-failed`,
            tone: "failed",
            supplier: "Sync Queue",
            message: `${failedAccounts} mailbox sync${failedAccounts === 1 ? "" : "s"} could not be queued`,
            detail: result?.queue_errors?.[0]?.message || "Email worker is unavailable.",
            timestamp: Date.now() + 2,
          });
        }
        setSyncActivityJob((current) => current ? {
          ...current,
          accountIds,
          total: newCandidates,
          events: [...current.events, ...apiEvents].slice(-100),
          status: result?.status === "error" ? "failed" : newCandidates === 0 ? "completed" : current.status,
          completedAt: result?.status === "error" || newCandidates === 0 ? Date.now() : current.completedAt,
        } : current);
        if (result?.status === "queued") {
          setSyncNotice(queuedAccounts > 0
            ? newCandidates > 0
              ? `${newCandidates} supplier email${newCandidates === 1 ? "" : "s"} queued for processing.`
              : "No new supplier emails require processing."
            : "No connected email accounts found.");
          window.setTimeout(() => {
            fetchSyncActivitySnapshot().catch((err) => console.error("Delayed inbox refresh failed", err));
          }, 2500);
        } else if (result?.status === "error") {
          setSyncNotice(result?.queue_errors?.[0]?.message || "Could not queue email sync. Check the Celery worker and Redis connection.");
        } else if (pending > 0) {
          setSyncNotice(`${pending} new supplier approval${pending === 1 ? "" : "s"} waiting. Approve trusted suppliers in Email Settings.`);
        } else {
          setSyncNotice(processed > 0 ? `Processed ${processed} catalogue item${processed === 1 ? "" : "s"}.` : "No new supplier catalogue emails found.");
        }
        setTimeout(() => {
          setSyncSuccess(false);
        }, 2000);
      } else {
        const errorPayload = await response.json().catch(() => null);
        console.error("Email sync failed", response.status, errorPayload);
        setSyncNotice(errorPayload?.detail || "Email sync failed. Check connected inbox settings and try again.");
        setSyncActivityJob((current) => current ? {
          ...current,
          status: "failed",
          failed: Math.max(current.failed, 1),
          completedAt: Date.now(),
          events: [
            ...current.events,
            {
              id: `sync-${startedAt}-request-failed`,
              tone: "failed",
              supplier: "Sync Failed",
              message: "Unable to start email processing",
              detail: errorPayload?.detail || "Check connected inbox settings and try again.",
              timestamp: Date.now(),
            } satisfies SyncActivityEvent,
          ].slice(-100),
        } : current);
      }
    } catch (err) {
      console.error(err);
      showConnectionFailure(err instanceof DOMException && err.name === "AbortError"
        ? "Email sync request timed out before MediCORE responded. Please retry when the connection is stable."
        : "Unable to communicate with MediCORE. Please check your internet connection and try again.");
      setSyncNotice(err instanceof DOMException && err.name === "AbortError"
        ? "Email sync request timed out. Check worker status and try again."
        : "Email sync failed. Check connected inbox settings and try again.");
        setSyncActivityJob((current) => current ? {
          ...current,
          status: "failed",
          failed: Math.max(current.failed, 1),
          completedAt: Date.now(),
          events: [
            ...current.events,
          {
            id: `sync-${startedAt}-connection-failed`,
            tone: "failed",
            supplier: "Connection Failed",
            message: "Unable to communicate with MediCORE",
            detail: "Please check your internet connection and try again.",
            timestamp: Date.now(),
          } satisfies SyncActivityEvent,
        ].slice(-100),
      } : current);
    } finally {
      window.clearTimeout(timeout);
      setIsSyncingEmails(false);
    }
  }

  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      text: "Hey User!\nHow can I help you today?"
    }
  ]);
  const [input, setInput] = useState("");
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [supplierRows, setSupplierRows] = useState<SupplierTableRow[]>([]);
  const [catalogEmails, setCatalogEmails] = useState<CatalogEmailRow[]>([]);
  const [supplierMetaRows, setSupplierMetaRows] = useState<SupplierApiRow[]>([]);
  const [supplierLoading, setSupplierLoading] = useState(true);
  const [isRefreshingInbox, setIsRefreshingInbox] = useState(false);
  const [supplierError, setSupplierError] = useState<string | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [selectedInboxSupplier, setSelectedInboxSupplier] = useState("");
  const [selectedCatalogSupplier, setSelectedCatalogSupplier] = useState("");
  const [selectedCatalogEmailId, setSelectedCatalogEmailId] = useState<string | null>(null);
  const [supplierSearch, setSupplierSearch] = useState("");
  const [supplierSort, setSupplierSort] = useState<SupplierSort>("latest");
  const [selectedSupplierCountries, setSelectedSupplierCountries] = useState<string[]>([]);
  const [supplierCountryOpen, setSupplierCountryOpen] = useState(false);
  const [certificateModalItems, setCertificateModalItems] = useState<CertificatePdf[] | null>(null);
  const [expandedCompareRows, setExpandedCompareRows] = useState<Record<string, boolean>>({});
  const [expandedAssistantRows, setExpandedAssistantRows] = useState<Record<string, boolean>>({});
  const [expandedCatalogRows, setExpandedCatalogRows] = useState<Record<string, boolean>>({});
  const [expandedInboxRows, setExpandedInboxRows] = useState<Record<string, boolean>>({});
  const [catalogSearch, setCatalogSearch] = useState("");
  const [catalogFilter, setCatalogFilter] = useState<"all" | "best" | "low-stock">("all");
  const [compareIngredient, setCompareIngredient] = useState("");
  const [selectedCompareIngredient, setSelectedCompareIngredient] = useState("");
  const [compareSearchFocused, setCompareSearchFocused] = useState(false);
  const [compareSort, setCompareSort] = useState<CompareSort>("best-value");
  const [authChecked, setAuthChecked] = useState(false);
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [dataRefreshKey, setDataRefreshKey] = useState(0);
  const [selectedInboxThreadId, setSelectedInboxThreadId] = useState<string | null>(null);
  const [inboxItemsByEmail, setInboxItemsByEmail] = useState<Record<string, SupplierTableRow[]>>({});
  const [inboxItemsLoadingId, setInboxItemsLoadingId] = useState<string | null>(null);
  const [inboxItemsErrorId, setInboxItemsErrorId] = useState<string | null>(null);
  const [latestSeenEmailId, setLatestSeenEmailId] = useState<string | null>(null);
  const [visibleGuides, setVisibleGuides] = useState<Record<string, boolean>>({});

  // Settings Redesign States
  const [settingsActiveTab, setSettingsActiveTab] = useState<"profile" | "email">("profile");
  const [connectedAccounts, setConnectedAccounts] = useState<ConnectedEmailAccount[]>([]);
  const [loadingAccounts, setLoadingAccounts] = useState(false);
  const [syncSettings, setSyncSettings] = useState<EmailSyncSetting>({
    id: "",
    user_id: "",
    poll_interval_minutes: 15,
    auto_extract_catalog: true,
    notify_on_new_catalog: true
  });
  const [savingSyncSettings, setSavingSyncSettings] = useState(false);
  const [settingsSaveFeedback, setSettingsSaveFeedback] = useState(false);
  const [onboardingChecked, setOnboardingChecked] = useState(false);

  // Local states for settings inputs
  const [localApproach, setLocalApproach] = useState<string>("approach_1");
  const [localTrusted, setLocalTrusted] = useState<string>("");
  const [localPollInterval, setLocalPollInterval] = useState<number>(15);

  // Profile edit states
  const [isEditingProfile, setIsEditingProfile] = useState(false);
  const [editName, setEditName] = useState("");
  const [editOrganisation, setEditOrganisation] = useState("");
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);

  // Chat streaming and indicator states/refs
  const [isTypingResponse, setIsTypingResponse] = useState(false);
  const streamIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const chatMessagesEndRef = useRef<HTMLDivElement | null>(null);
  const supplierCountryFilterRef = useRef<HTMLDivElement | null>(null);
  const syncActivityListRef = useRef<HTMLDivElement | null>(null);
  const supplierRowsRequestIdRef = useRef(0);
  const inboxItemsRequestIdRef = useRef(0);
  const completedSyncRefreshRef = useRef<string | null>(null);
  const syncEmailBaselineRef = useRef<Map<string, string>>(new Map());
  const syncEmailObservedRef = useRef<Map<string, string>>(new Map());

  // Initial load tracking ref
  const initialLoadRef = useRef(false);
  const profileFetchedRef = useRef(false);

  useEffect(() => {
    if (syncSettings) {
      setLocalApproach(syncSettings.ingestion_approach || "approach_1");
      setLocalTrusted(syncSettings.trusted_suppliers || "");
      setLocalPollInterval(syncSettings.poll_interval_minutes || 15);
    }
  }, [syncSettings]);

  const pendingApprovalsList = useMemo(() => {
    try {
      const approvals = JSON.parse(syncSettings.pending_approvals || "[]");
      return Array.isArray(approvals)
        ? approvals.filter(
            (item: any) => !item?.ignored && !trustedSupplierMatches(item?.sender, syncSettings.trusted_suppliers)
          )
        : [];
    } catch (e) {
      return [];
    }
  }, [syncSettings.pending_approvals, syncSettings.trusted_suppliers]);

  const failedEmailNotifications = useMemo(() => {
    return catalogEmails.filter((email) => String(email.processing_status || "").startsWith("failed"));
  }, [catalogEmails]);

  const notificationCount = pendingApprovalsList.length + failedEmailNotifications.length;
  const syncActivityVisibleEvents = useMemo(() => {
    if (!syncActivityJob) return [];
    const events = [...syncActivityJob.events].sort((left, right) => left.timestamp - right.timestamp);
    if (syncActivityJob.status === "running") {
      return events.slice(-80);
    }
    return events.length > 16 ? events.slice(0, 4).concat(events.slice(-12)) : events;
  }, [syncActivityJob]);
  const syncActivityHasCollapsedEvents = Boolean(syncActivityJob && syncActivityJob.events.length > syncActivityVisibleEvents.length);
  const syncActivityElapsedSeconds = syncActivityJob
    ? Math.max(1, Math.round(((syncActivityJob.completedAt || Date.now()) - syncActivityJob.startedAt) / 1000))
    : 0;
  const syncActivityTotal = syncActivityJob?.total || 0;
  const syncActivityDone = syncActivityJob ? syncActivityJob.processed + syncActivityJob.skipped + syncActivityJob.failed : 0;
  const syncActivityRemaining = Math.max(0, syncActivityTotal - syncActivityDone);
  const syncActivityProgress = syncActivityTotal > 0
    ? Math.min(100, Math.round((syncActivityDone / syncActivityTotal) * 100))
    : syncActivityJob?.status === "completed" ? 100 : 0;
  const syncActivityActiveEvent = [...syncActivityVisibleEvents].reverse().find((event) => event.tone === "processing") || null;
  const syncActivityCompletedEvents = syncActivityVisibleEvents.filter((event) => event.tone === "success");
  const syncActivitySkippedEvents = syncActivityVisibleEvents.filter((event) => event.tone === "skipped");
  const syncActivityFailedEvents = syncActivityVisibleEvents.filter((event) => event.tone === "failed");

  useEffect(() => {
    if (!syncActivityListRef.current) return;
    syncActivityListRef.current.scrollTop = syncActivityListRef.current.scrollHeight;
  }, [syncActivityVisibleEvents.length, syncActivityJob?.status]);

  // Click outside detection to close the notifications menu
  useEffect(() => {
    function handleDocumentClick(event: MouseEvent) {
      if (!userMenuOpen) return;
      const target = event.target as HTMLElement;
      const navbarActionsElement = document.querySelector(".navbar-actions");
      if (navbarActionsElement && !navbarActionsElement.contains(target)) {
        setUserMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleDocumentClick);
    return () => {
      document.removeEventListener("mousedown", handleDocumentClick);
    };
  }, [userMenuOpen]);



  // Add Account Form States
  const [addAccountExpanded, setAddAccountExpanded] = useState(false);
  const [setupStep, setSetupStep] = useState(1);
  const [newAccountProvider, setNewAccountProvider] = useState("Gmail");
  const [newAccountEmail, setNewAccountEmail] = useState("");
  const [newAccountPassword, setNewAccountPassword] = useState("");
  const [showSettingsPassword, setShowSettingsPassword] = useState(false);
  const [newAccountImapHost, setNewAccountImapHost] = useState("imap.gmail.com");
  const [newAccountImapPort, setNewAccountImapPort] = useState(993);

  // Filters States
  const [filterRequireAttachment, setFilterRequireAttachment] = useState(false);
  const [filterSenderKeywords, setFilterSenderKeywords] = useState("");
  const [filterSubjectKeywords, setFilterSubjectKeywords] = useState("");
  const [filterSkipPromotions, setFilterSkipPromotions] = useState(false);

  // Connection Testing States
  const [testingConnection, setTestingConnection] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [editingAccountId, setEditingAccountId] = useState<string | null>(null);
  const [savingAccount, setSavingAccount] = useState(false);






  const [syncingAccountsState, setSyncingAccountsState] = useState<Record<string, boolean>>({});
  const socketRef = useRef<WebSocket | null>(null);
  const apiBaseUrl = useMemo(() => {
    return getApiBaseUrl();
  }, []);

  const wsUrl = useMemo(() => {
    return getChatWsUrl();
  }, []);
  const showAssistantPanel = activeTab === "assistant";

  const inboxThreads = useMemo<InboxThread[]>(() => {
    const supplierMeta = new Map(supplierMetaRows.map((supplier) => [supplierKey(supplier.name, supplier.email_domain), supplier]));

    // Group items by their catalog_email_id
    const itemsByEmail = new Map<string, SupplierTableRow[]>();
    for (const row of supplierRows) {
      if (row.catalog_email_id) {
        const current = itemsByEmail.get(row.catalog_email_id) ?? [];
        current.push(row);
        itemsByEmail.set(row.catalog_email_id, current);
      }
    }

    return catalogEmails
      // The API omits these as well, but keep the Inbox clean during a rolling
      // deployment or when it receives cached certificate-only records.
      .filter((email) => normalizedProcessingStatus(email.processing_status) !== "certificate")
      .map((email) => {
      const items = inboxItemsByEmail[email.id] ?? itemsByEmail.get(email.id) ?? [];
      const sortedItems = [...items].sort((left, right) => displayItemName(left).localeCompare(displayItemName(right)));
      const meta = supplierMeta.get(supplierKey(email.supplier_name, email.email_domain));
      const bestItem = sortedItems[0];
      const itemCount = Number(email.item_count || 0) || sortedItems.length;
      const statusTone = inboxStatusTone(email.processing_status, itemCount);
      const statusLabel = inboxStatusLabel(email.processing_status, itemCount);

      return {
        id: email.id,
        supplier_name: email.supplier_name,
        email_domain: items[0]?.email_domain ?? meta?.email_domain ?? "-",
        country: meta?.country ?? (items[0] as any)?.country ?? "Unknown",
        item_count: itemCount,
        duplicate_count: Number(email.duplicate_count || 0),
        latest_item: email.subject || bestItem?.ingredient_name || "Email stored, extraction pending",
        received_at: email.received_at,
        latest_price: bestItem?.price_per_unit ?? 0,
        latest_currency: bestItem?.currency ?? "INR",
        latest_qty: bestItem?.available_qty ?? 0,
        latest_unit: bestItem?.unit ?? "",
        status_label: statusLabel,
        status_tone: statusTone,
        items: sortedItems,
        pdf_url: email.pdf_url,
        body_preview: email.body_preview,
        subject: email.subject
      };
      }).sort((left, right) => {
      const leftTime = new Date(left.received_at ?? 0).getTime();
      const rightTime = new Date(right.received_at ?? 0).getTime();
      return rightTime - leftTime;
    });
  }, [catalogEmails, inboxItemsByEmail, supplierMetaRows, supplierRows]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      setLatestSeenEmailId(localStorage.getItem("latestSeenEmailId"));
    }
  }, []);

  const hasNewMail = useMemo(() => {
    if (!inboxThreads.length) return false;
    if (activeTab === "inbox") return false;
    if (!latestSeenEmailId) {
      return true;
    }
    return inboxThreads[0].id !== latestSeenEmailId;
  }, [inboxThreads, latestSeenEmailId, activeTab]);

  useEffect(() => {
    if (activeTab === "inbox" && inboxThreads.length > 0) {
      const latestId = inboxThreads[0].id;
      localStorage.setItem("latestSeenEmailId", latestId);
      setLatestSeenEmailId(latestId);
    }
  }, [activeTab, inboxThreads]);

  const selectedInboxThread = useMemo(() => {
    if (!inboxThreads.length) {
      return null;
    }
    return inboxThreads.find((thread) => thread.id === selectedInboxThreadId) ?? inboxThreads[0];
  }, [inboxThreads, selectedInboxThreadId]);

  const assistantRows = useMemo(() => {
    const map = new Map<string, Record<string, unknown>>();
    const lastUserQuery = [...messages].reverse().find((message) => message.role === "user")?.text ?? "";
    const queryTokens = new Set(
      lastUserQuery
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, " ")
        .split(/\s+/)
        .filter((token) => token.length >= 3 && !["price", "supplier", "suppliers", "show", "find", "give", "for", "the"].includes(token))
    );
    for (const row of rows as Array<Record<string, unknown>>) {
      const rowName = String(row.ingredient_name ?? "").toLowerCase();
      const matchedToken = Array.from(queryTokens).find((token) => rowName.includes(token));
      const specKey = String(row.specification ?? "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
      const qtyKey = `${String(row.available_qty ?? "")}-${String(row.unit ?? "")}-${String(row.moq ?? "")}`;
      const itemKey = `${matchedToken || rowName.replace(/[^a-z0-9]+/g, " ").trim()}-${specKey}-${qtyKey}`;
      const key = `${String(row.email_domain ?? row.supplier_name ?? "").toLowerCase()}-${itemKey}`;
      const current = map.get(key);
      if (!current || shouldPreferAssistantRow(row, current)) {
        map.set(key, row);
      }
    }
    return Array.from(map.values()).sort((left, right) => displayItemName(left).localeCompare(displayItemName(right)));
  }, [messages, rows]);

  const latestSupplierRows = useMemo(() => {
    const map = new Map<string, SupplierTableRow>();
    for (const row of supplierRows) {
      const key = `${supplierKey(row.supplier_name, row.email_domain)}-${row.ingredient_name}-${row.specification || ""}`;
      const existing = map.get(key);
      if (!existing || new Date(row.received_at ?? 0).getTime() > new Date(existing.received_at ?? 0).getTime()) {
        map.set(key, row);
      }
    }
    return Array.from(map.values()).sort((left, right) => displayItemName(left).localeCompare(displayItemName(right)));
  }, [supplierRows]);

  const dashboardData = useMemo(() => {
    const completedCatalogs = catalogEmails.filter((email) => email.processing_status === "completed").length;

    const itemGroups = new Map<string, SupplierTableRow[]>();
    for (const row of latestSupplierRows) {
      const key = `${row.ingredient_name}-${row.specification || ""}`;
      const group = itemGroups.get(key) ?? [];
      group.push(row);
      itemGroups.set(key, group);
    }

    const deals = Array.from(itemGroups.entries())
      .map(([name, items]) => {
        const sorted = [...items].sort((left, right) => safePrice(left.price_per_unit, left.currency) - safePrice(right.price_per_unit, right.currency));
        const best = sorted[0];
        return { name, best };
      })
      .filter((deal) => deal.best)
      .sort((left, right) => safePrice(left.best.price_per_unit, left.best.currency) - safePrice(right.best.price_per_unit, right.best.currency));

    const activities = inboxThreads.slice(0, 5).map((thread, index) => ({
      tone: index === 2 ? "warning" : index % 2 === 0 ? "strong" : "soft",
      text: thread.item_count > 0
        ? `${thread.supplier_name} sent catalogue - ${thread.item_count} items extracted`
        : `${thread.supplier_name} sent catalogue email - extraction pending`,
      time: formatRelativeTime(thread.received_at),
    }));

    return {
      emailsReceived: catalogEmails.length,
      completedCatalogs,
      activeSuppliers: supplierMetaRows.length,
      deals: deals.slice(0, 3),
      activities,
    };
  }, [catalogEmails, inboxThreads, supplierMetaRows, latestSupplierRows]);

  const topDashboardDeal = dashboardData.deals[0];

  const supplierDirectory = useMemo(() => {
    const supplierMap = new Map<string, SupplierTableRow[]>();
    const emailBySupplier = new Map<string, CatalogEmailRow[]>();
    const supplierMeta = new Map(supplierMetaRows.map((supplier) => [supplierKey(supplier.name, supplier.email_domain), supplier]));
    const procurementEmails = catalogEmails.filter(isProcurementCatalogEmail);

    for (const row of supplierRows) {
      const key = supplierKey(row.supplier_name, row.email_domain);
      const current = supplierMap.get(key) ?? [];
      current.push(row);
      supplierMap.set(key, current);
    }

    for (const email of procurementEmails) {
      const key = supplierKey(email.supplier_name, email.email_domain);
      const current = emailBySupplier.get(key) ?? [];
      current.push(email);
      emailBySupplier.set(key, current);
    }

    const supplierKeys = new Set([...supplierMap.keys(), ...emailBySupplier.keys()]);
    const search = supplierSearch.trim().toLowerCase();
    const summaries = Array.from(supplierKeys).map((key) => {
      const items = supplierMap.get(key) ?? [];
      const emails = emailBySupplier.get(key) ?? [];
      const supplierName = items[0]?.supplier_name ?? emails[0]?.supplier_name ?? "-";
      const emailDomain = items[0]?.email_domain ?? emails[0]?.email_domain ?? "-";
      const meta = supplierMeta.get(key);
      const country = meta?.country || items[0]?.country || "Unknown";
      const sortedByPrice = [...items].sort((left, right) => safePrice(left.price_per_unit, left.currency) - safePrice(right.price_per_unit, right.currency));
      const latestEmail = emails.slice().sort((left, right) => {
        return new Date(right.received_at).getTime() - new Date(left.received_at).getTime();
      })[0];
      
      const latestItems = latestEmail
        ? items.filter((item) => item.catalog_email_id === latestEmail.id)
        : items;
      const sortedLatestByPrice = [...latestItems].sort((left, right) => safePrice(left.price_per_unit, left.currency) - safePrice(right.price_per_unit, right.currency));
      const totalQty = items.reduce((total, item) => total + safeQty(item.available_qty), 0);

      return {
        supplier_key: key,
        supplier_name: supplierName,
        email_domain: emailDomain ?? meta?.email_domain ?? "-",
        country,
        item_count: Number(meta?.item_count || 0) || items.length,
        best_item: sortedLatestByPrice[0],
        total_qty: totalQty,
        last_catalog_at: latestEmail?.received_at ?? items[0]?.valid_until ?? meta?.last_email_date ?? null,
        latest_email_id: latestEmail?.id ?? null,
        subject: latestEmail?.subject ?? "Catalogue email received",
        items: sortedByPrice,
        certifications: meta?.certifications ?? null,
      };
    }).filter((supplier) => {
      const countryMatches = selectedSupplierCountries.length === 0 || selectedSupplierCountries.includes(supplier.country || "Unknown");
      const searchMatches = !search
        || canonicalSearchText(supplier.supplier_name).includes(canonicalSearchText(search))
        || canonicalSearchText(supplier.email_domain).includes(canonicalSearchText(search))
        || supplier.items.some((item) => matchesSearch(item, search));
      return countryMatches && searchMatches;
    });

    return summaries.sort((left, right) => {
      if (supplierSort === "name") return left.supplier_name.localeCompare(right.supplier_name);
      if (supplierSort === "items") return right.item_count - left.item_count;
      return new Date(right.last_catalog_at ?? 0).getTime() - new Date(left.last_catalog_at ?? 0).getTime();
    });
  }, [catalogEmails, selectedSupplierCountries, supplierMetaRows, supplierRows, supplierSearch, supplierSort]);

  const supplierCountryOptions = useMemo(() => {
    const countries = supplierMetaRows
      .map((supplier) => supplier.country || "Unknown")
      .filter(Boolean);
    return Array.from(new Set(countries)).sort((left, right) => {
      if (left === "Unknown") return 1;
      if (right === "Unknown") return -1;
      return left.localeCompare(right);
    });
  }, [supplierMetaRows]);

  const toggleSupplierCountry = (country: string) => {
    setSelectedSupplierCountries((current) =>
      current.includes(country)
        ? current.filter((item) => item !== country)
        : [...current, country]
    );
  };

  const openCertificatePdf = async (pdf: CertificatePdf) => {
    if (pdf.storage_path) {
      try {
        const response = await authFetch(`${apiBaseUrl}/api/catalogs/certificate-url?storage_path=${encodeURIComponent(pdf.storage_path)}`);
        if (response.ok) {
          const payload: { url?: string } = await response.json();
          if (payload.url) {
            window.open(payload.url, "_blank", "noopener,noreferrer");
            return;
          }
        }
      } catch (error) {
        console.warn("Could not open signed certificate URL", error);
      }
    }
    if (pdf.url) {
      window.open(pdf.url, "_blank", "noopener,noreferrer");
    }
  };

  const openCertificatePdfs = (row: Pick<SupplierItem, "certificate_pdfs"> | Record<string, unknown>) => {
    const pdfs = certificatePdfs(row);
    if (pdfs.length === 0) return;
    if (pdfs.length === 1) {
      void openCertificatePdf(pdfs[0]);
      return;
    }
    setCertificateModalItems(pdfs);
  };

  const renderCertificatesCell = (row: Pick<SupplierItem, "certificate_pdfs"> & { certifications?: string | null } | Record<string, unknown>) => {
    const pdfs = certificatePdfs(row);
    if (pdfs.length > 0) {
      return (
        <button className="certificate-view-button" type="button" onClick={() => openCertificatePdfs(row)}>
          View Certificate
        </button>
      );
    }
    const rawCertifications = (row as { certifications?: unknown }).certifications;
    const certifications = typeof rawCertifications === "string" ? rawCertifications : "";
    if (!certifications.trim()) {
      return <span style={{ color: "var(--muted)", fontSize: "11px" }}>-</span>;
    }
    return (
      <div style={{ display: "flex", gap: "4px", flexWrap: "wrap", justifyContent: "center" }}>
        {certifications.split(",").map((cert) => {
          const trimmed = cert.trim();
          if (!trimmed) return null;
          return (
            <span key={trimmed} className="certificate-text-badge">
              {trimmed}
            </span>
          );
        })}
      </div>
    );
  };

  useEffect(() => {
    if (!supplierCountryOpen) return;

    const handlePointerDown = (event: PointerEvent) => {
      if (!supplierCountryFilterRef.current?.contains(event.target as Node)) {
        setSupplierCountryOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [supplierCountryOpen]);

  const selectedCatalog = useMemo(() => {
    if (!supplierDirectory.length) return null;
    return supplierDirectory.find((supplier) => supplier.supplier_key === selectedCatalogSupplier) ?? supplierDirectory[0];
  }, [selectedCatalogSupplier, supplierDirectory]);

  const supplierEmails = useMemo(() => {
    if (!selectedCatalogSupplier) return [];
    return catalogEmails.filter((email) => supplierKey(email.supplier_name, email.email_domain) === selectedCatalogSupplier && isProcurementCatalogEmail(email))
      .sort((left, right) => new Date(right.received_at).getTime() - new Date(left.received_at).getTime());
  }, [catalogEmails, selectedCatalogSupplier]);

  const activeCatalogEmail = useMemo(() => {
    return selectedCatalogEmailId ? supplierEmails.find((e) => e.id === selectedCatalogEmailId) ?? null : null;
  }, [supplierEmails, selectedCatalogEmailId]);

  useEffect(() => {
    if (supplierEmails.length > 0 && selectedCatalogEmailId) {
      const exists = supplierEmails.some((e) => e.id === selectedCatalogEmailId);
      if (!exists) {
        setSelectedCatalogEmailId(null);
      }
    } else {
      setSelectedCatalogEmailId(null);
    }
  }, [supplierEmails, selectedCatalogEmailId]);

  const selectedCatalogItems = useMemo(() => {
    if (!selectedCatalog) return [];
    const search = catalogSearch.trim();
    const selectedEmailItems = selectedCatalogEmailId ? inboxItemsByEmail[selectedCatalogEmailId] : undefined;
    const filteredByEmail = selectedCatalogEmailId
      ? selectedEmailItems ?? selectedCatalog.items.filter((item) => item.catalog_email_id === selectedCatalogEmailId)
      : selectedCatalog.items;

    if (filteredByEmail.length === 0) return [];
    const minQty = Math.min(...filteredByEmail.map((item) => safeQty(item.available_qty)));
    const bestPrice = Math.min(...filteredByEmail.map((item) => safePrice(item.price_per_unit, item.currency)));
    return filteredByEmail.filter((item) => {
      const itemMatchesSearch = !search
        || matchesSearch(item, search);
      if (!itemMatchesSearch) return false;
      if (catalogFilter === "best") return safePrice(item.price_per_unit, item.currency) <= bestPrice * 1.08;
      if (catalogFilter === "low-stock") return safeQty(item.available_qty) <= minQty * 1.35;
      return true;
    }).sort((left, right) => (
      search
        ? searchRelevance(right, search) - searchRelevance(left, search)
        : displayItemName(left).localeCompare(displayItemName(right))
    ));
  }, [catalogFilter, catalogSearch, inboxItemsByEmail, selectedCatalog, selectedCatalogEmailId]);

  const emailItemsCount = useMemo(() => {
    if (!selectedCatalog) return 0;
    if (selectedCatalogEmailId) {
      const activeEmailCount = Number(activeCatalogEmail?.item_count || 0);
      return activeEmailCount || inboxItemsByEmail[selectedCatalogEmailId]?.length || selectedCatalog.items.filter((item) => item.catalog_email_id === selectedCatalogEmailId).length;
    }
    return selectedCatalog.item_count || selectedCatalog.items.length;
  }, [activeCatalogEmail, inboxItemsByEmail, selectedCatalog, selectedCatalogEmailId]);

  const availableIngredients = useMemo(() => {
    return Array.from(new Set(latestSupplierRows.map((row) => row.ingredient_name)))
      .filter(Boolean)
      .sort((left, right) => left.localeCompare(right));
  }, [latestSupplierRows]);

  const compareSuggestions = useMemo(() => {
    const requested = compareIngredient.trim();
    const ranked = availableIngredients
      .filter((ingredient) => compareSearchMatches(ingredient, requested))
      .sort((left, right) => compareSearchRelevance(right, requested) - compareSearchRelevance(left, requested));
    return ranked.slice(0, 8);
  }, [availableIngredients, compareIngredient]);

  const compareData = useMemo(() => {
    const requested = selectedCompareIngredient.trim();
    if (!requested) {
      return { rows: [], topRows: [], otherRows: [], ingredientLabel: "ingredient" };
    }

    const matchedRows = latestSupplierRows.filter((row) => {
      return compareSearchMatches(row, requested);
    }).sort((left, right) => compareSearchRelevance(right, requested) - compareSearchRelevance(left, requested));

    const bySupplier = new Map<string, SupplierTableRow>();
    for (const row of matchedRows) {
      const identity = `${supplierKey(row.supplier_name, row.email_domain)}-${row.specification || ""}-${row.available_qty ?? ""}-${row.unit ?? ""}-${row.moq ?? ""}`;
      const current = bySupplier.get(identity);
      if (!current || safePrice(row.price_per_unit, row.currency) < safePrice(current.price_per_unit, current.currency)) {
        bySupplier.set(identity, row);
      }
    }

    const rows = Array.from(bySupplier.values());
    const finitePrices = rows.map((row) => safePrice(row.price_per_unit, row.currency)).filter(Number.isFinite);
    const minPrice = finitePrices.length ? Math.min(...finitePrices) : 0;
    const maxPrice = finitePrices.length ? Math.max(...finitePrices) : 1;
    const maxQty = Math.max(...rows.map((row) => safeQty(row.available_qty)), 1);

    const scored = rows.map((row) => {
      const rowPriceBase = safePrice(row.price_per_unit, row.currency);
      const priceScore = Number.isFinite(rowPriceBase) ? (maxPrice === minPrice ? 100 : ((maxPrice - rowPriceBase) / (maxPrice - minPrice)) * 100) : 0;
      const qtyScore = (safeQty(row.available_qty) / maxQty) * 100;
      const overallScore = Math.round(priceScore * 0.65 + qtyScore * 0.35);
      return {
        ...row,
        priceScore: Math.round(priceScore),
        qtyScore: Math.round(qtyScore),
        overallScore,
      };
    });

    const sorted = scored.sort((left, right) => {
      if (compareSort === "lowest-price") {
        return safePrice(left.price_per_unit, left.currency) - safePrice(right.price_per_unit, right.currency);
      }
      if (compareSort === "highest-qty") {
        return safeQty(right.available_qty) - safeQty(left.available_qty);
      }
      return right.overallScore - left.overallScore || safePrice(left.price_per_unit, left.currency) - safePrice(right.price_per_unit, right.currency);
    });

    return {
      rows: sorted,
      topRows: sorted.slice(0, 3),
      otherRows: sorted.slice(3),
      ingredientLabel: sorted[0]?.ingredient_name || requested || "ingredient",
    };
  }, [compareSort, selectedCompareIngredient, latestSupplierRows]);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const loadProfileDetails = async (sessionToken: string) => {
      if (profileFetchedRef.current) return;
      profileFetchedRef.current = true;
      try {
        const res = await fetch(`${apiBaseUrl}/api/profile`, {
          headers: {
            Authorization: `Bearer ${sessionToken}`
          }
        });
        if (res.ok) {
          const profileData = await res.json();
          setAuthUser(prev => {
            if (!prev) return null;
            if (prev.name === profileData.full_name && prev.organisation === profileData.organisation) {
              return prev;
            }
            return {
              ...prev,
              name: profileData.full_name,
              organisation: profileData.organisation
            };
          });
        }
      } catch (err) {
        console.error("Failed to load profile details:", err);
      }
    };

    // Get active Supabase session and set active user
    supabase.auth.getSession().then((res) => {
      const session = res?.data?.session;
      if (session?.user) {
        const u = session.user;
        const name = u.user_metadata?.full_name || u.email?.split("@")[0] || "User";
        const org = u.user_metadata?.organisation || "MediCORE Central";
        let userRole = u.user_metadata?.role
          ? (u.user_metadata.role.charAt(0).toUpperCase() + u.user_metadata.role.slice(1))
          : "Employee";
        if (userRole === "Member") {
          userRole = "Employee";
        }
        setAuthUser((prev) => {
          if (
            prev &&
            prev.email === (u.email || "") &&
            prev.name === name &&
            prev.role === userRole &&
            prev.organisation === org
          ) {
            return prev;
          }
          return {
            email: u.email || "",
            name: name,
            role: userRole,
            organisation: org
          };
        });
        loadProfileDetails(session.access_token);
      } else {
        setAuthUser(null);
        initialLoadRef.current = false;
        router.push("/login");
      }
      setAuthChecked(true);
    }).catch(() => {
      setAuthUser(null);
      setAuthChecked(true);
    });

    // Listen to changes in auth state (e.g. sign outs)
    const authListener = supabase.auth.onAuthStateChange((event, session) => {
      if (session?.user) {
        const u = session.user;
        const name = u.user_metadata?.full_name || u.email?.split("@")[0] || "User";
        const org = u.user_metadata?.organisation || "MediCORE Central";
        let userRole = u.user_metadata?.role
          ? (u.user_metadata.role.charAt(0).toUpperCase() + u.user_metadata.role.slice(1))
          : "Employee";
        if (userRole === "Member") {
          userRole = "Employee";
        }
        setAuthUser((prev) => {
          if (
            prev &&
            prev.email === (u.email || "") &&
            prev.name === name &&
            prev.role === userRole &&
            prev.organisation === org
          ) {
            return prev;
          }
          return {
            email: u.email || "",
            name: name,
            role: userRole,
            organisation: org
          };
        });
        loadProfileDetails(session.access_token);
      } else {
        setAuthUser(null);
        initialLoadRef.current = false;
        router.push("/login");
      }
    });

    const subscription = authListener?.data?.subscription;

    return () => {
      subscription?.unsubscribe();
    };
  }, [router]);

  useEffect(() => {
    if (authUser?.name) {
      setMessages((prev) => {
        if (
          prev.length === 1 &&
          prev[0].role === "assistant" &&
          (prev[0].text.startsWith("Hi there!") || prev[0].text.startsWith("Hey "))
        ) {
          return [
            {
              role: "assistant",
              text: `Hey ${authUser.name}!\nHow can I help you today?`,
            },
          ];
        }
        return prev;
      });
    }
  }, [authUser]);

  // Auto scroll to bottom of chat window
  useEffect(() => {
    if (chatMessagesEndRef.current) {
      chatMessagesEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, isTypingResponse]);

  // Clean up streaming interval on unmount
  useEffect(() => {
    return () => {
      if (streamIntervalRef.current) {
        clearInterval(streamIntervalRef.current);
      }
    };
  }, []);

  useEffect(() => {
    async function checkEmailAccountOnboarding() {
      if (!authUser) return;
      try {
        const res = await authFetch(`${apiBaseUrl}/api/email-accounts`);
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data) && data.length === 0) {
            router.push("/register/email-setup");
          } else {
            setOnboardingChecked(true);
          }
        } else {
          setOnboardingChecked(true); // Fallback to dashboard on API error
        }
      } catch (err) {
        console.error("Error during onboarding account check:", err);
        setOnboardingChecked(true); // Fallback to dashboard on network error
      }
    }

    if (authChecked && authUser) {
      checkEmailAccountOnboarding();
    }
  }, [authUser?.email, authChecked, apiBaseUrl, router]);

  useEffect(() => {
    if (!selectedInboxThreadId && inboxThreads[0]) {
      setSelectedInboxThreadId(inboxThreads[0].id);
      setSelectedInboxSupplier(inboxThreads[0].supplier_name);
    }
  }, [inboxThreads, selectedInboxThreadId]);

  useEffect(() => {
    const selectedEmailId = activeTab === "catalogs" ? selectedCatalogEmailId : selectedInboxThreadId;
    if (
      !authUser
      || !["inbox", "catalogs"].includes(activeTab)
      || !selectedEmailId
      || inboxItemsByEmail[selectedEmailId]
    ) {
      return;
    }

    const emailId = selectedEmailId;
    const reqId = ++inboxItemsRequestIdRef.current;
    setInboxItemsLoadingId(emailId);
    setInboxItemsErrorId(null);

    authFetch(
      `${apiBaseUrl}/api/catalogs/items?limit=${FULL_CATALOG_LIMIT}&latest_only=false&catalog_email_id=${encodeURIComponent(emailId)}`
    )
      .then(async (response) => {
        if (!response.ok) {
          throw new Error("Unable to load extracted items.");
        }
        const items: SupplierTableRow[] = await response.json();
        if (reqId === inboxItemsRequestIdRef.current) {
          setInboxItemsByEmail((current) => ({ ...current, [emailId]: items }));
        }
      })
      .catch((error) => {
        console.error("Inbox item detail refresh failed", error);
        if (reqId === inboxItemsRequestIdRef.current) {
          setInboxItemsErrorId(emailId);
        }
      })
      .finally(() => {
        if (reqId === inboxItemsRequestIdRef.current) {
          setInboxItemsLoadingId((current) => current === emailId ? null : current);
        }
      });
  }, [activeTab, apiBaseUrl, authUser?.email, inboxItemsByEmail, selectedCatalogEmailId, selectedInboxThreadId]);

  useEffect(() => {
    if (sidebarCollapsed) {
      document.body.classList.add("sidebar-collapsed");
    } else {
      document.body.classList.remove("sidebar-collapsed");
    }
  }, [sidebarCollapsed]);

  useEffect(() => {
    async function loadSupplierRows() {
      if (!authUser) {
        setSupplierLoading(false);
        return;
      }

      const reqId = ++supplierRowsRequestIdRef.current;

      if (!initialLoadRef.current) {
        setSupplierLoading(true);
      }
      setSupplierError(null);

      try {
        // Step 1: Instantly unblock Inbox and Dashboard by loading emails and supplier metadata
        const [suppliersRes, emailsRes] = await Promise.all([
          authFetch(`${apiBaseUrl}/api/suppliers`),
          authFetch(`${apiBaseUrl}/api/catalogs/emails?limit=${FULL_INBOX_LIMIT}`),
        ]);

        if (reqId !== supplierRowsRequestIdRef.current) return;

        if (!emailsRes.ok) {
          throw new Error("Failed to fetch supplier emails from backend.");
        }

        const suppliers: SupplierApiRow[] = suppliersRes.ok ? await suppliersRes.json() : [];
        const emails: CatalogEmailRow[] = await emailsRes.json();

        setSupplierMetaRows(suppliers);
        setCatalogEmails(emails);
        setSupplierError(!suppliersRes.ok ? "Showing fetched emails. Catalogue details are loading." : null);
        setSupplierLoading(false);
        initialLoadRef.current = true;

        // Step 2: Fetch catalog items in background to unblock Inbox instantly
        try {
          const itemsRes = await authFetch(`${apiBaseUrl}/api/catalogs/items?limit=${FULL_CATALOG_LIMIT}&latest_only=true`);
          if (itemsRes.ok && reqId === supplierRowsRequestIdRef.current) {
            const items: Array<SupplierItem & { supplier_name: string; email_domain?: string | null }> = await itemsRes.json();
            const supplierMeta = new Map(
              suppliers.map((supplier) => [supplierKey(supplier.name, supplier.email_domain), supplier])
            );
            const mergedRows: SupplierTableRow[] = items.map((item) => {
              const meta = supplierMeta.get(supplierKey(item.supplier_name, item.email_domain));
              return {
                ...item,
                email_domain: item.email_domain ?? meta?.email_domain ?? "-",
                country: (item as any).country ?? meta?.country ?? "Unknown",
                certifications: meta?.certifications ?? null,
              };
            });
            setSupplierRows(mergedRows);
          }
        } catch (itemErr) {
          console.warn("Background catalog items fetch error:", itemErr);
        }
      } catch (error) {
        if (reqId === supplierRowsRequestIdRef.current) {
          setSupplierError(error instanceof Error ? error.message : "Unable to load supplier table.");
          setSupplierLoading(false);
        }
      }
    }

    loadSupplierRows();
  }, [apiBaseUrl, authUser?.email, dataRefreshKey]);

  useEffect(() => {
    if (!authUser || syncActivityJob?.status !== "running") return;
    const intervalId = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      fetchSyncActivitySnapshot().catch((err) => console.error("Inbox sync activity refresh failed", err));
    }, 5000);
    return () => window.clearInterval(intervalId);
  }, [authUser, syncActivityJob?.status]);

  useEffect(() => {
    if (!syncActivityJob || syncActivityJob.status !== "completed") return;
    if (completedSyncRefreshRef.current === syncActivityJob.id) return;
    completedSyncRefreshRef.current = syncActivityJob.id;
    refreshWorkspaceData().catch((err) => console.error("Post-sync workspace refresh failed", err));
  }, [syncActivityJob?.id, syncActivityJob?.status]);

  useEffect(() => {
    if (authUser?.name) {
      setMessages((current) => {
        if (
          current.length === 1 &&
          current[0].role === "assistant" &&
          (current[0].text === "Hey User!\nHow can I help you today?" || current[0].text.startsWith("Hey User!"))
        ) {
          const firstName = authUser.name.split(" ")[0];
          return [
            {
              role: "assistant",
              text: `Hey ${firstName}!\nHow can I help you today?`
            }
          ];
        }
        return current;
      });
    }
  }, [authUser]);

  async function ensureSocket() {
    if (socketRef.current?.readyState === WebSocket.OPEN) return socketRef.current;

    const res = await supabase.auth.getSession();
    const session = res?.data?.session;
    const token = session?.access_token || "";
    const authenticatedWsUrl = token ? `${wsUrl}?token=${token}` : wsUrl;

    const socket = new WebSocket(authenticatedWsUrl);
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (payload.type === "status") {
        console.debug("ProcuraAI status", payload.message);
      }
      if (payload.type === "answer") {
        setIsTypingResponse(false);
        setRows(payload.rows || []);
        simulateStreamingResponse(payload.answer);
      }
      if (payload.type === "error") {
        setIsTypingResponse(false);
        console.error("ProcuraAI query failed", payload.message);
        setMessages((current) => [
          ...current,
          { role: "assistant", text: payload.message || "MediCORE could not complete that query." },
        ]);
      }
    };
    socket.onclose = () => {
      if (socketRef.current === socket) {
        socketRef.current = null;
      }
      setIsTypingResponse(false);
    };
    socket.onerror = () => {
      if (socketRef.current === socket) {
        socketRef.current = null;
      }
      setIsTypingResponse(false);
      showConnectionFailure("The MediCORE assistant connection was interrupted. Please retry when the connection is stable.");
    };
    socketRef.current = socket;
    return socket;
  }

  async function sendMessage(text = input) {
    const trimmed = text.trim();
    if (!trimmed) return;
    setMessages((current) => [...current, { role: "user", text: trimmed }]);
    setInput("");
    setRows([]);
    
    // Trigger typing response indicator
    setIsTypingResponse(true);
    
    try {
      const socket = await ensureSocket();
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(trimmed);
      } else {
        socket.onopen = () => socket.send(trimmed);
      }
    } catch (error) {
      console.error("Assistant connection failed", error);
      setIsTypingResponse(false);
      showConnectionFailure("The MediCORE assistant connection failed. Please check your connection and try again.");
    }
  }

  function simulateStreamingResponse(fullText: string) {
    if (streamIntervalRef.current) {
      clearInterval(streamIntervalRef.current);
    }
    
    // Add empty assistant message to stream into
    setMessages((current) => [...current, { role: "assistant", text: "" }]);
    
    let index = 0;
    const speed = 15;
    const charsPerChunk = 3;
    
    streamIntervalRef.current = setInterval(() => {
      setMessages((current) => {
        const next = [...current];
        const lastMsg = next[next.length - 1];
        if (lastMsg && lastMsg.role === "assistant") {
          const chunk = fullText.slice(index, index + charsPerChunk);
          lastMsg.text += chunk;
          index += charsPerChunk;
          
          if (index >= fullText.length) {
            if (streamIntervalRef.current) clearInterval(streamIntervalRef.current);
            streamIntervalRef.current = null;
          }
        }
        return next;
      });
    }, speed);
  }

  function handleRefreshChat() {
    socketRef.current?.close();
    socketRef.current = null;
    const nameToUse = authUser?.name ? authUser.name.split(" ")[0] : "User";
    setMessages([
      {
        role: "assistant",
        text: `Hey ${nameToUse}!\nHow can I help you today?`
      }
    ]);
    setInput("");
    setIsTypingResponse(false);
  }

  async function handleLogout() {
    await supabase.auth.signOut();
    if (typeof window !== "undefined") {
      // Clear cookie
      document.cookie = `sb-access-token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 UTC; SameSite=Lax; Secure`;
    }
    socketRef.current?.close();
    socketRef.current = null;
    setAuthUser(null);
    initialLoadRef.current = false;
    setActiveTab("dashboard");
    router.push("/login");
  }

  async function handleSaveProfile() {
    if (!editName.trim()) {
      setProfileError("Name cannot be empty.");
      return;
    }
    setIsSavingProfile(true);
    setProfileError(null);
    try {
      const { data, error } = await supabase.auth.updateUser({
        data: {
          full_name: editName.trim()
        }
      });
      if (error) throw error;
      
      // Update local state
      setAuthUser(prev => prev ? {
        ...prev,
        name: editName.trim()
      } : null);
      
      setIsEditingProfile(false);
    } catch (err: any) {
      setProfileError(err.message || "Failed to update profile.");
    } finally {
      setIsSavingProfile(false);
    }
  }

  // --- Premium Settings Integration Helpers ---
  function showConnectionFailure(message = "Unable to communicate with MediCORE. Please check your internet connection and try again.") {
    setConnectionError(message);
  }

  async function authFetch(url: string, options: RequestInit = {}) {
    try {
      const res = await supabase.auth.getSession();
      const session = res?.data?.session;
      const token = session?.access_token;
      const headers = {
        ...options.headers,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      };
      return await fetch(url, { ...options, headers });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        showConnectionFailure("The request timed out before MediCORE responded. Please retry when the connection is stable.");
      } else {
        showConnectionFailure();
      }
      throw error;
    }
  }

  async function refreshWorkspaceData() {
    setInboxItemsByEmail({});
    setInboxItemsErrorId(null);
    setDataRefreshKey((current) => current + 1);
    await Promise.allSettled([
      fetchConnectedAccounts(),
      fetchEmailSyncSettings(),
    ]);
  }

  async function fetchSyncActivitySnapshot() {
    const [emailsRes, accountsRes] = await Promise.all([
      authFetch(`${apiBaseUrl}/api/catalogs/emails?limit=${FULL_INBOX_LIMIT}`),
      authFetch(`${apiBaseUrl}/api/email-accounts`),
    ]);
    const emails: CatalogEmailRow[] = emailsRes.ok ? await emailsRes.json() : [];
    const accounts: ConnectedEmailAccount[] = accountsRes.ok ? await accountsRes.json() : [];

    if (emailsRes.ok) {
      setCatalogEmails(emails);
    }
    if (accountsRes.ok) {
      setConnectedAccounts(accounts);
    }

    const observedAt = Date.now();
    const changedEvents: SyncActivityEvent[] = [];
    for (const [index, email] of emails.entries()) {
      const signature = syncEmailSignature(email);
      const baseline = syncEmailBaselineRef.current.get(email.id);
      const lastObserved = syncEmailObservedRef.current.get(email.id);
      if ((baseline === undefined || baseline !== signature) && lastObserved !== signature) {
        changedEvents.push(syncEventFromEmail(email, observedAt + index));
        syncEmailObservedRef.current.set(email.id, signature);
      }
    }

    setSyncActivityJob((current) => {
      if (!current || current.status !== "running") return current;

      const eventsById = new Map(current.events.map((event) => [event.id, event]));
      for (const event of changedEvents) {
        eventsById.set(event.id, event);
      }

      const trackedAccounts = current.accountIds
        .map((accountId) => accounts.find((account) => account.id === accountId))
        .filter((account): account is ConnectedEmailAccount => Boolean(account));
      const accountSnapshotComplete = current.accountIds.length > 0
        && trackedAccounts.length === current.accountIds.length;
      const accountsSettled = accountSnapshotComplete
        && trackedAccounts.every((account) => !["pending", "processing", "queued"].includes(
          normalizedProcessingStatus(account.sync_status)
        ));

      if (accountsSettled) {
        for (const [index, email] of emails.entries()) {
          const baselineStatus = String(syncEmailBaselineRef.current.get(email.id) || "").split("|", 1)[0];
          const wasRetryable = ["failed", "error", "partial", "partially_processed"].some(
            (status) => baselineStatus.startsWith(status)
          );
          if (wasRetryable && !eventsById.has(`email-${email.id}`)) {
            eventsById.set(`email-${email.id}`, syncEventFromEmail(email, observedAt + index));
          }
        }
      }

      for (const account of trackedAccounts.filter((item) => normalizedProcessingStatus(item.sync_status) === "error")) {
        eventsById.set(`account-${account.id}`, {
          id: `account-${account.id}`,
          tone: "failed",
          supplier: account.email_address,
          message: "Mailbox sync failed",
          detail: syncActivityReason(account.sync_error_msg) || "The mailbox could not be processed.",
          timestamp: observedAt,
        });
      }

      const events = Array.from(eventsById.values())
        .sort((left, right) => left.timestamp - right.timestamp)
        .slice(-100);
      const emailEvents = events.filter((event) => event.emailId);
      const processed = emailEvents.filter((event) => event.tone === "success").length;
      const skipped = emailEvents.filter((event) => event.tone === "skipped").length;
      const failed = emailEvents.filter((event) => event.tone === "failed").length;
      const terminalCount = processed + skipped + failed;
      const allAccountsFailed = trackedAccounts.length > 0
        && trackedAccounts.every((account) => normalizedProcessingStatus(account.sync_status) === "error");

      return {
        ...current,
        status: accountsSettled ? (allAccountsFailed ? "failed" : "completed") : current.status,
        completedAt: accountsSettled ? observedAt : current.completedAt,
        total: accountsSettled ? terminalCount : current.total,
        processed,
        skipped,
        failed,
        events,
      };
    });
  }

  async function refreshInboxNow() {
    setIsRefreshingInbox(true);
    try {
      await refreshWorkspaceData();
    } finally {
      setIsRefreshingInbox(false);
    }
  }

  async function fetchConnectedAccounts() {
    setLoadingAccounts(true);
    try {
      const res = await authFetch(`${apiBaseUrl}/api/email-accounts`);
      if (res.ok) {
        const data = await res.json();
        setConnectedAccounts(data);
      }
    } catch (error) {
      console.error("Error loading email accounts:", error);
    } finally {
      setLoadingAccounts(false);
    }
  }

  async function fetchEmailSyncSettings() {
    try {
      const res = await authFetch(`${apiBaseUrl}/api/email-accounts/sync-settings`);
      if (res.ok) {
        const data = await res.json();
        setSyncSettings(data);
      }
    } catch (error) {
      console.error("Error loading sync settings:", error);
    }
  }

  async function saveEmailSyncSettings(updatedSettings: Partial<any>) {
    setSavingSyncSettings(true);
    const merged = { ...syncSettings, ...updatedSettings };
    setSyncSettings(merged);

    try {
      const res = await authFetch(`${apiBaseUrl}/api/email-accounts/sync-settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          poll_interval_minutes: Number(merged.poll_interval_minutes),
          auto_extract_catalog: Boolean(merged.auto_extract_catalog),
          notify_on_new_catalog: Boolean(merged.notify_on_new_catalog),
          ingestion_approach: String(merged.ingestion_approach || "approach_2"),
          trusted_suppliers: String(merged.trusted_suppliers || ""),
          pending_approvals: String(merged.pending_approvals || ""),
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setSyncSettings(data);
        setSettingsSaveFeedback(true);
        setTimeout(() => setSettingsSaveFeedback(false), 2500);
      }
    } catch (error) {
      console.error("Error saving sync settings:", error);
    } finally {
      setSavingSyncSettings(false);
    }
  }

  async function handleGrantAccess(item: any) {
    const sender = item.sender.trim().toLowerCase();
    const domain = sender.split("@")[1] || sender;

    const currentTrusted = syncSettings.trusted_suppliers || "";
    const trustedList = currentTrusted.split(",").map((s: string) => s.trim().toLowerCase()).filter(Boolean);
    if (!trustedList.includes(sender) && !trustedList.includes(domain)) {
      trustedList.push(sender);
    }
    const newTrusted = trustedList.join(", ");

    let currentPending: any[] = [];
    try {
      currentPending = JSON.parse(syncSettings.pending_approvals || "[]");
    } catch (e) {
      currentPending = [];
    }
    const newPending = currentPending.filter((p: any) => p.email_id !== item.email_id);

    await saveEmailSyncSettings({
      trusted_suppliers: newTrusted,
      pending_approvals: JSON.stringify(newPending)
    });

    try {
      await authFetch(`${apiBaseUrl}/api/ingestion/poll-now-sync-user`, { method: "POST" });
      await refreshWorkspaceData();
    } catch (e) {
      console.error("Error triggering immediate poll:", e);
    }
  }

  async function handleIgnoreAccess(item: any) {
    let currentPending: any[] = [];
    try {
      currentPending = JSON.parse(syncSettings.pending_approvals || "[]");
    } catch (e) {
      currentPending = [];
    }
    const ignoredRecord = {
      ...item,
      ignored: true,
      ignored_at: new Date().toISOString(),
    };
    const withoutCurrent = currentPending.filter((p: any) => p.email_id !== item.email_id);
    const newPending = [...withoutCurrent, ignoredRecord];

    await saveEmailSyncSettings({
      pending_approvals: JSON.stringify(newPending)
    });
  }

  async function testConnection() {
    if (!newAccountEmail.trim() || !newAccountPassword.trim()) {
      setTestResult({ success: false, message: "Email and app password are required to test connection." });
      return;
    }
    setTestingConnection(true);
    setTestResult(null);
    try {
      const res = await authFetch(`${apiBaseUrl}/api/email-accounts/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: newAccountProvider,
          email_address: newAccountEmail.trim(),
          imap_host: newAccountImapHost,
          imap_port: Number(newAccountImapPort),
          password: newAccountPassword,
        }),
      });
      const data = await res.json();
      if (res.ok && data.success) {
        setTestResult({ success: true, message: data.message || "Connected successfully! App credentials passed verification." });
      } else {
        setTestResult({ success: false, message: data.detail || data.message || "Verification failed. Check IMAP settings and App Password." });
      }
    } catch (error) {
      setTestResult({ success: false, message: "Server connection error. Please ensure backend is running." });
    } finally {
      setTestingConnection(false);
    }
  }

  async function saveAccount() {
    if (!newAccountEmail.trim() || (!editingAccountId && !newAccountPassword.trim())) {
      return;
    }
    setSavingAccount(true);
    try {
      const payload = {
        provider: newAccountProvider,
        email_address: newAccountEmail.trim(),
        imap_host: newAccountImapHost,
        imap_port: Number(newAccountImapPort),
        password: newAccountPassword || undefined,
        filters: {
          require_attachment: filterRequireAttachment,
          sender_keywords: filterSenderKeywords.trim() || null,
          subject_keywords: filterSubjectKeywords.trim() || null,
          skip_promotions_tab: filterSkipPromotions,
        }
      };

      const url = editingAccountId
        ? `${apiBaseUrl}/api/email-accounts/${editingAccountId}`
        : `${apiBaseUrl}/api/email-accounts`;

      const method = editingAccountId ? "PUT" : "POST";

      const res = await authFetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        await fetchConnectedAccounts();
        resetAddAccountForm();
        setDataRefreshKey((current) => current + 1);
      } else {
        const data = await res.json();
        setTestResult({ success: false, message: data.detail || "Failed to save email account credentials." });
      }
    } catch (error) {
      console.error("Error saving email account:", error);
    } finally {
      setSavingAccount(false);
    }
  }

  async function deleteAccount(id: string) {
    setDisconnectAccountConfirmId(id);
  }

  async function confirmDisconnectAccount() {
    if (!disconnectAccountConfirmId) return;
    setDisconnectAccountLoading(true);
    try {
      const res = await authFetch(`${apiBaseUrl}/api/email-accounts/${disconnectAccountConfirmId}`, {
        method: "DELETE",
      });
      if (res.ok) {
        await fetchConnectedAccounts();
        setDataRefreshKey((current) => current + 1);
        setDisconnectAccountConfirmId(null);
      } else {
        console.error("Could not disconnect the account", res.status);
      }
    } catch (error) {
      console.error("Error disconnecting account:", error);
    } finally {
      setDisconnectAccountLoading(false);
    }
  }

  async function triggerAccountSync(id: string) {
    setSyncingAccountsState(prev => ({ ...prev, [id]: true }));
    try {
      const res = await authFetch(`${apiBaseUrl}/api/email-accounts/${id}/sync`, {
        method: "POST",
      });
      if (res.ok) {
        setTimeout(async () => {
          await fetchConnectedAccounts();
          setSyncingAccountsState(prev => ({ ...prev, [id]: false }));
          setDataRefreshKey((current) => current + 1);
        }, 1500);
      } else {
        const errorPayload = await res.json().catch(() => null);
        setSyncNotice(errorPayload?.detail || "Email sync failed. Check connected inbox settings and try again.");
        setSyncingAccountsState(prev => ({ ...prev, [id]: false }));
      }
    } catch (error) {
      console.error("Error triggering sync:", error);
      setSyncingAccountsState(prev => ({ ...prev, [id]: false }));
    }
  }

  async function deleteCatalogEmail(emailId: string) {
    setDeleteEmailConfirmId(emailId);
  }

  async function confirmDeleteCatalogEmail() {
    if (!deleteEmailConfirmId) return;
    setDeleteEmailLoading(true);
    try {
      const res = await authFetch(`${apiBaseUrl}/api/catalogs/emails/${deleteEmailConfirmId}`, {
        method: "DELETE"
      });
      if (res.ok) {
        setSelectedInboxThreadId(null);
        setSelectedInboxSupplier("");
        setDataRefreshKey((current) => current + 1);
        setDeleteEmailConfirmId(null);
      } else {
        console.error("Could not delete catalogue email", res.status);
      }
    } catch (error) {
      console.error("Error deleting catalog email:", error);
    } finally {
      setDeleteEmailLoading(false);
    }
  }

  function editAccount(acc: ConnectedEmailAccount) {
    setEditingAccountId(acc.id);
    setNewAccountProvider(acc.provider);
    setNewAccountEmail(acc.email_address);
    setNewAccountPassword("");
    setNewAccountImapHost(acc.imap_host);
    setNewAccountImapPort(acc.imap_port);

    const filter = acc.filters?.[0];
    if (filter) {
      setFilterRequireAttachment(filter.require_attachment);
      setFilterSenderKeywords(filter.sender_keywords || "");
      setFilterSubjectKeywords(filter.subject_keywords || "");
      setFilterSkipPromotions(filter.skip_promotions_tab);
    } else {
      setFilterRequireAttachment(false);
      setFilterSenderKeywords("");
      setFilterSubjectKeywords("");
      setFilterSkipPromotions(false);
    }

    setSetupStep(3);
    setAddAccountExpanded(true);
    setTestResult({ success: true, message: "Testing is not required to update filters or provider details. Type a new app password if you want to update credentials." });
  }

  function resetAddAccountForm() {
    setAddAccountExpanded(false);
    setEditingAccountId(null);
    setSetupStep(1);
    setNewAccountProvider("Gmail");
    setNewAccountEmail(authUser?.email || "");
    setNewAccountPassword("");
    setNewAccountImapHost("imap.gmail.com");
    setNewAccountImapPort(993);
    setFilterRequireAttachment(false);
    setFilterSenderKeywords("");
    setFilterSubjectKeywords("");
    setFilterSkipPromotions(false);
    setTestResult(null);
  }

  useEffect(() => {
    if (authUser && activeTab === "settings") {
      fetchConnectedAccounts();
      fetchEmailSyncSettings();
      setNewAccountEmail(authUser.email);
    }
  }, [authUser, activeTab]);

  if (!authChecked || (authUser && !onboardingChecked)) {
    return <Loader variant="card" title="Setting up your workspace" subtitle="Verifying your credentials and preparing supplier catalogs..." />;
  }

  if (!authUser) {
    return null;
  }

  return (
    <>
      <style>{`
        @keyframes pulse-bell {
          0% { transform: scale(1); }
          50% { transform: scale(1.15) rotate(8deg); }
          100% { transform: scale(1); }
        }
        @keyframes fade-in-down {
          from { opacity: 0; transform: translateY(-8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
        .animate-spin {
          animation: spin 1s linear infinite;
          display: inline-block;
        }
      `}</style>

      {/* Navbar */}
      <nav className="navbar">
        <div className="navbar-brand" style={{ display: "flex", alignItems: "center", gap: "14px" }}>
          <h1>MediCORE</h1>
          <span style={{ fontSize: "12.5px", color: "var(--muted)", fontWeight: 500, letterSpacing: "0.02em", borderLeft: "1px solid var(--line)", paddingLeft: "14px" }}>
            AI-Powered Automated Procurement System
          </span>
        </div>
        <div className="navbar-actions" style={{ position: "relative", display: "flex", alignItems: "center", gap: "16px" }}>
          {/* Real-time email sync button */}
          <button
            type="button"
            onClick={handleSyncRealtimeEmails}
            disabled={isSyncingEmails}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              background: "none",
              border: syncSuccess ? "1px solid #0d6a50" : "1px solid var(--line)",
              borderRadius: "8px",
              padding: "6px 12px",
              fontSize: "12px",
              fontWeight: 500,
              color: syncSuccess ? "#0d6a50" : "var(--ink)",
              cursor: isSyncingEmails ? "not-allowed" : "pointer",
              transition: "all 0.2s",
            }}
            onMouseOver={(e) => {
              if (!isSyncingEmails) {
                e.currentTarget.style.background = "#fafcfb";
                e.currentTarget.style.borderColor = "var(--accent)";
              }
            }}
            onMouseOut={(e) => {
              if (!isSyncingEmails) {
                e.currentTarget.style.background = "none";
                e.currentTarget.style.borderColor = "var(--line)";
              }
            }}
          >
            {syncSuccess ? (
              <>
                <Check size={14} style={{ color: "#0d6a50" }} />
                <span style={{ color: "#0d6a50", fontWeight: 600 }}>Synced</span>
              </>
            ) : (
              <>
                <RefreshCw size={14} className={isSyncingEmails ? "animate-spin" : ""} style={{ color: "var(--accent)" }} />
                <span>{isSyncingEmails ? "Syncing..." : "Sync Emails"}</span>
              </>
            )}
          </button>
          {syncNotice && (
            <span
              style={{
                maxWidth: "280px",
                color: "var(--muted)",
                fontSize: "12px",
                lineHeight: 1.35,
              }}
            >
              {syncNotice}
            </span>
          )}

          <div className="user-menu" onClick={() => setUserMenuOpen(!userMenuOpen)}>
            <div className="user-avatar">{userInitials(authUser.name, authUser.email)}</div>
            <div className="user-info">
              <p>{authUser.name}</p>
              <span>{authUser.role}</span>
            </div>
            {/* Pulsating Bell Icon instead of ChevronDown */}
            <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center", marginLeft: "4px" }}>
              <Bell
                size={18}
                style={{
                  color: notificationCount > 0 ? "var(--accent)" : "var(--muted)",
                  transition: "all 0.3s ease",
                  animation: notificationCount > 0 ? "pulse-bell 1.5s infinite ease-in-out" : "none"
                }}
              />
              {notificationCount > 0 && (
                <span style={{
                  position: "absolute",
                  top: "-4px",
                  right: "-4px",
                  width: "10px",
                  height: "10px",
                  borderRadius: "50%",
                  background: "#ff5a5a",
                  border: "2px solid #fff",
                  boxShadow: "0 0 6px rgba(255, 90, 90, 0.6)"
                }} />
              )}
            </div>
          </div>

          {/* Floating Notifications Window */}
          {userMenuOpen && (
            <div style={{
              position: "absolute",
              top: "54px",
              right: 0,
              width: "380px",
              background: "rgba(255, 255, 255, 0.95)",
              backdropFilter: "blur(16px)",
              border: "1px solid var(--line)",
              borderRadius: "14px",
              boxShadow: "0 10px 30px rgba(0, 0, 0, 0.08)",
              zIndex: 1000,
              padding: "16px",
              display: "flex",
              flexDirection: "column",
              gap: "12px",
              animation: "fade-in-down 0.2s ease-out"
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid var(--line)", paddingBottom: "10px" }}>
                <span style={{ fontSize: "14px", fontWeight: 700, color: "#092f28", display: "flex", alignItems: "center", gap: "6px" }}>
                  <Bell size={16} /> Notifications
                </span>
                {notificationCount > 0 && (
                  <span style={{ fontSize: "11px", background: "rgba(255, 90, 90, 0.1)", color: "#ff5a5a", padding: "2px 8px", borderRadius: "10px", fontWeight: 600 }}>
                    {notificationCount} Notification{notificationCount > 1 ? "s" : ""}
                  </span>
                )}
              </div>

              {syncActivityJob && (
                <section className={`sync-activity-card ${syncActivityJob.status}`}>
                  <div className="sync-activity-head">
                    <div>
                      <strong>Email Sync</strong>
                      <span>
                        {syncActivityTotal > 0
                          ? `${syncActivityJob.status === "completed" ? "Processed" : "Processing"} ${syncActivityTotal} supplier email${syncActivityTotal === 1 ? "" : "s"}`
                          : syncActivityJob.status === "completed" ? "No new supplier emails found" : "Checking supplier emails"}
                      </span>
                    </div>
                    <span className="sync-activity-percent">{syncActivityProgress}%</span>
                  </div>
                  <div className="sync-activity-progress">
                    <span style={{ width: `${syncActivityProgress}%` }} />
                  </div>
                  <div className="sync-activity-stats">
                    <span className="success">Processed: {syncActivityJob.processed}</span>
                    <span className="skipped">Skipped: {syncActivityJob.skipped}</span>
                    <span className="failed">Failed: {syncActivityJob.failed}</span>
                    <span>Remaining: {syncActivityRemaining}</span>
                    <span>Time: {syncActivityElapsedSeconds}s</span>
                  </div>
                  {syncActivityHasCollapsedEvents && (
                    <div className="sync-activity-collapsed">
                      Older completed events collapsed to keep this feed readable.
                    </div>
                  )}
                  <div className="sync-activity-list" ref={syncActivityListRef}>
                    {syncActivityActiveEvent && (
                      <div className="sync-activity-section">
                        <h4>Currently Processing</h4>
                        <div className="sync-activity-event processing">
                          <span className="sync-activity-icon"><Loader2 size={14} /></span>
                          <div>
                            <p><strong>{syncActivityActiveEvent.supplier}</strong><span>{syncActivityActiveEvent.message}</span></p>
                            {syncActivityActiveEvent.detail && <small>{syncActivityActiveEvent.detail}</small>}
                          </div>
                        </div>
                      </div>
                    )}
                    {syncActivityCompletedEvents.length > 0 && (
                      <div className="sync-activity-section">
                        <h4>Completed</h4>
                        {syncActivityCompletedEvents.map((event) => (
                          <div className="sync-activity-event success" key={event.id}>
                            <span className="sync-activity-icon"><CheckCircle2 size={14} /></span>
                            <div>
                              <p><strong>{event.supplier}</strong><span>{event.message}</span></p>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                    {syncActivitySkippedEvents.length > 0 && (
                      <div className="sync-activity-section">
                        <h4>Skipped</h4>
                        {syncActivitySkippedEvents.map((event) => (
                          <div className="sync-activity-event skipped" key={event.id}>
                            <span className="sync-activity-icon"><Info size={14} /></span>
                            <div>
                              <p><strong>{event.supplier}</strong><span>{event.message}</span></p>
                              {event.detail && <small>{event.detail}</small>}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                    {syncActivityFailedEvents.length > 0 && (
                      <div className="sync-activity-section">
                        <h4>Failed</h4>
                        {syncActivityFailedEvents.map((event) => (
                          <div className="sync-activity-event failed" key={event.id}>
                            <span className="sync-activity-icon"><XCircle size={14} /></span>
                            <div>
                              <p><strong>{event.supplier}</strong><span>{event.message}</span></p>
                              {event.detail && <small>{event.detail}</small>}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                    {!syncActivityActiveEvent && syncActivityVisibleEvents.length === 0 && syncActivityJob.status === "completed" && (
                      <div className="sync-activity-empty">
                        No supplier emails required processing.
                      </div>
                    )}
                  </div>
                </section>
              )}

              {/* Notifications List Container */}
              <div style={{
                maxHeight: "280px",
                overflowY: "auto",
                display: "flex",
                flexDirection: "column",
                gap: "10px"
              }}>
                {notificationCount === 0 ? (
                  <div style={{
                    padding: "24px 16px",
                    textAlign: "center",
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    gap: "8px"
                  }}>
                    <div style={{
                      width: "36px",
                      height: "36px",
                      borderRadius: "50%",
                      background: "rgba(15, 122, 95, 0.06)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: "var(--accent)"
                    }}>
                      <CheckCircle2 size={20} />
                    </div>
                    <strong style={{ fontSize: "13px", color: "var(--ink)" }}>All Caught Up!</strong>
                    <span style={{ fontSize: "12px", color: "var(--muted)" }}>No supplier approvals or failed email extractions pending.</span>
                  </div>
                ) : (
                  <>
                  {failedEmailNotifications.map((email) => (
                    <div
                      key={`failed-${email.id}`}
                      style={{
                        padding: "12px",
                        borderRadius: "10px",
                        background: "rgba(239, 68, 68, 0.06)",
                        border: "1px solid rgba(239, 68, 68, 0.16)",
                        display: "flex",
                        flexDirection: "column",
                        gap: "6px",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "8px" }}>
                        <span style={{ fontWeight: 700, fontSize: "12.5px", color: "#9b1c1c" }}>
                          Email failed to process
                        </span>
                        <span style={{ fontSize: "10px", color: "var(--muted)", whiteSpace: "nowrap" }}>
                          {formatRelativeTime(email.received_at)}
                        </span>
                      </div>
                      <span style={{ fontSize: "11.5px", color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {email.supplier_name || "Supplier email"}
                      </span>
                      <span style={{ fontSize: "11.5px", color: "#9b1c1c", lineHeight: 1.35 }}>
                        {syncActivityReason(email.processing_status) || "Processing could not be completed for this email."}
                      </span>
                    </div>
                  ))}
                  {pendingApprovalsList.map((item: any) => (
                    <div
                      key={item.email_id}
                      style={{
                        padding: "12px",
                        borderRadius: "10px",
                        background: "rgba(0, 0, 0, 0.015)",
                        border: "1px solid var(--line)",
                        display: "flex",
                        flexDirection: "column",
                        gap: "8px",
                      }}
                    >
                      <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                          <span style={{ fontWeight: 700, fontSize: "12.5px", color: "var(--ink)", wordBreak: "break-all", paddingRight: "8px" }}>
                            {item.supplier_name || item.sender}
                          </span>
                          <span style={{ fontSize: "10px", color: "var(--muted)", whiteSpace: "nowrap" }}>
                            {formatRelativeTime(item.date)}
                          </span>
                        </div>
                        <span style={{ fontSize: "11.5px", color: "var(--muted)", fontStyle: "italic", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                          {item.subject || "(No Subject)"}
                        </span>
                      </div>

                      <div style={{ display: "flex", gap: "8px", marginTop: "4px" }}>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleGrantAccess(item);
                          }}
                          style={{
                            flex: 1,
                            padding: "6px 12px",
                            fontSize: "11.5px",
                            fontWeight: 600,
                            borderRadius: "6px",
                            border: "none",
                            background: "var(--accent)",
                            color: "#fff",
                            cursor: "pointer",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            gap: "4px"
                          }}
                        >
                          <CheckCircle2 size={13} /> Grant Access
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleIgnoreAccess(item);
                          }}
                          style={{
                            padding: "6px 12px",
                            fontSize: "11.5px",
                            fontWeight: 600,
                            borderRadius: "6px",
                            border: "1px solid var(--line)",
                            background: "#fff",
                            color: "var(--muted)",
                            cursor: "pointer",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            gap: "4px"
                          }}
                        >
                          <XCircle size={13} /> Ignore
                        </button>
                      </div>
                    </div>
                  ))}
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </nav>

      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-content">
          <div className="sidebar-top">
            <span className="sidebar-top-label"><h2>Main</h2></span>
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
                  className={`sidebar-nav-link ${activeTab === "dashboard" ? "active" : ""}`}
                  onClick={() => setActiveTab("dashboard")}
                >
                  <BarChart3 size={18} />
                  <span>Dashboard</span>
                </button>
              </li>
              <li className="sidebar-nav-item">
                <button
                  className={`sidebar-nav-link ${activeTab === "inbox" ? "active" : ""}`}
                  onClick={() => setActiveTab("inbox")}
                >
                  <div className="sidebar-icon-wrapper">
                    <Inbox size={18} />
                    {hasNewMail && <span className="notification-dot" />}
                  </div>
                  <span>Inbox</span>
                </button>
              </li>
              <li className="sidebar-nav-item">
                <button
                  className={`sidebar-nav-link ${activeTab === "suppliers" ? "active" : ""}`}
                  onClick={() => setActiveTab("suppliers")}
                >
                  <Users size={18} />
                  <span>Suppliers</span>
                </button>
              </li>
            </ul>
          </div>
          <div className="sidebar-section"><ul className="sidebar-nav">
            <li className="sidebar-nav-item">
              <button
                className={`sidebar-nav-link ${activeTab === "compare" ? "active" : ""}`}
                onClick={() => setActiveTab("compare")}
              >
                <GitCompare size={18} />
                <span>Compare</span>
              </button>
            </li>
            <li className="sidebar-nav-item">
              <button
                className={`sidebar-nav-link ${activeTab === "assistant" ? "active" : ""}`}
                onClick={() => setActiveTab("assistant")}
              >
                <Sparkles size={18} />
                <span>AI Assistant</span>
              </button>
            </li>
          </ul>
          </div>
          <div className="sidebar-settings-section">
            <div className="sidebar-section-title">Settings</div>
            <ul className="sidebar-nav">
              <li className="sidebar-nav-item">
                <button
                  className={`sidebar-nav-link ${activeTab === "settings" ? "active" : ""}`}
                  onClick={() => setActiveTab("settings")}
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
      <main className={`app-shell ${showAssistantPanel ? "has-chat" : ""}`}>
        <section className={`dashboard ${showAssistantPanel ? "assistant-layout" : ""}`}>
          {activeTab === "dashboard" && (
            <section className="overview-dashboard">
              <div style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "18px 20px",
                borderRadius: "10px",
                border: "1px solid var(--line)",
                background: "var(--panel)",
                marginBottom: "8px"
              }}>
                <h2 style={{ margin: 0, fontSize: "22px", fontWeight: 600, color: "#092f28" }}>Dashboard</h2>
              </div>


              <p className="overview-label">Overall overview</p>
              <div className="overview-metrics">
                <article>
                  <span>Emails received</span>
                  <strong>{dashboardData.emailsReceived}</strong>
                  <small>{dashboardData.activities.length} recent supplier updates</small>
                </article>
                <article>
                  <span>New catalogues</span>
                  <strong>{dashboardData.completedCatalogs}</strong>
                  <small>{Math.max(0, dashboardData.emailsReceived - dashboardData.completedCatalogs)} pending review</small>
                </article>
                <article>
                  <span>Active suppliers</span>
                  <strong>{dashboardData.activeSuppliers}</strong>
                  <small>All verified suppliers</small>
                </article>
              </div>

              <div className="overview-grid">
                <section className="overview-panel recent-activity-panel">
                  <div className="overview-panel-header">
                    <h2>Recent activity</h2>
                    <button type="button" onClick={() => setActiveTab("inbox")}>View all</button>
                  </div>
                  <div className="activity-list">
                    {supplierLoading ? (
                      <p className="dashboard-empty">Loading activity...</p>
                    ) : dashboardData.activities.length === 0 ? (
                      <p className="dashboard-empty">No recent catalogue activity.</p>
                    ) : dashboardData.activities.map((activity, index) => (
                      <div className="activity-row" key={`${activity.text}-${index}`}>
                        <span className={`activity-dot ${activity.tone}`} />
                        <div>
                          <p>{activity.text}</p>
                          <small>{activity.time}</small>
                        </div>
                      </div>
                    ))}
                  </div>
                </section>

                <section className="overview-panel best-deals-panel">
                  <div className="overview-panel-header">
                    <h2>Best Deals</h2>
                    <button type="button" onClick={() => setActiveTab("assistant")}>{"Open chat ->"}</button>
                  </div>
                  <div className="deal-list">
                    {supplierLoading ? (
                      <p className="dashboard-empty">Loading deals...</p>
                    ) : dashboardData.deals.length === 0 ? (
                      <p className="dashboard-empty">No deal data available.</p>
                    ) : dashboardData.deals.map((deal, index) => (
                      <article className={`deal-row ${index === 2 ? "warning" : ""}`} key={`${deal.name}-${supplierKey(deal.best?.supplier_name, deal.best?.email_domain)}`}>
                        <div>
                          <strong>{renderItemName(deal.best)}</strong>
                          <span>{deal.best.supplier_name} - {displayQuantity(deal.best)}</span>
                        </div>
                        <div className="deal-price">
                          <strong>{displayPrice(deal.best)}</strong>
                          <small>Best listed</small>
                        </div>
                      </article>
                    ))}
                  </div>
                </section>
              </div>
            </section>
          )}

          {activeTab === "inbox" && (
            <>
              <div className="inbox-layout">
                <aside className="inbox-list-panel">
                  <div className="inbox-panel-header" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <h2>Inbox</h2>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <span className="inbox-count">{inboxThreads.length}</span>
                      <button
                        type="button"
                        onClick={refreshInboxNow}
                        disabled={isRefreshingInbox || supplierLoading}
                        className={`inbox-refresh-button ${isRefreshingInbox || supplierLoading ? "refreshing" : ""}`}
                        title="Refresh Inbox"
                        style={{
                          width: "30px",
                          height: "30px",
                          display: "inline-flex",
                          alignItems: "center",
                          justifyContent: "center",
                          border: "1px solid var(--line)",
                          borderRadius: "6px",
                          background: "#ffffff",
                          color: "var(--ink)",
                          cursor: isRefreshingInbox || supplierLoading ? "wait" : "pointer"
                        }}
                      >
                        <RefreshCw size={14} />
                      </button>
                    </div>
                  </div>
                  <div className="inbox-column-header">
                    <span>Sender</span>
                    <span>Status</span>
                  </div>
                  <div className="inbox-list">
                    {supplierLoading ? (
                      <div className="inbox-empty-state">Loading supplier inbox data...</div>
                    ) : supplierError ? (
                      <div className="inbox-empty-state">{supplierError}</div>
                    ) : inboxThreads.length === 0 ? (
                      <div className="inbox-empty-state">No supplier emails found.</div>
                    ) : (
                      inboxThreads.map((thread) => (
                        <button
                          key={thread.id}
                          type="button"
                          className={`inbox-thread ${selectedInboxThread?.id === thread.id ? "active" : ""}`}
                          onClick={() => {
                            setSelectedInboxThreadId(thread.id);
                            setSelectedInboxSupplier(thread.supplier_name);
                          }}
                        >
                          <div className="inbox-thread-topline">
                            <strong>{thread.supplier_name}</strong>
                            <span>{formatRelativeTime(thread.received_at)}</span>
                          </div>
                          <div className="inbox-thread-subject" style={{ textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>
                            {thread.subject || "No Subject"}
                          </div>
                          <div className="inbox-thread-meta">
                            <span className={`thread-status ${thread.status_tone}`}>{thread.status_label}</span>
                            <span className="thread-meta-items" style={{ fontSize: "11px", color: "var(--muted)", marginLeft: "auto" }}>{thread.item_count} items</span>
                          </div>
                        </button>
                      ))
                    )}
                  </div>
                </aside>

                <section className="inbox-detail-panel">
                  {selectedInboxThread ? (
                    <>
                      <div className="inbox-panel-header inbox-panel-header-main" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "18px" }}>
                        <div>
                          <h2>{selectedInboxThread.supplier_name} — {selectedInboxThread.email_domain}</h2>
                          <div className="inbox-subline">{selectedInboxThread.subject || "No Subject"} — {selectedInboxThread.item_count} items enclosed</div>
                        </div>
                        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "8px" }}>
                          <div className="inbox-subtitle" style={{ margin: 0 }}>{formatInboxDate(selectedInboxThread.received_at)}</div>
                          <button
                            type="button"
                            onClick={() => deleteCatalogEmail(selectedInboxThread.id)}
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: "6px",
                              padding: "6px 12px",
                              background: "rgba(229, 62, 62, 0.08)",
                              color: "#e53e3e",
                              border: "1px solid rgba(229, 62, 62, 0.2)",
                              borderRadius: "6px",
                              fontSize: "12px",
                              fontWeight: 600,
                              cursor: "pointer",
                              transition: "all 0.2s"
                            }}
                          >
                            <Trash2 size={13} /> Delete Email
                          </button>
                        </div>
                      </div>

                      <div className="inbox-summary-grid">
                        <article className="summary-card">
                          <span>Items extracted</span>
                          <strong>{selectedInboxThread.item_count}</strong>
                        </article>
                        <article className="summary-card">
                          <span>Duplicates found</span>
                          <strong>{selectedInboxThread.duplicate_count}</strong>
                        </article>
                        <article className="summary-card">
                          <span>Best deals found</span>
                          <strong>{(() => {
                            const bestPrice = Math.min(...selectedInboxThread.items.map((row) => safePrice(row.price_per_unit, row.currency)));
                            return Number.isFinite(bestPrice) ? selectedInboxThread.items.filter((item) => safePrice(item.price_per_unit, item.currency) <= bestPrice * 1.05).length : 0;
                          })()}</strong>
                        </article>
                      </div>

                      {selectedInboxThread.status_tone === "skipped" ? (
                        <div className="results-panel inbox-email-preview-panel">
                          <div className="panel-title">
                            <Mail size={18} />
                            <h2>Email preview</h2>
                          </div>
                          <div className="skipped-email-reason">{selectedInboxThread.status_label}</div>
                          <div
                            className="skipped-email-body"
                            style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", lineHeight: 1.55 }}
                          >
                            {selectedInboxThread.body_preview || "No readable email body was available for this skipped email."}
                          </div>
                        </div>
                      ) : (
                        <div className="results-panel inbox-table-panel">
                          <div className="panel-title">
                            <Search size={18} />
                            <h2>AI extraction summary ({selectedInboxThread.items.length} {selectedInboxThread.items.length === 1 ? "item" : "items"})</h2>
                          </div>
                          <div className="table-wrap" style={{ maxHeight: "520px", overflowY: "auto" }}>
                            <table>
                              <thead>
                                <tr>
                                  <th>#</th>
                                  <th>Ingredient</th>
                                  <th className="specification-header">Specification</th>
                                  <th>Price/Unit</th>
                                  <th>Qty Avail.</th>
                                  <th>Lead Time</th>
                                  <th>MOQ</th>
                                  <th>Date</th>
                                  <th>Status</th>
                                </tr>
                              </thead>
                              <tbody>
                                {inboxItemsLoadingId === selectedInboxThread.id ? (
                                  <tr>
                                    <td colSpan={9}>Loading extracted items...</td>
                                  </tr>
                                ) : inboxItemsErrorId === selectedInboxThread.id ? (
                                  <tr>
                                    <td colSpan={9}>Unable to load extracted item details. Use Refresh to retry.</td>
                                  </tr>
                                ) : selectedInboxThread.items.length === 0 ? (
                                  <tr>
                                    <td colSpan={9}>
                                      {selectedInboxThread.item_count > 0
                                        ? "Extracted item details are temporarily unavailable."
                                        : "No catalogue items were extracted from this email."}
                                    </td>
                                  </tr>
                                ) : (
                                  selectedInboxThread.items.map((item, index) => {
                                    const bestPrice = Math.min(...selectedInboxThread.items.map((row) => safePrice(row.price_per_unit, row.currency)));
                                    const rowKey = `${item.supplier_name || selectedInboxThread.supplier_name}-${item.ingredient_name}-${index}`;
                                    const expanded = Boolean(expandedInboxRows[rowKey]);
                                    return (
                                      <tr key={rowKey}>
                                        <td>{index + 1}</td>
                                        <td className="two-line-cell">
                                          <button
                                            className="expandable-item-button"
                                            type="button"
                                            onClick={() => setExpandedInboxRows((current) => ({ ...current, [rowKey]: !current[rowKey] }))}
                                          >
                                            <span>{renderItemName(item)}</span>
                                          </button>
                                          {expanded && (
                                            <div className="expanded-supplier-inline">
                                              <span><b>Supplier:</b> <strong>{displayText(item.supplier_name || selectedInboxThread.supplier_name)}</strong></span>
                                              <span><b>Email:</b> <strong>{displayText(item.email_domain || selectedInboxThread.email_domain)}</strong></span>
                                              <span><b>Country:</b> <strong>{displayText(item.country || selectedInboxThread.country || "Unknown")}</strong></span>
                                            </div>
                                          )}
                                        </td>
                                        <td className="two-line-cell specification-cell">{displaySpecification(item)}</td>
                                        <td>{displayPrice(item)}</td>
                                        <td>{displayQuantity(item)}</td>
                                        <td>{displayLeadTime(item)}</td>
                                        <td>{displayMoq(item)}</td>
                                        <td>{formatDDMMYY(selectedInboxThread.received_at)}</td>
                                        <td>{safePrice(item.price_per_unit, item.currency) === bestPrice ? "Best price" : "-"}</td>
                                      </tr>
                                    );
                                  })
                                )}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}

                      <div className="inbox-actions">
                        <button type="button" onClick={() => setActiveTab("compare")}>Compare suppliers</button>
                        <button type="button" onClick={() => {
                          setSelectedCatalogSupplier(supplierKey(selectedInboxThread.supplier_name, selectedInboxThread.email_domain));
                          setSelectedCatalogEmailId(selectedInboxThread.id);
                          setActiveTab("catalogs");
                        }}>View full catalogue</button>
                        <button type="button" onClick={() => setActiveTab("assistant")}>Ask AI</button>
                      </div>
                    </>
                  ) : (
                    <div className="inbox-empty-state">Pick a supplier to view the extracted catalogue details.</div>
                  )}
                </section>
              </div>
            </>
          )}
          {activeTab === "catalogs" && (
            <section className="catalog-window">
              {selectedCatalog ? (
                <>
                  <div className="catalog-topline">
                    <button type="button" onClick={() => setActiveTab("suppliers")}>Suppliers</button>
                    <span>{selectedCatalog.supplier_name} {activeCatalogEmail ? `- ${formatDDMMYY(activeCatalogEmail.received_at)}` : ""}</span>
                  </div>

                  <div className="catalog-supplier-head" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
                    <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
                      <div className="supplier-badge">{supplierInitials(selectedCatalog.supplier_name)}</div>
                      <div>
                        <h2>{selectedCatalog.supplier_name}</h2>
                        {activeCatalogEmail ? (
                          <p>{activeCatalogEmail.subject || "Catalogue email"} — {emailItemsCount} items — received {formatDDMMYY(activeCatalogEmail.received_at)}</p>
                        ) : (
                          <p>{selectedCatalog.item_count} items total</p>
                        )}
                      </div>
                    </div>
                    {supplierEmails.length > 1 && (
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <span style={{ fontSize: "13px", fontWeight: 600, color: "#4f927f" }}>Catalogue Date:</span>
                        <select
                          value={selectedCatalogEmailId || ""}
                          onChange={(event) => setSelectedCatalogEmailId(event.target.value || null)}
                          style={{
                            padding: "6px 12px",
                            borderRadius: "6px",
                            border: "1px solid var(--line)",
                            background: "#fff",
                            fontSize: "13px",
                            fontWeight: 500,
                            color: "var(--text)",
                            cursor: "pointer",
                            outline: "none",
                          }}
                        >
                          <option value="">All catalogues</option>
                          {supplierEmails.map((email) => (
                            <option key={email.id} value={email.id}>
                              {formatDDMMYY(email.received_at)}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                  </div>

                  <div className="catalog-controls">
                    <label className="catalog-search">
                      <Search size={16} />
                      <input value={catalogSearch} onChange={(event) => setCatalogSearch(event.target.value)} placeholder="Search ingredients..." />
                    </label>
                    <div className="catalog-filter-tabs">
                      <button className={catalogFilter === "all" ? "active" : ""} type="button" onClick={() => setCatalogFilter("all")}>All ({emailItemsCount})</button>
                      <button className={catalogFilter === "best" ? "active" : ""} type="button" onClick={() => setCatalogFilter("best")}>Best deals</button>
                      <button className={catalogFilter === "low-stock" ? "active" : ""} type="button" onClick={() => setCatalogFilter("low-stock")}>Low stock</button>
                    </div>
                  </div>

                  <div className="catalog-table-wrap">
                    <table className="catalog-table">
                      <thead>
                        <tr>
                          <th>#</th>
                          <th>Ingredient</th>
                          <th className="specification-header">Specification</th>
                          <th>Price/unit</th>
                          <th>Qty avail.</th>
                          <th>Lead Time</th>
                          <th>MOQ</th>
                          <th>Date</th>
                          <th>Certificates</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedCatalogItems.length === 0 ? (
                          <tr>
                            <td colSpan={10}>No catalogue items match this filter.</td>
                          </tr>
                        ) : selectedCatalogItems.map((item, index) => {
                          const bestPrice = Math.min(...selectedCatalog.items.map((row) => safePrice(row.price_per_unit, row.currency)));
                          const minQty = Math.min(...selectedCatalog.items.map((row) => safeQty(row.available_qty)));
                          const status = safePrice(item.price_per_unit, item.currency) <= bestPrice * 1.08
                            ? "Best price"
                            : safeQty(item.available_qty) <= minQty * 1.35
                              ? "Low stock"
                              : "Good";
                          const rowKey = `${item.supplier_name || selectedCatalog.supplier_name}-${item.ingredient_name}-${index}`;
                          const expanded = Boolean(expandedCatalogRows[rowKey]);
                          return (
                            <tr key={rowKey}>
                              <td>{index + 1}</td>
                              <td className="two-line-cell">
                                <button
                                  className="expandable-item-button"
                                  type="button"
                                  onClick={() => setExpandedCatalogRows((current) => ({ ...current, [rowKey]: !current[rowKey] }))}
                                >
                                  <span>{renderItemName(item)}</span>
                                </button>
                                {expanded && (
                                  <div className="expanded-supplier-inline">
                                    <span><b>Supplier:</b> <strong>{displayText(item.supplier_name || selectedCatalog.supplier_name)}</strong></span>
                                    <span><b>Email:</b> <strong>{displayText(item.email_domain || selectedCatalog.email_domain)}</strong></span>
                                    <span><b>Country:</b> <strong>{displayText(item.country || selectedCatalog.country || "Unknown")}</strong></span>
                                  </div>
                                )}
                              </td>
                              <td className="two-line-cell specification-cell">{displaySpecification(item)}</td>
                              <td>{displayPrice(item)}</td>
                              <td>{displayQuantity(item)}</td>
                              <td>{displayLeadTime(item)}</td>
                              <td>{displayMoq(item)}</td>
                              <td>{formatDDMMYY(item.received_at)}</td>
                              <td>{renderCertificatesCell(item)}</td>
                              <td><span className={`catalog-status ${status === "Low stock" ? "warning" : status === "Best price" ? "best" : ""}`}>{status}</span></td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <div className="compare-empty">No supplier catalogue available.</div>
              )}
            </section>
          )}

          {activeTab === "analysis" && (
            <>
              <header className="topbar">
                <h2>Analysis</h2>
              </header>
              <div className="metrics">
                <article>
                  <span>Active Suppliers</span>
                  <strong>{inboxThreads.length}</strong>
                </article>
                <article>
                  <span>Catalogue Items</span>
                  <strong>{supplierRows.length}</strong>
                </article>
              </div>
            </>
          )}

          {activeTab === "compare" && (
            <section className="compare-window">
              <div className="compare-toolbar" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <h2 style={{ margin: 0, fontSize: "22px", fontWeight: 600, color: "#092f28" }}>Compare</h2>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "20px" }}>
                  <div className="compare-search-group">
                    <span>Comparing:</span>
                    <div className="compare-search-wrap">
                      <label className="compare-search">
                        <Search size={16} />
                        <input
                          value={compareIngredient}
                          onBlur={() => globalThis.setTimeout(() => setCompareSearchFocused(false), 180)}
                          onChange={(event) => { setCompareIngredient(event.target.value); setSelectedCompareIngredient(""); }}
                          onFocus={() => setCompareSearchFocused(true)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") {
                              event.preventDefault();
                              const query = compareIngredient.trim();
                              if (query) {
                                setSelectedCompareIngredient(query);
                                setCompareSearchFocused(false);
                              }
                            }
                          }}
                          placeholder="Search ingredient"
                        />
                      </label>
                      {compareSearchFocused && compareSuggestions.length > 0 && (
                        <div className="compare-suggestions">
                          {compareSuggestions.map((ingredient) => (
                            <button key={ingredient} type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => { setCompareIngredient(ingredient); setSelectedCompareIngredient(ingredient); setCompareSearchFocused(false); }}>{ingredient}</button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                  <label className="compare-sort">
                    <span>Sort by</span>
                    <select value={compareSort} onChange={(event) => setCompareSort(event.target.value as CompareSort)}>
                      <option value="best-value">Best value</option>
                      <option value="highest-qty">Highest qty</option>
                      <option value="lowest-price">Lowest price</option>
                    </select>
                  </label>
                </div>
              </div>

              {supplierLoading ? (
                <div className="compare-empty">Loading supplier comparison data...</div>
              ) : supplierError ? (
                <div className="compare-empty">{supplierError}</div>
              ) : !selectedCompareIngredient.trim() ? (
                <div className="compare-empty">Select an ingredient from suggestions or press Enter to compare.</div>
              ) : compareData.rows.length === 0 ? (
                <div className="compare-empty">No matching ingredients found.</div>
              ) : (
                <section className="compare-table-panel">
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>#</th>
                            <th>Item</th>
                            <th className="specification-header">Specification</th>
                            <th>Price/Unit</th>
                            <th>Available Qty</th>
                            <th>Lead Time</th>
                            <th>MOQ</th>
                            <th>Date</th>
                            <th>Certifications</th>
                          </tr>
                        </thead>
                        <tbody>
                          {compareData.rows.length === 0 ? (
                            <tr>
                              <td colSpan={9}>Only top suppliers found for this ingredient.</td>
                            </tr>
                          ) : compareData.rows.map((row, index) => {
                            const rowKey = comparisonRowKey(row as Record<string, unknown>, index);
                            const expanded = Boolean(expandedCompareRows[rowKey]);
                            return (
                              <tr key={rowKey}>
                                <td>{index + 1}</td>
                                <td className="two-line-cell">
                                  <button
                                    className="expandable-item-button"
                                    type="button"
                                    onClick={() => setExpandedCompareRows((current) => ({ ...current, [rowKey]: !current[rowKey] }))}
                                  >
                                    <span>{renderItemName(row)}</span>
                                  </button>
                                  {expanded && (
                                    <div className="expanded-supplier-inline">
                                      <span><b>Supplier:</b> <strong>{displayText(row.supplier_name)}</strong></span>
                                      <span><b>Email:</b> <strong>{displayText(row.email_domain)}</strong></span>
                                      <span><b>Country:</b> <strong>{displayText(row.country || "Unknown")}</strong></span>
                                    </div>
                                  )}
                                </td>
                                <td className="two-line-cell specification-cell">{displaySpecification(row)}</td>
                                <td>{displayPrice(row)}</td>
                                <td>{displayQuantity(row)}</td>
                                <td>{displayLeadTime(row)}</td>
                                <td>{displayMoq(row)}</td>
                                <td>{formatDDMMYY(row.received_at)}</td>
                                <td>{renderCertificatesCell(row)}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                </section>
              )}
            </section>
          )}



          {activeTab === "assistant" && (
            <>
              <div style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "18px 20px",
                borderRadius: "10px",
                border: "1px solid var(--line)",
                background: "var(--panel)",
                marginBottom: "24px"
              }}>
                <h2 style={{ margin: 0, fontSize: "22px", fontWeight: 600, color: "#092f28" }}>AI Assistant</h2>
              </div>
              <section className="results-panel">
                <div className="panel-title">
                  <Search size={18} />
                  <h2>Query Results</h2>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Item</th>
                        <th className="specification-header">Specification</th>
                        <th>Price/Unit</th>
                        <th>Qty</th>
                        <th>Lead Time</th>
                        <th>MOQ</th>
                        <th>Date</th>
                        <th>Certifications</th>
                      </tr>
                    </thead>
                    <tbody>
                      {assistantRows.length === 0 ? (
                        <tr>
                          <td colSpan={9}>Results appear after ProcuraAI returns supplier data.</td>
                        </tr>
                      ) : (
                        assistantRows.map((row, index) => {
                          const rowKey = comparisonRowKey(row, index);
                          const expanded = Boolean(expandedAssistantRows[rowKey]);
                          return (
                            <tr key={rowKey}>
                              <td>{index + 1}</td>
                              <td className="two-line-cell">
                                <button
                                  className="expandable-item-button"
                                  type="button"
                                  onClick={() => setExpandedAssistantRows((current) => ({ ...current, [rowKey]: !current[rowKey] }))}
                                >
                                  <span>{renderItemName(row)}</span>
                                </button>
                                {expanded && (
                                  <div className="expanded-supplier-inline">
                                    <span><b>Supplier:</b> <strong>{displayText(row.supplier_name)}</strong></span>
                                    <span><b>Email:</b> <strong>{displayText(row.email_domain)}</strong></span>
                                    <span><b>Country:</b> <strong>{displayText((row as any).country || "Unknown")}</strong></span>
                                  </div>
                                )}
                              </td>
                              <td className="two-line-cell specification-cell">{displaySpecification(row)}</td>
                              <td>{displayPrice(row as SupplierItem)}</td>
                              <td>{displayQuantity(row as SupplierItem)}</td>
                              <td>{!isMissingDisplayValue(row.lead_time_text) ? String(row.lead_time_text) : (row.lead_time_days != null ? `${row.lead_time_days} days` : "-")}</td>
                              <td>{!isMissingDisplayValue(row.moq_display) ? String(row.moq_display) : (row.moq != null ? `${formatQuantity(Number(row.moq))} ${String(row.unit ?? "")}` : "-")}</td>
                              <td>{formatDDMMYY(row.received_at as string)}</td>
                              <td>{renderCertificatesCell(row)}</td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}


          {activeTab === "settings" && (
            <>
              <div className="settings-container" style={{
                display: "flex",
                flexDirection: "row",
                height: "calc(100vh - var(--navbar-height) - 48px)",
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
                    { id: "email", label: "Supplier Connection", icon: <Sliders size={16} /> },
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
                  {/* PROFILE TAB */}
                  {settingsActiveTab === "profile" && authUser && (
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
                                setEditName(authUser.name);
                                setEditOrganisation(authUser.organisation || "");
                                setIsEditingProfile(true);
                                setProfileError(null);
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
                                disabled={isSavingProfile}
                                style={{
                                  background: "var(--accent)",
                                  color: "#fff",
                                  border: "none",
                                  padding: "4px 12px",
                                  borderRadius: "6px",
                                  fontSize: "12px",
                                  fontWeight: 600,
                                  cursor: isSavingProfile ? "not-allowed" : "pointer",
                                  opacity: isSavingProfile ? 0.7 : 1,
                                }}
                              >
                                {isSavingProfile ? "Saving..." : "Save"}
                              </button>
                              <button
                                onClick={() => setIsEditingProfile(false)}
                                disabled={isSavingProfile}
                                style={{
                                  background: "transparent",
                                  color: "var(--muted)",
                                  border: "1px solid var(--line)",
                                  padding: "4px 12px",
                                  borderRadius: "6px",
                                  fontSize: "12px",
                                  fontWeight: 600,
                                  cursor: isSavingProfile ? "not-allowed" : "pointer",
                                }}
                              >
                                Cancel
                              </button>
                            </div>
                          )}
                        </div>

                        {profileError && (
                          <div style={{
                            background: "#fdf2f2",
                            border: "1px solid #fde8e8",
                            borderRadius: "8px",
                            padding: "10px 14px",
                            marginBottom: "16px",
                            color: "#9b1c1c",
                            fontSize: "13px",
                          }}>
                            {profileError}
                          </div>
                        )}

                        <div style={{ background: "#fff", border: "1px solid var(--line)", borderRadius: "10px", padding: "0 20px" }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 0", borderBottom: "1px solid var(--line)" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "16px", minWidth: 0, flex: 1 }}>
                              <div className="user-avatar" style={{ width: "48px", height: "48px", fontSize: "18px", flexShrink: 0, boxShadow: "none" }}>
                                {userInitials(isEditingProfile ? editName : authUser.name, authUser.email)}
                              </div>
                              <div style={{ minWidth: 0, flex: 1, maxWidth: "400px" }}>
                                {!isEditingProfile ? (
                                  <>
                                    <strong style={{ display: "block", fontSize: "15px", color: "var(--ink)" }}>{authUser.name}</strong>
                                    <span style={{ fontSize: "13.0px", color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", display: "block", marginTop: "2px" }}>{authUser.email}</span>
                                  </>
                                ) : (
                                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                                    <input
                                      type="text"
                                      value={editName}
                                      onChange={(e) => setEditName(e.target.value)}
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
                                      disabled={isSavingProfile}
                                    />
                                    <span style={{ fontSize: "12.0px", color: "var(--muted)", display: "block" }}>{authUser.email}</span>
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
                              {authUser.role}
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
                              {authUser.organisation || "MediCORE Central"}
                            </span>
                          </div>
                        </div>
                      </div>


                    </div>
                  )}

                  {/* SUPPLIER CONNECTION TAB */}
                  {settingsActiveTab === "email" && (
                    <div style={{ display: "flex", flexDirection: "column", gap: "32px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: "18px", alignItems: "flex-start", flexWrap: "wrap", borderBottom: "1px solid var(--line)", paddingBottom: "24px" }}>
                        <div>
                          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                            <h2 style={{ margin: 0, fontSize: "22px", fontWeight: 600, color: "#092f28", letterSpacing: "-0.3px" }}>Supplier Connection</h2>
                            <span
                              onMouseEnter={() => setVisibleGuides(p => ({ ...p, email_tab_desc: true }))}
                              onMouseLeave={() => setVisibleGuides(p => ({ ...p, email_tab_desc: false }))}
                              style={{ position: "relative", display: "inline-flex", alignItems: "center", color: "var(--muted)", cursor: "default", marginTop: "4px" }}
                            >
                              <Info size={16} />
                              {visibleGuides.email_tab_desc && (
                                <span className="settings-tooltip centered" style={{ width: "240px" }}>
                                  Configure email sync connections, define ingestion approaches, and manage supplier validation filters.
                                </span>
                              )}
                            </span>
                          </div>
                        </div>
                      </div>



                      {/* Add/Edit Account Form Panel */}
                      {addAccountExpanded && (
                        <div style={{
                          padding: "24px",
                          borderRadius: "10px",
                          background: "#fff",
                          border: "1px solid var(--accent)",
                          boxShadow: "0 4px 24px rgba(15, 122, 95, 0.08)",
                          display: "flex",
                          flexDirection: "column",
                          gap: "20px",
                          position: "relative"
                        }}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                            <h3 style={{ margin: 0, fontSize: "18px", fontWeight: 700, color: "#092f28" }}>
                              {editingAccountId ? "Edit Mailbox Filters & Settings" : "Connect New Supplier Inbox"}
                            </h3>
                            <button
                              type="button"
                              onClick={resetAddAccountForm}
                              style={{
                                background: "rgba(0,0,0,0.05)",
                                border: "none",
                                borderRadius: "50%",
                                width: "28px",
                                height: "28px",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                cursor: "pointer",
                                color: "var(--muted)",
                                transition: "all 0.2s"
                              }}
                            >
                              <X size={16} />
                            </button>
                          </div>

                          {/* Setup Steps Tabs */}
                          {!editingAccountId && (
                            <div style={{ display: "flex", gap: "16px", borderBottom: "1px solid var(--line)", paddingBottom: "4px" }}>
                              {[
                                { step: 1, label: "1. Connection Credentials" },
                                { step: 3, label: "2. Rules & Filters" }
                              ].map((s) => (
                                <button
                                  key={s.step}
                                  type="button"
                                  onClick={() => setSetupStep(s.step)}
                                  style={{
                                    background: "none",
                                    border: "none",
                                    borderBottom: setupStep === s.step ? "3px solid var(--accent)" : "3px solid transparent",
                                    padding: "8px 4px 12px",
                                    color: setupStep === s.step ? "var(--accent)" : "var(--muted)",
                                    fontWeight: setupStep === s.step ? 700 : 500,
                                    fontSize: "14px",
                                    cursor: "pointer",
                                    transition: "all 0.2s"
                                  }}
                                >
                                  {s.label}
                                </button>
                              ))}
                            </div>
                          )}

                          {/* Step 1: Credentials Form */}
                          {(editingAccountId || setupStep === 1) && (
                            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px" }}>
                              <label style={{ display: "flex", flexDirection: "column", gap: "8px", gridColumn: "span 2" }}>
                                <span style={{ fontSize: "13.5px", fontWeight: 600, color: "var(--ink)" }}>Provider Type</span>
                                <select
                                  value={newAccountProvider}
                                  onChange={(e) => {
                                    setNewAccountProvider(e.target.value);
                                    if (e.target.value === "Gmail") {
                                      setNewAccountImapHost("imap.gmail.com");
                                      setNewAccountImapPort(993);
                                    }
                                  }}
                                  disabled={!!editingAccountId}
                                  style={{ padding: "11px 14px", borderRadius: "8px", border: "1px solid var(--line)", background: "#fff", fontSize: "14px", outline: "none" }}
                                >
                                  <option value="Gmail">Gmail</option>
                                  <option value="Custom">Custom IMAP Server</option>
                                </select>
                              </label>

                              <label style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                                <span style={{ fontSize: "13.5px", fontWeight: 600, color: "var(--ink)" }}>IMAP Username / Email Address</span>
                                <input
                                  type="email"
                                  value={newAccountEmail}
                                  onChange={(e) => setNewAccountEmail(e.target.value)}
                                  disabled={!!editingAccountId}
                                  placeholder="e.g. suppliers@company.com"
                                  style={{ padding: "11px 14px", borderRadius: "8px", border: "1px solid var(--line)", background: editingAccountId ? "#f7fafc" : "#fff", fontSize: "14px", outline: "none" }}
                                />
                              </label>

                              <label style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                                <span style={{ fontSize: "13.5px", fontWeight: 600, color: "var(--ink)" }}>
                                  {editingAccountId ? "New App Password (leave blank to keep)" : "Gmail App Password"}
                                </span>
                                <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
                                  <input
                                    type={showSettingsPassword ? "text" : "password"}
                                    value={newAccountPassword}
                                    onChange={(e) => setNewAccountPassword(e.target.value)}
                                    placeholder={editingAccountId ? "••••••••••••••••" : "16-character Google app password"}
                                    style={{
                                      padding: "11px 44px 11px 14px",
                                      borderRadius: "8px",
                                      border: "1px solid var(--line)",
                                      fontSize: "14px",
                                      outline: "none",
                                      width: "100%"
                                    }}
                                  />
                                  <button
                                    type="button"
                                    onClick={() => setShowSettingsPassword(!showSettingsPassword)}
                                    style={{
                                      position: "absolute",
                                      right: "12px",
                                      top: "50%",
                                      transform: "translateY(-50%)",
                                      background: "none",
                                      border: "none",
                                      color: "#66736d",
                                      cursor: "pointer",
                                      display: "flex",
                                      alignItems: "center",
                                      justifyContent: "center",
                                      padding: "4px",
                                      zIndex: 2,
                                    }}
                                    aria-label={showSettingsPassword ? "Hide password" : "Show password"}
                                  >
                                    {showSettingsPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                                  </button>
                                </div>
                              </label>

                              {newAccountProvider === "Custom" && (
                                <>
                                  <label style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                                    <span style={{ fontSize: "13.5px", fontWeight: 600, color: "var(--ink)" }}>IMAP Server Host</span>
                                    <input
                                      type="text"
                                      value={newAccountImapHost}
                                      onChange={(e) => setNewAccountImapHost(e.target.value)}
                                      placeholder="e.g. imap.example.com"
                                      style={{ padding: "11px 14px", borderRadius: "8px", border: "1px solid var(--line)", fontSize: "14px", outline: "none" }}
                                    />
                                  </label>

                                  <label style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                                    <span style={{ fontSize: "13.5px", fontWeight: 600, color: "var(--ink)" }}>IMAP Server Port</span>
                                    <input
                                      type="number"
                                      value={newAccountImapPort}
                                      onChange={(e) => setNewAccountImapPort(Number(e.target.value))}
                                      placeholder="e.g. 993"
                                      style={{ padding: "11px 14px", borderRadius: "8px", border: "1px solid var(--line)", fontSize: "14px", outline: "none" }}
                                    />
                                  </label>
                                </>
                              )}

                              {!editingAccountId && (
                                <div style={{ gridColumn: "span 2", display: "flex", gap: "12px", marginTop: "12px" }}>
                                  <button
                                    type="button"
                                    onClick={testConnection}
                                    disabled={testingConnection}
                                    style={{
                                      padding: "11px 20px",
                                      border: "1px solid var(--accent)",
                                      borderRadius: "8px",
                                      background: "transparent",
                                      color: "var(--accent)",
                                      fontWeight: 600,
                                      fontSize: "13.5px",
                                      cursor: "pointer",
                                      display: "flex",
                                      alignItems: "center",
                                      gap: "8px",
                                      transition: "all 0.2s"
                                    }}
                                  >
                                    {testingConnection && <Loader2 className="animate-spin" size={14} />}
                                    {testingConnection ? "Verifying Host..." : "Test Connection Setup"}
                                  </button>

                                  <button
                                    type="button"
                                    onClick={() => setSetupStep(3)}
                                    disabled={!testResult?.success}
                                    style={{
                                      padding: "11px 20px",
                                      borderRadius: "8px",
                                      background: testResult?.success ? "var(--accent)" : "#cbd5e0",
                                      color: "#fff",
                                      border: "none",
                                      fontWeight: 600,
                                      fontSize: "13.5px",
                                      cursor: testResult?.success ? "pointer" : "not-allowed",
                                      display: "flex",
                                      alignItems: "center",
                                      gap: "8px",
                                      transition: "all 0.2s"
                                    }}
                                  >
                                    Continue to Ingestion Rules <ArrowRight size={14} />
                                  </button>
                                </div>
                              )}
                            </div>
                          )}

                          {/* Step 3: Ingestion Rules & Filters Form */}
                          {(editingAccountId || setupStep === 3) && (
                            <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
                              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                                <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                  <h4 style={{ margin: 0, fontSize: "15px", fontWeight: 700, color: "var(--accent)" }}>
                                    Ingestion Gatekeeper Filters
                                  </h4>
                                  <span
                                    onMouseEnter={() => setVisibleGuides(p => ({ ...p, gatekeeper_filters_desc: true }))}
                                    onMouseLeave={() => setVisibleGuides(p => ({ ...p, gatekeeper_filters_desc: false }))}
                                    style={{ position: "relative", display: "inline-flex", alignItems: "center", color: "var(--muted)", cursor: "default" }}
                                  >
                                    <Info size={14} />
                                    {visibleGuides.gatekeeper_filters_desc && (
                                      <span className="settings-tooltip centered" style={{ width: "220px" }}>
                                        Fine-tune which messages inside the target mailbox get processed into catalogue sheets.
                                      </span>
                                    )}
                                  </span>
                                </div>
                              </div>

                              <div style={{ display: "flex", flexDirection: "column", gap: "16px", padding: "20px", background: "rgba(0,0,0,0.015)", borderRadius: "12px", border: "1px solid var(--line)" }}>
                                {/* Toggle 1: Require PDF Attachment */}
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                  <div style={{ paddingRight: "16px" }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                      <strong style={{ display: "block", fontSize: "14px", color: "var(--ink)" }}>Require PDF Attachment</strong>
                                      <span
                                        onMouseEnter={() => setVisibleGuides(p => ({ ...p, email_require_attachment: true }))}
                                        onMouseLeave={() => setVisibleGuides(p => ({ ...p, email_require_attachment: false }))}
                                        style={{ position: "relative", display: "inline-flex", alignItems: "center", color: "var(--muted)", cursor: "default" }}
                                      >
                                        <Info size={14} />
                                        {visibleGuides.email_require_attachment && (
                                          <span className="settings-tooltip centered" style={{ width: "220px" }}>
                                            Skip emails that do not contain parsed attachment files. (Turn off to parse text bodies)
                                          </span>
                                        )}
                                      </span>
                                    </div>
                                  </div>
                                  <ToggleSwitch checked={filterRequireAttachment} onChange={setFilterRequireAttachment} />
                                </div>

                                <hr style={{ margin: "4px 0", border: "none", borderTop: "1px solid var(--line)" }} />

                                {/* Toggle 2: Auto-Skip Bulk/Promotion */}
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                  <div style={{ paddingRight: "16px" }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                      <strong style={{ display: "block", fontSize: "14px", color: "var(--ink)" }}>Auto-Skip Bulk / Promotion Emails</strong>
                                      <span
                                        onMouseEnter={() => setVisibleGuides(p => ({ ...p, email_skip_promotions: true }))}
                                        onMouseLeave={() => setVisibleGuides(p => ({ ...p, email_skip_promotions: false }))}
                                        style={{ position: "relative", display: "inline-flex", alignItems: "center", color: "var(--muted)", cursor: "default" }}
                                      >
                                        <Info size={14} />
                                        {visibleGuides.email_skip_promotions && (
                                          <span className="settings-tooltip centered" style={{ width: "220px" }}>
                                            Skips bulk emails, newsletters, or unsubscribable list messages.
                                          </span>
                                        )}
                                      </span>
                                    </div>
                                  </div>
                                  <ToggleSwitch checked={filterSkipPromotions} onChange={setFilterSkipPromotions} />
                                </div>

                                <hr style={{ margin: "4px 0", border: "none", borderTop: "1px solid var(--line)" }} />

                                {/* Input 1: Subject Keywords */}
                                <label style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                    <span style={{ fontSize: "13.5px", fontWeight: 600, color: "var(--ink)" }}>Subject Keyword Restriction List</span>
                                    <span
                                      onMouseEnter={() => setVisibleGuides(p => ({ ...p, email_subject_keywords: true }))}
                                      onMouseLeave={() => setVisibleGuides(p => ({ ...p, email_subject_keywords: false }))}
                                      style={{ position: "relative", display: "inline-flex", alignItems: "center", color: "var(--muted)", cursor: "default" }}
                                    >
                                      <Info size={14} />
                                      {visibleGuides.email_subject_keywords && (
                                        <span className="settings-tooltip centered" style={{ width: "220px" }}>
                                          Only sync emails containing these keywords in the subject (leave blank for all). Separated by commas.
                                        </span>
                                      )}
                                    </span>
                                  </div>
                                  <input
                                    type="text"
                                    value={filterSubjectKeywords}
                                    onChange={(e) => setFilterSubjectKeywords(e.target.value)}
                                    placeholder="e.g. catalog, price, inventory"
                                    style={{ padding: "11px 14px", borderRadius: "8px", border: "1px solid var(--line)", background: "#fff", fontSize: "13.5px", outline: "none" }}
                                  />
                                </label>

                                <hr style={{ margin: "4px 0", border: "none", borderTop: "1px solid var(--line)" }} />

                                {/* Input 2: Sender Keywords */}
                                <label style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                    <span style={{ fontSize: "13.5px", fontWeight: 600, color: "var(--ink)" }}>Sender Address Restriction List</span>
                                    <span
                                      onMouseEnter={() => setVisibleGuides(p => ({ ...p, email_sender_keywords: true }))}
                                      onMouseLeave={() => setVisibleGuides(p => ({ ...p, email_sender_keywords: false }))}
                                      style={{ position: "relative", display: "inline-flex", alignItems: "center", color: "var(--muted)", cursor: "default" }}
                                    >
                                      <Info size={14} />
                                      {visibleGuides.email_sender_keywords && (
                                        <span className="settings-tooltip centered" style={{ width: "220px" }}>
                                          Only process emails from senders containing these letters/words (leave blank for all).
                                        </span>
                                      )}
                                    </span>
                                  </div>
                                  <input
                                    type="text"
                                    value={filterSenderKeywords}
                                    onChange={(e) => setFilterSenderKeywords(e.target.value)}
                                    placeholder="e.g. orders, sales, billing"
                                    style={{ padding: "11px 14px", borderRadius: "8px", border: "1px solid var(--line)", background: "#fff", fontSize: "13.5px", outline: "none" }}
                                  />
                                </label>
                              </div>

                              <div style={{ display: "flex", gap: "12px", justifyContent: "flex-end", marginTop: "8px" }}>
                                <button
                                  type="button"
                                  onClick={resetAddAccountForm}
                                  style={{
                                    padding: "10px 18px",
                                    border: "1px solid var(--line)",
                                    borderRadius: "8px",
                                    background: "transparent",
                                    color: "var(--ink)",
                                    fontSize: "13.5px",
                                    fontWeight: 600,
                                    cursor: "pointer"
                                  }}
                                >
                                  Cancel
                                </button>
                                <button
                                  type="button"
                                  onClick={saveAccount}
                                  disabled={savingAccount}
                                  style={{
                                    padding: "10px 20px",
                                    background: "var(--accent)",
                                    color: "#fff",
                                    border: "none",
                                    borderRadius: "8px",
                                    fontSize: "13.5px",
                                    fontWeight: 700,
                                    cursor: "pointer",
                                    display: "flex",
                                    alignItems: "center",
                                    gap: "8px",
                                    transition: "all 0.2s"
                                  }}
                                >
                                  {savingAccount && <Loader2 className="animate-spin" size={14} />}
                                  {editingAccountId ? "Update Account & Filters" : "Connect Account"}
                                </button>
                              </div>
                            </div>
                          )}

                          {testResult && (
                            <div style={{
                              padding: "14px 18px",
                              borderRadius: "8px",
                              fontSize: "13.5px",
                              lineHeight: "1.45",
                              background: testResult.success ? "rgba(49, 151, 149, 0.08)" : "rgba(229, 62, 62, 0.08)",
                              color: testResult.success ? "#2c7a7b" : "#c53030",
                              border: `1px solid ${testResult.success ? "rgba(49, 151, 149, 0.18)" : "rgba(229, 62, 62, 0.18)"}`
                            }}>
                              {testResult.message}
                            </div>
                          )}
                        </div>
                      )}



                      {/* Ingestion Mode Choice */}
                      <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                        <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: "#092f28", textTransform: "uppercase", letterSpacing: "0.05em" }}>Email Ingestion Mode</h3>
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "20px" }}>
                          {/* Approach 1: Gmail Label Ingestion */}
                          <div
                            role="button"
                            tabIndex={0}
                            onClick={() => setLocalApproach("approach_1")}
                            onKeyDown={(e) => e.key === "Enter" && setLocalApproach("approach_1")}
                            style={{
                              padding: "24px",
                              borderRadius: "12px",
                              border: `2px solid ${localApproach === "approach_1" ? "var(--accent)" : "var(--line)"}`,
                              background: localApproach === "approach_1" ? "linear-gradient(180deg, rgba(15, 122, 95, 0.05), #fff)" : "#fff",
                              color: "var(--ink)",
                              cursor: "pointer",
                              transition: "all 0.2s ease",
                              display: "flex",
                              flexDirection: "column",
                              gap: "12px",
                              textAlign: "left",
                              boxShadow: localApproach === "approach_1" ? "0 8px 20px rgba(15, 122, 95, 0.06)" : "0 2px 4px rgba(0,0,0,0.01)",
                              outline: "none"
                            }}
                          >
                            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
                              <span style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
                                <Mail size={18} color="var(--accent)" />
                                <strong style={{ fontSize: "16px", color: localApproach === "approach_1" ? "var(--accent)" : "#092f28" }}>Gmail Label Ingestion</strong>
                              </span>
                              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                <span
                                  onMouseEnter={() => setVisibleGuides(p => ({ ...p, approach_1_desc: true }))}
                                  onMouseLeave={() => setVisibleGuides(p => ({ ...p, approach_1_desc: false }))}
                                  onClick={(e) => e.stopPropagation()}
                                  style={{ position: "relative", display: "inline-flex", alignItems: "center", color: "var(--muted)", cursor: "default" }}
                                >
                                  <Info size={14} />
                                  {visibleGuides.approach_1_desc && (
                                    <span className="settings-tooltip right-aligned" style={{ width: "200px" }}>
                                      Only messages tagged with the Gmail label <strong style={{ color: "var(--accent)" }}>suppliers</strong> are parsed. Best for manual control.
                                    </span>
                                  )}
                                </span>
                                <div style={{
                                  width: "20px",
                                  height: "20px",
                                  borderRadius: "50%",
                                  border: `2px solid ${localApproach === "approach_1" ? "var(--accent)" : "var(--muted)"}`,
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  flexShrink: 0
                                }}>
                                  {localApproach === "approach_1" && <div style={{ width: "10px", height: "10px", borderRadius: "50%", background: "var(--accent)" }} />}
                                </div>
                              </div>
                            </div>
                            <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", color: "var(--accent)", fontSize: "12.5px", fontWeight: 700 }}>
                              <Sliders size={13} /> Explicit mailbox scope
                            </span>
                          </div>

                          {/* Approach 2: Trusted Supplier Approval */}
                          <div
                            role="button"
                            tabIndex={0}
                            onClick={() => setLocalApproach("approach_2")}
                            onKeyDown={(e) => e.key === "Enter" && setLocalApproach("approach_2")}
                            style={{
                              padding: "24px",
                              borderRadius: "12px",
                              border: `2px solid ${localApproach === "approach_2" ? "var(--accent)" : "var(--line)"}`,
                              background: localApproach === "approach_2" ? "linear-gradient(180deg, rgba(15, 122, 95, 0.05), #fff)" : "#fff",
                              color: "var(--ink)",
                              cursor: "pointer",
                              transition: "all 0.2s ease",
                              display: "flex",
                              flexDirection: "column",
                              gap: "12px",
                              textAlign: "left",
                              boxShadow: localApproach === "approach_2" ? "0 8px 20px rgba(15, 122, 95, 0.06)" : "0 2px 4px rgba(0,0,0,0.01)",
                              outline: "none"
                            }}
                          >
                            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
                              <span style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}>
                                <CheckCircle2 size={18} color="var(--accent)" />
                                <strong style={{ fontSize: "16px", color: localApproach === "approach_2" ? "var(--accent)" : "#092f28" }}>Trusted Supplier Approval</strong>
                              </span>
                              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                <span
                                  onMouseEnter={() => setVisibleGuides(p => ({ ...p, approach_2_desc: true }))}
                                  onMouseLeave={() => setVisibleGuides(p => ({ ...p, approach_2_desc: false }))}
                                  onClick={(e) => e.stopPropagation()}
                                  style={{ position: "relative", display: "inline-flex", alignItems: "center", color: "var(--muted)", cursor: "default" }}
                                >
                                  <Info size={14} />
                                  {visibleGuides.approach_2_desc && (
                                    <span className="settings-tooltip right-aligned" style={{ width: "200px" }}>
                                      Trusted senders ingest automatically. New matching suppliers stay blocked until approved.
                                    </span>
                                  )}
                                </span>
                                <div style={{
                                  width: "20px",
                                  height: "20px",
                                  borderRadius: "50%",
                                  border: `2px solid ${localApproach === "approach_2" ? "var(--accent)" : "var(--muted)"}`,
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  flexShrink: 0
                                }}>
                                  {localApproach === "approach_2" && <div style={{ width: "10px", height: "10px", borderRadius: "50%", background: "var(--accent)" }} />}
                                </div>
                              </div>
                            </div>
                            <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", color: "var(--accent)", fontSize: "12.5px", fontWeight: 700 }}>
                              <CheckCircle2 size={13} /> Approval gate enabled
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Section depending on Ingestion Mode */}
                      {localApproach === "approach_1" ? (
                        <div style={{
                          padding: "20px",
                          background: "#fafafa",
                          border: "1px solid var(--line)",
                          borderRadius: "10px",
                          display: "flex",
                          flexDirection: "column",
                          gap: "12px"
                        }}>
                          <h4 style={{ margin: 0, fontSize: "14px", fontWeight: 700, color: "var(--accent)", display: "flex", alignItems: "center", gap: "8px" }}>
                            <Sliders size={15} /> How to configure Gmail labeling
                          </h4>
                          <ol style={{ margin: 0, paddingLeft: "20px", fontSize: "13.0px", color: "var(--ink)", display: "flex", flexDirection: "column", gap: "8px", lineHeight: "1.5" }}>
                            <li>Open your linked Gmail account in a browser.</li>
                            <li>Go to <strong>Settings</strong> &gt; <strong>Labels</strong>. Scroll down and click <strong>Create a new label</strong>.</li>
                            <li>Enter <strong>suppliers</strong> (all lowercase) as the label name and click Create.</li>
                            <li>Apply this new label to any incoming emails from your suppliers.</li>
                            <li>MediCORE will dynamically sync and analyze catalogs <em>only</em> inside this labeled folder.</li>
                          </ol>
                        </div>
                      ) : (
                        <div style={{
                          display: "flex",
                          flexDirection: "column",
                          gap: "20px",
                          padding: "20px",
                          background: "#fff",
                          border: "1px solid var(--line)",
                          borderRadius: "10px"
                        }}>
                          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                              <label style={{ fontWeight: 600, fontSize: "14px", color: "#092f28", margin: 0 }}>Trusted Supplier Emails / Domains</label>
                              <span
                                onMouseEnter={() => setVisibleGuides(p => ({ ...p, email_trusted_suppliers: true }))}
                                onMouseLeave={() => setVisibleGuides(p => ({ ...p, email_trusted_suppliers: false }))}
                                style={{ position: "relative", display: "inline-flex", alignItems: "center", color: "var(--muted)", cursor: "default" }}
                              >
                                <Info size={14} />
                                {visibleGuides.email_trusted_suppliers && (
                                  <span className="settings-tooltip centered" style={{ width: "240px" }}>
                                    Enter trusted domains or exact emails (separated by commas). Senders matching these will bypass the approval gate entirely.
                                  </span>
                                )}
                              </span>
                            </div>
                            <textarea
                              value={localTrusted}
                              onChange={(e) => setLocalTrusted(e.target.value)}
                              placeholder="e.g. sigmaaldrich.com, orders@pharmacy.com, trustedsupplier.in"
                              rows={3}
                              style={{
                                padding: "10px 12px",
                                borderRadius: "8px",
                                border: "1px solid var(--line)",
                                background: "#fff",
                                fontSize: "13.5px",
                                lineHeight: "1.5",
                                resize: "vertical",
                                fontFamily: "inherit",
                                outline: "none",
                                transition: "border-color 0.15s ease"
                              }}
                            />
                          </div>

                        </div>
                      )}

                      {/* Automation/Polling settings */}
                      <div>
                        <h3 style={{ margin: "0 0 16px 0", fontSize: "12px", fontWeight: 600, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Background Sync & Automation</h3>
                        <div style={{
                          padding: "0 20px",
                          borderRadius: "10px",
                          background: "#fff",
                          border: "1px solid var(--line)",
                          display: "flex",
                          flexDirection: "column"
                        }}>
                          {/* Row 1: Polling Interval */}
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 0" }}>
                            <div style={{ paddingRight: "24px" }}>
                              <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                <strong style={{ display: "block", fontSize: "14px", color: "var(--ink)" }}>Global Polling Interval</strong>
                                <span
                                  onMouseEnter={() => setVisibleGuides(p => ({ ...p, email_poll_interval: true }))}
                                  onMouseLeave={() => setVisibleGuides(p => ({ ...p, email_poll_interval: false }))}
                                  style={{ position: "relative", display: "inline-flex", alignItems: "center", color: "var(--muted)", cursor: "default" }}
                                >
                                  <Info size={14} />
                                  {visibleGuides.email_poll_interval && (
                                    <span className="settings-tooltip centered" style={{ width: "220px" }}>
                                      Configure how frequently the background sync processes check for new supplier emails.
                                    </span>
                                  )}
                                </span>
                              </div>
                            </div>
                            <select
                              value={localPollInterval}
                              onChange={(e) => setLocalPollInterval(Number(e.target.value))}
                              style={{ padding: "8px 12px", borderRadius: "8px", border: "1px solid var(--line)", background: "#fff", cursor: "pointer", fontSize: "13px", fontWeight: 600, outline: "none", minWidth: "180px" }}
                            >
                              <option value={5}>Every 5 minutes</option>
                              <option value={10}>Every 10 minutes</option>
                              <option value={15}>Every 15 minutes</option>
                              <option value={30}>Every 30 minutes</option>
                              <option value={60}>Every hour</option>
                            </select>
                          </div>
                        </div>

                        {settingsSaveFeedback && (
                          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "12px" }}>
                            <span style={{ fontSize: "13px", background: "rgba(49, 151, 149, 0.1)", color: "#2c7a7b", padding: "6px 14px", borderRadius: "12px", fontWeight: 600 }}>
                              Settings saved
                            </span>
                          </div>
                        )}
                      </div>

                      {/* Save Footer */}
                      <div style={{
                        display: "flex",
                        justifyContent: "flex-end",
                        marginTop: "24px"
                      }}>
                        <button
                          type="button"
                          onClick={() => saveEmailSyncSettings({
                            ingestion_approach: localApproach,
                            trusted_suppliers: localTrusted,
                            poll_interval_minutes: localPollInterval,
                            auto_extract_catalog: true,
                            notify_on_new_catalog: true
                          })}
                          disabled={savingSyncSettings}
                          style={{
                            minHeight: "44px",
                            padding: "0 28px",
                            background: savingSyncSettings ? "rgba(15, 122, 95, 0.65)" : "var(--accent)",
                            color: "#fff",
                            border: "none",
                            borderRadius: "8px",
                            fontWeight: 700,
                            fontSize: "14px",
                            cursor: savingSyncSettings ? "not-allowed" : "pointer",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            gap: "8px",
                            transition: "all 0.2s ease"
                          }}
                        >
                          {savingSyncSettings ? <Loader2 className="animate-spin" size={16} /> : <CheckCircle2 size={16} />}
                          {savingSyncSettings ? "Saving..." : "Save"}
                        </button>
                      </div>
                    </div>
                  )}
                </main>
              </div>
            </>
          )}

          {activeTab === "suppliers" && (
            <section className="supplier-window">
              <div className="supplier-toolbar" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  <h2 style={{ margin: 0, fontSize: "22px", fontWeight: 600, color: "#092f28" }}>Suppliers</h2>
                </div>
                <div className="supplier-controls">
                  <label className="supplier-search">
                    <Search size={16} />
                    <input value={supplierSearch} onChange={(event) => setSupplierSearch(event.target.value)} placeholder="Search suppliers or ingredients..." />
                  </label>
                  <div className="supplier-country-control" ref={supplierCountryFilterRef}>
                    <span>Country</span>
                    <details className="supplier-country-filter" open={supplierCountryOpen}>
                      <summary onClick={(event) => {
                        event.preventDefault();
                        setSupplierCountryOpen((open) => !open);
                      }}>
                        <strong>{selectedSupplierCountries.length ? `${selectedSupplierCountries.length} selected` : "All"}</strong>
                        <ChevronDown size={14} />
                      </summary>
                      <div className="supplier-country-menu">
                        {supplierCountryOptions.length === 0 ? (
                          <span className="supplier-country-empty">No countries</span>
                        ) : supplierCountryOptions.map((country) => (
                          <label key={country} className="supplier-country-option">
                            <input
                              type="checkbox"
                              checked={selectedSupplierCountries.includes(country)}
                              onChange={() => toggleSupplierCountry(country)}
                            />
                            <span>{country}</span>
                            {selectedSupplierCountries.includes(country) && <Check size={14} />}
                          </label>
                        ))}
                        {selectedSupplierCountries.length > 0 && (
                          <button type="button" onClick={() => setSelectedSupplierCountries([])}>
                            Clear
                          </button>
                        )}
                      </div>
                    </details>
                  </div>
                  <label className="supplier-sort">
                    <span>Sort by</span>
                    <select value={supplierSort} onChange={(event) => setSupplierSort(event.target.value as SupplierSort)}>
                      <option value="items">Catalogue items</option>
                      <option value="latest">Latest catalogue</option>
                      <option value="name">Name</option>
                    </select>
                  </label>
                </div>
              </div>

              <div className="supplier-table-panel">
                <table className="supplier-directory-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Supplier</th>
                      <th>Email</th>
                      <th>Items</th>
                      <th>Total qty</th>
                      <th>Date</th>
                      <th>Certifications</th>
                      <th>View catalogue</th>
                    </tr>
                  </thead>
                  <tbody>
                    {supplierLoading ? (
                      <tr><td colSpan={8}>Loading supplier data...</td></tr>
                    ) : supplierError ? (
                      <tr><td colSpan={8}>{supplierError}</td></tr>
                    ) : supplierDirectory.length === 0 ? (
                      <tr><td colSpan={8}>No suppliers match your search.</td></tr>
                    ) : supplierDirectory.map((supplier, index) => (
                      <tr key={supplier.supplier_key}>
                        <td>{index + 1}</td>
                        <td>
                          <div className="supplier-name-cell">
                            <span className="supplier-mini-badge">{supplierInitials(supplier.supplier_name)}</span>
                            <div>
                              <strong>{supplier.supplier_name}</strong>
                            </div>
                          </div>
                        </td>
                        <td>{supplier.email_domain}</td>
                        <td>{supplier.item_count}</td>
                        <td>{formatQuantity(supplier.total_qty)}</td>
                        <td>{formatDDMMYY(supplier.last_catalog_at)}</td>
                        <td>
                          {supplier.certifications ? (
                            <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", justifyContent: "center" }}>
                              {supplier.certifications.split(",").map((cert) => {
                                const trimmed = cert.trim();
                                return (
                                  <span
                                    key={trimmed}
                                    style={{
                                      display: "inline-flex",
                                      alignItems: "center",
                                      background: "rgba(15, 122, 95, 0.06)",
                                      color: "var(--accent)",
                                      fontSize: "11.5px",
                                      fontWeight: 600,
                                      padding: "2px 8px",
                                      borderRadius: "4px",
                                      border: "1px solid rgba(15, 122, 95, 0.12)",
                                      letterSpacing: "0.02em",
                                    }}
                                  >
                                    {trimmed}
                                  </span>
                                );
                              })}
                            </div>
                          ) : (
                            <span style={{ color: "var(--muted)", fontSize: "12px" }}>-</span>
                          )}
                        </td>
                        <td>
                          <button className="table-action-button" type="button" onClick={() => {
                            setSelectedCatalogSupplier(supplier.supplier_key);
                            setSelectedCatalogEmailId(null);
                            setActiveTab("catalogs");
                          }}>View catalogue</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </section>
      </main>

      {certificateModalItems && (
        <div className="certificate-modal-backdrop" role="presentation" onMouseDown={() => setCertificateModalItems(null)}>
          <section className="certificate-modal" role="dialog" aria-modal="true" aria-label="Certificate PDFs" onMouseDown={(event) => event.stopPropagation()}>
            <div className="certificate-modal-head">
              <h2>Certificates</h2>
              <button type="button" onClick={() => setCertificateModalItems(null)} aria-label="Close certificates">
                <X size={16} />
              </button>
            </div>
            <div className="certificate-modal-list">
              {certificateModalItems.map((pdf) => (
                <button
                  key={`${pdf.storage_path || pdf.url}-${pdf.name}`}
                  type="button"
                  onClick={() => {
                    void openCertificatePdf(pdf);
                    setCertificateModalItems(null);
                  }}
                >
                  <FileText size={16} />
                  <span>{pdf.name}</span>
                  <small>{pdf.type || "Certificate"}</small>
                </button>
              ))}
            </div>
          </section>
        </div>
      )}

      {/* Chat Panel */}
      {showAssistantPanel && (
        <aside className="chat-panel">
          <div className="chat-header">
            <h2>ProcuraAI</h2>
            <button
              onClick={handleRefreshChat}
              style={{
                background: "none",
                border: "none",
                color: "var(--muted)",
                cursor: "pointer",
                padding: "6px",
                borderRadius: "6px",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                transition: "all 0.2s ease",
              }}
              title="Refresh Chat"
              type="button"
              className="chat-refresh-button"
            >
              <RefreshCw size={16} />
            </button>
          </div>
          <div className="messages">
            {messages.map((message, index) => (
              <div key={index} className={`message ${message.role}`}>
                {message.text}
              </div>
            ))}

            {messages.length === 1 && (
              <div style={{
                display: "flex",
                flexDirection: "column",
                gap: "10px",
                marginTop: "16px",
                paddingLeft: "4px",
                animation: "fadeInUp 0.6s ease"
              }}>
                <span style={{ fontSize: "11px", fontWeight: 700, color: "var(--accent)", letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: "4px", opacity: 0.8 }}>Suggested Actions</span>
                {exampleQuestions.map((question) => (
                  <button
                    key={question}
                    type="button"
                    onClick={() => sendMessage(question)}
                    style={{
                      padding: "12px 16px",
                      border: "1px solid rgba(15, 122, 95, 0.12)",
                      borderRadius: "12px",
                      background: "linear-gradient(135deg, rgba(15, 122, 95, 0.02) 0%, rgba(15, 122, 95, 0.05) 100%)",
                      color: "#1a3a32",
                      textAlign: "left",
                      cursor: "pointer",
                      fontSize: "13px",
                      fontWeight: 500,
                      lineHeight: "1.4",
                      transition: "all 0.25s cubic-bezier(0.4, 0, 0.2, 1)",
                      boxShadow: "0 2px 6px rgba(15, 122, 95, 0.01)",
                      display: "block",
                      width: "100%",
                      outline: "none"
                    }}
                    className="premium-suggestion-btn"
                  >
                    {question}
                  </button>
                ))}
              </div>
            )}

            {isTypingResponse && (
              <div className="message assistant" style={{ display: "inline-flex", alignItems: "center", gap: "4px", padding: "12px 16px", minWidth: "60px", background: "var(--soft)", border: "1px solid var(--line)" }}>
                <div className="typing-dot" />
                <div className="typing-dot" />
                <div className="typing-dot" />
              </div>
            )}
            <div ref={chatMessagesEndRef} />
          </div>
          <form
            className="composer"
            style={{ borderBottom: "none" }}
            onSubmit={(event) => {
              event.preventDefault();
              sendMessage();
            }}
          >
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="Ask ProcuraAI..."
            />
            <button type="submit" aria-label="Send message">
              <Send size={18} />
            </button>
          </form>
          <div style={{
            fontSize: "11px",
            color: "var(--muted)",
            textAlign: "center",
            padding: "0 18px 12px 18px",
            lineHeight: "1.4",
            letterSpacing: "-0.1px",
            background: "#fff",
            flexShrink: 0
          }}>
            ProcuraAI can make mistakes. Your data is never used to train our model.
          </div>
        </aside>
      )}

      {connectionError && (
        <div className="connection-modal-backdrop">
          <div className="connection-modal">
            <div className="connection-modal-icon">
              <ShieldAlert size={24} />
            </div>
            <h3>Connection Failed</h3>
            <p>{connectionError}</p>
            <div className="connection-modal-actions">
              <button type="button" onClick={() => window.location.reload()}>
                Retry
              </button>
              <button type="button" onClick={() => setConnectionError(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Action Confirmation Modals (Disconnect Account & Delete Catalog Email) */}
      {disconnectAccountConfirmId && (
        <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(15, 33, 28, 0.4)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1100 }}>
          <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "32px", width: "440px", boxShadow: "0 20px 40px rgba(0,0,0,0.1)", textAlign: "center" }}>
            <div style={{ background: "#fef2f2", color: "#ef4444", width: "48px", height: "48px", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 20px auto" }}>
              <ShieldAlert size={24} />
            </div>
            <h3 style={{ fontSize: "18px", fontWeight: 700, color: "#17211c", margin: "0 0 10px 0" }}>Disconnect Inbox</h3>
            <p style={{ fontSize: "14px", color: "#66736d", margin: "0 0 24px 0", lineHeight: 1.5 }}>
              Are you sure you want to disconnect this inbox? MediCORE will completely stop polling and remove all configurations.
            </p>
            <div style={{ display: "flex", gap: "12px" }}>
              <button
                onClick={() => setDisconnectAccountConfirmId(null)}
                disabled={disconnectAccountLoading}
                style={{ flex: 1, padding: "12px", borderRadius: "10px", border: "1px solid #dce4df", background: "none", color: "#66736d", fontSize: "14px", fontWeight: 600, cursor: "pointer" }}
              >
                Cancel
              </button>
              <button
                onClick={confirmDisconnectAccount}
                disabled={disconnectAccountLoading}
                style={{ flex: 1, padding: "12px", borderRadius: "10px", border: "none", background: "#ef4444", color: "#ffffff", fontSize: "14px", fontWeight: 600, cursor: "pointer" }}
              >
                {disconnectAccountLoading ? "Disconnecting..." : "Disconnect"}
              </button>
            </div>
          </div>
        </div>
      )}

      {deleteEmailConfirmId && (
        <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(15, 33, 28, 0.4)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1100 }}>
          <div style={{ background: "#ffffff", border: "1px solid #dce4df", borderRadius: "16px", padding: "32px", width: "440px", boxShadow: "0 20px 40px rgba(0,0,0,0.1)", textAlign: "center" }}>
            <div style={{ background: "#fef2f2", color: "#ef4444", width: "48px", height: "48px", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 20px auto" }}>
              <ShieldAlert size={24} />
            </div>
            <h3 style={{ fontSize: "18px", fontWeight: 700, color: "#17211c", margin: "0 0 10px 0" }}>Delete Email</h3>
            <p style={{ fontSize: "14px", color: "#0f7a5f", fontWeight: 600, margin: "0 0 10px 0" }}>
              WARNING: This will permanently delete this email and all of its extracted catalog data from MediCORE.
            </p>
            <p style={{ fontSize: "14px", color: "#66736d", margin: "0 0 24px 0", lineHeight: 1.5 }}>
              This action cannot be undone. Are you sure you want to proceed?
            </p>
            <div style={{ display: "flex", gap: "12px" }}>
              <button
                onClick={() => setDeleteEmailConfirmId(null)}
                disabled={deleteEmailLoading}
                style={{ flex: 1, padding: "12px", borderRadius: "10px", border: "1px solid #dce4df", background: "none", color: "#66736d", fontSize: "14px", fontWeight: 600, cursor: "pointer" }}
              >
                Cancel
              </button>
              <button
                onClick={confirmDeleteCatalogEmail}
                disabled={deleteEmailLoading}
                style={{ flex: 1, padding: "12px", borderRadius: "10px", border: "none", background: "#ef4444", color: "#ffffff", fontSize: "14px", fontWeight: 600, cursor: "pointer" }}
              >
                {deleteEmailLoading ? "Deleting..." : "Delete Permanently"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
















