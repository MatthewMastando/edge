import { Outlet } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { localSession, resolveSession, type SessionUser } from "../auth/session";
import { NewChatDialog } from "../chat/NewChatDialog";
import { LeftRail } from "./LeftRail";
import { TopBar } from "./TopBar";

export function Shell() {
  const [user, setUser] = useState<SessionUser>(localSession);

  useEffect(() => {
    let cancelled = false;
    void resolveSession().then((next) => {
      if (!cancelled) setUser(next);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="app">
      <LeftRail user={user} />
      <div className="stage">
        <TopBar />
        <div className="stage-body">
          <Outlet />
        </div>
      </div>
      <NewChatDialog />
    </div>
  );
}
