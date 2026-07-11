import { createHash } from "crypto";

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

export function sessionFingerprint(session: string): string {
  return createHash("sha256").update(session.trim()).digest("hex").slice(0, 10);
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
1. Railway → orderhunter-mtproto → STOP / Remove deployment (сначала останови!)
2. Settings → Replicas = 1
3. Локально новую session:
     cd mtproto-worker
     npm run telegram:login
   Смотри fingerprint в выводе (sessionFp=...). Он ДОЛЖЕН отличаться от Railway.
4. Вставь новую TELEGRAM_USER_SESSION в Variables → Save
5. Start / Redeploy один раз. Пока сервис up — не гоняй login с этой же строкой.
`;

/** Single shared client — never open two connections with the same StringSession. */
let clientPromise: Promise<Awaited<ReturnType<typeof createClient>>> | null =
  null;

async function createClient() {
  const proxy = parseProxy();
  const { TelegramClient } = await import("telegram");
  const { StringSession } = await import("telegram/sessions/index.js");

  const fp = sessionFingerprint(ENV.TELEGRAM_USER_SESSION);
  console.log(
    `[orderhunter] sessionFp=${fp} len=${ENV.TELEGRAM_USER_SESSION.length} (сверь с выводом telegram:login)`,
  );

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
      console.error(
        `[orderhunter] текущий sessionFp=${fp} — если после login fingerprint тот же, Variables не обновились`,
      );
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
