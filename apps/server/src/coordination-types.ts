import type { Agent, AgentRun, Message } from "./types.js";

export type CoordinationRunStatus =
  | "planning"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type CoordinationTaskStatus =
  | "blocked"
  | "ready"
  | "running"
  | "completed"
  | "failed"
  | "skipped";

export type TaskAttemptStatus =
  | "dispatching"
  | "running"
  | "completed"
  | "failed"
  | "timed_out"
  | "cancelled"
  | "stale";

export type CoordinationEventType =
  | "coordination_created"
  | "plan_requested"
  | "plan_received"
  | "plan_validated"
  | "plan_rejected"
  | "plan_failed"
  | "plan_timed_out"
  | "task_ready"
  | "attempt_dispatch_rejected"
  | "attempt_started"
  | "attempt_completed"
  | "attempt_failed"
  | "attempt_timed_out"
  | "task_requeued"
  | "stale_result_rejected"
  | "task_completed"
  | "task_unblocked"
  | "task_failed"
  | "task_skipped"
  | "coordination_completed"
  | "coordination_failed"
  | "coordination_cancelled"
  | "demo_fault_injected";

export interface CoordinationPolicy {
  maxTasks: number;
  maxParallelism: number;
  maxAttempts: number;
  taskTimeoutMs: number;
  plannerTimeoutMs: number;
  schedulerTickMs: number;
  maxDependencyContextBytes: number;
}

export const DEFAULT_COORDINATION_POLICY: Readonly<CoordinationPolicy> = {
  maxTasks: 6,
  maxParallelism: 2,
  maxAttempts: 2,
  taskTimeoutMs: 120_000,
  plannerTimeoutMs: 120_000,
  schedulerTickMs: 1_000,
  maxDependencyContextBytes: 30_000,
};

export interface CoordinationRun {
  id: string;
  status: CoordinationRunStatus;
  prompt: string;
  plannerAgentId: string;
  workerAgentIds: string[];
  plannerAgentRunId: string | null;
  planVersion: 1;
  finalTaskKey: string | null;
  finalOutput: string | null;
  error: string | null;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
}

export interface CoordinationTask {
  id: string;
  coordinationRunId: string;
  key: string;
  title: string;
  instruction: string;
  expectedOutput: string;
  dependsOn: string[];
  requiredCapability: string;
  status: CoordinationTaskStatus;
  attemptCount: number;
  currentAttemptId: string | null;
  assignedAgentId: string | null;
  output: string | null;
  error: string | null;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
}

export interface TaskAttempt {
  id: string;
  coordinationRunId: string;
  taskId: string;
  taskKey: string;
  attemptNumber: number;
  agentId: string;
  agentName: string;
  agentRunId: string | null;
  status: TaskAttemptStatus;
  timeoutAt: string | null;
  output: string | null;
  error: string | null;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
}

export interface CoordinationEvent {
  id: string;
  sequence: number;
  coordinationRunId: string;
  type: CoordinationEventType;
  message: string;
  taskId?: string;
  taskKey?: string;
  attemptId?: string;
  agentId?: string;
  createdAt: string;
  details?: Record<string, string | number | boolean | null>;
}

export interface CreateCoordinationRunInput {
  prompt: string;
  plannerAgentId: string;
  workerAgentIds: string[];
}

export interface CreateCoordinationRunResponse {
  coordinationRun: CoordinationRun;
}

export interface ListCoordinationRunsResponse {
  coordinationRuns: CoordinationRun[];
}

export interface StopCoordinationRunResponse {
  coordinationRun: CoordinationRun;
}

export interface ApiErrorResponse {
  error: string;
  details?: unknown[];
}

export interface CoordinationRunSnapshot {
  coordinationRun: CoordinationRun;
  tasks: CoordinationTask[];
  attempts: TaskAttempt[];
  events: CoordinationEvent[];
  latestSequence: number;
}

export interface PlannerTaskDraft {
  key: string;
  title: string;
  instruction: string;
  dependsOn: string[];
  requiredCapability: string;
  expectedOutput: string;
}

export interface PlannerPlanDraft {
  version: 1;
  summary: string;
  tasks: PlannerTaskDraft[];
  finalTaskKey: string;
}

export type ValidatedPlan = PlannerPlanDraft;

export interface PlannerRequest {
  coordinationRunId: string;
  plannerAgentId: string;
  userPrompt: string;
  availableCapabilities: string[];
  maxTasks: number;
}

export interface PlannerSuccess {
  ok: true;
  plannerAgentRunId: string;
  plan: ValidatedPlan;
}

export interface PlannerFailure {
  ok: false;
  plannerAgentRunId: string | null;
  code: "plan_rejected" | "plan_failed" | "plan_timed_out";
  error: string;
}

export type PlannerResult = PlannerSuccess | PlannerFailure;

export interface PlannerService {
  createPlan(request: PlannerRequest): Promise<PlannerResult>;
}

export type AgentRunOrigin =
  | { type: "playground" }
  | {
      type: "coordination_planner";
      coordinationRunId: string;
    }
  | {
      type: "coordination_worker";
      coordinationRunId: string;
      taskId: string;
      attemptId: string;
    };

/**
 * Task 03 will make `origin` required on the baseline AgentRun itself. Keeping
 * it explicit here lets coordination modules compile against the final shape
 * before that migration lands.
 */
export type ManagedAgentRun = AgentRun & { origin: AgentRunOrigin };

export interface ManagedRunHandle {
  run: ManagedAgentRun;
  completion: Promise<ManagedAgentRun>;
}

export interface AgentExecutionGateway {
  start(
    agentId: string,
    prompt: string,
    origin: AgentRunOrigin,
  ): Promise<ManagedRunHandle>;

  cancel(runId: string): Promise<void>;
}

export type CoordinatedAgent = Agent & { capabilities: string[] };

export interface DatabaseV2 {
  version: 2;
  agents: CoordinatedAgent[];
  messages: Message[];
  runs: ManagedAgentRun[];
  coordinationRuns: CoordinationRun[];
  coordinationTasks: CoordinationTask[];
  taskAttempts: TaskAttempt[];
  coordinationEvents: CoordinationEvent[];
}

export interface CoordinationRepository {
  snapshot(): DatabaseV2;
  mutate<T>(mutation: (database: DatabaseV2) => T | Promise<T>): Promise<T>;
}

export interface CoordinationServicePort {
  initialize(): Promise<void>;
  createRun(input: CreateCoordinationRunInput): Promise<CoordinationRun>;
  listRuns(): CoordinationRun[];
  getSnapshot(id: string): CoordinationRunSnapshot;
  stopRun(id: string): Promise<CoordinationRun>;
}

export interface CoordinationServiceDependencies {
  repository: CoordinationRepository;
  plannerService: PlannerService;
  executionGateway: AgentExecutionGateway;
  policy: CoordinationPolicy;
}
