import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

interface TipState {
  x: number;
  y: number;
  content: ReactNode;
}

interface TipApi {
  showAt: (x: number, y: number, content: ReactNode) => void;
  hide: () => void;
}

const TipContext = createContext<TipApi>({ showAt: () => {}, hide: () => {} });

// One tooltip for the whole app, positioned above whatever is hovered or focused.
export function TooltipProvider({ children }: { children: ReactNode }) {
  const [tip, setTip] = useState<TipState | null>(null);
  const showAt = useCallback((x: number, y: number, content: ReactNode) => setTip({ x, y, content }), []);
  const hide = useCallback(() => setTip(null), []);
  const api = useMemo(() => ({ showAt, hide }), [showAt, hide]);

  // The tooltip is fixed-position, so it would float away from its target on scroll.
  useEffect(() => {
    if (!tip) return;
    window.addEventListener("scroll", hide, { capture: true, passive: true });
    return () => window.removeEventListener("scroll", hide, { capture: true });
  }, [tip, hide]);
  return (
    <TipContext.Provider value={api}>
      {children}
      {tip && (
        <div className="tooltip" role="tooltip" style={{ left: tip.x, top: tip.y }}>
          {tip.content}
        </div>
      )}
    </TipContext.Provider>
  );
}

export function useTooltip() {
  const api = useContext(TipContext);
  // Spread the result onto any hoverable/focusable element.
  const tipProps = useCallback(
    (content: ReactNode) => {
      const show = (el: Element) => {
        const r = el.getBoundingClientRect();
        api.showAt(r.left + r.width / 2, r.top, content);
      };
      return {
        onMouseEnter: (e: React.MouseEvent) => show(e.currentTarget),
        onMouseLeave: api.hide,
        onFocus: (e: React.FocusEvent) => show(e.currentTarget),
        onBlur: api.hide,
      };
    },
    [api],
  );
  return { tipProps, ...api };
}
