import { AuthForm } from "@/components/AuthForm";

/**
 * Same form as /signup — AuthForm detects a signed-in guest via useAuth()
 * and calls /auth/claim instead of /auth/register, in place on the same
 * user_id. Reachable at any point (see AuthProvider's REDIRECT_EXEMPT_PATHS).
 */
export default function ClaimPage() {
  return <AuthForm mode="register" />;
}
