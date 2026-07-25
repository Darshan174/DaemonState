import { Navigate, useLocation } from "react-router-dom";

export default function PreparePage() {
  const location = useLocation();
  return <Navigate replace to={{ pathname: "/app", search: location.search }} />;
}
