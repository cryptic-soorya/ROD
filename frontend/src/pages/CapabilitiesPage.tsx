import './pages.css';

const TOOLS = [
  { name: 'get_sales_data', source: 'sales schema', description: 'Store-level revenue trends over time.' },
  { name: 'get_stores_with_sales_decline', source: 'sales schema', description: 'Scans every store and ranks the largest revenue declines, worst first.' },
  { name: 'get_stores_with_sku_decline', source: 'sales & inventory schema', description: 'Finds every store carrying a given SKU and ranks their revenue decline for it.' },
  { name: 'get_top_declining_skus_for_store', source: 'sales schema', description: "Breaks a store's revenue decline down by SKU, worst first." },
  { name: 'get_inventory_levels', source: 'inventory schema', description: 'Current stock, reserved units and reorder points per SKU/store.' },
  { name: 'get_replenishment_history', source: 'inventory schema', description: 'Past restock events per SKU and store.' },
  { name: 'get_low_stock_items_for_store', source: 'inventory schema', description: 'SKUs at or below reorder point at a store, worst first — including full stockouts.' },
  { name: 'get_return_reasons', source: 'returns schema', description: 'Why customers are returning items, broken down by reason. Can isolate a single store.' },
  { name: 'get_product_listing_changes', source: 'orchestrator schema', description: 'Recent edits to a listing — size charts, descriptions, images.' },
  { name: 'get_customer_complaints', source: 'customers schema', description: 'Complaint volume and category over a given window.' },
  { name: 'get_promotion_performance', source: 'promotions schema', description: 'Projected vs. actual uplift for a promotion.' },
  { name: 'get_underperforming_promotions', source: 'promotions schema', description: 'Scans recently-ended promotions and surfaces the ones that underperformed, worst first.' },
  { name: 'get_delivery_performance', source: 'suppliers schema', description: 'Supplier delivery times vs. baseline, plus defect rate. Can isolate a single store.' },
  { name: 'knowledge_search', source: 'chroma_db/', description: 'Semantic search over SOPs and past resolved cases.' },
];

const REACT_STEPS = [
  { title: 'Thought', body: 'The agent reasons about what evidence would confirm or rule out a hypothesis.' },
  { title: 'Action', body: 'It calls one of the 14 tools above with specific arguments.' },
  { title: 'Observation', body: 'The tool result is added to the evidence trail, shaping the next thought.' },
  { title: 'Repeat × 10', body: 'Up to 10 iterations. Confidence ≥ 0.7 → completed; otherwise → escalated.' },
];

const ROLES = [
  {
    role: 'Admin',
    scopes: ['read:sales', 'read:inventory', 'read:returns', 'read:customers', 'read:promotions', 'read:suppliers', 'read:knowledge', 'write:knowledge'],
  },
  {
    role: 'Store Manager',
    scopes: ['read:sales', 'read:inventory', 'read:returns', 'read:customers', 'read:suppliers', 'read:promotions', 'read:knowledge'],
    note: 'Restricted to their own store_id — enforced on every tool call, not just their own investigation list.',
  },
];

export default function CapabilitiesPage() {
  return (
    <div>
      <div className="page-header">
        <div>
          <h1>What ROD can do</h1>
          <p>One investigation, 14 sources of evidence, a compiled report with root cause and recommendations.</p>
        </div>
      </div>

      <div className="section-title">The 14 tools</div>
      <div className="capability-grid">
        {TOOLS.map((tool) => (
          <div className="card capability-card" key={tool.name}>
            <h3 className="mono">{tool.name}</h3>
            <span className="capability-source">{tool.source}</span>
            <p>{tool.description}</p>
          </div>
        ))}
      </div>

      <div className="section-title">How an investigation runs</div>
      <div className="card react-steps">
        {REACT_STEPS.map((step) => (
          <div className="react-step" key={step.title}>
            <h4>{step.title}</h4>
            <p>{step.body}</p>
          </div>
        ))}
      </div>

      <div className="section-title">Roles &amp; access</div>
      <div className="card">
        <table className="roles-table">
          <thead>
            <tr>
              <th>Role</th>
              <th>Scopes</th>
            </tr>
          </thead>
          <tbody>
            {ROLES.map((r) => (
              <tr key={r.role}>
                <td>
                  <strong>{r.role}</strong>
                  {r.note && <div className="inv-meta">{r.note}</div>}
                </td>
                <td>
                  <div className="scope-tags">
                    {r.scopes.map((s) => (
                      <span className="badge" key={s}>
                        {s}
                      </span>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}