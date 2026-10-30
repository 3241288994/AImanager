import type { Account } from "@/types/account";

/** Current account access outranks historical billing-product labels. An
 * inactive old Pro entitlement is not evidence that current Free is ambiguous. */
export function codexPlanDisplay(account: Pick<Account,"planType"|"hasSubscription"|"subscriptionPlan"|"subscriptionExpiresAt"|"planMonthlyUsd"|"planPriceSource">, now=Date.now()/1000) {
  const current=String(account.planType||"").trim().toLowerCase();
  const billing=String(account.subscriptionPlan||"").trim().toLowerCase();
  const known=["free","go","plus","pro","team","business","enterprise","edu"];
  const activeBilling=account.hasSubscription===true && (!account.subscriptionExpiresAt || account.subscriptionExpiresAt>now);
  const plan=known.includes(current) ? current : activeBilling && known.includes(billing) ? billing : null;
  const amount=plan==="pro" && activeBilling && account.planPriceSource==="user_confirmed" && [100,200,500].includes(account.planMonthlyUsd??0) ? account.planMonthlyUsd : null;
  return {
    label:amount ? `Pro ${amount}$` : plan ? plan.toUpperCase() : "暂无套餐数据",
    priceNote:amount ? "本期订阅档位 · 用户确认；不是实际账单金额" : null,
    free:plan==="free",
    paid:Boolean(plan && plan!=="free"),
    description:plan==="free" ? "免费版 · 无付费权益" : plan ? "当前套餐权益" : "等待官方套餐数据",
  };
}
