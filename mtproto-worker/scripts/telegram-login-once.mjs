/**
 * Вход в личный Telegram → TELEGRAM_USER_SESSION
 *   npm run telegram:login
 *
 * Если "invalid new nonce hash" / WebSocket failed:
 *   1) скрипт сам пробует TCP, потом WSS
 *   2) задайте TELEGRAM_PROXY_URL=socks5://user:pass@host:port в .env
 *   3) проверьте системное время (NTP)
 */
import { config } from "dotenv";
import fs from "fs";
import path from "path";
import readline from "readline";
import { fileURLToPath } from "url";
import { TelegramClient } from "telegram";
import { StringSession } from "telegram/sessions/index.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
config({ path: path.join(repoRoot, ".env") });

const apiId = Number(process.env.TELEGRAM_API_ID);
const apiHash = String(process.env.TELEGRAM_API_HASH ?? "").trim();
const proxyUrl = String(process.env.TELEGRAM_PROXY_URL ?? "").trim();

function createPrompter() {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return {
    ask(question) {
      return new Promise((resolve) => {
        rl.question(question, (answer) => resolve(String(answer ?? "").trim()));
      });
    },
    close() {
      rl.close();
    },
  };
}

function normalizePhone(raw) {
  let s = String(raw ?? "").replace(/[\s\-()]/g, "");
  if (!s) return "";
  if (s.startsWith("00")) s = "+" + s.slice(2);
  if (!s.startsWith("+")) {
    if (s.startsWith("8") && s.length === 11) s = "+7" + s.slice(1);
    else if (s.startsWith("7") && s.length === 11) s = "+" + s;
    else s = "+" + s;
  }
  return s;
}

function normalizeCode(raw) {
  return String(raw ?? "").replace(/\D/g, "");
}

function parseProxy(raw) {
  if (!raw) return undefined;
  const u = new URL(raw);
  const out = {
    ip: u.hostname,
    port: u.port ? Number(u.port) : 1080,
    socksType: 5,
  };
  if (u.username) out.username = decodeURIComponent(u.username);
  if (u.password) out.password = decodeURIComponent(u.password);
  return out;
}

function isNonceOrWsError(err) {
  const msg = String(err?.message ?? err?.errorMessage ?? err ?? "");
  return /nonce hash|WebSocket|TIMEOUT|CONNECTION|AUTH_KEY/i.test(msg);
}

if (!apiId || !apiHash) {
  console.error("Задайте TELEGRAM_API_ID и TELEGRAM_API_HASH в .env");
  process.exit(1);
}

const proxy = parseProxy(proxyUrl);
if (proxy) {
  console.log(`Прокси из .env: socks5://${proxy.ip}:${proxy.port}`);
  console.log("(если прокси не запущен — скрипт сам перейдёт на прямое подключение)\n");
}

const prompter = createPrompter();

/** Prefer TCP; WSS often breaks with "invalid new nonce hash" in RU/Windows. */
const modes = [];
if (proxy) {
  modes.push({ label: "TCP+proxy", useWSS: false, proxy });
}
modes.push(
  { label: "TCP (без прокси)", useWSS: false, proxy: undefined },
  { label: "WSS (без прокси)", useWSS: true, proxy: undefined },
);

let client = null;
let lastError = null;

try {
  for (const mode of modes) {
    console.log(`Подключение (${mode.label})…`);
    client = new TelegramClient(new StringSession(""), apiId, apiHash, {
      connectionRetries: 5,
      useWSS: mode.useWSS,
      ...(mode.proxy ? { proxy: mode.proxy } : {}),
      timeout: 15,
    });
    client.setLogLevel("error");

    try {
      await client.start({
        phoneNumber: async () => {
          for (;;) {
            const phone = normalizePhone(await prompter.ask("Номер (+79...): "));
            if (/^\+\d{10,15}$/.test(phone)) return phone;
            console.error("  Пример: +79337518613");
          }
        },
        phoneCode: async () => {
          for (;;) {
            const code = normalizeCode(await prompter.ask("Код (5 цифр): "));
            if (/^\d{5}$/.test(code)) return code;
          }
        },
        password: async () => await prompter.ask("2FA (или Enter): "),
        onError: async (err) => {
          console.error(err?.errorMessage ?? err?.message ?? err);
          return false;
        },
      });
      lastError = null;
      break;
    } catch (e) {
      lastError = e;
      console.error(`  ${mode.label} не вышло:`, e?.message ?? e);
      try {
        await client.disconnect();
      } catch {
        /* ignore */
      }
      client = null;
      if (!isNonceOrWsError(e) && modes.indexOf(mode) < modes.length - 1) {
        // non-network auth error — still try next mode once
      }
    }
  }

  if (!client || lastError) {
    console.error(`
Не удалось войти.

Что попробовать:
1. Повторите npm run telegram:login (иногда с первого раза падает handshake)
2. В .env добавьте SOCKS5-прокси:
   TELEGRAM_PROXY_URL=socks5://127.0.0.1:1080
3. Проверьте, что системные часы синхронизированы
4. VPN/прокси без DPI к Telegram DC
`);
    throw lastError ?? new Error("login failed");
  }

  const session = client.session.save();
  await client.disconnect();
  prompter.close();

  const outFile = path.join(repoRoot, ".telegram-user-session.local.txt");
  fs.writeFileSync(outFile, session + "\n", { encoding: "utf8", mode: 0o600 });
  console.log(`\nTELEGRAM_USER_SESSION:\n${session}\n\nСохранено: ${outFile}\n`);
  console.log(
    "Важно: одну session-строку нельзя использовать в двух процессах (AUTH_KEY_DUPLICATED).\n" +
      "Нужны Railway + локально — запустите login ещё раз и получите ВТОРУЮ строку для второго места.\n",
  );
} catch (e) {
  prompter.close();
  console.error(e?.message ?? e);
  process.exit(1);
}
