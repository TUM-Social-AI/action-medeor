import { requestJson } from './http';

export type CatalogueArticle = {
  id: string;
  source: 'erp' | 'sharepoint';
  name: string;
  vendor: string | null;
  category: string;
  reference: string;
  source_url: string | null;
  stock: string | null;
  on_hand: string | null;
  unit: string | null;
  valid_until: string | null;
  offer_date: string | null;
  offer_date_source: string | null;
  offer_validity_source: string | null;
  price: string | null;
  price_basis: string | null;
  unit_price: string | null;
  unit_price_unit: string | null;
  currency: string | null;
  embedded: boolean;
  blocked: boolean;
  sales_blocked: boolean;
  purchasing_blocked: boolean;
  master_item: boolean;
};

export function getCatalogueArticles(signal?: AbortSignal) {
  return requestJson<CatalogueArticle[]>('/api/v1/catalogue/articles', { signal });
}

export type CatalogImportResult = {
  import_id: string;
  catalog_snapshot_id: string | null;
  status: 'completed' | 'completed_with_warnings';
  idempotent_replay: boolean;
  inserted_items: number;
  text_updated_items: number;
  metadata_updated_items: number;
  unchanged_items: number;
  inventory_refreshed_items: number;
  missing_items: number;
  reactivated_items: number;
  embedding_jobs_created: number;
  warnings: string[];
  completed_at: string;
};

export type CatalogEmbeddingStatus = {
  import_id: string;
  model_id: string | null;
  configuration_error: string | null;
  pending: number;
  running: number;
  completed: number;
  failed: number;
};

export function importCatalogue(articleData: File, translations: File) {
  const body = new FormData();
  body.append('article_data', articleData);
  body.append('article_translations', translations);
  return requestJson<CatalogImportResult>('/api/v1/catalog-imports', { method: 'POST', body });
}

export function getCatalogueEmbeddingStatus(importId: string, signal?: AbortSignal) {
  return requestJson<CatalogEmbeddingStatus>(
    `/api/v1/catalog-imports/${encodeURIComponent(importId)}/embedding-status`, { signal },
  );
}
