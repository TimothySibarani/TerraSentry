import { useEffect, useState } from "react";
import SupplierDetail from "./SupplierDetail.jsx";

/**
 * Reads the supplier id from the URL.
 *
 * The page is statically built, so the id arrives as a query parameter at runtime rather
 * than at build time. That keeps the URL shareable -- /supplier/?id=SUP-001 can be
 * bookmarked, sent to a colleague, or opened straight from an email, which the previous
 * toggle-based panel could not do.
 */
export default function SupplierPage() {
  const [id, setId] = useState(null);

  useEffect(() => {
    setId(new URLSearchParams(window.location.search).get("id"));
  }, []);

  if (id === null) return <div className="empty">Loading…</div>;
  if (!id) {
    return (
      <div className="empty">
        No supplier specified. <a href="/" style={{ color: "var(--accent)" }}>Back to the supply base</a>.
      </div>
    );
  }
  return <SupplierDetail supplierId={id} />;
}
