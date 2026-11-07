import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import ToastProvider from "./ToastProvider.jsx";
import "./styles.css";
import "./reviewer.css";
createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </React.StrictMode>,
);
