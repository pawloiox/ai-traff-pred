import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import LandingPage from "./features/roles/LandingPage.jsx";
import DispatcherDashboard from "./features/dispatcher/DispatcherDashboard.jsx";
import DriverView from "./features/driver/DriverView.jsx";
import ClientPortal from "./features/client-tracking/ClientPortal.jsx";

// Przelacznik widoku po hashu (SPA serwowane przez FastAPI pod /app):
//   #/kierowca    -> mobilny HUD kierowcy
//   #/klient      -> portal klienta B2B
//   #/dyspozytor  -> podglad dashboardu firmy (realnie: Vanilla /dyspozytor)
//   (domyslnie)   -> strona tytulowa (wybor roli)
const h = window.location.hash;
const view =
  h === "#/kierowca" ? <DriverView /> :
  h === "#/klient" ? <ClientPortal /> :
  h === "#/dyspozytor" ? <DispatcherDashboard /> :
  <LandingPage />;

window.addEventListener("hashchange", () => window.location.reload());

createRoot(document.getElementById("root")).render(
  <StrictMode>{view}</StrictMode>
);
