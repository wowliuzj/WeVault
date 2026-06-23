type TurnstileCallback = (token: string) => void;

type TurnstileApi = {
  render: (
    container: HTMLElement,
    options: {
      sitekey: string;
      callback: TurnstileCallback;
      "expired-callback": () => void;
      "error-callback": () => void;
    },
  ) => string;
  reset: (widgetId?: string) => void;
  remove: (widgetId: string) => void;
};

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

const SCRIPT_ID = "cloudflare-turnstile-script";

export const turnstileSiteKey = import.meta.env.VITE_TURNSTILE_SITE_KEY || "";

export function loadTurnstileScript(): Promise<void> {
  if (!turnstileSiteKey || window.turnstile) {
    return Promise.resolve();
  }

  const existingScript = document.getElementById(SCRIPT_ID);
  if (existingScript) {
    return new Promise((resolve, reject) => {
      existingScript.addEventListener("load", () => resolve(), { once: true });
      existingScript.addEventListener("error", () => reject(new Error("Turnstile 加载失败")), {
        once: true,
      });
    });
  }

  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.id = SCRIPT_ID;
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    script.async = true;
    script.defer = true;
    script.addEventListener("load", () => resolve(), { once: true });
    script.addEventListener("error", () => reject(new Error("Turnstile 加载失败")), {
      once: true,
    });
    document.head.appendChild(script);
  });
}
