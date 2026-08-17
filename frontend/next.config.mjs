import nextEnv from "@next/env";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(__dirname, "..");
const { loadEnvConfig } = nextEnv;

loadEnvConfig(repoRoot);

const publicEnv = {
  NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "",
  NEXT_PUBLIC_WS_URL: process.env.NEXT_PUBLIC_WS_URL || "",
  NEXT_PUBLIC_SUPABASE_URL: process.env.NEXT_PUBLIC_SUPABASE_URL || "",
  NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "",
  NEXT_PUBLIC_SUPERADMIN_EMAIL: process.env.NEXT_PUBLIC_SUPERADMIN_EMAIL || "",
};

function originFromUrl(value) {
  if (!value) return "";
  try {
    return new URL(value).origin;
  } catch {
    return "";
  }
}

const connectSrc = new Set([
  "'self'",
  "https:",
  "wss:",
  "ws:",
  "http://localhost:8000",
  "http://127.0.0.1:8000",
  "http://192.168.29.44:8000",
  "http://192.168.29.215:8000",
]);

for (const origin of [
  originFromUrl(publicEnv.NEXT_PUBLIC_API_URL),
  originFromUrl(publicEnv.NEXT_PUBLIC_WS_URL),
]) {
  if (origin) connectSrc.add(origin);
}

const contentSecurityPolicy = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com data:",
  "img-src 'self' data: blob: https:",
  `connect-src ${Array.from(connectSrc).join(" ")}`,
  "frame-ancestors 'none'",
].join("; ") + ";";

/** @type {import('next').NextConfig} */
const nextConfig = {
  env: publicEnv,
  outputFileTracingRoot: __dirname,
  allowedDevOrigins: [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://192.168.29.44:3000",
    "http://192.168.29.215:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
  ],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
          {
            key: "X-Frame-Options",
            value: "DENY",
          },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
          {
            key: "Content-Security-Policy",
            value: contentSecurityPolicy,
          },
        ],
      },
    ];
  },
};

export default nextConfig;
