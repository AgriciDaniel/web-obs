/**
 * Shared building blocks for every Web-Obs panel. Keep panels quiet: one stat row,
 * sentence-case section titles, status shown with an icon and a word, details behind
 * tabs or disclosures. Charts follow the dataviz rules: thin marks, 2px surface gaps,
 * a legend for two or more parts, text in ink tokens only, hover titles on every mark.
 */
import React, { useId, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, ChevronRight, CircleDashed, Info, XCircle } from 'lucide-react';

export type Status = 'good' | 'warning' | 'critical' | 'neutral' | 'info';

const STATUS_ICON: Record<Status, React.ComponentType<{ size?: number; 'aria-hidden'?: boolean }>> = {
  good: CheckCircle2, warning: AlertTriangle, critical: XCircle, neutral: CircleDashed, info: Info,
};

export const formatCount = (value: number | null | undefined): string => {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'No data';
  if (Math.abs(value) >= 10000) return `${(value / 1000).toFixed(value >= 100000 ? 0 : 1)}K`;
  return value.toLocaleString('en-US');
};

/** Icon plus word. Colour never carries the meaning alone. */
export const StatusPill: React.FC<{ status: Status; label: React.ReactNode; title?: string }> = ({ status, label, title }) => {
  const Icon = STATUS_ICON[status];
  return <span className={`wo-ui-pill is-${status}`} title={title}><Icon size={12} aria-hidden /> {label}</span>;
};

export const StatTile: React.FC<{
  label: string; value: React.ReactNode; hint?: React.ReactNode; status?: Status; onClick?: () => void; icon?: React.ReactNode;
}> = ({ label, value, hint, status, onClick, icon }) => {
  const body = <>
    <span className="wo-ui-stat-label">{icon}{label}</span>
    <span className={`wo-ui-stat-value ${status ? `is-${status}` : ''}`}>{value}</span>
    {hint && <span className="wo-ui-stat-hint">{hint}</span>}
  </>;
  return onClick
    ? <button type="button" className="wo-ui-stat is-action" onClick={onClick}>{body}</button>
    : <div className="wo-ui-stat">{body}</div>;
};

export const StatRow: React.FC<{ children: React.ReactNode; label?: string }> = ({ children, label }) =>
  <div className="wo-ui-stat-row" role="group" aria-label={label}>{children}</div>;

export const Section: React.FC<{ title: string; aside?: React.ReactNode; children: React.ReactNode; id?: string }> = ({ title, aside, children, id }) =>
  <section className="wo-ui-section" aria-labelledby={id}>
    <header className="wo-ui-section-head"><h3 id={id}>{title}</h3>{aside && <span className="wo-ui-section-aside">{aside}</span>}</header>
    {children}
  </section>;

/** Collapsed by default. Use for caveats, long lists and raw tables. */
export const Disclosure: React.FC<{ summary: React.ReactNode; count?: number; defaultOpen?: boolean; children: React.ReactNode }> = ({ summary, count, defaultOpen = false, children }) =>
  <details className="wo-ui-disclosure" open={defaultOpen}>
    <summary><ChevronRight size={13} className="wo-ui-disclosure-chevron" aria-hidden="true" /><span>{summary}</span>{count !== undefined && <span className="wo-ui-count">{formatCount(count)}</span>}</summary>
    <div className="wo-ui-disclosure-body">{children}</div>
  </details>;

export interface KeyValue { label: string; value: React.ReactNode; status?: Status; title?: string }

/** Label left, value right, tabular figures. Rows with status get the icon, not a coloured value. */
export const KeyValueList: React.FC<{ rows: KeyValue[] }> = ({ rows }) =>
  <dl className="wo-ui-kv">
    {rows.map((row) => <div key={row.label} className="wo-ui-kv-row" title={row.title}>
      <dt>{row.label}</dt>
      <dd>{row.status ? <StatusPill status={row.status} label={row.value} /> : row.value}</dd>
    </div>)}
  </dl>;

export interface TabItem { id: string; label: string; badge?: number; content: React.ReactNode }

