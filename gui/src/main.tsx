import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AppProvider } from "./AppContext";
import { App } from "./App";
import { createBackend, selectBackendKind } from "./backend/select";
import "./styles.css";

const kind = selectBackendKind(window.location.search, import.meta.env.VITE_BACKEND);
const backend = createBackend(kind);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppProvider backend={backend}>
      <App />
    </AppProvider>
  </StrictMode>,
);
