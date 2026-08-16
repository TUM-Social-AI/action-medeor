const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly details?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, init);

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export async function requestBlob(path: string, init?: RequestInit): Promise<Blob> {
  const response = await request(path, init);
  return response.blob();
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    const body = await readErrorBody(response);
    const detail = getErrorDetail(body);
    throw new ApiError(detail ?? `Backend returned ${response.status}`, response.status, body);
  }

  return response;
}

async function readErrorBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') ?? '';
  if (contentType.includes('application/json')) {
    return response.json().catch(() => null);
  }
  return response.text().catch(() => null);
}

function getErrorDetail(body: unknown): string | null {
  if (typeof body === 'string') {
    return body || null;
  }
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail?: unknown }).detail;
    return typeof detail === 'string' ? detail : JSON.stringify(detail);
  }
  return null;
}
