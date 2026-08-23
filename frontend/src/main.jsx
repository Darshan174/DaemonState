import React from "react";
import ReactDOM from "react-dom/client";
import { ClerkProvider } from "@clerk/react";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CLERK_WAITLIST_URL, clerkWaitlistEnabled } from "./auth/clerk";
import { WorkspaceProvider } from "./context/WorkspaceContext";
import { ThemeProvider } from "./context/ThemeContext";
import { initializeWaitlistAnalytics } from "./waitlist/tracking";
import App from "./App";
import "@fontsource-variable/archivo/wght.css";
import "@fontsource-variable/archivo/wght-italic.css";
import "./index.css";

void initializeWaitlistAnalytics(import.meta.env);

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 1000 * 60 * 5 } },
});

const app = (
  <QueryClientProvider client={queryClient}>
    <ThemeProvider>
      <BrowserRouter>
        <WorkspaceProvider>
          <App />
        </WorkspaceProvider>
      </BrowserRouter>
    </ThemeProvider>
  </QueryClientProvider>
);

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    {clerkWaitlistEnabled(import.meta.env) ? (
      <ClerkProvider waitlistUrl={CLERK_WAITLIST_URL}>
        {app}
      </ClerkProvider>
    ) : app}
  </React.StrictMode>,
);
