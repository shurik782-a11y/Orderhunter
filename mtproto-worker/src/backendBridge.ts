import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { parse as parseYaml } from "yaml";

import { ENV } from "./env.js";

export type ChannelConfig = {
  username: string;
  title: string;
  enabled: boolean;
};

export function loadChannels(): ChannelConfig[] {
  const path = resolve(process.cwd(), ENV.CHANNELS_CONFIG);
  const raw = parseYaml(readFileSync(path, "utf8")) as {
    channels?: ChannelConfig[];
  };
  return (raw.channels || []).filter((c) => c.enabled && c.username);
}

export async function postToBackend(payload: {
  message_id: number;
  channel: string;
  text: string;
  url: string;
  contact_hint: string;
}): Promise<void> {
  const res = await fetch(`${ENV.ORDERHUNTER_BACKEND_URL}/internal/telegram/ingest`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Internal-Secret": ENV.INTERNAL_API_SECRET,
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`backend ingest ${res.status}: ${body}`);
  }
}

export function extractContactHint(text: string): string {
  const tg = text.match(/@[\w\d_]{4,}/);
  if (tg) return tg[0];
  const link = text.match(/t\.me\/[\w\d_]+/i);
  if (link) return `@${link[0].split("/").pop()}`;
  return "";
}
