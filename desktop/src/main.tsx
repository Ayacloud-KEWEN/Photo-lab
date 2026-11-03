import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { BackendProvider } from "@/api/backend-context";
import { TooltipProvider } from "@/components/ui/tooltip";
import "@/i18n";
import "@/styles/globals.css";

import App from "./App";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BackendProvider>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider delayDuration={400}>
          <App />
        </TooltipProvider>
      </QueryClientProvider>
    </BackendProvider>
  </StrictMode>,
);
