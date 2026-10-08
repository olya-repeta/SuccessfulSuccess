"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import { useAuth } from "react-oidc-context";

import { AuthLoading } from "@/components/require-auth";
import { Button } from "@/components/ui/button";

export default function LoginPage() {
  const auth = useAuth();
  const router = useRouter();
  const hasRedirected = useRef(false);

  useEffect(() => {
    if (auth.isLoading) return;

    if (auth.isAuthenticated) {
      router.replace("/today");
      return;
    }

    if (!hasRedirected.current) {
      hasRedirected.current = true;
      void auth.signinRedirect().catch((error) => {
        console.error("signinRedirect failed:", error);
      });
    }
  }, [auth, auth.isLoading, auth.isAuthenticated, router]);

  if (auth.error) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 py-24 text-center">
        <p className="text-destructive text-base font-semibold">Sign-in error</p>
        <p className="text-muted-foreground max-w-md text-sm">
          {auth.error.message}
        </p>
        <Button
          onClick={() => {
            hasRedirected.current = false;
            void auth.signinRedirect();
          }}
        >
          Try again
        </Button>
      </div>
    );
  }

  return <AuthLoading label="Redirecting to sign in…" />;
}
