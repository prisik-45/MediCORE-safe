"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { getSessionProfile, loginWithPassword, logoutSession } from "@/lib/auth";
import { Sparkles, ArrowRight, ShieldCheck, Mail, Lock, Loader2, Eye, EyeOff } from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [loginRole, setLoginRole] = useState<"admin" | "employee">("admin");

  async function handleLogin(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      await loginWithPassword(email.trim(), password);

      // Verify database status of profile (active/disabled/deleted)
      let role = "employee";
      try {
        const profileData = await getSessionProfile();
        if (!profileData) {
          await logoutSession();
          setError("You are not authorised to use MediCORE");
          setLoading(false);
          return;
        }
        role = profileData.role || "employee";
        if (loginRole === "admin" && role !== "admin" && role !== "superadmin") {
          await logoutSession();
          setError("This account is not configured as an administrator.");
          setLoading(false);
          return;
        }

        if (loginRole === "employee" && (role === "admin" || role === "superadmin")) {
          await logoutSession();
          setError("This account is configured as an administrator. Please select Admin Login.");
          setLoading(false);
          return;
        }

        if (profileData.status === "Pending Approval") {
          await logoutSession();
          setError("Your workspace registration is pending approval by the MediCORE Superadmin. You will be granted access once approved.");
          setLoading(false);
          return;
        }
        if (profileData.status === "Disabled") {
          await logoutSession();
          setError("You are not authorised to use MediCORE");
          setLoading(false);
          return;
        }
      } catch (err) {
        console.error("Failed to verify user profile during login:", err);
        await logoutSession();
        setError("You are not authorised to use MediCORE");
        setLoading(false);
        return;
      }

      if (role === "superadmin") {
        router.push("/superadmin");
      } else if (role === "admin") {
        router.push("/admin");
      } else {
        router.push("/employee");
      }
      router.refresh();
    } catch (err) {
      setError("An unexpected error occurred. Please try again.");
      setLoading(false);
    }
  }

  return (
    <main className="auth-page">
      <div className="auth-card-wrapper">
        <div className="auth-card-glow"></div>
        <form className="auth-card" onSubmit={handleLogin}>
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
            <h2>Sign In</h2>
            <p style={{ fontSize: "13px", color: "#66736d", marginTop: "4px" }}>
              {loginRole === "admin" 
                ? "Enter your credentials to access the Admin Console" 
                : "Enter your credentials to access the Employee Workspace"}
            </p>
          </div>

          {error && (
            <div className="auth-error-box" style={{ marginBottom: "20px" }}>
              <ShieldCheck className="error-icon" />
              <span>{error}</span>
            </div>
          )}

          {/* Segmented Selector for Role Selection */}
          <div style={{
            display: "flex",
            background: "#f4f7f5",
            padding: "4px",
            borderRadius: "10px",
            border: "1px solid #dce4df",
            marginBottom: "20px"
          }}>
            <button
              type="button"
              onClick={() => {
                setLoginRole("admin");
                setError(null);
              }}
              style={{
                flex: 1,
                padding: "8px 16px",
                border: "none",
                borderRadius: "8px",
                background: loginRole === "admin" ? "#ffffff" : "transparent",
                color: loginRole === "admin" ? "#0f7a5f" : "#66736d",
                fontWeight: 500,
                fontSize: "13px",
                cursor: "pointer",
                transition: "all 0.2s",
                boxShadow: loginRole === "admin" ? "0 2px 6px rgba(23, 33, 28, 0.05)" : "none"
              }}
            >
              Admin Login
            </button>
            <button
              type="button"
              onClick={() => {
                setLoginRole("employee");
                setError(null);
              }}
              style={{
                flex: 1,
                padding: "8px 16px",
                border: "none",
                borderRadius: "8px",
                background: loginRole === "employee" ? "#ffffff" : "transparent",
                color: loginRole === "employee" ? "#0f7a5f" : "#66736d",
                fontWeight: 500,
                fontSize: "13px",
                cursor: "pointer",
                transition: "all 0.2s",
                boxShadow: loginRole === "employee" ? "0 2px 6px rgba(23, 33, 28, 0.05)" : "none"
              }}
            >
              Employee Login
            </button>
          </div>

          <div className="input-group">
            <label htmlFor="email">
              <span>{loginRole === "admin" ? "Admin Email Address" : "Work Email Address"}</span>
              <div className="input-with-icon">
                <Mail className="field-icon" />
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@company.com"
                  required
                  autoComplete="email"
                />
              </div>
            </label>
          </div>

          <div className="input-group">
            <label htmlFor="password">
              <span>Password</span>
              <div className="input-with-icon">
                <Lock className="field-icon" />
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="password-input"
                  placeholder="••••••••"
                  required
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="password-toggle-btn"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </label>
          </div>

          <button type="submit" className="auth-submit-btn" disabled={loading}>
            {loading ? (
              <>
                <Loader2 className="animate-spin mr-2" size={18} />
                Signing in...
              </>
            ) : (
              <>
                Sign In
                <ArrowRight size={16} />
              </>
            )}
          </button>

          <p className="auth-footer-text">
            Don't have an account? <Link href="/register" className="auth-link">Create one</Link>
          </p>
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

        .brand-icon {
          width: 24px;
          height: 24px;
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
        }

        .input-group label span {
          display: block;
          font-size: 13px;
          font-weight: 600;
          color: #17211c;
          margin-bottom: 8px;
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

        .input-with-icon input.password-input {
          padding-right: 44px !important;
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

        .auth-submit-btn {
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

        .auth-submit-btn:hover {
          background: #0d6a50;
          box-shadow: 0 4px 12px rgba(15, 122, 95, 0.2);
        }

        .auth-submit-btn:disabled {
          background: #80bfae;
          cursor: not-allowed;
          box-shadow: none;
        }

        .auth-footer-text {
          margin: 24px 0 0;
          text-align: center;
          font-size: 14px;
          color: #66736d;
        }

        .auth-link {
          color: #0f7a5f;
          font-weight: 600;
          text-decoration: none;
          transition: color 0.2s;
        }

        .auth-link:hover {
          color: #0d6a50;
          text-decoration: underline;
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
