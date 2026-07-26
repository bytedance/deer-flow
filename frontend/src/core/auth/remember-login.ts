const REMEMBER_LOGIN_KEY = "deerflow.auth.remember_login";
const REMEMBERED_EMAIL_KEY = "deerflow.auth.remembered_email";

export interface RememberLoginPreference {
  email: string;
  rememberMe: boolean;
}

function getStorage(): Storage | null {
  if (typeof globalThis.localStorage === "undefined") return null;
  return globalThis.localStorage;
}

export function loadRememberLoginPreference(): RememberLoginPreference {
  try {
    const storage = getStorage();
    if (!storage) {
      return { email: "", rememberMe: true };
    }
    const rememberValue = storage.getItem(REMEMBER_LOGIN_KEY);
    const rememberMe = rememberValue !== "0";
    return {
      email: rememberMe ? (storage.getItem(REMEMBERED_EMAIL_KEY) ?? "") : "",
      rememberMe,
    };
  } catch {
    return { email: "", rememberMe: true };
  }
}

export function saveRememberLoginPreference({
  email,
  rememberMe,
}: RememberLoginPreference): void {
  try {
    const storage = getStorage();
    if (!storage) return;
    storage.setItem(REMEMBER_LOGIN_KEY, rememberMe ? "1" : "0");
    if (rememberMe) {
      storage.setItem(REMEMBERED_EMAIL_KEY, email);
    } else {
      storage.removeItem(REMEMBERED_EMAIL_KEY);
    }
  } catch {
    // Login must not depend on localStorage availability.
  }
}
