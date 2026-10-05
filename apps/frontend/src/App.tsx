import { useEffect, useRef, useState } from 'react';
import type { LoadingType, ManualItemCreate, PartnerDetails, ReviewResponse, Screen } from './api/types';
import { createImport } from './api/client';
import { getAvatar, getCurrentUser, saveAvatar, type AvatarId } from './api/identity';
import {
  createManualRequest,
  finalizeRequest,
  getRequest,
  reopenRequestMatching,
  startRequestMatching,
  uploadRequestFile,
  type SavedRequest,
} from './api/workflow';
import { HelpScreen } from './components/HelpScreen';
import { SettingsScreen } from './components/SettingsScreen';
import { HomeScreen } from './components/HomeScreen';
import { IngestionScreen } from './components/IngestionScreen';
import { Layout } from './components/Layout';
import { OrderSummaryScreen } from './components/OrderSummaryScreen';
import { ProcessingScreen } from './components/ProcessingScreen';
import { ReviewItemsScreen } from './components/ReviewItemsScreen';
import { SmartMatchingScreen } from './components/SmartMatchingScreen';
import { TrendDashboard } from './components/TrendDashboard';
import { CatalogueScreen } from './components/CatalogueScreen';

function screenFor(request: SavedRequest): Screen {
  if (request.status === 'draft') return 'ingestion';
  if (request.status === 'review') return 'review';
  if (request.status === 'finalized') return 'summary';
  return 'matching';
}

const WORKFLOW_SCREENS: Screen[] = ['ingestion', 'review', 'matching', 'summary'];
const GENERAL_SCREENS: Screen[] = ['home', 'history', 'dashboard', 'catalogue', 'settings', 'help'];

function emptyManualReview(): ReviewResponse {
  return {
    requestId: '', source: { fileName: '', rowsDetected: 0, partner: '' },
    partner: { partner: '', region: '', requestId: '', contact: '', confirmed: false },
    items: [], sourceReferences: [],
    counts: { total: 0, verified: 0, needsReview: 0, lowConfidence: 0, missing: 0 },
    attributeColumns: [], columnLabels: {}, availableColumns: [],
  };
}

