import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Helper to check if a JWT token is expired
function isTokenExpired(token: string): boolean {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return true;
    
    // Decode base64url payload
    const base64Url = parts[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    
    const payload = JSON.parse(jsonPayload);
    if (payload && payload.exp) {
      // Buffer of 10 seconds
      return Date.now() >= (payload.exp - 10) * 1000;
    }
    return true;
  } catch (e) {
    return true;
  }
}

// Helper to get JWT Payload fields
function getJwtPayload(token: string): any {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return null;
    const base64Url = parts[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    return JSON.parse(jsonPayload);
  } catch (e) {
    return null;
  }
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  
  // Exclude static assets, next internals, etc.
  if (
    pathname.startsWith("/_") ||
    pathname.startsWith("/api") ||
    pathname.includes(".") ||
    pathname === "/favicon.ico"
  ) {
    return NextResponse.next();
  }
  
  const sessionToken = request.cookies.get("sb-access-token")?.value;
  const isAuthenticated = sessionToken && !isTokenExpired(sessionToken);
  
  // Extract custom user role from JWT metadata
  let userRole: string | undefined;
  if (isAuthenticated && sessionToken) {
    const payload = getJwtPayload(sessionToken);
    userRole = payload?.user_metadata?.role;
  }
  
  const isAuthRoute = 
    pathname === "/login" || 
    pathname === "/register" || 
    pathname.startsWith("/activate") || 
    pathname.startsWith("/reset-password");
    
  const isSetupRoute = pathname.startsWith("/register/email-setup") || pathname.startsWith("/register/done");
  
  // Route guard: only superadmin can access superadmin routes
  if (pathname.startsWith("/superadmin")) {
    if (!isAuthenticated) {
      const loginUrl = new URL("/login", request.url);
      return NextResponse.redirect(loginUrl);
    }
    if (userRole !== "superadmin") {
      const loginUrl = new URL("/login", request.url);
      return NextResponse.redirect(loginUrl);
    }
    return NextResponse.next();
  }

  // Route guard: only admin can access admin routes
  if (pathname.startsWith("/admin")) {
    if (!isAuthenticated) {
      const loginUrl = new URL("/login", request.url);
      return NextResponse.redirect(loginUrl);
    }
    if (userRole !== "admin") {
      const loginUrl = new URL("/login", request.url);
      return NextResponse.redirect(loginUrl);
    }
    return NextResponse.next();
  }

  // Route guard: only employees can access employee routes
  if (pathname.startsWith("/employee")) {
    if (!isAuthenticated) {
      const loginUrl = new URL("/login", request.url);
      return NextResponse.redirect(loginUrl);
    }
    if (userRole === "admin") {
      const adminUrl = new URL("/admin", request.url);
      return NextResponse.redirect(adminUrl);
    }
    if (userRole === "superadmin") {
      const superadminUrl = new URL("/superadmin", request.url);
      return NextResponse.redirect(superadminUrl);
    }
    return NextResponse.next();
  }
  
  if (!isAuthenticated) {
    // Unauthenticated users attempting to access dashboard or setup pages are sent to login
    if (!isAuthRoute) {
      const loginUrl = new URL("/login", request.url);
      return NextResponse.redirect(loginUrl);
    }
  } else {
    // Redirect admins away from employee dashboard to admin portal
    if (pathname === "/" && userRole === "admin") {
      const adminUrl = new URL("/admin", request.url);
      return NextResponse.redirect(adminUrl);
    }

    // Redirect superadmins away from employee dashboard to superadmin portal
    if (pathname === "/" && userRole === "superadmin") {
      const superadminUrl = new URL("/superadmin", request.url);
      return NextResponse.redirect(superadminUrl);
    }
    
    // Redirect employees away from root to /employee
    if (pathname === "/" && userRole !== "admin" && userRole !== "superadmin") {
      const employeeUrl = new URL("/employee", request.url);
      return NextResponse.redirect(employeeUrl);
    }

    // Authenticated users attempting to go to login or register are sent to their respective dashboard
    if (isAuthRoute) {
      let targetPath = "/employee";
      if (userRole === "superadmin") {
        targetPath = "/superadmin";
      } else if (userRole === "admin") {
        targetPath = "/admin";
      }
      const redirectUrl = new URL(targetPath, request.url);
      return NextResponse.redirect(redirectUrl);
    }
  }
  
  return NextResponse.next();
}

