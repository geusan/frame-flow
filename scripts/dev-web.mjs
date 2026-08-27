import net from "node:net";
import { spawn } from "node:child_process";

const DEFAULT_PORT = 3000;
const MAX_PORT_ATTEMPTS = 100;

function parsePort(value) {
  const port = Number(value ?? DEFAULT_PORT);

  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`Invalid WEB_PORT/PORT value: ${value}`);
  }

  return port;
}

function isPortAvailable(port) {
  return new Promise((resolve) => {
    const server = net.createServer();

    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen({ host: "0.0.0.0", port, exclusive: true });
  });
}

async function findAvailablePort(preferredPort) {
  for (let offset = 0; offset < MAX_PORT_ATTEMPTS; offset += 1) {
    const port = preferredPort + offset;

    if (port > 65535) break;
    if (await isPortAvailable(port)) return port;
  }

  throw new Error(
    `No available port found between ${preferredPort} and ${Math.min(65535, preferredPort + MAX_PORT_ATTEMPTS - 1)}`,
  );
}

const preferredPort = parsePort(process.env.WEB_PORT ?? process.env.PORT);
const port = await findAvailablePort(preferredPort);

if (port !== preferredPort) {
  console.log(`[dev-web] Port ${preferredPort} is busy; using http://localhost:${port}`);
}

const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const child = spawn(
  npmCommand,
  ["run", "dev", "--workspace", "apps/web", "--", "--port", String(port)],
  {
    env: { ...process.env, PORT: String(port) },
    stdio: "inherit",
  },
);

child.once("error", (error) => {
  console.error(`[dev-web] Failed to start Next.js: ${error.message}`);
  process.exitCode = 1;
});

child.once("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }

  process.exitCode = code ?? 1;
});
