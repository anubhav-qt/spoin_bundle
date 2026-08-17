import { AuthProvider } from "@/components/AuthProvider";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}
