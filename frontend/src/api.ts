export type HealthResponse = {
  status: string;
};

export async function getBackendHealth(): Promise<HealthResponse> {
  const response = await fetch("/api/health");

  if (!response.ok) {
    throw new Error(`Backend health check failed: ${response.status}`);
  }

  return (await response.json()) as HealthResponse;
}
