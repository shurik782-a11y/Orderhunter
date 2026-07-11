import { ENV } from "./env.js";

type ProxyOpts = {
  ip: string;
  port: number;
  socksType: 5;
  username?: string;
  password?: string;
};

function parseProxy(): ProxyOpts | undefined {
  const raw = ENV.TELEGRAM_PROXY_URL;
  if (!raw) return undefined;
  const u = new URL(raw);
  const out: ProxyOpts = {
    ip: u.hostname,
    port: u.port ? Number(u.port) : 1080,
    socksType: 5,
  };
  if (u.username) out.username = decodeURIComponent(u.username);
  if (u.password) out.password = decodeURIComponent(u.password);
  return out;
}

export function isAuthKeyDuplicated(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return /AUTH_KEY_DUPLICATED/i.test(msg);
}

export const AUTH_KEY_DUPLICATED_HELP = `
[orderhunter] AUTH_KEY_DUPLICATED — эта TELEGRAM_USER_SESSION уже использовалась
параллельно (2 реплики / локально + Railway) и Telegram её заблокировал.

Повторный Redeploy со СТАРОЙ строкой обычно НЕ помогает — нужна НОВАЯ session.

Что сделать:
1. Railway → orderhunter-mtproto → Settings → Replicas = 1
2. Убедитесь, что нигде больше не крутится mtproto с этой session
3. Локально получите новую session:
     cd mtproto-worker
     npm run telegram:login
4. Скопируйте новую TELEGRAM_USER_SESSION в Railway Variables (замените старую)
5. Redeploy orderhunter-mtproto один раз
`;

/** Single shared client — never open two connections with the same StringSession. */
let clientPromise: Promise<Awaited<ReturnType<typeof createClient>>> | null =
  null;

async function createClient() {
  const proxy = parseProxy();
  const { TelegramClient } = await import("telegram");
  const { StringSession } = await import("telegram/sessions/index.js");

  // autoReconnect MUST stay false: on AUTH_KEY_DUPLICATED gramJS reconnect
  // keeps the crash-loop alive and fights the sleep/exit path.
  const client = new TelegramClient(
    new StringSession(ENV.TELEGRAM_USER_SESSION),
    ENV.TELEGRAM_API_ID,
    ENV.TELEGRAM_API_HASH,
    {
      connectionRetries: 1,
      autoReconnect: false,
      ...(proxy ? { proxy } : {}),
      useWSS: !proxy,
    },
  );

  try {
    await client.connect();
  } catch (e) {
    try {
      await client.disconnect();
    } catch {
      /* ignore */
    }
    if (isAuthKeyDuplicated(e)) {
      console.error(AUTH_KEY_DUPLICATED_HELP);
    }
    throw e;
  }
  return client;
}

export async function getFullClient() {
  if (!clientPromise) {
    clientPromise = createClient().catch((e) => {
      clientPromise = null;
      throw e;
    });
  }
  return clientPromise;
}

/** @deprecated use getFullClient — kept for compatibility */
export async function getTelegramClient() {
  return getFullClient();
}
