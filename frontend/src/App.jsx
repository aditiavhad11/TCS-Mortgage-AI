import CustomerPortal from "./CustomerPortal";
import AdminPortal from "./AdminPortal";
import ReviewerPortal from "./ReviewerPortal";
import BankAdminPortal from "./BankAdminPortal";

export default function App() {
  const path = window.location.pathname;
  if (path.startsWith("/admin")) return <AdminPortal />;
  if (path.startsWith("/reviewer")) return <ReviewerPortal />;
  if (path.startsWith("/bank-admin")) return <BankAdminPortal />;
  return <CustomerPortal />;
}
