/**
 * Вход в личный Telegram → TELEGRAM_USER_SESSION
 *   npm run telegram:login
 *
 * По умолчанию — QR (без SMS). Код по номеру чаще приходит В ПРИЛОЖЕНИЕ Telegram, не SMS.
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

function tokenToTgUrl(token) {
  const b64 = Buffer.from(token).toString("base64url");
  return `tg://login?token=${b64}`;
}

/** Opens in browser → Telegram Web (must already be logged in there). */
function tokenToWebUrl(token) {
  const tg = tokenToTgUrl(token);
  return `https://web.telegram.org/k/#?tgaddr=${encodeURIComponent(tg)}`;
}

async function printLoginLink(token) {
  const webUrl = tokenToWebUrl(token);
  const tgUrl = tokenToTgUrl(token);

  console.log("\n========================================");
  console.log("1) Откройте Telegram Web и войдите в аккаунт (если ещё нет):");
  console.log("   https://web.telegram.org/k/");
  console.log("2) Затем откройте ссылку подтверждения:");
  console.log("========================================\n");
  console.log(webUrl);
  console.log("\n========================================\n");

  try {
    const { exec } = await import("child_process");
    const cmd =
      process.platform === "win32"
        ? `start "" "${webUrl}"`
        : process.platform === "darwin"
          ? `open "${webUrl}"`
          : `xdg-open "${webUrl}"`;
    exec(cmd);
  } catch {
    /* ignore */
  }

  // fallback for Desktop if Web не сработал
  console.log("(запасной вариант для Telegram Desktop):");
  console.log(tgUrl + "\n");
}

function buildClient(mode) {
  const c = new TelegramClient(new StringSession(""), apiId, apiHash, {
    connectionRetries: 5,
    useWSS: mode.useWSS,
    ...(mode.proxy ? { proxy: mode.proxy } : {}),
    timeout: 20,
  });
  c.setLogLevel("error");
  return c;
}

async function connectWithFallback(modes) {
  let lastError = null;
  for (const mode of modes) {
    console.log(`Подключение (${mode.label})…`);
    const client = buildClient(mode);
    try {
      await client.connect();
      console.log(`OK: ${mode.label}`);
      return client;
    } catch (e) {
      lastError = e;
      console.error(`  ${mode.label}:`, e?.message ?? e);
      try {
        await client.disconnect();
      } catch {
        /* ignore */
      }
    }
  }
  throw lastError ?? new Error("connect failed");
}

async function loginQr(client, prompter) {
  console.log("\n=== Вход через Telegram Web (без SMS) ===");
  console.log("Нужен уже открытый аккаунт в https://web.telegram.org/k/\n");
  await client.signInUserWithQrCode(
    { apiId, apiHash },
    {
      qrCode: async ({ token }) => {
        await printLoginLink(token);
        console.log("Жду подтверждение в Web… (ссылка обновляется ~раз в 30с)");
      },
      password: async (hint) =>
        await prompter.ask(`2FA пароль${hint ? ` (подсказка: ${hint})` : ""}: `),
      onError: async (err) => {
        console.error(err?.message ?? err);
        return true;
      },
    },
  );
}

async function loginPhone(client, prompter) {
  console.log("\n=== Вход по номеру ===");
  console.log(
    "Важно: код чаще приходит В ПРИЛОЖЕНИЕ Telegram (чат «Telegram»), а не SMS.\n" +
      "Откройте Telegram на телефоне и проверьте уведомления.\n",
  );
  await client.start({
    phoneNumber: async () => {
      for (;;) {
        const phone = normalizePhone(await prompter.ask("Номер (+79...): "));
        if (/^\+\d{10,15}$/.test(phone)) return phone;
        console.error("  Пример: +79337518613");
      }
    },
    phoneCode: async (isCodeViaApp) => {
      const via = isCodeViaApp
        ? "в приложении Telegram"
        : "SMS или в приложении Telegram";
      for (;;) {
        const code = normalizeCode(
          await prompter.ask(`Код (${via}, обычно 5 цифр): `),
        );
        if (/^\d{4,6}$/.test(code)) return code;
      }
    },
    password: async (hint) =>
      await prompter.ask(`2FA пароль${hint ? ` (подсказка: ${hint})` : ""} (или Enter): `),
    onError: async (err) => {
      console.error(err?.errorMessage ?? err?.message ?? err);
      return false;
    },
  });
}

function saveSession(client) {
  const session = client.session.save();
  const outFile = path.join(repoRoot, ".telegram-user-session.local.txt");
  fs.writeFileSync(outFile, session + "\n", { encoding: "utf8", mode: 0o600 });
  console.log(`\nTELEGRAM_USER_SESSION:\n${session}\n\nСохранено: ${outFile}\n`);
  console.log(
    "Одну session-строку нельзя использовать в двух процессах.\n" +
      "Нужны два места — login ещё раз → вторая строка.\n",
  );
}

if (!apiId || !apiHash) {
  console.error("Задайте TELEGRAM_API_ID и TELEGRAM_API_HASH в .env");
  process.exit(1);
}

const proxy = parseProxy(proxyUrl);
if (proxy) {
  console.log(`Прокси из .env: socks5://${proxy.ip}:${proxy.port}`);
  console.log("(если не запущен — будет прямое подключение)\n");
}

const modes = [];
if (proxy) modes.push({ label: "TCP+proxy", useWSS: false, proxy });
modes.push(
  { label: "TCP", useWSS: false, proxy: undefined },
  { label: "WSS", useWSS: true, proxy: undefined },
);

const prompter = createPrompter();

try {
  const method =
    (await prompter.ask(
      "Вход: [1] ссылка web.telegram.org (без SMS)  [2] номер телефона\nВыбор (1/2): ",
    )) || "1";

  const client = await connectWithFallback(modes);

  if (method.trim() === "2") {
    await loginPhone(client, prompter);
  } else {
    await loginQr(client, prompter);
  }

  saveSession(client);
  await client.disconnect();
  prompter.close();
} catch (e) {
  prompter.close();
  console.error("\nНе удалось войти:", e?.message ?? e);
  console.error(`
Подсказки:
• SMS часто НЕ приходит — смотрите код в приложении Telegram или выберите вход по QR (1)
• Уберите мёртвый TELEGRAM_PROXY_URL из .env, если SOCKS не запущен
• Проверьте системное время Windows
`);
  process.exit(1);
}