export default function App() {
  const [currentScreen, setCurrentScreen] = useState<Screen>('home');
  const [displayName, setDisplayName] = useState('Local User');
  const [avatarId, setAvatarId] = useState<AvatarId>('cat');
  const [loadingType, setLoadingType] = useState<LoadingType | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [reviewData, setReviewData] = useState<ReviewResponse | null>(null);
  const [workflowError, setWorkflowError] = useState<string | null>(null);
  const [manualDraft, setManualDraft] = useState(false);

  const navigationVersion = useRef(0);

  useEffect(() => {
    let active = true;
    void getCurrentUser().then(user => {
      if (active) setDisplayName(user.displayName || 'Local User');
    }).catch(() => {});
    void getAvatar().then(preference => {
      if (active) setAvatarId(preference.avatarId);
    }).catch(() => {});
    return () => { active = false; };
  }, []);

  const changeAvatar = async (choice: AvatarId) => {
    const saved = await saveAvatar(choice);
    setAvatarId(saved.avatarId);
  };

  const navigate = (screen: Screen, id = requestId, isManualDraft = false) => {
    navigationVersion.current += 1;
    setLoadingType(null);
    setWorkflowError(null);
    setCurrentScreen(screen);
    setManualDraft(isManualDraft);
    const url = new URL(window.location.href);
    url.searchParams.delete('mode');
    if (id && WORKFLOW_SCREENS.includes(screen)) {
      url.searchParams.delete('screen');
      url.searchParams.set('request', id);
      url.searchParams.set('step', screen);
    } else {
      url.searchParams.delete('request');
      url.searchParams.delete('step');
      url.searchParams.set('screen', screen);
      if (isManualDraft) url.searchParams.set('mode', 'manual');
    }
    window.history.pushState({}, '', url);
  };

  useEffect(() => {
    const restore = async () => {
      const version = ++navigationVersion.current;
      const params = new URLSearchParams(window.location.search);
      const id = params.get('request');
      setLoadingType(null);
      setWorkflowError(null);
      setReviewData(null);
      setRequestId(null);
      setManualDraft(false);
      if (!id) {
        const screen = params.get('screen') as Screen | null;
        if (screen === 'review' && params.get('mode') === 'manual') {
          setReviewData(emptyManualReview());
          setManualDraft(true);
          setCurrentScreen('review');
          return;
        }
        setCurrentScreen(screen && (GENERAL_SCREENS.includes(screen) || screen === 'ingestion') ? screen : 'home');
        return;
      }
      setCurrentScreen('home');
      try {
        const request = await getRequest(id);
        if (version !== navigationVersion.current) return;
        setRequestId(id);
        const allowed = ['complete', 'finalized'].includes(request.status) && params.get('step') === 'summary';
        setCurrentScreen(allowed ? 'summary' : screenFor(request));
      } catch (caught) {
        if (version !== navigationVersion.current) return;
        setWorkflowError(caught instanceof Error ? caught.message : 'Request unavailable');
      }
    };
    void restore();
    window.addEventListener('popstate', restore);
    return () => {
      navigationVersion.current += 1;
      window.removeEventListener('popstate', restore);
    };
  }, []);

  const openRequest = (request: SavedRequest) => {
    setRequestId(request.requestId);
    setReviewData(null);
    navigate(screenFor(request), request.requestId);
  };

  const createNewRequest = () => {
    setRequestId(null);
    setReviewData(null);
    navigate('ingestion', null);
  };

  const handleImport = async (file: File) => {
    setWorkflowError(null);
    setLoadingType('extracting');
    try {
      const response = requestId
        ? await uploadRequestFile(requestId, file)
        : await createImport(file);
      setRequestId(response.requestId);
      setReviewData(response);
      navigate('review', response.requestId);
    } catch (caught) {
      setWorkflowError(caught instanceof Error ? caught.message : 'Unable to extract file');
    } finally {
      setLoadingType(null);
    }
  };

  const handleStartMatching = async () => {
    if (!requestId) return;
    setWorkflowError(null);
    setLoadingType('matching');
    try {
      await startRequestMatching(requestId);
      navigate('matching');
    } catch (caught) {
      setWorkflowError(caught instanceof Error ? caught.message : 'Unable to start matching');
    } finally {
      setLoadingType(null);
    }
  };

  const handleStartManual = () => {
    setRequestId(null);
    setReviewData(emptyManualReview());
    navigate('review', null, true);
  };

  const handleCreateManual = async (
    item: ManualItemCreate, partner: PartnerDetails, columnLabels: Record<string, string>,
  ) => {
    const version = navigationVersion.current;
    const response = await createManualRequest(item, partner, columnLabels);
    if (version === navigationVersion.current) {
      setRequestId(response.requestId);
      setReviewData(response);
      navigate('review', response.requestId);
    }
    return response;
  };

  const finalizeAndOpenSummary = async () => {
    if (!requestId) return;
    await finalizeRequest(requestId);
    navigate('summary');
  };

  const returnToMatching = async () => {
    if (!requestId) return;
    await reopenRequestMatching(requestId);
    navigate('matching');
  };

  const handleNavigate = (screen: Screen) => {
    if (screen === 'ingestion') {
      if (!WORKFLOW_SCREENS.includes(currentScreen)) createNewRequest();
      return;
    }
    navigate(screen);
  };

  return <Layout currentScreen={currentScreen} onNavigate={handleNavigate} displayName={displayName} avatarId={avatarId} onAvatarChange={changeAvatar}>
    {loadingType ? <ProcessingScreen type={loadingType} /> : <>
      {(currentScreen === 'home' || currentScreen === 'history') && <HomeScreen
        history={currentScreen === 'history'}
        displayName={displayName}
        onCreateRequest={createNewRequest}
        onOpenRequest={openRequest}
        onViewDashboard={() => navigate('dashboard')}
        onViewHistory={() => navigate('history')}
        error={workflowError}
      />}
      {currentScreen === 'settings' && <SettingsScreen />}
      {currentScreen === 'help' && <HelpScreen onViewHistory={() => navigate('history')} />}
      {currentScreen === 'dashboard' && <TrendDashboard />}
      {currentScreen === 'catalogue' && <CatalogueScreen />}
      {currentScreen === 'ingestion' && <IngestionScreen
        onContinue={file => void handleImport(file)} error={workflowError} onOpenRequest={openRequest}
        onStartManual={handleStartManual}
      />}
      {currentScreen === 'review' && (requestId || manualDraft) && <ReviewItemsScreen
        key={requestId ?? 'manual-draft'} requestId={requestId} initialData={reviewData}
        onCreateManual={handleCreateManual}
        onContinue={() => void handleStartMatching()}
      />}
      {currentScreen === 'matching' && requestId && <SmartMatchingScreen
        key={requestId} requestId={requestId} onContinue={finalizeAndOpenSummary}
      />}
      {currentScreen === 'summary' && requestId && <OrderSummaryScreen
        key={requestId} requestId={requestId} onBack={returnToMatching}
      />}
    </>}
  </Layout>;
}
