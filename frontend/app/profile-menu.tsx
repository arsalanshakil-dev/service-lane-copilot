"use client";

// Advisor profile menu (issue #59): the ··· button beside the advisor name opens a small
// panel with Settings. Closes on Escape, outside click, or after a choice.

import { KeyboardEvent, useEffect, useRef, useState } from "react";

export function ProfileMenu() {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const firstItemRef = useRef<HTMLAnchorElement>(null);

  useEffect(() => {
    if (!open) return;
    firstItemRef.current?.focus();
    const onPointerDown = (event: PointerEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && open) {
      event.preventDefault();
      setOpen(false);
      buttonRef.current?.focus();
    }
  }

  return (
    <div className="profile-menu-wrap" ref={wrapRef} onKeyDown={onKeyDown}>
      <button ref={buttonRef} type="button" className="more profile-menu-button" aria-haspopup="menu" aria-expanded={open} aria-controls="profile-menu"
        aria-label="Profile menu" title="Profile menu" onClick={() => setOpen((value) => !value)}>···</button>
      {open && (
        <div className="profile-menu" id="profile-menu" role="menu" aria-label="Profile">
          <a ref={firstItemRef} role="menuitem" className="profile-menu-item" href="#settings" onClick={() => setOpen(false)}>
            <span className="nav-icon" aria-hidden="true">⚙</span> Settings
          </a>
        </div>
      )}
    </div>
  );
}
