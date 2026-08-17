"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Loader from "@/components/Loader";
import { getSessionProfile } from "@/lib/auth";

export default function RootPage() {
  const router = useRouter();

  useEffect(() => {
    getSessionProfile().then((profile) => {
      if (profile) {
        const role = profile.role;
        if (role === "admin") {
          router.replace("/admin");
        } else if (role === "superadmin") {
          router.replace("/superadmin");
        } else {
          router.replace("/employee");
        }
      } else {
        router.replace("/login");
      }
    }).catch(() => {
      router.replace("/login");
    });

  }, [router]);

  return <Loader variant="fullscreen" title="MediCORE" subtitle="Verifying your session..." />;
}
