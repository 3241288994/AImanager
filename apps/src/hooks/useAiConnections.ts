"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { aiConnectionsClient } from "@/lib/api/ai-connections-client";

export function useAiConnections() {
  const client = useQueryClient();
  const overview = useQuery({ queryKey: ["ai-connections"], queryFn: aiConnectionsClient.list, retry: false });
  const invalidate = () => client.invalidateQueries({ queryKey: ["ai-connections"] });
  const save = useMutation({ mutationFn: aiConnectionsClient.save, onSuccess: invalidate });
  const remove = useMutation({ mutationFn: aiConnectionsClient.remove, onSuccess: invalidate });
  const probe = useMutation({ mutationFn: aiConnectionsClient.probe });
  return { overview, save, remove, probe };
}
