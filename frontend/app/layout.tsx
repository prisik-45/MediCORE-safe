import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./styles.css";

export const metadata: Metadata = {
  title: "MediCORE",
  description: "AI-powered supplier catalog search and recommendations"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="mobile-gate">
          <div className="mobile-gate-card">
            <div className="mobile-gate-icon">
              <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="4" width="18" height="12" rx="2" ry="2"></rect>
                <line x1="2" y1="20" x2="22" y2="20"></line>
                <line x1="12" y1="16" x2="12" y2="20"></line>
              </svg>
            </div>
            <h2>Desktop Experience Required</h2>
            <p>
              MediCORE is designed for professional use on larger displays. Please access this system from a desktop or laptop computer.
            </p>
            <div className="mobile-gate-badge">
              Use a screen width of 1024px or larger
            </div>
          </div>
        </div>
        {children}
      </body>
    </html>
  );
}

