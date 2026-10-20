import { createAccountWebCommands } from "./transport-web-commands/account";
import { createAiConnectionsWebCommands } from "./transport-web-commands/ai-connections";
import { createCodexProfileWebCommands } from "./transport-web-commands/codex-profile";
import { createLoginWebCommands } from "./transport-web-commands/login";
import { createLabContextWebCommands } from "./transport-web-commands/labcontext";
import { createMiscWebCommands } from "./transport-web-commands/misc";
import { createSessionCatalogWebCommands } from "./transport-web-commands/session-catalog";
import type { WebCommandDescriptor } from "./transport-web-commands/shared";

export type { InvokeParams, WebCommandDescriptor } from "./transport-web-commands/shared";

export function createWebCommandMap(): Record<string, WebCommandDescriptor> {
  return {
    ...createAiConnectionsWebCommands(),
    ...createMiscWebCommands(),
    ...createCodexProfileWebCommands(),
    ...createSessionCatalogWebCommands(),
    ...createAccountWebCommands(),
    ...createLoginWebCommands(),
    ...createLabContextWebCommands(),
  };
}
