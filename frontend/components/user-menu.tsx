"use client";

import { LogOut } from "lucide-react";
import { useAuth } from "react-oidc-context";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { initials } from "@/lib/datetime";
import { signOut } from "@/lib/auth";

export function UserMenu() {
  const auth = useAuth();
  const user = auth.user;
  if (!user) return null;

  const email = user.profile.email;
  const name = user.profile.name;
  const label = name ?? email ?? "Account";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon-lg"
          className="rounded-full"
          aria-label="Account menu"
        >
          <Avatar className="size-9">
            <AvatarFallback className="tint-violet text-xs font-semibold">
              {initials(name ?? email?.split("@")[0] ?? "?")}
            </AvatarFallback>
          </Avatar>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuLabel className="font-normal">
          <p className="truncate text-sm font-semibold">{label}</p>
          {email && email !== label ? (
            <p className="text-muted-foreground truncate text-xs">
              {email}
            </p>
          ) : null}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void signOut(() => auth.removeUser())}>
          <LogOut aria-hidden />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
