import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Sign in — SuccessfulSuccess",
};

export default function LoginLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
