import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Webview root element was not found.");
}

const avatarUri = document.body.dataset.avatarUri;
createRoot(rootElement).render(
  <React.StrictMode>
    <App avatarUri={avatarUri} />
  </React.StrictMode>
);
