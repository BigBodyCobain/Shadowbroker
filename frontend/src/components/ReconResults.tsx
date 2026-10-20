'use client';

import React from 'react';
import { ExternalLink } from 'lucide-react';

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function fmt(value: unknown): string {
  if (value == null || value === '') return '—';
  if (typeof value === 'boolean') return value ? 'YES' : 'NO';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

function DossierShell({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <div className="max-h-52 overflow-y-auto styled-scrollbar border border-cyan-900/40 bg-black/60">
      {title && (
        <div className="border-b border-cyan-900/40 bg-cyan-950/25 px-2 py-1.5 text-[10px] font-mono font-bold tracking-[0.2em] text-cyan-400">
          {title}
        </div>
      )}
      <div className="px-2 py-1.5 space-y-0">{children}</div>
    </div>
  );
}

function DossierRow({
  label,
  value,
  href,
  highlight,
}: {
  label: string;
  value: React.ReactNode;
  href?: string;
  highlight?: 'red' | 'amber' | 'green' | 'cyan';
}) {
  const tone =
    highlight === 'red'
      ? 'text-red-300'
      : highlight === 'amber'
        ? 'text-amber-300'
        : highlight === 'green'
          ? 'text-green-300'
          : 'text-cyan-200';

  const content =
    href && typeof value === 'string' ? (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={`${tone} hover:underline inline-flex items-center gap-1 justify-end`}
      >
        {value}
        <ExternalLink size={9} className="shrink-0 opacity-70" />
      </a>
    ) : (
      <span className={`${tone} text-right break-all leading-snug`}>{value}</span>
    );

  return (
    <div className="flex justify-between items-start gap-3 border-b border-cyan-900/25 py-1 last:border-0">
      <span className="text-[10px] font-mono text-cyan-600 tracking-wider shrink-0 pt-0.5">
        {label}
      </span>
      <span className="text-[11px] font-mono min-w-0">{content}</span>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[9px] font-mono tracking-[0.22em] text-cyan-500/80 pt-2 pb-0.5">
      {children}
    </div>
  );
}

function GitHubDossier({ data }: { data: Record<string, unknown> }) {
  const profile = asRecord(data.profile) || {};
  const repos = asArray(data.repos) as Array<Record<string, unknown>>;
  const displayName = fmt(profile.name) !== '—' ? String(profile.name) : fmt(data.username);

  return (
    <DossierShell title="GITHUB DOSSIER">
      <DossierRow label="HANDLE" value={`@${fmt(data.username)}`} highlight="cyan" />
      <DossierRow label="NAME" value={displayName} />
      {profile.bio ? <DossierRow label="BIO" value={fmt(profile.bio)} /> : null}
      {profile.location ? <DossierRow label="LOCATION" value={fmt(profile.location)} /> : null}
      {profile.company ? <DossierRow label="COMPANY" value={fmt(profile.company)} /> : null}
      <DossierRow label="FOLLOWERS" value={fmt(profile.followers)} />
      <DossierRow label="PUBLIC REPOS" value={fmt(profile.public_repos)} />
      {profile.created_at ? (
        <DossierRow
          label="MEMBER SINCE"
          value={new Date(String(profile.created_at)).toLocaleDateString()}
        />
      ) : null}
      {profile.html_url ? (
        <DossierRow label="PROFILE" value="Open on GitHub" href={String(profile.html_url)} />
      ) : null}
      {repos.length > 0 && (
        <>
          <SectionLabel>RECENT REPOSITORIES</SectionLabel>
          {repos.slice(0, 6).map((repo) => (
            <DossierRow
              key={String(repo.name)}
              label={String(repo.language || 'REPO')}
              value={`${repo.name}${repo.stars != null ? ` · ★${repo.stars}` : ''}`}
            />
          ))}
        </>
      )}
    </DossierShell>
  );
}

function IpDossier({ data }: { data: Record<string, unknown> }) {
  const geo = asRecord(data.geo) || {};
  const rep = asRecord(data.reputation) || {};
  const sanctions = asRecord(data.sanctions_match);
  const risk = String(rep.risk_level || 'UNKNOWN');

  return (
    <DossierShell title="IP DOSSIER">
      <DossierRow label="TARGET" value={fmt(data.ip)} highlight="cyan" />
      <DossierRow
        label="LOCATION"
        value={[geo.city, geo.region, geo.country].filter(Boolean).join(', ') || '—'}
      />
      <DossierRow label="ISP" value={fmt(geo.isp)} />
      <DossierRow label="ORG" value={fmt(geo.org)} />
      <DossierRow label="ASN" value={fmt(geo.as_number)} />
      <DossierRow
        label="RISK"
        value={risk}
        highlight={risk === 'HIGH' ? 'red' : risk === 'MEDIUM' ? 'amber' : 'green'}
      />
      <DossierRow label="PROXY" value={fmt(rep.is_proxy)} />
      <DossierRow label="HOSTING" value={fmt(rep.is_hosting)} />
      {sanctions ? (
        <DossierRow
          label="SANCTIONS"
          value={`${asArray(sanctions.hits).length} OFAC hit(s)`}
          highlight="red"
        />
      ) : null}
    </DossierShell>
  );
}

function DnsDossier({ data }: { data: Record<string, unknown> }) {
  const summary = asRecord(data.summary) || {};
  return (
    <DossierShell title="DNS DOSSIER">
      <DossierRow label="DOMAIN" value={fmt(data.domain)} highlight="cyan" />
      <DossierRow label="A RECORDS" value={asArray(summary.ip_addresses).join(', ') || '—'} />
      <DossierRow label="MAIL (MX)" value={asArray(summary.mail_servers).join(', ') || '—'} />
      <DossierRow label="NAMESERVERS" value={asArray(summary.nameservers).join(', ') || '—'} />
      <DossierRow label="TOTAL RECORDS" value={fmt(summary.total_records)} />
    </DossierShell>
  );
}

function WhoisDossier({ data }: { data: Record<string, unknown> }) {
  const rdap = asRecord(data.rdap) || {};
  const http = asRecord(data.http) || {};
  const score = asRecord(data.security_score) || {};
  const entity = asRecord(asArray(rdap.entities)[0]);

  return (
    <DossierShell title="WHOIS / RDAP DOSSIER">
      <DossierRow label="DOMAIN" value={fmt(data.domain)} highlight="cyan" />
      <DossierRow label="REGISTRAR" value={fmt(entity?.org || entity?.name)} />
      <DossierRow label="REGISTERED" value={fmt(data.registration)} />
      <DossierRow label="EXPIRES" value={fmt(data.expiration)} />
      <DossierRow label="LAST CHANGED" value={fmt(data.last_changed)} />
      <DossierRow label="HTTP STATUS" value={fmt(http.status)} />
      <DossierRow
        label="SECURITY"
        value={score.grade ? `${score.grade} (${score.score}/${score.max})` : '—'}
        highlight={score.grade === 'A' ? 'green' : score.grade === 'F' ? 'red' : 'amber'}
      />
      <DossierRow label="NAMESERVERS" value={asArray(rdap.nameservers).slice(0, 4).join(', ') || '—'} />
    </DossierShell>
  );
}

function CertsDossier({ data }: { data: Record<string, unknown> }) {
  const subs = asArray(data.subdomains) as string[];
  const certs = asArray(data.certificates) as Array<Record<string, unknown>>;
  return (
    <DossierShell title="CERTIFICATE DOSSIER">
      <DossierRow label="DOMAIN" value={fmt(data.domain)} highlight="cyan" />
      <DossierRow label="CERTS FOUND" value={fmt(data.total_found)} />
      <DossierRow label="SUBDOMAINS" value={subs.length ? `${subs.length} discovered` : '—'} />
      {subs.slice(0, 5).map((sub) => (
        <DossierRow key={sub} label="HOST" value={sub} />
      ))}
      {certs[0] ? (
        <DossierRow label="LATEST CN" value={fmt(certs[0].common_name)} />
      ) : null}
    </DossierShell>
  );
}

function SanctionsDossier({ data }: { data: Record<string, unknown> }) {
  const matches = asArray(data.matches) as Array<Record<string, unknown>>;
  return (
    <DossierShell title="SANCTIONS DOSSIER">
      <DossierRow label="QUERY" value={fmt(data.query)} highlight="cyan" />
      <DossierRow label="MATCHES" value={fmt(data.total)} highlight={matches.length ? 'red' : 'green'} />
      <DossierRow label="SOURCE" value={fmt(data.source)} />
      {matches.slice(0, 8).map((hit, i) => (
        <DossierRow
          key={`${hit.id || i}`}
          label={String(hit.schema || 'ENTITY').toUpperCase()}
          value={fmt(hit.caption || hit.name || hit.id)}
          highlight="red"
        />
      ))}
    </DossierShell>
  );
}

function CveDossier({ data }: { data: Record<string, unknown> }) {
  return (
    <DossierShell title="CVE DOSSIER">
      <DossierRow label="CVE" value={fmt(data.id)} highlight="cyan" />
      {'cvss' in data ? <DossierRow label="CVSS" value={fmt(data.cvss)} /> : null}
      <div className="pt-1 text-[11px] font-mono text-cyan-200/90 leading-relaxed">
        {fmt(data.description)}
      </div>
    </DossierShell>
  );
}

function LeaksDossier({ data }: { data: Record<string, unknown> }) {
  const sources = asArray(data.sources);
  const found = Boolean(data.found);
  return (
    <DossierShell title="BREACH DOSSIER">
      <DossierRow label="EMAIL" value={fmt(data.email)} highlight="cyan" />
      <DossierRow
        label="EXPOSED"
        value={found ? 'YES' : 'NO'}
        highlight={found ? 'red' : 'green'}
      />
      {sources.length > 0 ? (
        <DossierRow label="SOURCES" value={sources.map((s) => fmt(s)).join(', ')} highlight="red" />
      ) : null}
    </DossierShell>
  );
}

function MacDossier({ data }: { data: Record<string, unknown> }) {
  return (
    <DossierShell title="MAC DOSSIER">
      <DossierRow label="MAC" value={fmt(data.mac)} highlight="cyan" />
      <DossierRow label="VENDOR" value={fmt(data.vendor)} />
    </DossierShell>
  );
}

function ThreatsDossier({ data }: { data: Record<string, unknown> }) {
  const otx = asRecord(data.otx) || {};
  const pulses = asArray(data.pulses) as Array<Record<string, unknown>>;
  const level = String(data.threat_level || 'LOW');
  return (
    <DossierShell title="THREAT INTEL DOSSIER">
      <DossierRow
        label="THREAT LEVEL"
        value={level}
        highlight={level === 'HIGH' ? 'red' : level === 'MEDIUM' ? 'amber' : 'green'}
      />
      {'pulse_count' in otx ? <DossierRow label="OTX PULSES" value={fmt(otx.pulse_count)} /> : null}
      {'tor_exit_node' in data ? (
        <DossierRow label="TOR EXIT" value={fmt(data.tor_exit_node)} highlight="amber" />
      ) : null}
      {pulses.slice(0, 4).map((pulse, i) => (
        <div key={i} className="border-b border-cyan-900/25 py-1 last:border-0">
          <div className="text-[10px] font-mono text-cyan-300 leading-snug">{fmt(pulse.name)}</div>
          {pulse.adversary ? (
            <div className="text-[9px] font-mono text-cyan-600 mt-0.5">{fmt(pulse.adversary)}</div>
          ) : null}
        </div>
      ))}
    </DossierShell>
  );
}

function BgpDossier({ data }: { data: Record<string, unknown> }) {
  const asn = asRecord(data.asn) || {};
  const ip = asRecord(data.ip) || {};
  const prefixes = asRecord(data.prefixes) || {};
  return (
    <DossierShell title="BGP DOSSIER">
      <DossierRow label="QUERY" value={fmt(data.query)} highlight="cyan" />
      {data.type === 'asn' ? (
        <>
          <DossierRow label="ASN" value={fmt(asn.asn)} />
          <DossierRow label="NAME" value={fmt(asn.name)} />
          <DossierRow label="COUNTRY" value={fmt(asn.country_code)} />
          <DossierRow label="PREFIXES V4" value={fmt(prefixes.total_v4)} />
        </>
      ) : (
        <>
          <DossierRow label="PREFIX" value={fmt(ip.prefix)} />
          <DossierRow label="ASN" value={fmt(ip.asn)} />
          <DossierRow label="NAME" value={fmt(ip.name)} />
        </>
      )}
    </DossierShell>
  );
}

function SweepDossier({ data }: { data: Record<string, unknown> }) {
  const summary = asRecord(data.summary) || {};
  const devices = asArray(data.devices) as Array<Record<string, unknown>>;
  return (
    <DossierShell title="SWEEP DOSSIER">
      <DossierRow label="SCANNED" value={fmt(summary.total_hosts)} />
      <DossierRow
        label="RESPONSIVE"
        value={fmt(summary.total_responsive)}
        highlight={Number(summary.total_responsive) > 0 ? 'amber' : 'green'}
      />
      <DossierRow label="DURATION" value={data.sweep_time_ms != null ? `${data.sweep_time_ms} ms` : '—'} />
      {devices.slice(0, 8).map((device) => (
        <DossierRow
          key={String(device.ip)}
          label={fmt(device.ip)}
          value={[
            asArray(device.ports).length ? `ports ${asArray(device.ports).join(',')}` : '',
            asArray(device.vulns).length ? `${asArray(device.vulns).length} vuln(s)` : '',
          ]
            .filter(Boolean)
            .join(' · ') || 'responsive'}
          highlight={asArray(device.vulns).length ? 'red' : undefined}
        />
      ))}
    </DossierShell>
  );
}

function GenericDossier({ data }: { data: Record<string, unknown> }) {
  const rows = Object.entries(data).filter(([key]) => key !== 'timestamp');
  return (
    <DossierShell title="RECON DOSSIER">
      {rows.slice(0, 12).map(([key, value]) => (
        <DossierRow
          key={key}
          label={key.replace(/_/g, ' ').toUpperCase()}
          value={
            typeof value === 'object' && value !== null
              ? Array.isArray(value)
                ? `${value.length} item(s)`
                : 'See details'
              : fmt(value)
          }
        />
      ))}
    </DossierShell>
  );
}

export default function ReconResults({
  tabId,
  results,
}: {
  tabId: string;
  results: unknown;
}) {
  const data = asRecord(results);
  if (!data) return null;

  switch (tabId) {
    case 'github':
      return <GitHubDossier data={data} />;
    case 'ip':
      return <IpDossier data={data} />;
    case 'dns':
      return <DnsDossier data={data} />;
    case 'whois':
      return <WhoisDossier data={data} />;
    case 'certs':
      return <CertsDossier data={data} />;
    case 'sanctions':
      return <SanctionsDossier data={data} />;
    case 'cve':
      return <CveDossier data={data} />;
    case 'leaks':
      return <LeaksDossier data={data} />;
    case 'mac':
      return <MacDossier data={data} />;
    case 'threats':
      return <ThreatsDossier data={data} />;
    case 'bgp':
      return <BgpDossier data={data} />;
    case 'sweep':
      return <SweepDossier data={data} />;
    default:
      return <GenericDossier data={data} />;
  }
}
