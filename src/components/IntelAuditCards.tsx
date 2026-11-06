import React from 'react';
import type { SiteGraphManifest } from '../types/site';
import { Disclosure, KeyValueList, Section, type KeyValue, type Status } from './ui';

/**
 * Transport sections for the Site Intel Tech tab: TLS certificate, homepage header
 * quality and email DNS. Each is a label and value list; issues sit behind a disclosure.
 * Their scope notes are returned separately so the drawer can collect them in one place.
 */
const NO_DATA = 'No data';
const STATE: Record<string, { status: Status; label: string }> = {
  ok: { status: 'good', label: 'OK' },
  warn: { status: 'warning', label: 'Review' },
  partial: { status: 'warning', label: 'Partial' },
  fail: { status: 'critical', label: 'Problem' },
  skipped: { status: 'neutral', label: 'Skipped' },
  unreachable: { status: 'neutral', label: 'Unreachable' },
};
const stateRow = (label: string, state?: string, title?: string): KeyValue => {
  const known = STATE[state ?? ''];
  return known ? { label, value: known.label, status: known.status, title } : { label, value: state || NO_DATA, title };
};

function IssueList({ items }: { items: string[] }) {
  if (!items.length) return null;
  return <Disclosure summary="Issues" count={items.length}>
    <ul className="wo-dr-list">{items.map((item) => <li key={item}>{item}</li>)}</ul>
  </Disclosure>;
}

/** Scope notes for the transport checks, for the drawer's "About these numbers" disclosure. */
export function transportNotes(manifest: SiteGraphManifest): string[] {
  const transport = manifest.siteIntel?.transport;
  if (!transport) return [];
  const notes: string[] = [];
  if (transport.tls) notes.push("TLS is read from one handshake with the site's own address. Other hosts may present their own certificate.");
  if (transport.headerQuality) notes.push('Header quality covers the homepage response only. Header settings alone do not establish a secure configuration.');
  if (transport.emailDns) {
    notes.push(transport.emailDns.note || 'Email DNS is queried through the system DNS resolver.');
    if (transport.emailDns.dkim?.note) notes.push(transport.emailDns.dkim.note);
    if (transport.emailDns.state === 'skipped') notes.push('To enable email DNS checks, install dnspython in the Python environment Web-Obs uses and keep DNS checks turned on in settings.');
  }
  return notes;
}

export const TransportSections: React.FC<{ manifest: SiteGraphManifest }> = ({ manifest }) => {
  const transport = manifest.siteIntel?.transport;
  if (!transport) return null;
  const { tls, headerQuality: headers, emailDns: email } = transport;

  const tlsRows: KeyValue[] = tls ? [stateRow('State', tls.state, tls.detail ?? undefined)] : [];
  if (tls && tls.state !== 'skipped') {
    tlsRows.push(
      typeof tls.daysRemaining === 'number'
        ? { label: 'Days remaining', value: String(tls.daysRemaining), status: tls.daysRemaining < 21 ? 'warning' : undefined }
        : { label: 'Days remaining', value: NO_DATA },
      { label: 'Expires', value: tls.notAfter ? tls.notAfter.slice(0, 10) : NO_DATA },
      { label: 'Issuer', value: tls.issuer || NO_DATA },
      { label: 'Protocol', value: tls.tlsVersion || NO_DATA },
      { label: 'Verified', value: tls.verified === undefined || tls.verified === null ? NO_DATA : tls.verified ? 'Yes' : 'No' },
    );
    if (tls.san?.length) tlsRows.push({ label: 'Names covered', value: tls.san.slice(0, 4).join(', ') + (tls.san.length > 4 ? ` and ${tls.san.length - 4} more` : ''), title: tls.san.join('\n') });
  }

  const headerIssues = headers ? [...(headers.hsts?.issues ?? []), ...(headers.csp?.issues ?? []), ...(headers.otherIssues ?? [])] : [];
  const headerRows: KeyValue[] = headers && !headers.error ? [
    { label: 'HSTS', value: headers.hsts ? headers.hsts.present ? `max-age ${headers.hsts.maxAge ?? NO_DATA}` : 'Not set' : NO_DATA,
      title: headers.hsts?.present ? [headers.hsts.includeSubDomains && 'includeSubDomains', headers.hsts.preload && 'preload'].filter(Boolean).join(', ') : undefined },
    { label: 'Preload ready', value: headers.hsts ? headers.hsts.preloadReady ? 'Yes' : 'No' : NO_DATA },
    { label: 'Content Security Policy', value: headers.csp ? headers.csp.present ? headers.csp.reportOnly ? 'Report only' : 'Enforced' : 'Not set' : NO_DATA },
    { label: 'Cookies set by the homepage', value: headers.cookies ? String(headers.cookies.length) : NO_DATA },
  ] : [];

  const emailIssues = email ? [...(email.spf?.issues ?? []), ...(email.dmarc?.issues ?? [])] : [];
  const emailRows: KeyValue[] = email ? [stateRow('State', email.state, email.detail ?? undefined)] : [];
  if (email && email.state !== 'skipped') {
    emailRows.push(
      { label: 'MX', value: email.mx?.length ? email.mx.slice(0, 2).join(', ') + (email.mx.length > 2 ? ` +${email.mx.length - 2}` : '') : 'None', title: email.mx?.join('\n') },
      { label: 'SPF', value: email.spf ? email.spf.present ? `${email.spf.allQualifier ?? '?'}all, ${email.spf.lookupCount ?? 0} lookups` : 'Not found' : NO_DATA },
      { label: 'DMARC', value: email.dmarc ? email.dmarc.present ? `p=${email.dmarc.policy ?? 'not set'}` : 'Not found' : NO_DATA },
      { label: 'DKIM', value: email.dkim ? email.dkim.found.length ? email.dkim.found.join(', ') : 'No common selector' : NO_DATA },
      { label: 'CAA', value: email.caa?.length ? email.caa.join(', ') : 'None' },
    );
  }

  return <>
    {tls && <Section title="TLS certificate"><KeyValueList rows={tlsRows} /></Section>}
    {headers && <Section title="Header quality" aside="Homepage">
      {headers.error ? <p className="wo-ui-note">{headers.error}</p> : <KeyValueList rows={headerRows} />}
      {(headers.cookies ?? []).length > 0 && <Disclosure summary="Cookies" count={headers.cookies!.length}>
        <ul className="wo-dr-list">{headers.cookies!.map((cookie) => <li key={cookie.name}><code>{cookie.name}</code> {[cookie.secure ? 'Secure' : 'not Secure', cookie.httpOnly ? 'HttpOnly' : 'no HttpOnly', cookie.sameSite ? `SameSite ${cookie.sameSite}` : 'no SameSite'].join(', ')}</li>)}</ul>
      </Disclosure>}
      <IssueList items={headerIssues} />
    </Section>}
    {email && <Section title="Email DNS">
      <KeyValueList rows={emailRows} />
      <IssueList items={emailIssues} />
    </Section>}
  </>;
};
