import { buildPlannerPrompt } from "./coordination-prompts.js";
import {
  PlannerOutputValidationError,
  validatePlannerOutput,
} from "./coordination-graph.js";
import type {
  AgentExecutionGateway,
  AgentStartFailureCode,
  ManagedAgentRun,
  PlannerFailure,
  PlannerRequest,
  PlannerResult,
  PlannerService as PlannerServiceContract,
} from "./coordination-types.js";

type DeadlineOutcome<T> =
  | { type: "resolved"; value: T }
  | { type: "rejected" }
  | { type: "timed_out" };

const admissionFailureMessages: Record<AgentStartFailureCode, string> = {
  busy: "Planner Agent is already running",
  stopped: "Planner Agent is stopped",
  not_found: "Planner Agent was not found",
  not_configured: "Planner runtime is not configured",
  internal: "Planner Agent could not be started",
};

export class PlannerService implements PlannerServiceContract {
  constructor(private readonly executionGateway: AgentExecutionGateway) {}

  async createPlan(request: PlannerRequest): Promise<PlannerResult> {
    if (!Number.isSafeInteger(request.maxTasks) || request.maxTasks < 1) {
      return planFailure(null, "plan_failed", "Planner maxTasks policy is invalid");
    }
    if (!Number.isFinite(request.timeoutMs) || request.timeoutMs < 1) {
      return planFailure(null, "plan_failed", "Planner timeout policy is invalid");
    }

    let startResult;
    try {
      startResult = await this.executionGateway.start(
        request.plannerAgentId,
        buildPlannerPrompt(request),
        {
          type: "coordination_planner",
          coordinationRunId: request.coordinationRunId,
        },
      );
    } catch {
      return planFailure(
        null,
        "plan_failed",
        "Planner execution gateway failed unexpectedly",
      );
    }

    if (!startResult.ok) {
      return planFailure(null, "plan_failed", admissionFailureMessages[startResult.code]);
    }

    const handle = startResult.handle;
    const plannerAgentRunId = handle.run.id;
    ignoreUnexpectedCompletionFailure(handle.completion);
    const deadlineAt = Date.now() + request.timeoutMs;
    const registration = await waitUntilDeadline(
      Promise.resolve().then(() => request.registerAgentRun(plannerAgentRunId)),
      deadlineAt,
    );
    if (registration.type === "timed_out") {
      this.cancelBestEffort(plannerAgentRunId);
      return planFailure(plannerAgentRunId, "plan_timed_out", "Planner AgentRun timed out");
    }
    if (registration.type === "rejected") {
      this.cancelBestEffort(plannerAgentRunId);
      return planFailure(
        plannerAgentRunId,
        "plan_failed",
        "Planner AgentRun registration failed",
      );
    }

    if (!registration.value) {
      this.cancelBestEffort(plannerAgentRunId);
      return planFailure(
        plannerAgentRunId,
        "plan_failed",
        "Coordination run is no longer accepting Planner results",
      );
    }

    const outcome = await waitUntilDeadline(handle.completion, deadlineAt);
    if (outcome.type === "timed_out") {
      this.cancelBestEffort(plannerAgentRunId);
      return planFailure(plannerAgentRunId, "plan_timed_out", "Planner AgentRun timed out");
    }
    if (outcome.type === "rejected") {
      this.cancelBestEffort(plannerAgentRunId);
      return planFailure(
        plannerAgentRunId,
        "plan_failed",
        "Planner AgentRun completion failed unexpectedly",
      );
    }

    const completedRun = outcome.value;
    if (completedRun.id !== plannerAgentRunId) {
      this.cancelBestEffort(plannerAgentRunId);
      return planFailure(
        plannerAgentRunId,
        "plan_failed",
        "Planner AgentRun completion correlation failed",
      );
    }
    if (completedRun.status !== "completed") {
      if (completedRun.status === "queued" || completedRun.status === "running") {
        this.cancelBestEffort(plannerAgentRunId);
      }
      return planFailure(
        plannerAgentRunId,
        "plan_failed",
        completedRun.status === "cancelled"
          ? "Planner AgentRun was cancelled"
          : "Planner AgentRun failed",
      );
    }
    if (completedRun.output === null || completedRun.output.trim().length === 0) {
      return planFailure(
        plannerAgentRunId,
        "plan_failed",
        "Planner AgentRun completed without output",
      );
    }

    try {
      const plan = validatePlannerOutput(completedRun.output, {
        availableCapabilities: request.availableCapabilities,
        maxTasks: request.maxTasks,
      });
      return { ok: true, plannerAgentRunId, plan };
    } catch (error) {
      if (error instanceof PlannerOutputValidationError) {
        return planFailure(plannerAgentRunId, "plan_rejected", error.message);
      }
      return planFailure(
        plannerAgentRunId,
        "plan_failed",
        "Planner output validation failed unexpectedly",
      );
    }
  }

  private cancelBestEffort(runId: string): void {
    try {
      void this.executionGateway.cancel(runId).catch(() => undefined);
    } catch {
      // Cancellation is best-effort and must not replace the original outcome.
    }
  }
}

function ignoreUnexpectedCompletionFailure(completion: Promise<ManagedAgentRun>): void {
  void completion.catch(() => undefined);
}

function planFailure(
  plannerAgentRunId: string | null,
  code: PlannerFailure["code"],
  error: string,
): PlannerFailure {
  return { ok: false, plannerAgentRunId, code, error };
}

async function waitUntilDeadline<T>(
  promise: Promise<T>,
  deadlineAt: number,
): Promise<DeadlineOutcome<T>> {
  let timeout: NodeJS.Timeout | undefined;
  const timeoutResult = new Promise<DeadlineOutcome<T>>((resolve) => {
    timeout = setTimeout(
      () => resolve({ type: "timed_out" }),
      Math.max(0, deadlineAt - Date.now()),
    );
  });
  const settledResult = promise.then<DeadlineOutcome<T>, DeadlineOutcome<T>>(
    (value) => ({ type: "resolved", value }),
    () => ({ type: "rejected" }),
  );

  try {
    return await Promise.race([settledResult, timeoutResult]);
  } finally {
    if (timeout) clearTimeout(timeout);
  }
}
