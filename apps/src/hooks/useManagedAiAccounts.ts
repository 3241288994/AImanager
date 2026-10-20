"use client";

import { useEffect, useState } from "react";
import { create } from "zustand";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { aiAccountsClient, FINAL_AUTH_PHASES, type AiAuthSession } from "@/lib/api/ai-accounts-client";
import { getAppErrorMessage } from "@/lib/api/transport";

const SESSION_KEY = "aimanager.cli-auth-session";
const useSessionStore = create<{ id: string | null; setId: (id: string | null) => void }>(set => ({
  id: null,
  setId: id => {
    if (id) sessionStorage.setItem(SESSION_KEY, id);
    else sessionStorage.removeItem(SESSION_KEY);
    set({ id });
  },
}));

export function useManagedAiAccounts() {
  const client = useQueryClient();
  const accounts = useQuery({
    queryKey: ["ai-accounts"], queryFn: () => aiAccountsClient.sync(), retry: false,
    staleTime: 5_000, refetchInterval: 15_000, refetchIntervalInBackground: false,
    refetchOnWindowFocus: "always",
  });
  async function synchronize() {
    const data = await aiAccountsClient.sync(true);
    client.setQueryData(["ai-accounts"], data);
  }
  return { accounts, synchronize };
}

export function useManagedCliSession() {
  const client = useQueryClient();
  const { id, setId } = useSessionStore();
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const saved = sessionStorage.getItem(SESSION_KEY);
    if (saved && /^[a-f0-9]{32}$/.test(saved)) setId(saved);
  }, [setId]);
  const session = useQuery({
    queryKey: ["ai-auth-session", id], queryFn: () => aiAccountsClient.session(id!),
    enabled: Boolean(id), retry: false,
    refetchInterval: query => query.state.data && FINAL_AUTH_PHASES.has(query.state.data.phase) ? false : 1200,
  });
  useEffect(() => {
    if (session.data && FINAL_AUTH_PHASES.has(session.data.phase)) {
      void client.invalidateQueries({ queryKey: ["ai-accounts"] });
    }
  }, [session.data?.phase, client]);
  async function run(operation: () => Promise<unknown>) {
    setBusy(true);
    try { await operation(); await client.invalidateQueries({ queryKey: ["ai-accounts"] }); }
    catch (error) { toast.error(getAppErrorMessage(error)); }
    finally { setBusy(false); }
  }
  function start(value: AiAuthSession) {
    client.setQueryData(["ai-auth-session", value.id], value);
    setId(value.id);
  }
  return { id, close: () => setId(null), session, busy, run, start, live: Boolean(session.data && !FINAL_AUTH_PHASES.has(session.data.phase)) };
}
