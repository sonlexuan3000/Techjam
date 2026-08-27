import { describe, expect, it, vi } from "vitest";
import type {
  AgentExecutionGateway,
  AgentStartResult,
  ManagedAgentRun,
  PlannerRequest,
} from "./coordination-types.js";
import { PlannerService } from "./planner-service.js";

const validOutput = JSON.stringify({
  version: 1,
  summary: "Research and synthesize.",
  tasks: [
    {
      key: "research",
      title: "Research",
      instruction: "Research the available options.",
      dependsOn: [],
      requiredCapability: "research",
      expectedOutput: "Concise findings",
    },
    {
      key: "synthesis",
      title: "Synthesize",
      instruction: "Synthesize the research.",
      dependsOn: ["research"],
      requiredCapability: "synthesis",
      expectedOutput: "Final recommendation",
    },
  ],
  finalTaskKey: "synthesis",
});

function managedRun(
  overrides: Partial<ManagedAgentRun> = {},
): ManagedAgentRun {
  return {
    id: "planner-run-1",
    agentId: "planner-agent-1",
    status: "completed",
    prompt: "planner prompt",
    output: validOutput,
    error: null,
    usage: null,
    startedAt: "2026-08-27T00:00:00.000Z",
    completedAt: "2026-08-27T00:00:01.000Z",
    createdAt: "2026-08-27T00:00:00.000Z",
    origin: {
      type: "coordination_planner",
      coordinationRunId: "coordination-run-1",
    },
    ...overrides,
  };
}

function plannerRequest(overrides: Partial<PlannerRequest> = {}): PlannerRequest {
  return {
    coordinationRunId: "coordination-run-1",
    plannerAgentId: "planner-agent-1",
    userPrompt: "Compare two approaches and recommend one.",
    availableCapabilities: ["synthesis", "research", "research"],
    maxTasks: 3,
    timeoutMs: 1_000,
    registerAgentRun: async () => true,
    ...overrides,
  };
}

function fakeGateway(startResult: AgentStartResult) {
  const start = vi.fn(async (): Promise<AgentStartResult> => startResult);
  const cancel = vi.fn(async (): Promise<void> => undefined);
  const gateway: AgentExecutionGateway = { start, cancel };
  return { gateway, start, cancel };
}

