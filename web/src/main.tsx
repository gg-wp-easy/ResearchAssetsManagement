import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/golos-text/400.css";
import "@fontsource/golos-text/500.css";
import "@fontsource/golos-text/600.css";
import "@fontsource/golos-text/700.css";
import "@fontsource/pt-serif/400.css";
import "@fontsource/pt-serif/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "./styles.css";
import App from "./App";
import { applyThemeMode, savedThemeMode } from "./theme";

applyThemeMode(savedThemeMode());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
