import { utils } from "telegram";

import { loadChannels, postToBackend, extractContactHint } from "./backendBridge.js";
import { ENV } from "./env.js";
import { getFullClient } from "./telegramClient.js";

const seen = new Set<string>();
const baselined = new Set<string>();
const invalidUsernames = new Set<string>();

type TgClient = Awaited<ReturnType<typeof getFullClient>>;
// GramJS entity — keep loose to avoid fragile type imports across versions.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type EntityLike = any;

let sharedClient: TgClient | null = null;

function messageKey(channel: string, id: number): string {
  return `${channel}:${id}`;
}

async function client(): Promise<TgClient> {
  if (!sharedClient) {
    sharedClient = await getFullClient();
  }
  return sharedClient;
}

function entityUsername(entity: unknown): string {
  const u = entity as { username?: string };
  return (u.username || "").toLowerCase();
}

/** Peer id string for NewMessage.chats — never pass raw entity objects. */
function peerIdOf(entity: EntityLike): string | null {
  try {
    return String(utils.getPeerId(entity));
  } catch {
    if (entity?.id != null) return String(entity.id);
    return null;
  }
}

async function resolveChannel(
  c: TgClient,
  username: string,
): Promise<{ username: string; entity: EntityLike } | null> {
  const clean = username.replace(/^@/, "").toLowerCase();
  if (invalidUsernames.has(clean)) return null;
  try {
    const entity = await c.getEntity(clean);
    return { username: clean, entity };
  } catch (e) {
    invalidUsernames.add(clean);
    const msg = e instanceof Error ? e.message : String(e);
    console.warn(`[orderhunter] skip @${clean}: ${msg}`);
    return null;
  }
}

export async function pollChannelsOnce(): Promise<void> {
  const channels = loadChannels();
  if (!channels.length) {
    console.warn("[orderhunter] no enabled channels in config");
    return;
  }

  const c = await client();
  for (const ch of channels) {
    const resolved = await resolveChannel(c, ch.username);
    if (!resolved) continue;
    const { username, entity } = resolved;
    const isBaseline = !baselined.has(username);
    try {
      for await (const msg of c.iterMessages(entity, { limit: 15 })) {
        if (!msg.id || msg.out) continue;
        const key = messageKey(username, msg.id);
        if (seen.has(key)) continue;
        seen.add(key);
        if (isBaseline) continue;
        const text = msg.message || "";
        if (text.length < 40) continue;
        await postToBackend({
          message_id: msg.id,
          channel: username,
          text,
          url: `https://t.me/${username}/${msg.id}`,
          contact_hint: extractContactHint(text),
        });
        console.log(`[orderhunter] ingested ${username}/${msg.id}`);
      }
      if (isBaseline) {
        baselined.add(username);
        console.log(`[orderhunter] baseline done for @${username}`);
      }
    } catch (e) {
      console.error(`[orderhunter] poll @${username} failed`, e);
    }
  }
}

export async function startRealtimeListener(): Promise<void> {
  const channels = loadChannels();
  const c = await client();

  const chatIds: string[] = [];
  const allowed = new Set<string>();

  for (const ch of channels) {
    const resolved = await resolveChannel(c, ch.username);
    if (!resolved) continue;
    const pid = peerIdOf(resolved.entity);
    if (pid) chatIds.push(pid);
    allowed.add(resolved.username);
  }

  if (!allowed.size) {
    console.warn("[orderhunter] no valid channels for realtime — poll-only mode");
    return;
  }

  const { NewMessage } = await import("telegram/events/NewMessage.js");

  // Do NOT pass entity objects into NewMessage.chats — GramJS stringifies them
  // as "[object Object]" and crashes the process. Filter by username allowlist.
  c.addEventHandler(async (event) => {
    try {
      const msg = event.message;
      if (!msg || msg.out) return;
      const text = msg.message || "";
      if (text.length < 40) return;
      const chat = await event.getChat();
      const username = entityUsername(chat);
      if (!username || !allowed.has(username)) return;
      const key = messageKey(username, msg.id);
      if (seen.has(key)) return;
      seen.add(key);
      await postToBackend({
        message_id: msg.id,
        channel: username,
        text,
        url: `https://t.me/${username}/${msg.id}`,
        contact_hint: extractContactHint(text),
      });
      console.log(`[orderhunter] realtime ${username}/${msg.id}`);
    } catch (e) {
      console.error("[orderhunter] realtime handler error", e);
    }
  }, new NewMessage({ incoming: true }));

  console.log(`[orderhunter] realtime on: ${[...allowed].join(", ")}`);
}

export async function runMonitor(): Promise<void> {
  // GramJS can throw outside our handler while resolving event filters —
  // keep the process alive so poll loop continues.
  process.on("uncaughtException", (e) => {
    console.error("[orderhunter] uncaughtException (kept alive)", e);
  });
  process.on("unhandledRejection", (e) => {
    console.error("[orderhunter] unhandledRejection (kept alive)", e);
  });

  await pollChannelsOnce();
  await startRealtimeListener();
  const interval = ENV.POLL_INTERVAL_SECONDS * 1000;
  setInterval(() => {
    pollChannelsOnce().catch((e) => console.error("[orderhunter] poll error", e));
  }, interval);
  console.log("[orderhunter] monitor running");
}
