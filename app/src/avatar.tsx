// アバター試作ページの入口(avatar.html)。チャット画面(main.tsx)とは別ページにして互いに影響させない。
import React from "react";
import { createRoot } from "react-dom/client";
import { AvatarApp } from "./features/avatar/AvatarApp";
import "./features/avatar/avatar.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AvatarApp />
  </React.StrictMode>,
);
