import { API_BASE_URL, ApiError, Role, setRole, setToken } from "./client";

interface LoginResponse {
  access_token: string;
  token_type: string;
  role: Role;
}

// POST /auth/login expects OAuth2PasswordRequestForm — url-encoded form
// fields, not JSON (see app/main.py).
export async function login(username: string, password: string): Promise<void> {
  const body = new URLSearchParams({ username, password }).toString();
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = "login failed";
    }
    throw new ApiError(response.status, detail);
  }

  const data: LoginResponse = await response.json();
  await setToken(data.access_token);
  await setRole(data.role);
}
