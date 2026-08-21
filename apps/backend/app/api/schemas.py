from typing import Literal

from pydantic import BaseModel

Priority = Literal["critical", "high", "medium", "low"]
ItemStatus = Literal["verified", "needs_review", "low_confidence", "missing"]
ImportFileType = Literal["pdf", "xlsx", "xls"]
RiskLevel = Literal["critical", "high", "medium"]


class HomeStat(BaseModel):
    key: str
    label: str
    value: str
    sub: str


class RecentRequest(BaseModel):
    id: str
    partner: str
    region: str
    date: str
    items: int
    matchRate: int
    status: str


class HomeResponse(BaseModel):
    userName: str
    organization: str
    currentDate: str
    stats: list[HomeStat]
    recentRequests: list[RecentRequest]


class RecentImport(BaseModel):
    id: int
    fileName: str
    partner: str
    date: str
    items: int
    type: ImportFileType


class SourceInfo(BaseModel):
    fileName: str
    rowsDetected: int
    partner: str


class PartnerDetails(BaseModel):
    partner: str
    region: str
    requestId: str
    contact: str
    confirmed: bool = False
    requestDate: str | None = None
    sourceFile: str | None = None


class SourceReference(BaseModel):
    itemId: int
    page: int
    row: int
    excerpt: str


class ExtractedItem(BaseModel):
    id: int
    name: str
    quantity: int | None
    unit: str
    notes: str
    priority: Priority
    confidence: int | None
    status: ItemStatus


class ReviewCounts(BaseModel):
    total: int
    verified: int
    needsReview: int
    lowConfidence: int
    missing: int


class ReviewResponse(BaseModel):
    requestId: str
    source: SourceInfo
    partner: PartnerDetails
    items: list[ExtractedItem]
    sourceReferences: list[SourceReference]
    counts: ReviewCounts


class ItemUpdate(BaseModel):
    name: str | None = None
    quantity: int | None = None
    unit: str | None = None
    notes: str | None = None
    priority: Priority | None = None


class PartnerUpdate(BaseModel):
    partner: str
    region: str
    requestId: str
    contact: str


class RequestedItem(BaseModel):
    id: int
    name: str
    quantity: int
    unit: str
    priority: Literal["critical", "high", "medium"]


class ErpMatch(BaseModel):
    id: str
    name: str
    sku: str
    manufacturer: str
    score: int
    stock: int
    unit: str
    lowStock: bool = False


class MatchingResponse(BaseModel):
    requestId: str
    requestedItems: list[RequestedItem]
    matches: dict[int, list[ErpMatch]]
    selectedMatches: dict[int, str]


class MatchSelection(BaseModel):
    matchId: str


class MatchSelectionResponse(BaseModel):
    itemId: int
    matchId: str


class SummaryItem(BaseModel):
    id: int
    requested: str
    erpProduct: str
    sku: str
    quantity: int
    unit: str
    packageSize: str
    matchScore: int
    stock: str
    pricePerUnit: float


class SummaryMetrics(BaseModel):
    totalLineItems: int
    highConfidenceMatches: int
    averageMatchScore: int
    estimatedTotalValue: float


class SummaryResponse(BaseModel):
    requestId: str
    sourceFile: str
    partner: PartnerDetails
    items: list[SummaryItem]
    metrics: SummaryMetrics


class OfferResponse(BaseModel):
    requestId: str
    fileName: str
    lineItems: int
    totalValue: float
    partner: str
    generatedAt: str


class KpiCard(BaseModel):
    key: str
    label: str
    value: str
    delta: str
    up: bool
    sub: str


class DemandTrendPoint(BaseModel):
    month: str
    antibiotics: int
    analgesics: int
    trauma: int
    ivFluids: int


class RegionalDemand(BaseModel):
    region: str
    requests: int
    items: int


class CategoryDemand(BaseModel):
    name: str
    items: int
    change: int
    risk: RiskLevel


class TopRequestedItem(BaseModel):
    name: str
    requests: int
    totalQty: int
    trend: int


class TrendsResponse(BaseModel):
    asOf: str
    kpis: list[KpiCard]
    demandTrend: list[DemandTrendPoint]
    regionalDemand: list[RegionalDemand]
    categoryDemand: list[CategoryDemand]
    topItems: list[TopRequestedItem]
