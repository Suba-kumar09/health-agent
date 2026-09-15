import { Outlet } from "react-router-dom";
import { Sidebar } from "./layout/Sidebar";
import "./App.css";

function App() {
  return (
    <div className="shell">
      <Sidebar />
      <main className="page-content">
        <Outlet />
      </main>
    </div>
  );
}

export default App;
