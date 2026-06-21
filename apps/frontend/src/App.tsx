import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Activity, CheckCircle2, Database, Server, TriangleAlert } from 'lucide-react';

type HealthResponse = {
  status: 'ok' | 'degraded';
  service: string;
  environment: string;
  database: {
    status: 'ok' | 'error';
    detail?: string;
  };
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const apiHealthUrl = useMemo(() => `${apiBaseUrl.replace(/\/$/, '')}/api/health`, []);

  useEffect(() => {
    let isMounted = true;

    async function loadHealth() {
      try {
        setIsLoading(true);
        const response = await fetch(apiHealthUrl);

        if (!response.ok) {
          throw new Error(`Backend returned ${response.status}`);
        }

        const data = (await response.json()) as HealthResponse;

        if (isMounted) {
          setHealth(data);
          setError(null);
        }
      } catch (caughtError) {
        if (isMounted) {
          setHealth(null);
          setError(caughtError instanceof Error ? caughtError.message : 'Unable to reach backend');
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    loadHealth();

    return () => {
      isMounted = false;
    };
  }, [apiHealthUrl]);

  const apiStatus = health?.status ?? (error ? 'degraded' : 'ok');
  const databaseStatus = health?.database.status ?? 'error';

  return (
    <main className="shell">
      <section className="workspace">
        <div className="masthead">
          <div>
            <p className="eyebrow">Full-stack workspace</p>
            <h1>Allocura</h1>
          </div>
          <div className={`status-pill ${apiStatus}`}>
            {apiStatus === 'ok' ? <CheckCircle2 size={18} /> : <TriangleAlert size={18} />}
            <span>{isLoading ? 'Checking services' : apiStatus}</span>
          </div>
        </div>

        <div className="status-grid" aria-live="polite">
          <StatusTile
            icon={<Server size={24} />}
            title="Backend API"
            value={isLoading ? 'Checking' : health?.service ?? 'Unavailable'}
            detail={error ?? apiHealthUrl}
            tone={error ? 'warning' : 'success'}
          />
          <StatusTile
            icon={<Database size={24} />}
            title="Database"
            value={isLoading ? 'Checking' : databaseStatus}
            detail={health?.database.detail ?? 'Postgres via DATABASE_URL'}
            tone={databaseStatus === 'ok' ? 'success' : 'warning'}
          />
          <StatusTile
            icon={<Activity size={24} />}
            title="Environment"
            value={health?.environment ?? 'development'}
            detail="Configured through Vite and FastAPI settings"
            tone="neutral"
          />
        </div>
      </section>
    </main>
  );
}

type StatusTileProps = {
  icon: ReactNode;
  title: string;
  value: string;
  detail: string;
  tone: 'success' | 'warning' | 'neutral';
};

function StatusTile({ icon, title, value, detail, tone }: StatusTileProps) {
  return (
    <article className={`status-tile ${tone}`}>
      <div className="tile-icon">{icon}</div>
      <div>
        <p>{title}</p>
        <h2>{value}</h2>
        <span>{detail}</span>
      </div>
    </article>
  );
}
