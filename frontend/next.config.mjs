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
};

export default nextConfig;