/** Segmented tabs with arrow-key support. Only the active panel renders. */
export const Tabs: React.FC<{ tabs: TabItem[]; label: string; initial?: string; onChange?: (id: string) => void }> = ({ tabs, label, initial, onChange }) => {
  const visible = tabs.filter(Boolean);
  const [active, setActive] = useState(initial && visible.some((t) => t.id === initial) ? initial : visible[0]?.id);
  const base = useId();
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const select = (index: number) => {
    const tab = visible[(index + visible.length) % visible.length];
    setActive(tab.id);
    onChange?.(tab.id);
    refs.current[(index + visible.length) % visible.length]?.focus();
  };
  const current = visible.find((t) => t.id === active) ?? visible[0];
  return <div className="wo-ui-tabs">
    <div className="wo-ui-tablist" role="tablist" aria-label={label} onKeyDown={(event) => {
      const index = visible.findIndex((t) => t.id === current?.id);
      if (event.key === 'ArrowRight') { event.preventDefault(); select(index + 1); }
      if (event.key === 'ArrowLeft') { event.preventDefault(); select(index - 1); }
      if (event.key === 'Home') { event.preventDefault(); select(0); }
      if (event.key === 'End') { event.preventDefault(); select(visible.length - 1); }
    }}>
      {visible.map((tab, index) => <button key={tab.id} ref={(el) => { refs.current[index] = el; }} type="button" role="tab"
        id={`${base}-tab-${tab.id}`} aria-controls={`${base}-panel-${tab.id}`} aria-selected={tab.id === current?.id}
        tabIndex={tab.id === current?.id ? 0 : -1} className={`wo-ui-tab ${tab.id === current?.id ? 'is-active' : ''}`}
        onClick={() => { setActive(tab.id); onChange?.(tab.id); }}>
        {tab.label}{tab.badge ? <span className="wo-ui-count">{formatCount(tab.badge)}</span> : null}
      </button>)}
    </div>
    {current && <div className="wo-ui-tabpanel" role="tabpanel" id={`${base}-panel-${current.id}`} aria-labelledby={`${base}-tab-${current.id}`} tabIndex={0}>{current.content}</div>}
  </div>;
};

export interface Part { id: string; label: string; value: number; status?: Status; color?: string }

const partColor = (part: Part) => part.color ?? `var(--status-${part.status ?? 'neutral'})`;

/**
 * Tall segmented bar: one whole split into at most six parts. Zero parts draw nothing.
 * The legend names the parts in order with their counts; every block has a hover title.
 */
export const SegmentedBar: React.FC<{ parts: Part[]; label: string; unit?: string; thin?: boolean }> = ({ parts, label, unit = '', thin }) => {
  const total = parts.reduce((sum, part) => sum + Math.max(0, part.value), 0);
  const shown = parts.filter((part) => part.value > 0);
  const description = parts.map((part) => `${part.label} ${formatCount(part.value)}`).join(', ');
  return <figure className="wo-ui-segbar">
    <div className={`wo-ui-segbar-track ${thin ? 'is-thin' : ''}`} role="img" aria-label={`${label}: ${description}`}>
      {total === 0 ? <span className="wo-ui-segbar-empty">No data</span> : shown.map((part) => {
        const share = part.value / total;
        return <span key={part.id} className="wo-ui-segbar-part" style={{ flexGrow: part.value, background: partColor(part) }}
          title={`${part.label}: ${formatCount(part.value)}${unit} (${Math.round(share * 100)}%)`}>
          {!thin && share >= 0.12 && <span className={`wo-ui-segbar-text ${part.status === 'warning' || part.status === 'good' ? 'is-dark' : ''}`}>{Math.round(share * 100)}%</span>}
        </span>;
      })}
    </div>
    <figcaption className="wo-ui-legend">
      {parts.map((part) => <span key={part.id} className={`wo-ui-legend-item ${part.value === 0 ? 'is-zero' : ''}`}>
        <i style={{ background: partColor(part) }} aria-hidden="true" />{part.label}<b>{formatCount(part.value)}</b>
      </span>)}
    </figcaption>
  </figure>;
};

export interface Bar { id: string; label: string; value: number; hint?: string; onClick?: () => void }

/** Ranked horizontal bars, largest first, one hue. Value at the tip. */
export const RankedBars: React.FC<{ bars: Bar[]; label: string; max?: number; limit?: number }> = ({ bars, label, max, limit = 8 }) => {
  const sorted = [...bars].sort((a, b) => b.value - a.value || a.label.localeCompare(b.label));
  const shown = sorted.slice(0, limit);
  const rest = sorted.slice(limit);
  const rows = rest.length ? [...shown, { id: '__other', label: `Other (${rest.length})`, value: rest.reduce((s, b) => s + b.value, 0) }] : shown;
  const top = max ?? Math.max(1, ...rows.map((b) => b.value));
  return <ul className="wo-ui-bars" aria-label={label}>
    {rows.map((bar) => {
      const inner = <>
        <span className="wo-ui-bar-label">{bar.label}</span>
        <span className="wo-ui-bar-track"><span className="wo-ui-bar-fill" style={{ width: `${Math.max(2, (bar.value / top) * 100)}%` }} /></span>
        <span className="wo-ui-bar-value">{formatCount(bar.value)}</span>
      </>;
      const title = `${bar.label}: ${formatCount(bar.value)}${'hint' in bar && bar.hint ? `. ${bar.hint}` : ''}`;
      return <li key={bar.id} title={title}>{'onClick' in bar && bar.onClick
        ? <button type="button" className="wo-ui-bar is-action" onClick={bar.onClick}>{inner}</button>
        : <div className="wo-ui-bar">{inner}</div>}</li>;
    })}
  </ul>;
};

/** One quiet line for caveats; the full text sits behind it. */
export const Note: React.FC<{ children: React.ReactNode }> = ({ children }) => <p className="wo-ui-note">{children}</p>;

export const EmptyState: React.FC<{ children: React.ReactNode }> = ({ children }) => <p className="wo-ui-empty">{children}</p>;
