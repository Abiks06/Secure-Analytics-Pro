import { lazy, Suspense, useEffect, type ReactNode } from "react";
import { createBrowserRouter, Navigate, RouterProvider, useLocation } from "react-router";
import { LogoMark } from "./components/Brand";
import { initAuth, useAuth } from "./lib/api";

const Landing = lazy(() => import("./pages/Landing"));
const AuthPage = lazy(() => import("./pages/Auth"));
const AppShell = lazy(() => import("./components/AppShell"));
const Workspace = lazy(() => import("./pages/Workspace"));
const DatasetPage = lazy(() => import("./pages/dataset/DatasetPage"));
const Security = lazy(() => import("./pages/Security"));

function Splash() {
  return (
    <div className="grid min-h-dvh place-items-center bg-ink-950">
      <div className="flex flex-col items-center gap-4">
        <LogoMark className="size-12 animate-pulse" />
        <div className="h-0.5 w-32 overflow-hidden rounded-full bg-white/5">
          <div className="skeleton h-full w-full" />
        </div>
      </div>
    </div>
  );
}

function RequireAuth({ children }: { children: ReactNode }) {
  const status = useAuth((s) => s.status);
  const location = useLocation();
  if (status === "loading") return <Splash />;
  if (status === "anon") return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

function GuestOnly({ children }: { children: ReactNode }) {
  const status = useAuth((s) => s.status);
  const recovering = useAuth((s) => s.recovering);
  if (status === "loading") return <Splash />;
  if (status === "authed" && !recovering) return <Navigate to="/app" replace />;
  return <>{children}</>;
}

const s = (el: ReactNode) => <Suspense fallback={<Splash />}>{el}</Suspense>;

const router = createBrowserRouter([
  { path: "/", element: s(<Landing />) },
  { path: "/login", element: s(<GuestOnly><AuthPage mode="login" /></GuestOnly>) },
  { path: "/register", element: s(<GuestOnly><AuthPage mode="register" /></GuestOnly>) },
  { path: "/forgot-password", element: s(<GuestOnly><AuthPage mode="forgot" /></GuestOnly>) },
  { path: "/reset-password", element: s(<AuthPage mode="reset" />) },
  {
    path: "/app",
    element: s(<RequireAuth><AppShell /></RequireAuth>),
    children: [
      { index: true, element: s(<Workspace />) },
      { path: "datasets/:id", element: s(<DatasetPage />) },
      { path: "security", element: s(<Security />) },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
]);

export default function App() {
  useEffect(() => initAuth(), []);
  return <RouterProvider router={router} />;
}
