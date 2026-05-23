import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./lib/pdfjsSetup";          // register pdf.js worker before any <Document> mounts
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
