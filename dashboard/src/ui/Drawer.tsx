import { useEffect, useRef, type ReactNode } from "react";
import { CloseIcon } from "./icons";
import { useTooltip } from "./Tooltip";

interface DrawerProps {
  chip?: ReactNode;
  title: string;
  meta?: string;
  onClose: () => void;
  children: ReactNode;
}

// Side panel (bottom sheet on phones) for click-through details.
export function Drawer({ chip, title, meta, onClose, children }: DrawerProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const { hide } = useTooltip();

  useEffect(() => {
    hide();
    const previous = document.activeElement as HTMLElement | null;
    document.body.classList.add("drawer-open");
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.classList.remove("drawer-open");
      // Returning focus fires the element's focus tooltip; the user didn't ask for it.
      previous?.focus?.();
      hide();
    };
  }, [onClose, hide]);

  // Opening a different item in the same drawer starts at the top.
  useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 });
  }, [title]);

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
        <div className="drawer-head">
          <div className="grow">
            {chip}
            <h3 id="drawer-title">{title}</h3>
            {meta && <div className="meta">{meta}</div>}
          </div>
          <button ref={closeRef} className="icon-btn" onClick={onClose} aria-label="Close details">
            <CloseIcon />
          </button>
        </div>
        <div className="drawer-body" ref={bodyRef}>
          {children}
        </div>
      </aside>
    </>
  );
}
