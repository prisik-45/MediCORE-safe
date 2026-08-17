"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Sparkles, Check, ArrowRight } from "lucide-react";
import { getSessionProfile } from "@/lib/auth";

export default function RegisterDonePage() {
  const router = useRouter();
  const [role, setRole] = useState<string | null>(null);

  useEffect(() => {
    getSessionProfile().then((profile) => {
      if (profile) {
        setRole(profile.role || "employee");
      }
    }).catch(() => {});
  }, []);

  const isAdmin = role === "admin";

  function handleGoToDashboard() {
    if (isAdmin) {
      router.push("/admin");
    } else {
      router.push("/");
    }
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
          {!isAdmin && (
            <div className="step-indicator">
              <div className="step completed">
                <div className="step-circle">1</div>
                <span>Account</span>
              </div>
              <div className="step-line completed"></div>
              <div className="step completed">
                <div className="step-circle">2</div>
                <span>Email Setup</span>
              </div>
              <div className="step-line completed"></div>
              <div className="step active">
                <div className="step-circle">3</div>
                <span>Done</span>
              </div>
            </div>
          )}

          <div className="success-content">
            <div className="success-badge">
              <Check className="check-icon" />
            </div>
            <h2>Setup Complete!</h2>
            <p className="success-lead-text">
              Your MediCORE account is successfully configured and active.
            </p>
            <div className="success-details-card">
              {isAdmin ? (
                <p>
                  Your company workspace has been successfully initialized. You can now access the Admin Portal
                  to invite your employees, monitor data usage metrics, inspect database telemetry, and manage active session controls.
                </p>
              ) : (
                <p>
                  We have connected your supplier inbox and set up automated scanning. Our AI engine will now
                  regularly parse incoming supplier catalogs, extract PDF product items, and make them searchable
                  directly in your dashboard!
                </p>
              )}
            </div>
          </div>

          <button
            type="button"
            className="auth-submit-btn"
            onClick={handleGoToDashboard}
          >
            {isAdmin ? "Go to Admin Portal" : "Go to Dashboard"}
            <ArrowRight size={16} />
          </button>
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
          margin-bottom: 36px;
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

        /* Success screen specifics */
        .success-content {
          text-align: center;
          margin-bottom: 32px;
        }

        .success-badge {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 72px;
          height: 72px;
          border-radius: 50%;
          background: linear-gradient(135deg, rgba(16, 185, 129, 0.06) 0%, rgba(15, 122, 95, 0.12) 100%);
          border: 1px solid rgba(15, 122, 95, 0.2);
          color: #0f7a5f;
          margin-bottom: 24px;
          box-shadow: 0 8px 24px rgba(15, 122, 95, 0.05), 0 0 0 8px rgba(15, 122, 95, 0.03);
          animation: scaleIn 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) both;
        }

        .check-icon {
          width: 32px;
          height: 32px;
        }

        .success-content h2 {
          margin: 0;
          font-size: 26px;
          font-weight: 500;
          background: linear-gradient(135deg, #092f28 0%, #0f7a5f 100%);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          letter-spacing: -0.5px;
        }

        .success-lead-text {
          margin: 8px 0 0;
          font-size: 14px;
          color: #66736d;
          font-weight: 500;
        }

        .success-details-card {
          margin-top: 24px;
          background: linear-gradient(180deg, #fafcfb 0%, #f4f7f5 100%);
          border: 1px solid rgba(15, 122, 95, 0.1);
          border-left: 4px solid #0f7a5f;
          border-radius: 14px;
          padding: 20px 24px;
          font-size: 13px;
          line-height: 1.6;
          color: #4a5751;
          text-align: left;
          box-shadow: 0 4px 16px rgba(15, 122, 95, 0.01);
        }

        .success-details-card p {
          margin: 0;
        }

        .auth-submit-btn {
          width: 100%;
          height: 50px;
          background: #0f7a5f;
          color: #ffffff;
          border: none;
          border-radius: 12px;
          font-size: 15px;
          font-weight: 500;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          cursor: pointer;
          transition: all 0.25s ease;
          box-shadow: 0 4px 14px rgba(15, 122, 95, 0.15);
        }

        .auth-submit-btn:hover {
          background: #0d6a50;
          transform: translateY(-1px);
          box-shadow: 0 6px 20px rgba(15, 122, 95, 0.25);
        }

        @keyframes scaleIn {
          0% {
            transform: scale(0.8);
            opacity: 0;
          }
          100% {
            transform: scale(1);
            opacity: 1;
          }
        }
      `}</style>
    </main>
  );
}
