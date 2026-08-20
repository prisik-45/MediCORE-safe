"use client";

import { useState, useEffect, FormEvent, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { getApiBaseUrl, getApiErrorMessage } from "@/lib/api";
import { loginWithPassword } from "@/lib/auth";
import { Sparkles, ArrowRight, ShieldCheck, Mail, Lock, User, Briefcase, Loader2, Info, Eye, EyeOff } from "lucide-react";

function RegisterStep1Content() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const token = searchParams.get("token");
  const initialEmail = searchParams.get("email") || "";
  const initialName = searchParams.get("name") || "";
  const isEmployee = !!token;

  const [fullName, setFullName] = useState(initialName);
  const [organisation, setOrganisation] = useState("");
  const [email, setEmail] = useState(initialEmail);
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [signUpSuccess, setSignUpSuccess] = useState(false);
  const [signUpPendingApproval, setSignUpPendingApproval] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  useEffect(() => {
    if (initialEmail) setEmail(initialEmail);
    if (initialName) setFullName(initialName);
  }, [initialEmail, initialName]);

  async function handleRegister(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);

    try {
      const apiBaseUrl = getApiBaseUrl();

      if (isEmployee) {
        // Complete activation using backend API to auto-confirm email and bypass Supabase signUp email trigger
        const res = await fetch(`${apiBaseUrl}/api/admin/activate/complete`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            token: token,
            password: password,
            name: fullName.trim(),
          }),
        });

        if (!res.ok) {
          const detail = await res.json().catch(() => ({}));
          throw new Error(getApiErrorMessage(detail, "Failed to complete account activation."));
        }

        // Now, log the user in immediately so that we have an active session
        await loginWithPassword(email.trim(), password);

        // Redirect directly to email setup
        router.push("/register/email-setup");
      } else {
        // Register Workspace Admin - Bypasses email confirmation but flags profile as Pending Approval
        const res = await fetch(`${apiBaseUrl}/api/admin/register-admin`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            name: fullName.trim(),
            email: email.trim(),
            password: password,
            organisation: organisation.trim(),
          }),
        });

        if (!res.ok) {
          const detail = await res.json().catch(() => ({}));
          throw new Error(getApiErrorMessage(detail, "Workspace registration failed."));
        }

        // Set pending approval flag
        setSignUpPendingApproval(true);
        setLoading(false);
      }
      router.refresh();
    } catch (err: any) {
      setError(err.message || "An unexpected error occurred. Please try again.");
      setLoading(false);
    }
  }

  if (signUpPendingApproval) {
    return (
      <main className="auth-page">
        <div className="auth-card-wrapper">
          <div className="auth-card-glow"></div>
          <div className="auth-card" style={{ textAlign: "center" }}>
            <div className="auth-brand" style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
              <div className="brand-logo" style={{ background: "transparent", width: "64px", height: "64px", padding: 0, display: "inline-flex", justifyContent: "center", alignItems: "center", marginBottom: "12px" }}>
                <img src="/Tarkshy.png" alt="Tarkshy Logo" style={{ width: "100%", height: "100%", objectFit: "contain" }} />
              </div>
              <h1>MediCORE</h1>
              <p className="brand-tagline" style={{ margin: "2px 0 16px 0" }}>
                <span style={{ fontSize: "12px", opacity: 0.8 }}>By Tarkshy Consultancy Services</span>
              </p>
            </div>

            <div className="success-content" style={{ marginTop: "24px", display: "flex", flexDirection: "column", alignItems: "center" }}>
              <div className="success-badge" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "64px", height: "64px", borderRadius: "50%", background: "rgba(15, 122, 95, 0.08)", color: "#0f7a5f", border: "1px solid rgba(15, 122, 95, 0.2)", margin: "24px auto 16px auto" }}>
                <ShieldCheck className="check-icon" style={{ width: "32px", height: "32px" }} />
              </div>
              <h2 style={{ fontSize: "22px", fontWeight: 600, color: "#0f7a5f", margin: "0 0 10px 0" }}>Registration Received</h2>
              <p style={{ fontSize: "14px", color: "#66736d", lineHeight: 1.6, margin: "0 0 24px 0" }}>
                Your workspace registration for <strong style={{ color: "#17211c" }}>{organisation}</strong> has been submitted successfully.<br /><br />
                It is currently <span style={{ color: "var(--accent)", fontWeight: 600 }}>Awaiting Approval</span> by the MediCORE Superadmin. You will be able to log in once approved.
              </p>

              <div style={{ padding: "16px", background: "#f4f7f5", borderRadius: "10px", fontSize: "12.5px", color: "#66736d", textAlign: "left", lineHeight: 1.5, marginBottom: "24px", width: "100%" }}>
                <span style={{ fontWeight: 600, color: "#17211c" }}>Next Steps:</span> No email verification is required. Our team will review your workspace details and grant access shortly.
              </div>

              <Link href="/login" className="submit-btn" style={{ textDecoration: "none", width: "100%", display: "flex", justifyContent: "center", alignItems: "center" }}>
                Back to Sign In
              </Link>
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
        `}</style>
      </main>
    );
  }

  if (signUpSuccess) {
    return (
      <main className="auth-page">
        <div className="auth-card-wrapper">
          <div className="auth-card-glow"></div>
          <div className="auth-card" style={{ textAlign: "center" }}>
            <div className="auth-brand" style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
              <div className="brand-logo" style={{ background: "transparent", width: "64px", height: "64px", padding: 0, display: "inline-flex", justifyContent: "center", alignItems: "center", marginBottom: "12px" }}>
                <img src="/Tarkshy.png" alt="Tarkshy Logo" style={{ width: "100%", height: "100%", objectFit: "contain" }} />
              </div>
              <h1>MediCORE</h1>
              <p className="brand-tagline" style={{ margin: "2px 0 16px 0" }}>
                <span style={{ fontSize: "12px", opacity: 0.8 }}>By Tarkshy Consultancy Services</span>
              </p>
            </div>

            <div style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: "64px",
              height: "64px",
              background: "rgba(15, 122, 95, 0.08)",
              color: "#0f7a5f",
              borderRadius: "50%",
              margin: "24px 0 16px 0",
            }}>
              <Mail size={32} />
            </div>

            <h2 style={{ fontSize: "22px", fontWeight: 500, color: "#17211c", margin: "0 0 10px 0" }}>Verify Your Email</h2>
            <p style={{ fontSize: "14px", color: "#66736d", lineHeight: 1.6, margin: "0 0 24px 0" }}>
              We have sent a verification link to <span style={{ color: "#17211c", fontWeight: 500 }}>{email}</span>.<br />
              {isEmployee
                ? "Please click the link in the email to confirm your account and proceed to Email Setup."
                : "Please click the link in the email to confirm your account and log in."
              }
            </p>

            <div style={{ padding: "16px", background: "#f4f7f5", borderRadius: "10px", fontSize: "12px", color: "#66736d", textAlign: "left", lineHeight: 1.5, marginBottom: "24px" }}>
              <span style={{ fontWeight: 500 }}>Tip:</span> If you don't see the email within a few minutes, please check your Spam or Junk folder.
            </div>

            <Link href="/login" className="auth-submit-btn" style={{ textDecoration: "none" }}>
              Proceed to Sign In
            </Link>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="auth-page">
      <div className="auth-card-wrapper">
        <div className="auth-card-glow"></div>
        <div className="auth-card">
          <div className="auth-brand">
            <div className="brand-logo" style={{ background: "transparent", width: "64px", height: "64px", padding: 0, display: "inline-flex", justifyContent: "center", alignItems: "center", marginBottom: "12px" }}>
              <img src="/Tarkshy.png" alt="Tarkshy Logo" style={{ width: "100%", height: "100%", objectFit: "contain" }} />
            </div>
            <h1>MediCORE</h1>
            <p className="brand-tagline" style={{ margin: "2px 0 16px 0" }}>
              <span style={{ fontSize: "12px", opacity: 0.8 }}>By Tarkshy Consultancy Services</span>
            </p>
          </div>

          {/* Step indicator */}
          {isEmployee && (
            <div className="step-indicator">
              <div className="step active">
                <div className="step-circle">1</div>
                <span>Account</span>
              </div>
              <div className="step-line"></div>
              <div className="step">
                <div className="step-circle">2</div>
                <span>Email Setup</span>
              </div>
              <div className="step-line"></div>
              <div className="step">
                <div className="step-circle">3</div>
                <span>Done</span>
              </div>
            </div>
          )}

          <div className="auth-header-text" style={{ textAlign: "center" }}>
            <h2>{isEmployee ? "Employee Registration" : "Create Company Workspace (Admin)"}</h2>
            <p style={{ fontSize: "13px", color: "#66736d", marginTop: "4px" }}>
              {isEmployee
                ? "Set up your employee credentials to start syncing catalogs"
                : "Register your organization to manage employee access"}
            </p>
          </div>

          {error && (
            <div className="auth-error-box">
              <ShieldCheck className="error-icon" />
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleRegister}>
            <div className="input-group">
              <label htmlFor="fullName">
                <span>Full Name</span>
                <div className="input-with-icon">
                  <User className="field-icon" />
                  <input
                    id="fullName"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="Dr. Sarah Connor"
                    required
                    autoComplete="name"
                  />
                </div>
              </label>
            </div>

            {!isEmployee && (
              <div className="input-group">
                <label htmlFor="organisation">
                  <span>Company Name</span>
                  <div className="input-with-icon">
                    <Briefcase className="field-icon" />
                    <input
                      id="organisation"
                      value={organisation}
                      onChange={(e) => setOrganisation(e.target.value)}
                      placeholder="Core Consultancy Ltd"
                      required
                      autoComplete="organization"
                    />
                  </div>
                </label>
              </div>
            )}

            <div className="input-group">
              <label htmlFor="email">
                <span>Work Email Address</span>
                <div className="input-with-icon">
                  <Mail className="field-icon" />
                  <input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="sarah@coreconsultancy.com"
                    required={!isEmployee}
                    disabled={isEmployee}
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
                    autoComplete="new-password"
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

            <div className="input-group">
              <label htmlFor="confirmPassword">
                <span>Confirm Password</span>
                <div className="input-with-icon">
                  <Lock className="field-icon" />
                  <input
                    id="confirmPassword"
                    type={showConfirmPassword ? "text" : "password"}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="password-input"
                    placeholder="••••••••"
                    required
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    className="password-toggle-btn"
                    aria-label={showConfirmPassword ? "Hide password" : "Show password"}
                  >
                    {showConfirmPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </label>
              <div className="hint-box">
                <Info className="hint-icon" />
                <span>
                  This password is for logging into MediCORE only. Do not use your email app password here.
                </span>
              </div>
            </div>

            <button type="submit" className="auth-submit-btn" disabled={loading}>
              {loading ? (
                <>
                  <Loader2 className="animate-spin mr-2" size={18} />
                  Creating account...
                </>
              ) : (
                <>
                  {isEmployee ? "Continue to Email Setup" : "Create Account"}
                  <ArrowRight size={16} />
                </>
              )}
            </button>

            <p className="auth-footer-text">
              Already have an account? <Link href="/login" className="auth-link">Sign In</Link>
            </p>
          </form>
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
          max-width: 460px;
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
          margin-bottom: 24px;
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
          font-weight: 500;
          color: #0f7a5f;
          letter-spacing: -0.5px;
        }

        .brand-tagline {
          margin: 4px 0 0;
          font-size: 12px;
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
          margin-bottom: 32px;
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
          width: 32px;
          height: 32px;
          border-radius: 50%;
          border: 2px solid #dce4df;
          background: #ffffff;
          color: #66736d;
          font-size: 14px;
          font-weight: 500;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.3s;
        }

        .step span {
          font-size: 11px;
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
          background: rgba(15, 122, 95, 0.1);
          color: #0f7a5f;
        }

        .step.completed span {
          color: #17211c;
        }

        .step-line {
          flex: 1;
          height: 2px;
          background: #dce4df;
          margin-bottom: 22px;
        }

        .step-line.completed {
          background: #0f7a5f;
        }

        .auth-header-text {
          margin-bottom: 24px;
        }

        .auth-header-text h2 {
          margin: 0;
          font-size: 20px;
          font-weight: 500;
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
        }

        .input-group {
          margin-bottom: 20px;
          position: relative;
        }

        .input-group label span {
          display: block;
          font-size: 13px;
          font-weight: 400;
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

        .hint-box {
          display: flex;
          align-items: flex-start;
          gap: 6px;
          margin-top: 6px;
          color: #66736d;
          font-size: 11px;
          line-height: 1.4;
        }

        .hint-icon {
          flex-shrink: 0;
          margin-top: 2px;
          color: #0f7a5f;
          width: 14px;
          height: 14px;
        }

        .auth-submit-btn {
          width: 100%;
          height: 48px;
          background: #0f7a5f;
          color: #ffffff;
          border: none;
          border-radius: 10px;
          font-size: 15px;
          font-weight: 500;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          cursor: pointer;
          transition: all 0.2s;
          margin-top: 24px;
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
          font-weight: 500;
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

export default function RegisterStep1Page() {
  return (
    <Suspense fallback={
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh', background: 'radial-gradient(circle at 10% 20%, rgba(244, 247, 245, 1) 0%, rgba(220, 228, 223, 0.4) 90%)', color: '#66736d', fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif' }}>
        Loading...
      </div>
    }>
      <RegisterStep1Content />
    </Suspense>
  );
}
