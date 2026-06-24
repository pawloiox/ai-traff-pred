import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import LandingPage from "./features/roles/LandingPage.jsx";
import DispatcherDashboard from "./features/dispatcher/DispatcherDashboard.jsx";

// Prosty przelacznik podgladu: domyslnie dashboard firmy,
// strona tytulowa dostepna pod #/landing.
const view = window.location.hash === "#/landing" ? <LandingPage /> : <DispatcherDashboard />;

createRoot(document.getElementById("root")).render(
  <StrictMode>{view}</StrictMode>
);
