import { createClient } from "@supabase/supabase-js";

const rawUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
const rawKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";

const supabaseUrl = rawUrl.trim() || "https://placeholder.supabase.co";
const supabaseAnonKey = rawKey.trim() || "placeholder-anon-key";

if (!rawUrl || !rawKey) {
  console.warn("Supabase URL or Anon Key is missing in environment variables. Please check NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in the root .env file.");
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

