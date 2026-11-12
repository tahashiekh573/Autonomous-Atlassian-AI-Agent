import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { BackgroundFX } from "./components/BackgroundFX";
import { CursorFX } from "./components/CursorFX";
import { applyFx } from "./fx";
import "./styles.css";
import "./refresh.css";

applyFx();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BackgroundFX />
    <App />
    <CursorFX />
  </StrictMode>,
);
