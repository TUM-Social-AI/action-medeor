export type Screen = 'home' | 'ingestion' | 'review' | 'matching' | 'summary' | 'dashboard';
export type WorkflowStep = 'ingestion' | 'review' | 'matching' | 'summary';
export type LoadingType = 'extracting' | 'matching';

export type Priority = 'critical' | 'high' | 'medium' | 'low';
export type ReviewPriority = 'critical' | 'high' | 'medium';
export type ItemStatus = 'verified' | 'needs_review' | 'low_confidence' | 'missing';
export type ImportFileType = 'pdf' | 'xlsx' | 'xls';
export type RiskLevel = 'critical' | 'high' | 'medium';

export const DEFAULT_REQUEST_ID = 'SD-2024-0611';

export type HomeStat = {
  key: string;
  label: string;
  value: string;
  sub: string;
};

export type RecentRequest = {
  id: string;
  partner: string;
  region: string;
  date: string;
  items: number;
  matchRate: number;
  status: string;
};

export type HomeResponse = {
  userName: string;
  organization: string;
  currentDate: string;
  stats: HomeStat[];
  recentRequests: RecentRequest[];
};

export type RecentImport = {
  id: number;
  fileName: string;
  partner: string;
  date: string;
  items: number;
  type: ImportFileType;
};

export type SourceInfo = {
  fileName: string;
  rowsDetected: number;
  partner: string;
};

export type PartnerDetails = {
  partner: string;
  region: string;
  requestId: string;
  contact: string;
  confirmed: boolean;
  requestDate?: string | null;
  sourceFile?: string | null;
};

export type SourceReference = {
  itemId: number;
  page: number;
  row: number;
  excerpt: string;
};

export type ExtractedItem = {
  id: number;
  name: string;
  quantity: number | null;
  unit: string;
  notes: string;
  priority: Priority;
  confidence: number | null;
  status: ItemStatus;
};

export type ReviewCounts = {
  total: number;
  verified: number;
  needsReview: number;
  lowConfidence: number;
  missing: number;
};

export type ReviewResponse = {
  requestId: string;
  source: SourceInfo;
  partner: PartnerDetails;
  items: ExtractedItem[];
  sourceReferences: SourceReference[];
  counts: ReviewCounts;
};

export type ItemUpdate = Partial<Pick<ExtractedItem, 'name' | 'quantity' | 'unit' | 'notes' | 'priority'>>;

export type PartnerUpdate = Pick<PartnerDetails, 'partner' | 'region' | 'requestId' | 'contact'>;

export type RequestedItem = {
  id: number;
  name: string;
  quantity: number;
  unit: string;
  priority: ReviewPriority;
};

export type ErpMatch = {
  id: string;
  name: string;
  sku: string;
  manufacturer: string;
  score: number;
  stock: number;
  unit: string;
  lowStock: boolean;
};

export type MatchingResponse = {
  requestId: string;
  requestedItems: RequestedItem[];
  matches: Record<string, ErpMatch[]>;
  selectedMatches: Record<string, string>;
};

export type SummaryItem = {
  id: number;
  requested: string;
  erpProduct: string;
  sku: string;
  quantity: number;
  unit: string;
  packageSize: string;
  matchScore: number;
  stock: string;
  pricePerUnit: number;
};

export type SummaryMetrics = {
  totalLineItems: number;
  highConfidenceMatches: number;
  averageMatchScore: number;
  estimatedTotalValue: number;
};

export type SummaryResponse = {
  requestId: string;
  sourceFile: string;
  partner: PartnerDetails;
  items: SummaryItem[];
  metrics: SummaryMetrics;
};

export type OfferResponse = {
  requestId: string;
  fileName: string;
  lineItems: number;
  totalValue: number;
  partner: string;
  generatedAt: string;
};

export type KpiCard = {
  key: string;
  label: string;
  value: string;
  delta: string;
  up: boolean;
  sub: string;
};

export type DemandTrendPoint = {
  month: string;
  antibiotics: number;
  analgesics: number;
  trauma: number;
  ivFluids: number;
};

export type RegionalDemand = {
  region: string;
  requests: number;
  items: number;
};

export type CategoryDemand = {
  name: string;
  items: number;
  change: number;
  risk: RiskLevel;
};

export type TopRequestedItem = {
  name: string;
  requests: number;
  totalQty: number;
  trend: number;
};

export type TrendsResponse = {
  asOf: string;
  kpis: KpiCard[];
  demandTrend: DemandTrendPoint[];
  regionalDemand: RegionalDemand[];
  categoryDemand: CategoryDemand[];
  topItems: TopRequestedItem[];
};

