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
};

export function getCatalogueArticles(signal?: AbortSignal) {
  return requestJson<CatalogueArticle[]>('/api/v1/catalogue/articles', { signal });
}
