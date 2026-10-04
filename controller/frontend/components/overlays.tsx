"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { IconMore, IconX } from "./icons";

function useEscape(onClose: () => void, active = true) {
  useEffect(() => {
    if (!active) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose, active]);
}

/** Move focus into an overlay on open and restore it on close. */
function useFocusTrap(ref: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current;
    const first = el?.querySelector<HTMLElement>("[data-autofocus], input, textarea, select, button");
    first?.focus();
    return () => prev?.focus?.();
  }, [ref]);
}

export function Dialog({
  title,
  description,
  children,
  footer,
  onClose,
  wide,
}: {
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEscape(onClose);
  useFocusTrap(ref);
  return createPortal(
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} className={`dialog${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined}>
        <div className="dialog-header">
          <h2 style={{ fontSize: 16 }}>{title}</h2>
          {description && <p className="muted" style={{ marginTop: 4 }}>{description}</p>}
        </div>
        {children && <div className="dialog-body">{children}</div>}
        {footer && <div className="dialog-footer">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function Drawer({
  title,
  subtitle,
  actions,
  children,
  onClose,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEscape(onClose);
  useFocusTrap(ref);
  return createPortal(
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside ref={ref} className="drawer" role="dialog" aria-modal="true">
        <div className="drawer-header">
          <div className="grow">
            <h2 style={{ fontSize: 16 }}>{title}</h2>
            {subtitle && <div className="muted small" style={{ marginTop: 2 }}>{subtitle}</div>}
          </div>
          {actions}
          <button type="button" className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close" data-autofocus>
            <IconX />
          </button>
        </div>
        <div className="drawer-body">{children}</div>
      </aside>
    </div>,
    document.body,
  );
}

export type MenuItem =
  | { label: ReactNode; icon?: ReactNode; onSelect: () => void; danger?: boolean; disabled?: boolean }
  | { href: string; label: ReactNode; icon?: ReactNode; download?: boolean }
  | "separator";

export function Menu({ items, label = "More actions" }: { items: MenuItem[]; label?: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useEscape(close, open);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);
  return (
    <div className="menu" ref={ref}>
      <button
        type="button"
        className="btn btn-icon"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label}
        title={label}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
      >
        <IconMore />
      </button>
      {open && (
        <div className="menu-list" role="menu" onClick={(e) => e.stopPropagation()}>
          {items.map((item, i) =>
            item === "separator" ? (
              <div key={i} className="menu-sep" role="separator" />
            ) : "href" in item ? (
              <a key={i} className="menu-item" role="menuitem" href={item.href} download={item.download} onClick={close}>
                {item.icon}
                {item.label}
              </a>
            ) : (
              <button
                key={i}
                type="button"
                role="menuitem"
                className={`menu-item${item.danger ? " danger" : ""}`}
                disabled={item.disabled}
                onClick={() => {
                  close();
                  item.onSelect();
                }}
              >
                {item.icon}
                {item.label}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  );
}

// ── Toasts + confirm ───────────────────────────────────────────────

type Toast = { id: number; message: ReactNode; tone?: "danger" };
type ConfirmOptions = { title: string; body?: ReactNode; confirmLabel?: string; danger?: boolean };

const FeedbackCtx = createContext<{
  toast: (message: ReactNode, tone?: "danger") => void;
  confirm: (opts: ConfirmOptions) => Promise<boolean>;
} | null>(null);

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [pending, setPending] = useState<(ConfirmOptions & { resolve: (v: boolean) => void }) | null>(null);
  const seq = useRef(0);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const toast = useCallback((message: ReactNode, tone?: "danger") => {
    const id = ++seq.current;
    setToasts((t) => [...t, { id, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "danger" ? 7000 : 3500);
  }, []);

  const confirm = useCallback(
    (opts: ConfirmOptions) => new Promise<boolean>((resolve) => setPending({ ...opts, resolve })),
    [],
  );

  const settle = (v: boolean) => {
    pending?.resolve(v);
    setPending(null);
  };

  return (
    <FeedbackCtx.Provider value={{ toast, confirm }}>
      {children}
      {mounted &&
        createPortal(
          <div className="toasts" aria-live="polite">
            {toasts.map((t) => (
              <div key={t.id} className="toast" data-tone={t.tone}>
                {t.message}
              </div>
            ))}
          </div>,
          document.body,
        )}
      {pending && (
        <Dialog
          title={pending.title}
          onClose={() => settle(false)}
          footer={
            <>
              <button type="button" className="btn" onClick={() => settle(false)}>
                Cancel
              </button>
              <button
                type="button"
                className={`btn ${pending.danger ? "btn-danger-solid" : "btn-primary"}`}
                onClick={() => settle(true)}
                data-autofocus
              >
                {pending.confirmLabel ?? "Confirm"}
              </button>
            </>
          }
        >
          {pending.body && <div className="muted">{pending.body}</div>}
        </Dialog>
      )}
    </FeedbackCtx.Provider>
  );
}

export function useFeedback() {
  const ctx = useContext(FeedbackCtx);
  if (!ctx) throw new Error("useFeedback must be used inside FeedbackProvider");
  return ctx;
}
