import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import LandingPage from "./features/roles/LandingPage.jsx";
import DispatcherDashboard from "./features/dispatcher/DispatcherDashboard.jsx";
import DriverView from "./features/driver/DriverView.jsx";
import ClientPortal from "./features/client-tracking/ClientPortal.jsx";

// Prosty przelacznik podgladu po hashu:
//   #/landing     -> strona tytulowa
//   #/dyspozytor  -> dashboard firmy
//   #/kierowca    -> mobilny HUD kierowcy
//   (domyslnie)   -> portal klienta B2B
const h = window.location.hash;
const view =
  h === "#/landing" ? <LandingPage /> :
  h === "#/dyspozytor" ? <DispatcherDashboard /> :
  h === "#/kierowca" ? <DriverView /> :
  <ClientPortal />;

window.addEventListener("hashchange", () => window.location.reload());

createRoot(document.getElementById("root")).render(
  <StrictMode>{view}</StrictMode>
);
