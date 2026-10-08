"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  AuthProvider as OidcAuthProvider,
  useAuth as useOidcAuth,
} from "react-oidc-context";
import { useEffect, useRef } from "react";

import { syncMe } from "@/lib/api";
import { oidcConfig } from "@/lib/auth";

function AuthSync({ children }: { children: React.ReactNode }) {
  const auth = useOidcAuth();
  const queryClient = useQueryClient();
  const syncedSub = useRef<string | null>(null);

  useEffect(() => {
    if (auth.isAuthenticated && auth.user?.id_token && auth.user.profile.sub) {
      const sub = auth.user.profile.sub;
      if (syncedSub.current !== sub) {
        syncedSub.current = sub;
        queryClient.clear();
        syncMe(auth.user.id_token).catch((error) =>
          console.warn("Profile sync failed", error),
        );
      }
    } else if (!auth.isAuthenticated) {
      if (syncedSub.current !== null) {
        syncedSub.current = null;
        queryClient.clear();
      }
    }
  }, [auth.isAuthenticated, auth.user, queryClient]);

  return <>{children}</>;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  return (
    <OidcAuthProvider
      {...oidcConfig}
      onSigninCallback={() => {
        if (typeof window !== "undefined") {
          window.history.replaceState(
            {},
            document.title,
            window.location.pathname,
          );
        }
      }}
    >
      <AuthSync>{children}</AuthSync>
    </OidcAuthProvider>
  );
}

export { useOidcAuth as useAuth };
