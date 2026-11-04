import React, { useEffect, useId, useRef, useState } from 'react';
import { Check } from 'lucide-react';

export interface MenuItem {
  id: string;
  label: string;
  icon?: React.ReactNode;
  /** Present for on/off items. They keep the menu open so several can be switched in a row. */
  checked?: boolean;
  title?: string;
  onSelect: () => void;
}

interface MenuButtonProps {
  label: string;
  icon: React.ReactNode;
  text?: string;
  items: MenuItem[];
  placement?: 'below' | 'above';
  className?: string;
  /** Small count shown on the button, for example how many layers are on. */
  badge?: number;
}

/** Button plus a small menu. Arrow keys move, Escape closes and returns focus, outside clicks close. */
export function MenuButton({ label, icon, text, items, placement = 'below', className = '', badge }: MenuButtonProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    itemRefs.current[0]?.focus({ preventScroll: true });
    const onPointer = (event: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointer);
    return () => document.removeEventListener('pointerdown', onPointer);
  }, [open]);

  const close = (refocus: boolean) => {
    setOpen(false);
    if (refocus) requestAnimationFrame(() => buttonRef.current?.focus({ preventScroll: true }));
  };
  const move = (delta: number) => {
    const current = itemRefs.current.findIndex((el) => el === document.activeElement);
    const next = (current + delta + items.length) % items.length;
    itemRefs.current[next]?.focus();
  };

  return (
    <div ref={rootRef} className={`wo-menu ${className}`}>
      <button ref={buttonRef} type="button" className={`wo-menu-button ${open ? 'is-open' : ''}`} aria-label={label} title={label}
        aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined} onClick={() => setOpen((value) => !value)}>
        {icon}{text && <span>{text}</span>}{badge ? <span className="wo-menu-badge">{badge}</span> : null}
      </button>
      {open && (
        <div id={menuId} role="menu" aria-label={label} className={`wo-menu-list is-${placement}`}
          onKeyDown={(event) => {
            if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(true); }
            else if (event.key === 'ArrowDown') { event.preventDefault(); move(1); }
            else if (event.key === 'ArrowUp') { event.preventDefault(); move(-1); }
            else if (event.key === 'Home') { event.preventDefault(); itemRefs.current[0]?.focus(); }
            else if (event.key === 'End') { event.preventDefault(); itemRefs.current[items.length - 1]?.focus(); }
            else if (event.key === 'Tab') close(false);
          }}>
          {items.map((item, index) => {
            const toggle = item.checked !== undefined;
            return (
              <button key={item.id} ref={(el) => { itemRefs.current[index] = el; }} type="button"
                role={toggle ? 'menuitemcheckbox' : 'menuitem'} aria-checked={toggle ? item.checked : undefined}
                tabIndex={-1} title={item.title} className={`wo-menu-item ${item.checked ? 'is-on' : ''}`}
                onClick={() => { item.onSelect(); if (!toggle) close(true); }}>
                <span className="wo-menu-item-icon" aria-hidden="true">{toggle ? (item.checked ? <Check size={14} /> : null) : item.icon}</span>
                <span>{item.label}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
