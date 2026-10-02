import { useEffect, useState } from 'react';
import { berlinDay } from './offer-display';

/** Refresh date-dependent labels locally, including after a suspended tab resumes. */
export function useOfferDateRefresh(): void {
  const [, setDay] = useState(() => berlinDay(new Date()));

  useEffect(() => {
    const refresh = () => setDay(berlinDay(new Date()));
    refresh();
    const timer = window.setInterval(refresh, 60_000);
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('focus', refresh);
      document.removeEventListener('visibilitychange', refresh);
    };
  }, []);
}
