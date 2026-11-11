import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { CursorFX } from "./components/CursorFX";
import "./styles.css";
import "./refresh.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
    <CursorFX />
  </StrictMode>,
);
