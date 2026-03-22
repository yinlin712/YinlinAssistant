import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";

// 文件说明：
// 本文件是 React Webview 的入口，负责挂载根组件并注入头像资源。

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
