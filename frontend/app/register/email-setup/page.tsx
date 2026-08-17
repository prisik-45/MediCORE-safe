"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { getApiBaseUrl } from "@/lib/api";
import { authFetch, getSessionProfile, SessionProfile } from "@/lib/auth";
import {
  Sparkles,
  ArrowRight,
  ShieldCheck,
  Mail,
  Key,
  ChevronDown,
  ChevronUp,
  Sliders,
  CheckCircle2,
  XCircle,
  HelpCircle,
  Loader2,
  Settings,
  Eye,
  EyeOff
} from "lucide-react";

export default function EmailSetupPage() {
  const router = useRouter();
  const [session, setSession] = useState<SessionProfile | null>(null);
  const [provider, setProvider] = useState("Gmail");
  const [emailAddress, setEmailAddress] = useState("");
  const [appPassword, setAppPassword] = useState("");
  const [showAppPassword, setShowAppPassword] = useState(false);
  
  // Filters state (Skip Promotions is always ON, Require Attachments is not mandatory)
  const [requireAttachment] = useState(false);
  const [senderKeywords] = useState("");
  const [subjectKeywords] = useState("");
  const [skipPromotionsTab] = useState(true);
  const [ingestionApproach, setIngestionApproach] = useState("approach_1");

  // Status and loading states
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Check for active session and pre-fill email address or redirect if admin
    getSessionProfile().then((profile) => {
      if (profile) {
        setSession(profile);
        const role = profile.role;
        if (role === "admin") {
          router.push("/register/done");
          return;
        }
        if (profile.email) {
          setEmailAddress(profile.email);
        }
      } else {
        router.push("/login");
      }
    }).catch(() => {
      router.push("/login");
    });

  }, [router]);

  const apiBaseUrl = getApiBaseUrl();

  async function handleTestConnection() {
    if (!emailAddress || !appPassword) {
      setError("Please fill in both the email address and app password.");
      return;
    }

    setError(null);
    setTesting(true);
    setTestResult(null);

    try {
      if (!session) {
        throw new Error("No active authentication session. Please sign in again.");
      }

      // Hardcode port 993 and imap host for Gmail, or adapt if custom
      const imapHost = provider === "Gmail" ? "imap.gmail.com" : "imap.gmail.com";
      const imapPort = 993;

      const response = await authFetch(`${apiBaseUrl}/api/email-accounts/test`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          provider,
          email_address: emailAddress.trim(),
          imap_host: imapHost,
          imap_port: imapPort,
          password: appPassword.trim(),
        }),
      });

      if (!response.ok) {
        const errDetail = await response.json();
        throw new Error(errDetail?.detail || "Connection test request failed.");
      }

      const data = await response.json();
      setTestResult({
        success: data.success,
        message: data.message,
      });
    } catch (err: any) {
      setTestResult({
        success: false,
        message: err.message || "An unexpected error occurred during connection test.",
      });
    } finally {
      setTesting(false);
    }
  }

  async function handleSaveAccount() {
    if (!testResult?.success) return;
    setError(null);
    setSaving(true);

    try {
      if (!session) {
        throw new Error("No active session found.");
      }

      const imapHost = provider === "Gmail" ? "imap.gmail.com" : "imap.gmail.com";
      const imapPort = 993;

      const response = await authFetch(`${apiBaseUrl}/api/email-accounts`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          provider,
          email_address: emailAddress.trim(),
          imap_host: imapHost,
          imap_port: imapPort,
          password: appPassword.trim(),
          filters: {
            require_attachment: requireAttachment,
            sender_keywords: senderKeywords ? senderKeywords.trim() : null,
            subject_keywords: subjectKeywords ? subjectKeywords.trim() : null,
            skip_promotions_tab: skipPromotionsTab,
          },
          ingestion_approach: ingestionApproach,
        }),
      });

      if (!response.ok) {
        const errDetail = await response.json();
        throw new Error(errDetail?.detail || "Failed to save email account details.");
      }

      router.push("/register/done");
    } catch (err: any) {
      setError(err.message || "Failed to save settings. Please try again.");
      setSaving(false);
    }
  }

  return (
    <main className="auth-page">
      <div className="auth-card-wrapper">
        <div className="auth-card-glow"></div>
        <div className="auth-card">
          <div className="auth-brand">
            <div className="brand-logo" style={{ background: "transparent", width: "54px", height: "54px", padding: 0, display: "inline-flex", justifyContent: "center", alignItems: "center", marginBottom: "8px" }}>
              <img src="/Tarkshy.png" alt="Tarkshy Logo" style={{ width: "100%", height: "100%", objectFit: "contain" }} />
            </div>
            <h1>MediCORE</h1>
            <p className="brand-tagline" style={{ margin: "2px 0 16px 0" }}>
              <span style={{ fontSize: "12px", opacity: 0.8 }}>By Tarkshy Consultancy Services</span>
            </p>
          </div>

          {/* Step indicator */}
          <div className="step-indicator">
            <div className="step completed">
              <div className="step-circle">1</div>
              <span>Account</span>
            </div>
            <div className="step-line completed"></div>
            <div className="step active">
              <div className="step-circle">2</div>
              <span>Email Setup</span>
            </div>
            <div className="step-line"></div>
            <div className="step">
              <div className="step-circle">3</div>
              <span>Done</span>
            </div>
          </div>

          <div className="auth-header-text" style={{ textAlign: "center", marginBottom: "20px" }}>
            <h2>Email Connection</h2>
          </div>

          {error && (
            <div className="auth-error-box">
              <ShieldCheck className="error-icon" size={16} />
              <span>{error}</span>
            </div>
          )}

          {/* Provider Card Selector - Redesigned as clean, single-provider badge with theme color */}
          <div className="provider-selector-section">
            <span className="section-label">Active Provider</span>
            <div className="provider-integration-badge">
              <Mail className="provider-badge-icon" size={18} />
              <div className="provider-badge-info">
                <strong>Gmail</strong>
                <span>Secure IMAP Connection</span>
              </div>
              <span className="provider-status-dot"></span>
            </div>
          </div>

          {/* Form */}
          <div className="form-fields">
            <div className="input-group">
              <label htmlFor="emailAddress" className="input-label-row">
                <span>Email Address</span>
              </label>
              <div className="input-with-icon">
                <Mail className="field-icon" size={18} />
                <input
                  id="emailAddress"
                  type="email"
                  value={emailAddress}
                  onChange={(e) => setEmailAddress(e.target.value)}
                  placeholder="sarah@coreconsultancy.com"
                  required
                  readOnly
                />
              </div>
            </div>

            <div className="input-group">
              <label htmlFor="appPassword" className="input-label-row">
                <span>App Password</span>
              </label>
              <div className="input-with-icon">
                <Key className="field-icon" size={18} />
                <input
                  id="appPassword"
                  type={showAppPassword ? "text" : "password"}
                  value={appPassword}
                  onChange={(e) => {
                    setAppPassword(e.target.value);
                    setTestResult(null); // Reset test status when password changes
                  }}
                  className="password-input"
                  placeholder="xxxx xxxx xxxx xxxx"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowAppPassword(!showAppPassword)}
                  className="password-toggle-btn"
                  aria-label={showAppPassword ? "Hide password" : "Show password"}
                >
                  {showAppPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            {/* Inline App Password Guide - Collapsible details accordion */}
            <details className="guide-accordion">
              <summary className="guide-summary">
                <HelpCircle className="guide-summary-icon" size={14} />
                <span>How to generate an App Password?</span>
                <ChevronDown className="guide-chevron" size={14} />
              </summary>
              <div className="guide-content">
                <ol className="guide-list">
                  <li>Turn on <strong>2-Step Verification</strong> in Google Security settings.</li>
                  <li>Search for <strong>App Passwords</strong> in your Google Account.</li>
                  <li>Select <strong>Other (Custom name)</strong>, type <strong>MediCORE</strong>, and generate.</li>
                  <li>Copy the 16-character code and paste it above.</li>
                </ol>
              </div>
            </details>

            {/* Email Ingestion Mode Option */}
            <div className="input-group" style={{ marginBottom: "0px" }}>
              <label className="input-label-row">
                <span style={{ fontSize: "13px", fontWeight: 600, color: "#17211c" }}>Email Ingestion Mode</span>
              </label>
              <div style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: "12px",
                marginTop: "6px"
              }}>
                {/* Option 1: Gmail Label */}
                <div
                  onClick={() => setIngestionApproach("approach_1")}
                  style={{
                    border: `1px solid ${ingestionApproach === "approach_1" ? "var(--accent)" : "#dce4df"}`,
                    background: ingestionApproach === "approach_1" ? "rgba(15, 122, 95, 0.03)" : "#ffffff",
                    borderRadius: "12px",
                    padding: "12px 14px",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                    display: "flex",
                    flexDirection: "column",
                    gap: "6px",
                    boxShadow: ingestionApproach === "approach_1" ? "0 4px 12px rgba(15, 122, 95, 0.06)" : "none"
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <div style={{
                      width: "14px",
                      height: "14px",
                      borderRadius: "50%",
                      border: `1.5px solid ${ingestionApproach === "approach_1" ? "var(--accent)" : "#a2b0a9"}`,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flexShrink: 0
                    }}>
                      {ingestionApproach === "approach_1" && (
                        <div style={{ width: "6px", height: "6px", borderRadius: "50%", background: "var(--accent)" }} />
                      )}
                    </div>
                    <strong style={{ fontSize: "12px", color: ingestionApproach === "approach_1" ? "var(--accent)" : "var(--ink)", fontWeight: 600, lineHeight: 1.2 }}>Gmail Label Ingestion</strong>
                  </div>
                  <span style={{ fontSize: "10.5px", color: "#66736d", lineHeight: 1.35 }}>
                    Ingest only emails marked with the 'suppliers' label in Gmail. Safe & highly recommended.
                  </span>
                </div>

                {/* Option 2: Trusted Supplier Approval */}
                <div
                  onClick={() => setIngestionApproach("approach_2")}
                  style={{
                    border: `1px solid ${ingestionApproach === "approach_2" ? "var(--accent)" : "#dce4df"}`,
                    background: ingestionApproach === "approach_2" ? "rgba(15, 122, 95, 0.03)" : "#ffffff",
                    borderRadius: "12px",
                    padding: "12px 14px",
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                    display: "flex",
                    flexDirection: "column",
                    gap: "6px",
                    boxShadow: ingestionApproach === "approach_2" ? "0 4px 12px rgba(15, 122, 95, 0.06)" : "none"
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <div style={{
                      width: "14px",
                      height: "14px",
                      borderRadius: "50%",
                      border: `1.5px solid ${ingestionApproach === "approach_2" ? "var(--accent)" : "#a2b0a9"}`,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flexShrink: 0
                    }}>
                      {ingestionApproach === "approach_2" && (
                        <div style={{ width: "6px", height: "6px", borderRadius: "50%", background: "var(--accent)" }} />
                      )}
                    </div>
                    <strong style={{ fontSize: "12px", color: ingestionApproach === "approach_2" ? "var(--accent)" : "var(--ink)", fontWeight: 600, lineHeight: 1.2 }}>Trusted Supplier Approval</strong>
                  </div>
                  <span style={{ fontSize: "10.5px", color: "#66736d", lineHeight: 1.35 }}>
                    Ingests catalogs automatically from trusted senders, while holding new suppliers for approval.
                  </span>
                </div>
              </div>
            </div>

            {/* Test Connection Display */}
            {testResult && (
              <div className={`test-feedback-box ${testResult.success ? "success" : "failed"}`}>
                {testResult.success ? (
                  <>
                    <CheckCircle2 className="feedback-icon" size={18} />
                    <div className="feedback-text">
                      <strong>Connection Succeeded</strong>
                    </div>
                  </>
                ) : (
                  <>
                    <XCircle className="feedback-icon" size={18} />
                    <div className="feedback-text">
                      {testResult.message.toLowerCase().includes("authentication failed") ||
                      testResult.message.toLowerCase().includes("login error") ? (
                        <strong>Connection Failed : Invalid Credentials</strong>
                      ) : (
                        <>
                          <strong>Connection Failed</strong>
                          <p>{testResult.message}</p>
                        </>
                      )}
                    </div>
                  </>
                )}
              </div>
            )}

            {/* Action Buttons */}
            <div className="button-group">
              <button
                type="button"
                className="btn-test-connection"
                onClick={handleTestConnection}
                disabled={testing || !emailAddress || !appPassword}
              >
                {testing ? (
                  <>
                    <Loader2 className="animate-spin mr-2" size={16} />
                    Testing...
                  </>
                ) : (
                  "Test Connection"
                )}
              </button>

              <button
                type="button"
                className="btn-save-credentials"
                onClick={handleSaveAccount}
                disabled={saving || !testResult?.success}
              >
                {saving ? (
                  <>
                    <Loader2 className="animate-spin mr-2" size={16} />
                    Saving...
                  </>
                ) : (
                  <>
                    Save and Continue
                    <ArrowRight size={16} />
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
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
          max-width: 480px;
        }

        .auth-card-glow {
          position: absolute;
          top: -20px;
          left: -20px;
          right: -20px;
          bottom: -20px;
          background: radial-gradient(circle, rgba(15, 122, 95, 0.05) 0%, transparent 60%);
          filter: blur(12px);
          z-index: 0;
          pointer-events: none;
        }

        .auth-card {
          position: relative;
          background: rgba(255, 255, 255, 0.9);
          backdrop-filter: blur(16px);
          border: 1px solid rgba(15, 122, 95, 0.12);
          border-radius: 24px;
          padding: 36px;
          box-shadow: 0 20px 40px rgba(15, 122, 95, 0.04), 0 1px 3px rgba(15, 122, 95, 0.02);
          z-index: 1;
        }

        .auth-brand {
          text-align: center;
          margin-bottom: 24px;
        }

        .brand-logo {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          margin-bottom: 8px;
        }

        .auth-brand h1 {
          margin: 0;
          font-size: 24px;
          font-weight: 500;
          color: #0f7a5f;
          letter-spacing: -0.5px;
        }

        .brand-tagline {
          margin: 4px 0 0;
          font-size: 11px;
          color: #66736d;
          font-weight: 400;
          letter-spacing: 0.5px;
          text-transform: uppercase;
        }

        /* Step indicator styling */
        .step-indicator {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 28px;
          padding: 0 10px;
        }

        .step {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 6px;
          width: 80px;
        }

        .step-circle {
          width: 28px;
          height: 28px;
          border-radius: 50%;
          border: 2px solid #dce4df;
          background: #ffffff;
          color: #66736d;
          font-size: 13px;
          font-weight: 500;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.3s;
        }

        .step span {
          font-size: 10px;
          font-weight: 500;
          color: #66736d;
          text-align: center;
        }

        .step.active .step-circle {
          border-color: #0f7a5f;
          background: #0f7a5f;
          color: #ffffff;
          box-shadow: 0 0 0 4px rgba(15, 122, 95, 0.15);
        }

        .step.active span {
          color: #0f7a5f;
          font-weight: 500;
        }

        .step.completed .step-circle {
          border-color: #0f7a5f;
          background: rgba(15, 122, 95, 0.08);
          color: #0f7a5f;
        }

        .step.completed span {
          color: #17211c;
        }

        .step-line {
          flex: 1;
          height: 2px;
          background: #dce4df;
          margin-bottom: 20px;
        }

        .step-line.completed {
          background: #0f7a5f;
        }

        .auth-header-text h2 {
          margin: 0;
          font-size: 18px;
          font-weight: 500;
          color: #17211c;
        }

        .auth-error-box {
          background: var(--soft);
          border: 1px solid var(--line);
          color: var(--ink);
          padding: 12px 16px;
          display: flex;
          align-items: flex-start;
          gap: 10px;
          margin-bottom: 24px;
          font-size: 13px;
          border-radius: 12px;
        }

        .error-icon {
          flex-shrink: 0;
          margin-top: 1px;
          color: #0f7a5f;
        }

        .provider-selector-section {
          margin-bottom: 24px;
        }

        .section-label {
          display: block;
          font-size: 11px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          color: #66736d;
          margin-bottom: 8px;
        }

        .provider-integration-badge {
          display: flex;
          align-items: center;
          gap: 14px;
          padding: 14px 18px;
          border: 1px solid rgba(15, 122, 95, 0.15);
          border-radius: 14px;
          background: rgba(15, 122, 95, 0.03);
          position: relative;
          overflow: hidden;
        }

        .provider-badge-icon {
          color: #0f7a5f;
          background: rgba(15, 122, 95, 0.08);
          padding: 8px;
          border-radius: 10px;
          box-sizing: content-box;
        }

        .provider-badge-info {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }

        .provider-badge-info strong {
          font-size: 14px;
          font-weight: 600;
          color: var(--ink);
        }

        .provider-badge-info span {
          font-size: 11px;
          color: #66736d;
        }

        .provider-status-dot {
          position: absolute;
          right: 18px;
          width: 8px;
          height: 8px;
          background: #0f7a5f;
          border-radius: 50%;
          box-shadow: 0 0 0 4px rgba(15, 122, 95, 0.15);
          animation: pulse 2s infinite;
        }

        @keyframes pulse {
          0% {
            box-shadow: 0 0 0 0 rgba(15, 122, 95, 0.35);
          }
          70% {
            box-shadow: 0 0 0 6px rgba(15, 122, 95, 0);
          }
          100% {
            box-shadow: 0 0 0 0 rgba(15, 122, 95, 0);
          }
        }

        /* Guide Accordion */
        .guide-accordion {
          border: 1px solid var(--line);
          border-radius: 12px;
          background: var(--soft);
          margin-bottom: 4px;
          overflow: hidden;
          transition: all 0.3s ease;
        }

        .guide-accordion[open] {
          border-color: rgba(15, 122, 95, 0.2);
          background: #ffffff;
          box-shadow: 0 4px 12px rgba(15, 122, 95, 0.02);
        }

        .guide-summary {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 12px 16px;
          cursor: pointer;
          user-select: none;
          font-size: 13px;
          font-weight: 600;
          color: #0f7a5f;
          list-style: none;
        }

        .guide-summary::-webkit-details-marker {
          display: none;
        }

        .guide-summary-icon {
          flex-shrink: 0;
          color: #0f7a5f;
        }

        .guide-summary span {
          flex-grow: 1;
        }

        .guide-chevron {
          transition: transform 0.25s ease;
          color: #66736d;
        }

        .guide-accordion[open] .guide-chevron {
          transform: rotate(180deg);
        }

        .guide-content {
          padding: 0 16px 14px 16px;
          border-top: 1px solid rgba(15, 122, 95, 0.08);
        }

        .guide-list {
          margin: 10px 0 0 0;
          padding-left: 20px;
          font-size: 11px;
          line-height: 1.6;
          color: #66736d;
        }

        .guide-list li {
          margin-bottom: 6px;
        }

        .guide-list li strong {
          color: #17211c;
        }

        .form-fields {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .input-group {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .input-label-row {
          font-size: 13px;
          font-weight: 500;
          color: #17211c;
        }

        .input-with-icon {
          position: relative;
          display: flex;
          align-items: center;
        }

        .field-icon {
          position: absolute;
          left: 16px;
          color: #66736d;
          transition: color 0.2s ease;
        }

        .input-with-icon input {
          width: 100% !important;
          height: 48px !important;
          padding: 0 16px 0 48px !important;
          border: 1px solid #dce4df !important;
          border-radius: 12px !important;
          font-size: 14px !important;
          color: #17211c !important;
          background: #fafcfb !important;
          outline: none !important;
          transition: all 0.2s ease !important;
        }

        .input-with-icon input:focus {
          border-color: #0f7a5f !important;
          background: #ffffff !important;
          box-shadow: 0 0 0 3px rgba(15, 122, 95, 0.08) !important;
        }

        .input-with-icon input:focus + .field-icon {
          color: #0f7a5f !important;
        }

        .input-with-icon input.password-input {
          padding-right: 44px !important;
        }

        .auth-card .password-toggle-btn,
        .auth-card button.password-toggle-btn {
          position: absolute;
          right: 14px;
          top: 50%;
          transform: translateY(-50%);
          background: none !important;
          border: none !important;
          padding: 0 !important;
          color: #66736d !important;
          cursor: pointer;
          display: inline-flex !important;
          align-items: center;
          justify-content: center;
          transition: color 0.2s;
          z-index: 10;
          width: 36px !important;
          min-width: 36px !important;
          max-width: 36px !important;
          height: 36px !important;
          min-height: 36px !important;
          box-shadow: none !important;
        }

        .auth-card .password-toggle-btn:hover {
          color: #17211c;
        }

        .input-with-icon input[readonly] {
          background: rgba(220, 228, 223, 0.25) !important;
          border-color: #dce4df !important;
          color: #66736d !important;
          cursor: not-allowed !important;
          opacity: 0.8 !important;
        }

        .input-simple input {
          width: 100% !important;
          height: 48px !important;
          padding: 0 16px !important;
          border: 1px solid #dce4df !important;
          border-radius: 12px !important;
          font-size: 14px !important;
          color: #17211c !important;
          background: #fafcfb !important;
          outline: none !important;
          transition: all 0.2s ease !important;
        }

        .input-simple input:focus {
          border-color: #0f7a5f !important;
          background: #ffffff !important;
          box-shadow: 0 0 0 3px rgba(15, 122, 95, 0.08) !important;
        }

        /* Collapsible Advanced Section */
        .collapsible-section {
          border: 1px solid #dce4df;
          border-radius: 14px;
          overflow: hidden;
          background: #ffffff;
          transition: all 0.2s ease;
        }

        .collapsible-section:hover {
          border-color: rgba(15, 122, 95, 0.2);
        }

        .collapsible-trigger {
          width: 100% !important;
          padding: 14px 20px !important;
          display: flex !important;
          align-items: center !important;
          justify-content: space-between !important;
          background: #ffffff !important;
          border: none !important;
          color: #17211c !important;
          cursor: pointer !important;
          transition: all 0.2s ease !important;
        }

        .collapsible-trigger:hover {
          background: #fafcfb !important;
        }

        .trigger-label {
          display: flex !important;
          align-items: center !important;
          gap: 10px !important;
          font-size: 13px !important;
          font-weight: 500 !important;
          color: #17211c !important;
        }

        .trigger-icon {
          color: #0f7a5f !important;
        }

        .trigger-chevron {
          color: #66736d !important;
        }

        .collapsible-content {
          padding: 18px 20px;
          border-top: 1px solid #dce4df;
          display: flex;
          flex-direction: column;
          gap: 16px;
          background: #ffffff;
        }

        .filter-toggle-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 16px;
          padding-bottom: 12px;
          border-bottom: 1px dashed #dce4df;
        }

        .filter-toggle-row:last-of-type {
          border-bottom: none;
          padding-bottom: 0;
        }

        .toggle-label {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }

        .toggle-label strong {
          font-size: 13px;
          color: #17211c;
          font-weight: 500;
        }

        .toggle-label span {
          font-size: 11px;
          color: #66736d;
          line-height: 1.4;
        }

        /* Premium Switch */
        .ios-switch {
          position: relative !important;
          width: 44px !important;
          height: 24px !important;
          display: inline-block !important;
          flex-shrink: 0 !important;
          appearance: none !important;
          background: #dce4df !important;
          border: none !important;
          outline: none !important;
          border-radius: 20px !important;
          cursor: pointer !important;
          transition: background 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
          box-sizing: border-box !important;
          padding: 0 !important;
          margin: 0 !important;
        }

        .ios-switch:checked {
          background: #0f7a5f !important;
        }

        .ios-switch::before {
          content: "" !important;
          position: absolute !important;
          width: 18px !important;
          height: 18px !important;
          border-radius: 50% !important;
          top: 3px !important;
          left: 3px !important;
          background: #ffffff !important;
          box-shadow: 0 2px 4px rgba(23, 33, 28, 0.15) !important;
          transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
          border: none !important;
          padding: 0 !important;
          margin: 0 !important;
        }

        .ios-switch:checked::before {
          transform: translateX(20px) !important;
        }

        /* Test Feedback Box */
        .test-feedback-box {
          display: flex;
          align-items: flex-start;
          gap: 12px;
          padding: 14px 16px;
          border-radius: 12px;
          font-size: 13px;
          line-height: 1.45;
          transition: all 0.3s ease;
        }

        .test-feedback-box.success {
          background: rgba(15, 122, 95, 0.04);
          border: 1px solid rgba(15, 122, 95, 0.18);
          color: #0f7a5f;
        }

        .test-feedback-box.failed {
          background: #fafcfb;
          border: 1px solid #dce4df;
          color: #17211c;
        }

        .feedback-icon {
          margin-top: 2px;
          flex-shrink: 0;
        }

        .test-feedback-box.failed .feedback-icon {
          color: #66736d;
        }

        .feedback-text {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }

        .feedback-text strong {
          font-weight: 500;
          font-size: 13px;
        }

        .feedback-text p {
          margin: 0;
          opacity: 0.85;
        }

        /* Buttons layout */
        .button-group {
          display: grid;
          grid-template-columns: 1fr 1.2fr;
          gap: 12px;
          margin-top: 6px;
        }

        .btn-test-connection {
          height: 48px !important;
          border: 1px solid #0f7a5f !important;
          background: #ffffff !important;
          color: #0f7a5f !important;
          border-radius: 12px !important;
          font-size: 14px !important;
          font-weight: 500 !important;
          cursor: pointer !important;
          transition: all 0.2s ease !important;
          display: flex !important;
          align-items: center !important;
          justify-content: center !important;
        }

        .btn-test-connection:hover:not(:disabled) {
          background: rgba(15, 122, 95, 0.04) !important;
          box-shadow: 0 4px 12px rgba(15, 122, 95, 0.05) !important;
        }

        .btn-save-credentials {
          height: 48px !important;
          background: #0f7a5f !important;
          color: #ffffff !important;
          border: none !important;
          border-radius: 12px !important;
          font-size: 14px !important;
          font-weight: 500 !important;
          cursor: pointer !important;
          transition: all 0.2s ease !important;
          display: flex !important;
          align-items: center !important;
          justify-content: center !important;
          gap: 6px !important;
        }

        .btn-save-credentials:hover:not(:disabled) {
          background: #0d6a50 !important;
          box-shadow: 0 6px 18px rgba(15, 122, 95, 0.15) !important;
        }

        .btn-test-connection:disabled,
        .btn-save-credentials:disabled {
          opacity: 0.45 !important;
          cursor: not-allowed !important;
          box-shadow: none !important;
        }

        .animate-spin {
          animation: spin 1s linear infinite;
        }

        .mr-2 {
          margin-right: 8px;
        }

        @keyframes spin {
          from {
            transform: rotate(0deg);
          }
          to {
            transform: rotate(360deg);
          }
        }
      `}</style>
    </main>
  );
}
