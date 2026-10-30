"use client";

import type { Account, AccountListResult, AccountUsage, LoginStartResult } from "@/types";
import { calcAvailability, getUsageDisplayBuckets, isLowQuotaUsage, toNullableNumber } from "@/lib/utils/usage";

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function string(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function integer(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.trunc(parsed) : fallback;
}

function strings(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(string).filter(Boolean);
  return typeof value === "string" ? value.split(",").map((item) => item.trim()).filter(Boolean) : [];
}

export function normalizeUsageSnapshot(value: unknown): AccountUsage | null {
  const source = object(value);
  const accountId = string(source.accountId ?? source.account_id);
  if (!accountId) return null;
  return {
    accountId,
    availabilityStatus: string(source.availabilityStatus ?? source.availability_status),
    usedPercent: toNullableNumber(source.usedPercent ?? source.used_percent),
    windowMinutes: toNullableNumber(source.windowMinutes ?? source.window_minutes),
    resetsAt: toNullableNumber(source.resetsAt ?? source.resets_at),
    secondaryUsedPercent: toNullableNumber(source.secondaryUsedPercent ?? source.secondary_used_percent),
    secondaryWindowMinutes: toNullableNumber(source.secondaryWindowMinutes ?? source.secondary_window_minutes),
    secondaryResetsAt: toNullableNumber(source.secondaryResetsAt ?? source.secondary_resets_at),
    creditsJson: string(source.creditsJson ?? source.credits_json) || null,
    capturedAt: toNullableNumber(source.capturedAt ?? source.captured_at),
  };
}

export function normalizeUsageList(value: unknown): AccountUsage[] {
  const source = object(value);
  return array(source.items ?? value).map(normalizeUsageSnapshot).filter((item): item is AccountUsage => item !== null);
}

function normalizeAccount(value: unknown, usage?: AccountUsage | null): Account | null {
  const source = object(value);
  const id = string(source.id);
  if (!id) return null;
  const name = string(source.label || source.name) || id;
  const status = string(source.status);
  const statusReason = string(source.statusReason ?? source.status_reason);
  const hasToken = typeof (source.hasToken ?? source.has_token) === "boolean" ? Boolean(source.hasToken ?? source.has_token) : true;
  const availability = calcAvailability(usage, { status, statusReason, hasToken });
  const buckets = getUsageDisplayBuckets(usage);
  const groupName = string(source.groupName ?? source.group_name);
  return {
    id,
    name,
    label: name,
    group: groupName,
    groupName,
    priority: integer(source.sort ?? source.priority, 0),
    sort: integer(source.sort ?? source.priority, 0),
    preferred: source.preferred === true,
    status,
    statusReason,
    hasToken,
    planType: string(source.planType ?? source.plan_type) || null,
    planTypeRaw: string(source.planTypeRaw ?? source.plan_type_raw) || null,
    hasSubscription: typeof (source.hasSubscription ?? source.has_subscription) === "boolean" ? Boolean(source.hasSubscription ?? source.has_subscription) : null,
    subscriptionPlan: string(source.subscriptionPlan ?? source.subscription_plan) || null,
    planMonthlyUsd: toNullableNumber(source.planMonthlyUsd ?? source.plan_monthly_usd),
    planPriceSource: string(source.planPriceSource ?? source.plan_price_source) || null,
    subscriptionExpiresAt: toNullableNumber(source.subscriptionExpiresAt ?? source.subscription_expires_at),
    subscriptionRenewsAt: toNullableNumber(source.subscriptionRenewsAt ?? source.subscription_renews_at),
    note: string(source.note) || null,
    tags: strings(source.tags),
    modelSlugs: strings(source.modelSlugs ?? source.model_slugs),
    quotaCapacityPrimaryWindowTokens: toNullableNumber(source.quotaCapacityPrimaryWindowTokens ?? source.quota_capacity_primary_window_tokens),
    quotaCapacitySecondaryWindowTokens: toNullableNumber(source.quotaCapacitySecondaryWindowTokens ?? source.quota_capacity_secondary_window_tokens),
    isAvailable: availability.level === "ok",
    isLowQuota: isLowQuotaUsage(usage),
    lastRefreshAt: usage?.capturedAt ?? null,
    availabilityText: availability.text,
    availabilityLevel: availability.level,
    primaryRemainPercent: buckets.primaryRemainPercent,
    secondaryRemainPercent: buckets.secondaryRemainPercent,
    usage: usage ?? null,
  };
}

export function normalizeAccountList(value: unknown, usages: AccountUsage[] = []): AccountListResult {
  const source = object(value);
  const usageMap = new Map(usages.map((usage) => [usage.accountId, usage]));
  const items = array(source.items ?? value)
    .map((item) => normalizeAccount(item, usageMap.get(string(object(item).id))))
    .filter((item): item is Account => item !== null);
  return {
    items,
    total: integer(source.total, items.length),
    page: integer(source.page, 1),
    pageSize: integer(source.pageSize, items.length || 20),
  };
}

export function attachUsagesToAccounts(accounts: Account[], usages: AccountUsage[]): Account[] {
  const usageMap = new Map(usages.map((usage) => [usage.accountId, usage]));
  return accounts.map((account) => normalizeAccount(account, usageMap.get(account.id)) || account);
}

export function normalizeLoginStartResult(value: unknown): LoginStartResult {
  const source = object(value);
  const verificationUrl = string(source.verificationUrl ?? source.verification_url);
  return {
    type: string(source.type ?? source.loginType ?? source.login_type),
    authUrl: string(source.authUrl ?? source.auth_url ?? verificationUrl) || null,
    loginId: string(source.loginId ?? source.login_id),
    verificationUrl: verificationUrl || null,
    userCode: string(source.userCode ?? source.user_code) || null,
  };
}