describe("PlannerService", () => {
  it("starts, registers and validates a Planner AgentRun", async () => {
    const run = managedRun();
    const { gateway, start } = fakeGateway({
      ok: true,
      handle: { run: managedRun({ status: "queued", output: null }), completion: Promise.resolve(run) },
    });
    const registerAgentRun = vi.fn(async () => true);
    const service = new PlannerService(gateway);

    const result = await service.createPlan(plannerRequest({ registerAgentRun }));

    expect(result).toMatchObject({
      ok: true,
      plannerAgentRunId: "planner-run-1",
      plan: { finalTaskKey: "synthesis" },
    });
    expect(registerAgentRun).toHaveBeenCalledWith("planner-run-1");
    expect(start).toHaveBeenCalledWith(
      "planner-agent-1",
      expect.stringContaining('"maxTasks": 3'),
      { type: "coordination_planner", coordinationRunId: "coordination-run-1" },
    );
    const prompt = start.mock.calls[0]?.[1] ?? "";
    expect(prompt).toContain('"availableCapabilities": [\n    "research",\n    "synthesis"');
    expect(prompt).toContain("Return JSON only");
    expect(prompt).toContain("Compare two approaches and recommend one.");
  });

  it("awaits AgentRun registration before consuming an already completed result", async () => {
    let releaseRegistration!: (registered: boolean) => void;
    const registration = new Promise<boolean>((resolve) => {
      releaseRegistration = resolve;
    });
    const registerAgentRun = vi.fn(() => registration);
    const { gateway } = fakeGateway({
      ok: true,
      handle: {
        run: managedRun({ status: "queued", output: null }),
        completion: Promise.resolve(managedRun()),
      },
    });
    const resultPromise = new PlannerService(gateway).createPlan(
      plannerRequest({ registerAgentRun }),
    );

    await vi.waitFor(() => expect(registerAgentRun).toHaveBeenCalledWith("planner-run-1"));
    const stateBeforeRegistration = await Promise.race([
      resultPromise.then(() => "settled" as const),
      Promise.resolve("waiting-for-registration" as const),
    ]);
    expect(stateBeforeRegistration).toBe("waiting-for-registration");

    releaseRegistration(true);
    await expect(resultPromise).resolves.toMatchObject({ ok: true });
  });

  it.each(["busy", "not_configured"] as const)(
    "maps %s admission failure to plan_failed",
    async (code) => {
      const { gateway } = fakeGateway({ ok: false, code, error: "unsafe gateway detail" });
      const result = await new PlannerService(gateway).createPlan(plannerRequest());
      expect(result).toMatchObject({
        ok: false,
        plannerAgentRunId: null,
        code: "plan_failed",
      });
      expect(result.error).not.toContain("unsafe gateway detail");
    },
  );

  it("maps an unexpected Gateway exception to plan_failed", async () => {
    const gateway: AgentExecutionGateway = {
      start: async () => {
        throw new Error("secret runtime detail");
      },
      cancel: async () => undefined,
    };
    const result = await new PlannerService(gateway).createPlan(plannerRequest());
    expect(result).toEqual({
      ok: false,
      plannerAgentRunId: null,
      code: "plan_failed",
      error: "Planner execution gateway failed unexpectedly",
    });
  });

  it("rejects invalid Planner output without creating a fallback plan", async () => {
    const run = managedRun({ output: "not JSON secret-output" });
    const { gateway } = fakeGateway({
      ok: true,
      handle: { run: managedRun({ status: "queued", output: null }), completion: Promise.resolve(run) },
    });
    const result = await new PlannerService(gateway).createPlan(plannerRequest());
    expect(result).toEqual({
      ok: false,
      plannerAgentRunId: "planner-run-1",
      code: "plan_rejected",
      error: "Planner output is not valid JSON",
    });
  });

  it("maps terminal runtime failure to plan_failed without exposing runtime error", async () => {
    const failedRun = managedRun({
      status: "failed",
      output: null,
      error: "ARK_API_KEY=secret",
    });
    const { gateway } = fakeGateway({
      ok: true,
      handle: {
        run: managedRun({ status: "queued", output: null }),
        completion: Promise.resolve(failedRun),
      },
    });
    const result = await new PlannerService(gateway).createPlan(plannerRequest());
    expect(result).toMatchObject({ ok: false, code: "plan_failed" });
    expect(result.error).not.toContain("secret");
  });

  it("times out and best-effort cancels the admitted Planner Run", async () => {
    const completion = new Promise<ManagedAgentRun>(() => undefined);
    const { gateway, cancel } = fakeGateway({
      ok: true,
      handle: { run: managedRun({ status: "running", output: null }), completion },
    });
    const result = await new PlannerService(gateway).createPlan(
      plannerRequest({ timeoutMs: 5 }),
    );
    expect(result).toEqual({
      ok: false,
      plannerAgentRunId: "planner-run-1",
      code: "plan_timed_out",
      error: "Planner AgentRun timed out",
    });
    expect(cancel).toHaveBeenCalledWith("planner-run-1");
  });

  it("cancels and ignores output when parent registration loses the stop race", async () => {
    const completion = new Promise<ManagedAgentRun>(() => undefined);
    const { gateway, cancel } = fakeGateway({
      ok: true,
      handle: { run: managedRun({ status: "running", output: null }), completion },
    });
    const result = await new PlannerService(gateway).createPlan(
      plannerRequest({ registerAgentRun: async () => false }),
    );
    expect(result).toMatchObject({
      ok: false,
      plannerAgentRunId: "planner-run-1",
      code: "plan_failed",
    });
    expect(cancel).toHaveBeenCalledWith("planner-run-1");
  });

  it("cancels when registering the admitted Planner Run throws", async () => {
    const { gateway, cancel } = fakeGateway({
      ok: true,
      handle: {
        run: managedRun({ status: "running", output: null }),
        completion: new Promise<ManagedAgentRun>(() => undefined),
      },
    });
    const result = await new PlannerService(gateway).createPlan(
      plannerRequest({
        registerAgentRun: async () => {
          throw new Error("store failed");
        },
      }),
    );
    expect(result).toMatchObject({ ok: false, code: "plan_failed" });
    expect(cancel).toHaveBeenCalledWith("planner-run-1");
  });

  it("maps a rejected completion Promise to plan_failed", async () => {
    const { gateway, cancel } = fakeGateway({
      ok: true,
      handle: {
        run: managedRun({ status: "running", output: null }),
        completion: Promise.reject(new Error("unexpected completion failure")),
      },
    });
    const result = await new PlannerService(gateway).createPlan(plannerRequest());
    expect(result).toMatchObject({
      ok: false,
      plannerAgentRunId: "planner-run-1",
      code: "plan_failed",
    });
    expect(cancel).toHaveBeenCalledWith("planner-run-1");
  });
});
