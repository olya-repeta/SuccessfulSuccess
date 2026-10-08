import { UserManager, type UserManagerSettings } from "oidc-client-ts";

export const authConfig = {
  userPoolId: process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID ?? "",
  clientId: process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID ?? "",
  domain: process.env.NEXT_PUBLIC_COGNITO_DOMAIN ?? "",
  region: process.env.NEXT_PUBLIC_COGNITO_REGION ?? "us-east-1",
  authority:
    process.env.NEXT_PUBLIC_COGNITO_AUTHORITY ||
    (process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID
      ? `https://cognito-idp.${process.env.NEXT_PUBLIC_COGNITO_REGION ?? "us-east-1"}.amazonaws.com/${process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID}`
      : ""),
  redirectUri:
    process.env.NEXT_PUBLIC_COGNITO_REDIRECT_URI ||
    (typeof window !== "undefined"
      ? `${window.location.origin}/`
      : "http://localhost:3000/"),
  googleEnabled: process.env.NEXT_PUBLIC_COGNITO_GOOGLE_ENABLED === "true",
  scope: "openid email profile",
};

export const isAuthConfigured = Boolean(
  authConfig.authority && authConfig.clientId,
);

export const oidcConfig: UserManagerSettings = {
  authority: authConfig.authority,
  client_id: authConfig.clientId,
  redirect_uri: authConfig.redirectUri,
  response_type: "code",
  scope: authConfig.scope,
  automaticSilentRenew: false,
};

let userManager: UserManager | null = null;

export function getUserManager(): UserManager | null {
  if (typeof window === "undefined" || !isAuthConfigured) return null;
  if (!userManager) {
    userManager = new UserManager(oidcConfig);
  }
  return userManager;
}

/** The current access token, or null when signed out or expired. */
export async function getAccessToken(): Promise<string | null> {
  if (!isAuthConfigured) return null;
  const manager = getUserManager();
  if (!manager) return null;
  try {
    let user = await manager.getUser();
    if (!user) return null;
    if (user.expired) {
      try {
        user = await manager.signinSilent();
      } catch {
        return null;
      }
    }
    return user?.access_token ?? null;
  } catch {
    return null;
  }
}

/**
 * Sign-out: Cognito does not implement OIDC's standard end-session endpoint.
 * Clear the local session, then send the browser to:
 * https://<prefix>.auth.us-east-1.amazoncognito.com/logout?client_id=…&logout_uri=…
 */
export async function signOut(authRemoveUser?: () => Promise<void>) {
  if (typeof window === "undefined") return;

  if (authRemoveUser) {
    try {
      await authRemoveUser();
    } catch {
      // ignore
    }
  }

  const manager = getUserManager();
  if (manager) {
    try {
      await manager.removeUser();
      await manager.clearStaleState();
    } catch {
      // ignore
    }
  }

  const { domain, clientId, redirectUri } = authConfig;
  const logoutUri = redirectUri || `${window.location.origin}/`;

  if (domain && clientId) {
    const host = domain.replace(/^https?:\/\//, "");
    const url = new URL(`https://${host}/logout`);
    url.searchParams.set("client_id", clientId);
    url.searchParams.set("logout_uri", logoutUri);
    window.location.href = url.toString();
  } else {
    window.location.replace("/");
  }
}

/** Cognito errors carry a readable message; fall back for anything else. */
export function authErrorMessage(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : "Something went wrong.";
}
