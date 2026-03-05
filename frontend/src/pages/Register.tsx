import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/core/auth";
import { useAppConfig } from "@/core/config";

export function Register() {
  const { register, isAuthenticated, isLoading } = useAuth();
  const { brand } = useAppConfig();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (isLoading) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-[#0a0a0a]">
        <div className="border-primary h-8 w-8 animate-spin rounded-full border-4 border-t-transparent" />
      </div>
    );
  }

  if (isAuthenticated) {
    return <Navigate to="/workspace" replace />;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    if (!/\d/.test(password)) {
      setError("Password must contain at least one digit");
      return;
    }
    if (!/[a-zA-Z]/.test(password)) {
      setError("Password must contain at least one letter");
      return;
    }

    setSubmitting(true);

    try {
      await register(email, password, displayName ? displayName : undefined);
      void navigate("/workspace", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a] px-4">
      <div className="w-full max-w-sm space-y-8">
        <div className="text-center">
          <h1 className="text-2xl font-semibold tracking-tight text-white">
            Create your account
          </h1>
          <p className="text-muted-foreground mt-2 text-sm">
            Get started with {brand.name}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="rounded-md border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-400">
              {error}
            </div>
          )}

          <div className="space-y-2">
            <label
              htmlFor="displayName"
              className="text-sm font-medium text-neutral-300"
            >
              Display name{" "}
              <span className="text-neutral-500">(optional)</span>
            </label>
            <Input
              id="displayName"
              type="text"
              placeholder="Your name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              autoComplete="name"
              autoFocus
              maxLength={128}
              className="bg-neutral-900/50 border-neutral-700 text-white placeholder:text-neutral-500"
            />
          </div>

          <div className="space-y-2">
            <label
              htmlFor="email"
              className="text-sm font-medium text-neutral-300"
            >
              Email
            </label>
            <Input
              id="email"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              className="bg-neutral-900/50 border-neutral-700 text-white placeholder:text-neutral-500"
            />
          </div>

          <div className="space-y-2">
            <label
              htmlFor="password"
              className="text-sm font-medium text-neutral-300"
            >
              Password
            </label>
            <Input
              id="password"
              type="password"
              placeholder="Min. 8 characters with a letter and digit"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="new-password"
              minLength={8}
              maxLength={128}
              className="bg-neutral-900/50 border-neutral-700 text-white placeholder:text-neutral-500"
            />
          </div>

          <Button
            type="submit"
            className="w-full"
            disabled={submitting || !email || !password}
          >
            {submitting ? "Creating account..." : "Create account"}
          </Button>
        </form>

        <p className="text-muted-foreground text-center text-sm">
          Already have an account?{" "}
          <Link
            to="/login"
            className="text-primary font-medium hover:underline"
          >
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
