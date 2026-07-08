import { useEffect, useState, type FormEvent } from 'react';
import * as api from '../lib/api';
import type { KnowledgeDocument } from '../lib/types';
import './pages.css';

const EMPTY_FORM = { documentText: '', category: 'SOP' as 'SOP' | 'Past Case', tags: '' };

export default function KnowledgeAdminPage() {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  function refresh() {
    setLoading(true);
    api
      .listKnowledgeDocuments()
      .then((res) => setDocuments(res.documents))
      .catch(() => setError('Could not load knowledge base documents.'))
      .finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  function startEdit(doc: KnowledgeDocument) {
    setEditingId(doc.document_id);
    setForm({ documentText: doc.document_text, category: doc.category, tags: doc.tags.join(', ') });
  }

  function startNew() {
    setEditingId(null);
    setForm(EMPTY_FORM);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    const payload = {
      document_text: form.documentText.trim(),
      category: form.category,
      tags: form.tags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
    };
    try {
      if (editingId) {
        await api.updateKnowledgeDocument(editingId, payload);
      } else {
        await api.createKnowledgeDocument(payload);
      }
      startNew();
      refresh();
    } catch {
      setError('Could not save this document. Check the text length (max 2000 characters).');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(documentId: string) {
    if (!confirm('Delete this document permanently? This cannot be undone.')) return;
    setDeletingId(documentId);
    try {
      await api.deleteKnowledgeDocument(documentId);
      if (editingId === documentId) startNew();
      refresh();
    } catch {
      setError('Could not delete this document.');
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Knowledge base</h1>
          <p>SOPs and past cases the agent draws on during `knowledge_search`. Admin only.</p>
        </div>
      </div>

      {error && <div className="banner-error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="knowledge-layout">
        <div>
          {loading && documents.length === 0 && (
            <p style={{ color: 'var(--color-text-muted)' }}>Loading documents…</p>
          )}

          {!loading && documents.length === 0 && (
            <div className="card empty-state">
              <h3>No documents yet</h3>
              <p>Add the first SOP or past case using the form on the right.</p>
            </div>
          )}

          {documents.map((doc) => (
            <div className="card doc-card" key={doc.document_id}>
              <div className="doc-card-head">
                <span className="badge">{doc.category}</span>
                <span className="doc-id mono">{doc.document_id}</span>
              </div>
              <div className="doc-text">{doc.document_text}</div>
              {doc.tags.length > 0 && (
                <div className="doc-tags">
                  {doc.tags.map((tag) => (
                    <span className="badge" key={tag}>
                      {tag}
                    </span>
                  ))}
                </div>
              )}
              <div className="doc-actions" style={{ marginTop: 10 }}>
                <button className="btn btn-secondary btn-sm" onClick={() => startEdit(doc)}>
                  Edit
                </button>
                <button
                  className="btn btn-danger btn-sm"
                  disabled={deletingId === doc.document_id}
                  onClick={() => handleDelete(doc.document_id)}
                >
                  {deletingId === doc.document_id ? 'Deleting…' : 'Delete'}
                </button>
              </div>
            </div>
          ))}
        </div>

        <div className="card card-padded" style={{ position: 'sticky', top: 24 }}>
          <div className="section-title">{editingId ? 'Edit document' : 'Add document'}</div>
          <form className="form-grid" onSubmit={handleSubmit}>
            <label className="form-field">
              <span>Category</span>
              <select
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value as 'SOP' | 'Past Case' })}
              >
                <option value="SOP">SOP</option>
                <option value="Past Case">Past Case</option>
              </select>
            </label>

            <label className="form-field">
              <span>Document text</span>
              <textarea
                rows={8}
                maxLength={2000}
                value={form.documentText}
                onChange={(e) => setForm({ ...form, documentText: e.target.value })}
                required
              />
              <span className="field-hint char-counter">{form.documentText.length}/2000</span>
            </label>

            <label className="form-field">
              <span>Tags (comma separated)</span>
              <input value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} placeholder="sizing, qa" />
            </label>

            <div style={{ display: 'flex', gap: 8 }}>
              <button type="submit" className="btn btn-primary" disabled={saving}>
                {saving ? 'Saving…' : editingId ? 'Save changes' : 'Add document'}
              </button>
              {editingId && (
                <button type="button" className="btn btn-secondary" onClick={startNew}>
                  Cancel
                </button>
              )}
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
