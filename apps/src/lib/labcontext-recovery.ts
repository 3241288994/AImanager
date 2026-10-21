import type { LabContextConnectionStatus } from "@/lib/api/labcontext-router-client";

export type LabContextRecoveryPlan = {
  title: string;
  summary: string;
  command: string;
  steps: string[];
};

export function buildLabContextRecoveryPlan(
  status?: LabContextConnectionStatus,
): LabContextRecoveryPlan | null {
  if (!status) {
    return {
      title: "本机 Router 未响应",
      summary: "先检查配置和依赖，再以当前配置重新启动完整链路。",
      command: "labcontext repair",
      steps: [
        "确认 1460 端口没有被其他程序占用。",
        "若启动器记录失效，restart 会拒绝误杀无关进程并给出 PID。",
      ],
    };
  }
  if (status.overall === "ready") return null;

  const components = status.launcher.components || [];
  const ssh = components.find((item) => item.id === "ssh-bridge");
  const server = status.providers.find((provider) => provider.id === "server");
  const failedComponent = components.find((item) => ["retrying", "exited"].includes(item.status));

  if (ssh && ["retrying", "exited"].includes(ssh.status)) {
    const attempts = ssh.restartAttempts ? `，已重试 ${ssh.restartAttempts} 次` : "";
    const exitCode = ssh.exitCode != null ? `退出码 ${ssh.exitCode}` : "进程已退出";
    return {
      title: "SSH 桥接没有建立成功",
      summary: `${exitCode}${attempts}。常见原因是 SSH 别名/密钥没有沿用、跳板机配置被绕过，或本地/服务器转发端口仍被旧会话占用。`,
      command: "labcontext repair",
      steps: [
        "doctor 会真实验证 SSH 登录与独立反向端口，并指出认证、超时或远端端口占用。",
        "修正 launcher.env 后，repair 会干净停止旧监督器并加载新配置。",
        "若 SSH 正常但服务器 Provider 仍不可用，再到服务器检查 1455 端口与 Provider 服务。",
      ],
    };
  }

  if (server?.status === "unavailable") {
    return {
      title: "服务器 Provider 未通过真实调用",
      summary: server.error || "SSH 进程可能仍在，但远端 1455 端口没有返回兼容的 LabContext Provider。",
      command: "labcontext status",
      steps: [
        "先确认 SSH 桥接显示正常，再检查服务器 Provider 是否监听 127.0.0.1:1455。",
        "服务器服务恢复后点击“重新检测”；无需重启本地 Router。",
      ],
    };
  }

  if (status.tunnel.enabled && status.tunnel.status !== "ready") {
    return {
      title: "OpenAI Tunnel 未就绪",
      summary: status.tunnel.detail || "Tunnel 健康检查没有通过。",
      command: "labcontext connections reconnect",
      steps: [
        "先确认 Tunnel profile 指向 http://127.0.0.1:1460/mcp。",
        "新版支持只重连当前 Tunnel，不重启 Provider、SSH 或 Router。",
        "若启动器较旧，请更新本机 labcontext 后在方便时重启一次。",
      ],
    };
  }

  return {
    title: failedComponent ? `${failedComponent.label}需要恢复` : "连接链路需要恢复",
    summary: "连接中心检测到组件状态与真实能力不一致。",
    command: "labcontext repair",
    steps: ["复制诊断可保留完整状态；repair 只会操作已验证的 LabContext 监督器。"],
  };
}
