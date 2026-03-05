import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/core/auth";
import { useAppConfig } from "@/core/config";

export function Login() {
  const { login, isAuthenticated, isLoading } = useAuth();
  const { brand } = useAppConfig();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
    setSubmitting(true);

    try {
      await login(email, password);
      void navigate("/workspace", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a] px-4">
      <div className="w-full max-w-sm space-y-8">
        <div className="text-center">
          <h1 className="text-2xl font-semibold tracking-tight text-white">
            Sign in to {brand.name}
          </h1>
          <p className="text-muted-foreground mt-2 text-sm">
            Enter your credentials to access your workspace
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
              autoFocus
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
              placeholder="Enter your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              minLength={8}
              className="bg-neutral-900/50 border-neutral-700 text-white placeholder:text-neutral-500"
            />
          </div>

          <Button
            type="submit"
            className="w-full"
            disabled={submitting || !email || !password}
          >
            {submitting ? "Signing in..." : "Sign in"}
          </Button>
        </form>

        <p className="text-muted-foreground text-center text-sm">
          Don&apos;t have an account?{" "}
          <Link
            to="/register"
            className="text-primary font-medium hover:underline"
          >
            Create one
          </Link>
        </p>
      </div>
    </div>
  );
}
