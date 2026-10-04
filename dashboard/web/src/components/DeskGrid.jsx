import { useLayoutEffect, useRef, useState } from "react";
import { arrangeColumns } from "../lib/columns.js";

const WIDE = "(min-width: 1200px)";

function useWideDesk() {
  const [wide, setWide] = useState(() => window.matchMedia(WIDE).matches);
  useLayoutEffect(() => {
    const media = window.matchMedia(WIDE);
    const onChange = () => setWide(media.matches);
    onChange();
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return wide;
}

export function DeskGrid({ panels, renderPanel, prelude, children, onPointerLeave }) {
  const wide = useWideDesk();
  const balance = wide && panels.length > 0;
  const rootRef = useRef(null);
  const [measured, setMeasured] = useState(null);
  const signature = panels.map((panel) => `${panel.cat.id}:${panel.rows.length}:${panel.open}`).join("|");
  const arranged = balance ? arrangeColumns(panels, measured) : null;

  useLayoutEffect(() => {
    if (!balance) return undefined;
    const root = rootRef.current;
    if (!root) return undefined;
    const read = () => {
      const next = {};
      for (const panel of panels) {
        const el = root.querySelector(`[data-panel="${CSS.escape(panel.cat.id)}"]`);
        if (el) next[panel.cat.id] = Math.round(el.getBoundingClientRect().height);
      }
      setMeasured((prev) => {
        if (prev && panels.every((panel) => prev[panel.cat.id] === next[panel.cat.id])) return prev;
        return next;
      });
    };
    read();
    const observer = new ResizeObserver(read);
    for (const panel of panels) {
      const el = root.querySelector(`[data-panel="${CSS.escape(panel.cat.id)}"]`);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [balance, signature, panels]);

  return (
    <div
      ref={rootRef}
      className={balance ? "grid is-balanced" : "grid"}
      style={arranged ? { paddingTop: arranged.pad } : undefined}
      onPointerLeave={onPointerLeave}
    >
      {prelude}
      {panels.map((panel) => renderPanel(panel, arranged ? arranged.place.get(panel.cat.id) : null))}
      {children}
    </div>
  );
}
