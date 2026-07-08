import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import * as api from '../lib/api';
import type { Investigation } from '../lib/types';
import StatusPill from '../components/StatusPill';
import './pages.css';

const MAX_ITERATIONS = 10;
const POLL_INTERVAL_MS = 2000;

function formatDate(iso: string | null) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatArgs(args: Record<string, unknown>) {
  const entries = Object.entries(args ?? {});
  if (!entries.length) return null;
  return entries.map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join('\n');
}

function formatOutput(output: unknown) {
  if (output == null) return null;
  return typeof output === 'string' ? output : JSON.stringify(output, null, 2);
}

export default function InvestigationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [investigation, setInvestigation] = useState<Investigation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;

    async function poll() {
      try {
        const inv = await api.getInvestigation(Number(id));
        if (cancelled) return;
        setInvestigation(inv);
        if (inv.status === 'completed' || inv.status === 'escalated') {
          if (timerRef.current) clearInterval(timerRef.current);
        }
      } catch {
        if (!cancelled) setError('Could not load this investigation.');
        if (timerRef.current) clearInterval(timerRef.current);
      }
    }

    poll();
    timerRef.current = setInterval(poll, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [id]);

  if (error) {
    return <div className="banner-error">{error}</div>;
  }

  if (!investigation) {
    return <p style={{ color: 'var(--color-text-muted)' }}>Loading investigation…</p>;
  }

  const isDone = investigation.status === 'completed' || investigation.status === 'escalated';
  const progressPct = Math.min(100, (investigation.iteration_count / MAX_ITERATIONS) * 100);

  return (
    <div>
      <div className="detail-header">
        <div>
          <div className="detail-query">{investigation.query}</div>
          <div className="detail-meta-row">
            <StatusPill status={investigation.status} />
            <span className="badge">P{investigation.priority}</span>
            <span style={{ fontSize: 13, color: 'var(--color-text-faint)' }}>
              started {formatDate(investigation.created_at)}
            </span>
          </div>
        </div>
        {isDone && (
          <button className="btn btn-primary" onClick={() => navigate(`/investigations/${investigation.id}/report`)}>
            View report
          </button>
        )}
      </div>

      <div className="card card-padded" style={{ marginBottom: 24 }}>
        <div className="section-title">
          Iteration {investigation.iteration_count} / {MAX_ITERATIONS}
          {!isDone && ' · investigating…'}
        </div>
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${progressPct}%` }} />
        </div>

        {investigation.tool_calls.length === 0 ? (
          <div className="empty-state" style={{ padding: '32px 0' }}>
            <h3>{isDone ? 'No evidence was gathered' : 'Gathering the first piece of evidence…'}</h3>
            <p>
              {isDone
                ? 'This investigation finished without calling any tools — see the report for details.'
                : "The agent hasn't called a tool yet. This page refreshes automatically."}
            </p>
          </div>
        ) : (
          <div className="timeline">
            {investigation.tool_calls.map((call, idx) => {
              const argsText = formatArgs(call.input_args);
              const outputText = call.error ? call.error : formatOutput(call.output);
              return (
                <div className="timeline-item" key={call.id}>
                  <div className="timeline-step">{idx + 1}</div>
                  <div className="timeline-body">
                    <span className="timeline-tool">{call.tool_name}</span>
                    <span className="timeline-time">{formatDate(call.called_at)}</span>
                    {argsText && <div className="timeline-detail">{argsText}</div>}
                    {outputText && (
                      <div className={`timeline-detail ${call.error ? 'timeline-error' : ''}`}>{outputText}</div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {!isDone && (
        <p style={{ fontSize: 12, color: 'var(--color-text-faint)' }}>
          Watching for updates every {POLL_INTERVAL_MS / 1000}s. You can leave this page — the investigation keeps
          running.{' '}
          <Link to="/investigations">Back to list</Link>
        </p>
      )}
    </div>
  );
}
