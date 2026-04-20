export type TokenPayload = {
  identity: string;
  room: string;
  name?: string;
  access_key?: string;
};

export type TokenResponse = {
  token: string;
  room: string;
  identity: string;
  ws_url: string;
};

function getApiBaseUrl(): string {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "");
  if (configured) {
    return configured;
  }

  // For cloud/browser deployments, default to same origin when not explicitly configured.
  if (typeof window !== "undefined") {
    return window.location.origin;
  }

  return "http://localhost:8000";
}

export async function fetchLivekitToken(payload: TokenPayload): Promise<TokenResponse> {
  let response: Response;
  const apiBaseUrl = getApiBaseUrl();

  try {
    response = await fetch(`${apiBaseUrl}/api/v1/livekit/token`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
  } catch {
    throw new Error(
      `Cannot reach backend API at ${apiBaseUrl}. Set NEXT_PUBLIC_API_BASE_URL for cloud deployment.`
    );
  }

  if (!response.ok) {
    const reason = await response.text();
    throw new Error(reason || "Failed to fetch LiveKit token");
  }

  return response.json();
}
