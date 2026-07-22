import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import * as api from '../lib/api';
import { ApiError } from '../lib/api';
import './pages.css';

export default function NewInvestigationPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [storeId, setStoreId] = useState('');
  const [sku, setSku] = useState('');
  const [priority, setPriority] = useState(3);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (query.trim().length < 5) {
      setError('Describe the anomaly in at least 5 characters.');
      return;
    }

    setSubmitting(true);
    try {
      const context: Record<string, string> = {};
      if (storeId.trim()) context.store_id = storeId.trim();
      if (sku.trim()) context.sku = sku.trim();

      const investigation = await api.createInvestigation({
        query: query.trim(),
        context: Object.keys(context).length ? context : undefined,
        priority,
      });
      navigate(`/investigations/${investigation.investigation_id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(typeof err.detail === 'string' ? err.detail : 'Could not start the investigation.');
      } else {
        setError('Could not start the investigation.');
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>New investigation</h1>
          <p>Describe what looks wrong — ROD's ReAct agent will gather evidence across all 9 tools and report back.</p>
        </div>
      </div>

      <div className="card card-padded form-card">
        <form className="form-grid" onSubmit={handleSubmit}>
          <label className="form-field">
            <span>What's the anomaly?</span>
            <textarea
              rows={4}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. Returns for SKU-7782 spiked 40% over the last two weeks at store ST-104"
              maxLength={1000}
              required
            />
            <span className="field-hint char-counter">{query.length}/1000</span>
          </label>

          <div className="form-row">
            <label className="form-field">
              <span>Store ID (optional)</span>
              <input value={storeId} onChange={(e) => setStoreId(e.target.value)} placeholder="ST-104" />
            </label>
            <label className="form-field">
              <span>SKU (optional)</span>
              <input value={sku} onChange={(e) => setSku(e.target.value)} placeholder="SKU-7782" />
            </label>
          </div>

          <label className="form-field">
            <span>Priority</span>
            <select value={priority} onChange={(e) => setPriority(Number(e.target.value))}>
              {[1, 2, 3, 4, 5].map((p) => (
                <option key={p} value={p}>
                  {p} {p === 1 ? '(lowest)' : p === 5 ? '(highest)' : ''}
                </option>
              ))}
            </select>
          </label>

          {error && <div className="banner-error">{error}</div>}

          <div>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? 'Starting investigation…' : 'Start investigation'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

