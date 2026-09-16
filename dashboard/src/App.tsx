import { Outlet } from "react-router-dom";
import { Sidebar } from "./layout/Sidebar";
import { Header } from "./layout/Header";
import "./App.css";

function App() {
  return (
    <div className="shell">
      <Sidebar />
      <div className="shell__content">
        <Header />
        <main className="page-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export default App;
