import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WorkspaceProvider } from "./context/WorkspaceContext";
import { ThemeProvider } from "./context/ThemeContext";
import App from "./App";
import "@fontsource-variable/archivo/wght.css";
import "@fontsource-variable/archivo/wght-italic.css";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 1000 * 60 * 5 } },
});

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <WorkspaceProvider>
            <App />
          </WorkspaceProvider>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
