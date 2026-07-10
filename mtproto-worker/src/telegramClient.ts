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

function isAuthKeyDuplicated(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return /AUTH_KEY_DUPLICATED/i.test(msg);
}

/** Single shared client — never open two connections with the same StringSession. */
let clientPromise: Promise<Awaited<ReturnType<typeof createClient>>> | null = null;

async function createClient() {
  const proxy = parseProxy();
  const { TelegramClient } = await import("telegram");
  const { StringSession } = await import("telegram/sessions/index.js");
  const client = new TelegramClient(
    new StringSession(ENV.TELEGRAM_USER_SESSION),
    ENV.TELEGRAM_API_ID,
    ENV.TELEGRAM_API_HASH,
    {
      connectionRetries: 3,
      autoReconnect: true,
      ...(proxy ? { proxy } : {}),
      useWSS: !proxy,
    },
  );
  try {
    await client.connect();
  } catch (e) {
    if (isAuthKeyDuplicated(e)) {
      console.error(`
[orderhunter] AUTH_KEY_DUPLICATED — эта TELEGRAM_USER_SESSION уже подключена где-то ещё.

Что сделать:
1. Railway → orderhunter-mtproto → Settings → Replicas = 1 (не больше)
2. Остановите локальный mtproto-worker / другой хост с той же session
3. Подождите 1–2 минуты, затем Redeploy
4. Если не помогло — перелогиньтесь:
   cd mtproto-worker && npm run telegram:login
   и обновите TELEGRAM_USER_SESSION в Railway
`);
      // Slow down Railway crash-loop while the other connection dies
      await new Promise((r) => setTimeout(r, 120_000));
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
