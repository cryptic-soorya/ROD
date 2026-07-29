export type Role = 'admin' | 'category_manager' | 'store_manager';

export interface UserPublic {
  id: string;
  role: Role;
  scopes: string[];
}

export interface LoginResponse {
  token: string;
  expires_in: number;
  token_type?: string;
  user: UserPublic;
}

export type InvestigationStatus = 'pending' | 'in_progress' | 'completed' | 'escalated';

export interface InvestigationContext {
  store_id?: string;
  sku?: string;
  [key: string]: unknown;
}

export interface ToolCall {
  id: number;
  investigation_id: number;
  tool_name: string;
  input_args: Record<string, unknown>;
  output: unknown;
  error: string | null;
  called_at: string;
}

export interface Investigation {
  investigation_id: number;
  query: string;
  context: InvestigationContext;
  status: InvestigationStatus;
  report: Report | null;
  tool_calls: ToolCall[];
}

export interface InvestigationListItem {
  investigation_id: number;
  query: string;
  status: InvestigationStatus;
  store_id: string | null;
  sku: string | null;
}

export interface PaginatedInvestigations {
  total: number;
  page: number;
  per_page: number;
  pages: number;
  items: InvestigationListItem[];
}

export interface EvidenceStep {
  step: number;
  tool: string;
  finding: string;
}

export interface Report {
  investigation_id: string;
  root_cause: string;
  confidence_score: number;
  status: string;
  anomaly_category: string;
  evidence: EvidenceStep[];
  recommendations: {
    immediate: string[];
    customer_recovery: string[];
    process_improvement: string[];
  };
  estimated_impact: string;
  generated_at: string;
  total_iterations: number;
  human_readable_summary: string;
}

export interface KnowledgeDocument {
  document_id: string;
  document_text: string;
  category: 'SOP' | 'Past Case';
  tags: string[];
}