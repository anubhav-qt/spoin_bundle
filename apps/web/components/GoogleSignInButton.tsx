"use client";

/**
 * Google Identity Services button. Renders disabled if
 * NEXT_PUBLIC_GOOGLE_CLIENT_ID isn't set (mirrors the API's own
 * `settings.google_client_id` gate on `/auth/google` — a configured client ID
 * on one side with none on the other is a broken button, not a working one).
 */

import { useEffect, useRef } from "react";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: {
            client_id: string;
            callback: (response: { credential: string }) => void;
          }) => void;
          renderButton: (parent: HTMLElement, options: Record<string, unknown>) => void;
        };
      };
    };
  }
}

const SCRIPT_ID = "google-identity-services";

interface Props {
  onToken: (idToken: string) => void;
}

export function GoogleSignInButton({ onToken }: Props) {
  const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!clientId) return;

    function render() {
      if (!window.google || !containerRef.current) return;
      window.google.accounts.id.initialize({
        client_id: clientId!,
        callback: (response) => onToken(response.credential),
      });
      window.google.accounts.id.renderButton(containerRef.current, {
        theme: "outline",
        size: "large",
        width: 320,
        text: "continue_with",
      });
    }

    if (window.google) {
      render();
      return;
    }
    if (document.getElementById(SCRIPT_ID)) return;

    const script = document.createElement("script");
    script.id = SCRIPT_ID;
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = render;
    document.body.appendChild(script);
  }, [clientId, onToken]);

  if (!clientId) {
    return (
      <button type="button" className="auth-button auth-button-secondary" disabled>
        Google sign-in not configured
      </button>
    );
  }

  return <div ref={containerRef} className="auth-google-button" />;
}
