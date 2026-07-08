import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import * as api from '../lib/api';
import type { InvestigationListItem, PaginatedInvestigations } from '../lib/types';
import StatusPill from '../components/StatusPill';
import './pages.css';

const STATUS_OPTIONS = ['', 'pending', 'in_progress', 'completed', 'escalated'];

function formatDate(iso: string | null) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function InvestigationsListPage() {
  const navigate = useNavigate();
  const [data, setData] = useState<PaginatedInvestigations | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState('');
  const [storeId, setStoreId] = useState('');
  const [sku, setSku] = useState('');
  const [page, setPage] = useState(1);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .listInvestigations({ page, per_page: 15, status: status || undefined, store_id: storeId || undefined, sku: sku || undefined })
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch(() => {
        if (!cancelled) setError('Could not load investigations.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [page, status, storeId, sku]);

  const items: InvestigationListItem[] = data?.items ?? [];

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Investigations</h1>
          <p>Every anomaly ROD has been asked to look into.</p>
        </div>
        <button className="btn btn-primary" onClick={() => navigate('/investigations/new')}>
          New investigation
        </button>
      </div>

      <div className="filter-bar">
        <label className="form-field">
          <span>Status</span>
          <select
            value={status}
            onChange={(e) => {
              setPage(1);
              setStatus(e.target.value);
            }}
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s ? s.replace('_', ' ') : 'All'}
              </option>
            ))}
          </select>
        </label>
        <label className="form-field">
          <span>Store ID</span>
          <input
            value={storeId}
            onChange={(e) => {
              setPage(1);
              setStoreId(e.target.value);
            }}
            placeholder="e.g. ST-104"
          />
        </label>
        <label className="form-field">
          <span>SKU</span>
          <input
            value={sku}
            onChange={(e) => {
              setPage(1);
              setSku(e.target.value);
            }}
            placeholder="e.g. SKU-7782"
          />
        </label>
      </div>

      <div className="card">
        {error && <div className="banner-error" style={{ margin: 16 }}>{error}</div>}

        {!error && !loading && items.length === 0 && (
          <div className="empty-state">
            <h3>No investigations match these filters</h3>
            <p>Try clearing a filter, or start a new investigation to see it appear here.</p>
          </div>
        )}

        {items.length > 0 && (
          <table className="inv-table">
            <thead>
              <tr>
                <th>Query</th>
                <th>Status</th>
                <th>Priority</th>
                <th>Confidence</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {items.map((inv) => (
                <tr key={inv.id} onClick={() => navigate(`/investigations/${inv.id}`)}>
                  <td className="inv-query-cell">
                    {inv.query}
                    <div className="inv-meta">
                      {inv.store_id && `store ${inv.store_id}`}
                      {inv.store_id && inv.sku && ' · '}
                      {inv.sku && `sku ${inv.sku}`}
                    </div>
                  </td>
                  <td>
                    <StatusPill status={inv.status} />
                  </td>
                  <td>P{inv.priority}</td>
                  <td>{inv.confidence_score != null ? `${Math.round(inv.confidence_score * 100)}%` : '—'}</td>
                  <td>{formatDate(inv.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {data && data.pages > 1 && (
        <div className="pagination">
          <button className="btn btn-secondary btn-sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </button>
          <span>
            Page {data.page} of {data.pages}
          </span>
          <button className="btn btn-secondary btn-sm" disabled={page >= data.pages} onClick={() => setPage((p) => p + 1)}>
            Next
          </button>
        </div>
      )}
    </div>
  );
}
