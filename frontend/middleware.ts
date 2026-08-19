import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const SESSION_COOKIE = "medicore_session_id";
const ACCESS_TOKEN_COOKIE = "medicore_access_token";
const REFRESH_TOKEN_COOKIE = "medicore_refresh_token";

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (
    pathname.startsWith("/_") ||
    pathname.startsWith("/api") ||
    pathname.includes(".") ||
    pathname === "/favicon.ico"
  ) {
    return NextResponse.next();
  }

  const hasSession = Boolean(
    request.cookies.get(ACCESS_TOKEN_COOKIE)?.value ||
    request.cookies.get(SESSION_COOKIE)?.value ||
    request.cookies.get(REFRESH_TOKEN_COOKIE)?.value
  );

  const isAuthRoute =
    pathname === "/login" ||
    pathname === "/register" ||
    pathname.startsWith("/activate") ||
    pathname.startsWith("/reset-password");

  if (!hasSession && !isAuthRoute) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (hasSession && (pathname === "/login" || pathname === "/register")) {
    return NextResponse.redirect(new URL("/", request.url));
  }

  return NextResponse.next();
}
