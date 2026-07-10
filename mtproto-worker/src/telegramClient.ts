import { ENV } from "./env.js";

type TelegramClientLike = {
  connect(): Promise<boolean>;
  getMe(): Promise<unknown>;
};

let clientPromise: Promise<TelegramClientLike> | null = null;

function parseProxy():
  | { ip: string; port: number; socksType: 5; username?: string; password?: string }
  | undefined {
  const raw = ENV.TELEGRAM_PROXY_URL;
  if (!raw) return undefined;
  const u = new URL(raw);
  const out: { ip: string; port: number; socksType: 5; username?: string; password?: string } = {
    ip: u.hostname,
    port: u.port ? Number(u.port) : 1080,
    socksType: 5,
  };
  if (u.username) out.username = decodeURIComponent(u.username);
  if (u.password) out.password = decodeURIComponent(u.password);
  return out;
}

export async function getTelegramClient(): Promise<TelegramClientLike> {
  if (!clientPromise) {
    clientPromise = (async () => {
      const proxy = parseProxy();
      const { TelegramClient } = await import("telegram");
      const { StringSession } = await import("telegram/sessions/index.js");
      const client = new TelegramClient(
        new StringSession(ENV.TELEGRAM_USER_SESSION),
        ENV.TELEGRAM_API_ID,
        ENV.TELEGRAM_API_HASH,
        {
          connectionRetries: 8,
          autoReconnect: true,
          ...(proxy ? { proxy } : {}),
          useWSS: !proxy,
        },
      ) as unknown as TelegramClientLike;
      await client.connect();
      return client;
    })();
  }
  return clientPromise;
}

export async function getFullClient() {
  const proxy = parseProxy();
  const { TelegramClient } = await import("telegram");
  const { StringSession } = await import("telegram/sessions/index.js");
  const client = new TelegramClient(
    new StringSession(ENV.TELEGRAM_USER_SESSION),
    ENV.TELEGRAM_API_ID,
    ENV.TELEGRAM_API_HASH,
    {
      connectionRetries: 8,
      autoReconnect: true,
      ...(proxy ? { proxy } : {}),
      useWSS: !proxy,
    },
  );
  await client.connect();
  return client;
}
