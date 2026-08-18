import { useState } from 'react';
import { createImport } from './api/client';
import type { LoadingType, ReviewResponse, Screen } from './api/types';
import { DEFAULT_REQUEST_ID } from './api/types';
import { HomeScreen } from './components/HomeScreen';
import { IngestionScreen } from './components/IngestionScreen';
import { Layout } from './components/Layout';
import { OrderSummaryScreen } from './components/OrderSummaryScreen';
import { ProcessingScreen } from './components/ProcessingScreen';
import { ReviewItemsScreen } from './components/ReviewItemsScreen';
import { SmartMatchingScreen } from './components/SmartMatchingScreen';
import { TrendDashboard } from './components/TrendDashboard';
import { fixtureMatchingWorkflowApi } from './features/matching/fixture-api';
import type { MatchingScreenView } from './features/matching/models';

const EXTRACTION_LOADING_DURATION = 3000;

export default function App() {
  const [currentScreen, setCurrentScreen] = useState<Screen>('home');
  const [loadingType, setLoadingType] = useState<LoadingType | null>(null);
  const [requestId, setRequestId] = useState(DEFAULT_REQUEST_ID);
  const [reviewData, setReviewData] = useState<ReviewResponse | null>(null);
  const [matchingData, setMatchingData] = useState<MatchingScreenView | null>(null);
  const [workflowError, setWorkflowError] = useState<string | null>(null);

  const navigate = (screen: Screen) => {
    setWorkflowError(null);
    setCurrentScreen(screen);
  };

  const handleImport = async (file: File) => {
    setWorkflowError(null);
    setLoadingType('extracting');

    try {
      const [response] = await Promise.all([createImport(file), delay(EXTRACTION_LOADING_DURATION)]);
      setReviewData(response);
      setRequestId(response.requestId);
      setCurrentScreen('review');
    } catch (caught) {
      setWorkflowError(caught instanceof Error ? caught.message : 'Unable to create import');
      setCurrentScreen('ingestion');
    } finally {
      setLoadingType(null);
    }
  };

  const handleStartMatching = async () => {
    setWorkflowError(null);
    setLoadingType('matching');

    try {
      const response = await fixtureMatchingWorkflowApi.start(requestId);
      setMatchingData(response);
      setCurrentScreen('matching');
    } catch (caught) {
      setWorkflowError(caught instanceof Error ? caught.message : 'Unable to start matching');
      setCurrentScreen('review');
    } finally {
      setLoadingType(null);
    }
  };

  return (
    <Layout currentScreen={currentScreen} onNavigate={navigate}>
      {loadingType ? (
        <ProcessingScreen type={loadingType} />
      ) : (
        <>
          {currentScreen === 'home' && (
            <HomeScreen
              onCreateRequest={() => navigate('ingestion')}
              onViewDashboard={() => navigate('dashboard')}
            />
          )}
          {currentScreen === 'dashboard' && <TrendDashboard />}
          {currentScreen === 'ingestion' && (
            <IngestionScreen onContinue={file => void handleImport(file)} error={workflowError} />
          )}
          {currentScreen === 'review' && (
            <ReviewItemsScreen
              requestId={requestId}
              initialData={reviewData}
              onContinue={() => void handleStartMatching()}
            />
          )}
          {currentScreen === 'matching' && (
            <SmartMatchingScreen
              requestId={requestId}
              initialData={matchingData}
              api={fixtureMatchingWorkflowApi}
              onContinue={() => navigate('summary')}
            />
          )}
          {currentScreen === 'summary' && (
            <OrderSummaryScreen requestId={requestId} onBack={() => navigate('matching')} />
          )}
        </>
      )}
    </Layout>
  );
}

function delay(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms));
}
