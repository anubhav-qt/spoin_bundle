"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    const checkAuth = async () => {
      // If there is no token in localStorage, redirect immediately
      if (!localStorage.getItem("spoin_access_token")) {
        router.push("/login");
        return;
      }

      try {
        await api.me();
        setLoading(false);
      } catch (error) {
        // If api.ts didn't already intercept and redirect, do it here.
        router.push("/login");
      }
    };
    checkAuth();
  }, [router]);

  if (loading) {
    // Minimal loading state matching the theme
    return (
      <div className="auth-layout" style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div className="auth-loader" style={{ transform: "scale(1.5)" }} />
      </div>
    );
  }

  return <>{children}</>;
}
