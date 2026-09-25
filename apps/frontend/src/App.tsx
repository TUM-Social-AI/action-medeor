import { useEffect, useState } from 'react';
import type { LoadingType, ReviewResponse, Screen } from './api/types';
import { createImport } from './api/client';
import {
  finalizeRequest,
  getRequest,
  reopenRequestMatching,
  startRequestMatching,
  uploadRequestFile,
  type SavedRequest,
} from './api/workflow';
import { HomeScreen } from './components/HomeScreen';
import { IngestionScreen } from './components/IngestionScreen';
import { Layout } from './components/Layout';
import { OrderSummaryScreen } from './components/OrderSummaryScreen';
import { ProcessingScreen } from './components/ProcessingScreen';
import { ReviewItemsScreen } from './components/ReviewItemsScreen';
import { SmartMatchingScreen } from './components/SmartMatchingScreen';
import { TrendDashboard } from './components/TrendDashboard';

function screenFor(request: SavedRequest): Screen {
  if (request.status === 'draft') return 'ingestion';
  if (request.status === 'review') return 'review';
  if (request.status === 'finalized') return 'summary';
  return 'matching';
}

export default function App() {
  const [currentScreen, setCurrentScreen] = useState<Screen>('home');
  const [loadingType, setLoadingType] = useState<LoadingType | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [reviewData, setReviewData] = useState<ReviewResponse | null>(null);
  const [workflowError, setWorkflowError] = useState<string | null>(null);

  const navigate = (screen: Screen, id = requestId) => {
    setWorkflowError(null);
    setCurrentScreen(screen);
    const url = new URL(window.location.href);
    if (id && !['home', 'history', 'dashboard'].includes(screen)) {
      url.searchParams.set('request', id);
      url.searchParams.set('step', screen);
    } else {
      url.searchParams.delete('request');
      url.searchParams.delete('step');
    }
    window.history.pushState({}, '', url);
  };

  useEffect(() => {
    const restore = async () => {
      const params = new URLSearchParams(window.location.search);
      const id = params.get('request');
      if (!id) return;
      try {
        const request = await getRequest(id);
        setRequestId(id);
        const requestedStep = params.get('step') as Screen | null;
        const allowed = ['complete', 'finalized'].includes(request.status) && requestedStep === 'summary';
        setCurrentScreen(allowed ? 'summary' : screenFor(request));
      } catch (caught) {
        setWorkflowError(caught instanceof Error ? caught.message : 'Request unavailable');
      }
    };
    void restore();
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
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
      if (currentScreen !== 'ingestion') createNewRequest();
      return;
    }
    if (['review', 'matching', 'summary'].includes(screen)) {
      if (!requestId) return;
      void getRequest(requestId).then(async request => {
        const matchingAvailable = !['draft', 'review'].includes(request.status);
        if (screen === 'review' && request.status !== 'review') navigate(screenFor(request));
        else if (screen === 'matching' && !matchingAvailable) navigate(screenFor(request));
        else if (screen === 'matching' && request.status === 'finalized') await returnToMatching();
        else if (screen === 'summary' && request.status === 'complete') await finalizeAndOpenSummary();
        else if (screen === 'summary' && request.status !== 'finalized') navigate(screenFor(request));
        else navigate(screen);
      }).catch(caught => setWorkflowError(caught instanceof Error ? caught.message : 'Request unavailable'));
      return;
    }
    navigate(screen);
  };

  return <Layout currentScreen={currentScreen} onNavigate={handleNavigate}>
    {loadingType ? <ProcessingScreen type={loadingType} /> : <>
      {(currentScreen === 'home' || currentScreen === 'history') && <HomeScreen
        history={currentScreen === 'history'}
        onCreateRequest={createNewRequest}
        onOpenRequest={openRequest}
        onViewDashboard={() => navigate('dashboard')}
        onViewHistory={() => navigate('history')}
        error={workflowError}
      />}
      {currentScreen === 'dashboard' && <TrendDashboard />}
      {currentScreen === 'ingestion' && <IngestionScreen
        onContinue={file => void handleImport(file)} error={workflowError} onOpenRequest={openRequest}
      />}
      {currentScreen === 'review' && requestId && <ReviewItemsScreen
        key={requestId} requestId={requestId} initialData={reviewData}
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
