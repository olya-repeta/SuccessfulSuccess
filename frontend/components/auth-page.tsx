"use client";

import { ArrowRight, Clock, Sparkles, Users } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "react-oidc-context";

import { GoogleIcon, HeaderAuth } from "@/components/header-auth";
import { SiteHeader } from "@/components/site-header";
import { Button } from "@/components/ui/button";
import { FieldSeparator } from "@/components/ui/field";
import { authConfig, isAuthConfigured } from "@/lib/auth";

/** Decorative right-hand panel: a gradient canvas with floating "meeting" cards. */
function Showcase() {
  return (
    <div
      className="relative hidden overflow-hidden rounded-[2rem] lg:block"
      style={{
        backgroundImage:
          "linear-gradient(135deg, var(--canva-teal) 0%, var(--canva-blue) 45%, var(--canva-violet) 80%, var(--canva-pink) 120%)",
      }}
      aria-hidden
    >
      <div className="absolute -top-16 -left-16 size-64 rounded-full bg-white/15 blur-2xl" />
      <div className="absolute -right-10 -bottom-20 size-72 rounded-full bg-white/10 blur-2xl" />

      <div className="relative flex h-full flex-col justify-between p-10 text-white">
        <div>
          <p className="text-sm font-semibold tracking-wide text-white/80 uppercase">
            SuccessfulSuccess
          </p>
          <h2 className="mt-3 max-w-sm text-4xl leading-tight font-extrabold tracking-tight">
            Every meeting, beautifully organised.
          </h2>
        </div>

        <div className="relative h-72">
          <div className="absolute top-0 left-0 w-64 -rotate-3 rounded-3xl bg-white p-4 text-[var(--canva-ink)] shadow-2xl">
            <div className="tint-violet inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold">
              <Clock className="size-3.5" /> 09:30 – 10:00
            </div>
            <p className="mt-3 font-bold">Daily stand-up</p>
            <p className="text-muted-foreground text-sm">
              Design team · Room 3
            </p>
          </div>
          <div className="absolute top-24 right-0 w-60 rotate-2 rounded-3xl bg-white p-4 text-[var(--canva-ink)] shadow-2xl">
            <div className="tint-teal inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold">
              <Users className="size-3.5" /> 4 people
            </div>
            <p className="mt-3 font-bold">Sprint planning</p>
            <p className="text-muted-foreground text-sm">13:00 – 14:30</p>
          </div>
          <div className="absolute bottom-0 left-10 flex items-center gap-2 rounded-full bg-white/95 px-4 py-2.5 text-sm font-semibold text-[var(--canva-ink)] shadow-xl">
            <Sparkles className="size-4 text-[var(--canva-pink)]" /> 3 meetings
            today
          </div>
        </div>
      </div>
    </div>
  );
}

export function AuthPage() {
  const auth = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (auth.isAuthenticated) {
      router.replace("/today");
    }
  }, [auth.isAuthenticated, router]);

  const onGoogle = () => {
    void auth.signinRedirect({
      extraQueryParams: { identity_provider: "Google" },
    });
  };

  const onSignIn = () => {
    void auth.signinRedirect();
  };

  return (
    <>
      <SiteHeader>
        <div className="ml-auto">
          <HeaderAuth />
        </div>
      </SiteHeader>

      <main className="mx-auto grid w-full max-w-6xl flex-1 gap-8 p-4 sm:p-6 lg:grid-cols-2 lg:p-8">
        <div className="flex flex-col">
          <div className="flex flex-1 items-center justify-center py-6">
            <div className="bg-card w-full max-w-md rounded-[2rem] border p-8 shadow-[0_24px_60px_-20px_rgba(139,61,255,0.25)] sm:p-10">
              <h1 className="text-center text-3xl font-extrabold tracking-tight">
                Log in or <span className="text-gradient-canva">sign up</span> in seconds
              </h1>
              <p className="text-muted-foreground mt-3 text-center text-sm">
                Sign in with your email and password or Google to manage your meetings.
              </p>

              {!isAuthConfigured ? (
                <div className="tint-amber mt-6 rounded-2xl px-4 py-3 text-sm">
                  Sign-in isn&apos;t configured. Run{" "}
                  <code>make aws-deploy-auth</code> and put the values from{" "}
                  <code>make aws-auth-env</code> in <code>.env</code>.
                </div>
              ) : null}

              {auth.isAuthenticated ? (
                <div className="mt-8 space-y-4 text-center">
                  <p className="text-sm font-medium">
                    You are signed in as{" "}
                    <span className="font-semibold">
                      {auth.user?.profile.email ?? auth.user?.profile.name}
                    </span>
                  </p>
                  <Button asChild className="h-12 w-full gap-2 text-[0.95rem]">
                    <Link href="/today">
                      <span>Go to your meetings</span>
                      <ArrowRight className="size-4" />
                    </Link>
                  </Button>
                </div>
              ) : (
                <div className="mt-8 space-y-4">
                  <Button
                    type="button"
                    className="h-12 w-full text-[0.95rem]"
                    onClick={onSignIn}
                  >
                    Sign in
                  </Button>

                  {authConfig.googleEnabled ? (
                    <>
                      <FieldSeparator className="my-3">or</FieldSeparator>
                      <Button
                        type="button"
                        variant="outline"
                        className="h-12 w-full gap-3 text-[0.95rem]"
                        onClick={onGoogle}
                      >
                        <GoogleIcon className="size-5" />
                        Continue with Google
                      </Button>
                    </>
                  ) : null}
                </div>
              )}

              <p className="text-muted-foreground mt-8 text-center text-xs leading-relaxed">
                By continuing, you agree to the SuccessfulSuccess Terms of Use
                and acknowledge the Privacy Policy.
              </p>
            </div>
          </div>
        </div>

        <Showcase />
      </main>
    </>
  );
}
