import { z } from "zod";
import type { ValidatedPlan } from "./coordination-types.js";

const taskKeySchema = z.string().regex(/^[a-z0-9][a-z0-9-]{0,63}$/);

const plannerTaskSchema = z
  .object({
    key: taskKeySchema,
    title: z.string().min(1).max(120),
    instruction: z.string().min(1).max(4_000),
    dependsOn: z.array(taskKeySchema),
    requiredCapability: z.string(),
    expectedOutput: z.string().min(1).max(500),
  })
  .strict();

const plannerPlanSchema = z
  .object({
    version: z.literal(1),
    summary: z.string(),
    tasks: z.array(plannerTaskSchema).min(1),
    finalTaskKey: taskKeySchema,
  })
  .strict();

export interface PlannerValidationOptions {
  availableCapabilities: string[];
  maxTasks: number;
}

export class PlannerOutputValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PlannerOutputValidationError";
  }
}

export function stripOuterJsonFence(output: string): string {
  const trimmed = output.trim();
  const fenced = /^```(?:json)?[\t ]*\r?\n([\s\S]*?)\r?\n```$/i.exec(trimmed);
  return fenced?.[1] ?? trimmed;
}

export function validatePlannerOutput(
  output: string,
  options: PlannerValidationOptions,
): ValidatedPlan {
  if (!Number.isSafeInteger(options.maxTasks) || options.maxTasks < 1) {
    throw new PlannerOutputValidationError("Planner maxTasks policy must be a positive integer");
  }

  let parsedJson: unknown;
  try {
    parsedJson = JSON.parse(stripOuterJsonFence(output)) as unknown;
  } catch {
    throw new PlannerOutputValidationError("Planner output is not valid JSON");
  }

  const parsed = plannerPlanSchema.safeParse(parsedJson);
  if (!parsed.success) {
    const locations = parsed.error.issues.slice(0, 8).map((issue) => {
      const path = issue.path.length > 0 ? issue.path.join(".") : "root";
      return path + " (" + issue.code + ")";
    });
    const remainingIssueCount = parsed.error.issues.length - locations.length;
    throw new PlannerOutputValidationError(
      "Planner output failed schema validation at " +
        locations.join(", ") +
        (remainingIssueCount > 0 ? " and " + remainingIssueCount + " more locations" : ""),
    );
  }

  const plan = parsed.data;
  if (plan.tasks.length > options.maxTasks) {
    throw new PlannerOutputValidationError(
      "Planner output exceeds the configured task limit of " + options.maxTasks,
    );
  }

  const tasksByKey = new Map<string, (typeof plan.tasks)[number]>();
  for (const task of plan.tasks) {
    if (tasksByKey.has(task.key)) {
      throw new PlannerOutputValidationError("Planner output contains duplicate task keys");
    }
    tasksByKey.set(task.key, task);
  }

  const allowedCapabilities = new Set(options.availableCapabilities);
  for (const task of plan.tasks) {
    if (!allowedCapabilities.has(task.requiredCapability)) {
      throw new PlannerOutputValidationError(
        "Planner task " + task.key + " requires an unavailable capability",
      );
    }
    for (const dependencyKey of task.dependsOn) {
      if (dependencyKey === task.key) {
        throw new PlannerOutputValidationError(
          "Planner task " + task.key + " cannot depend on itself",
        );
      }
      if (!tasksByKey.has(dependencyKey)) {
        throw new PlannerOutputValidationError(
          "Planner task " + task.key + " references a missing dependency",
        );
      }
    }
  }

  if (!tasksByKey.has(plan.finalTaskKey)) {
    throw new PlannerOutputValidationError("Planner finalTaskKey does not reference a task");
  }

  assertAcyclic(tasksByKey);
  assertEveryTaskLeadsToFinalTask(plan.finalTaskKey, tasksByKey);

  return plan;
}

function assertAcyclic(
  tasksByKey: ReadonlyMap<string, { key: string; dependsOn: string[] }>,
): void {
  const state = new Map<string, "visiting" | "visited">();

  const visit = (taskKey: string): void => {
    const currentState = state.get(taskKey);
    if (currentState === "visiting") {
      throw new PlannerOutputValidationError("Planner task graph contains a cycle");
    }
    if (currentState === "visited") return;

    state.set(taskKey, "visiting");
    const task = tasksByKey.get(taskKey);
    if (!task) return;
    for (const dependencyKey of [...task.dependsOn].sort()) {
      visit(dependencyKey);
    }
    state.set(taskKey, "visited");
  };

  for (const taskKey of [...tasksByKey.keys()].sort()) {
    visit(taskKey);
  }
}

function assertEveryTaskLeadsToFinalTask(
  finalTaskKey: string,
  tasksByKey: ReadonlyMap<string, { key: string; dependsOn: string[] }>,
): void {
  const ancestorsOfFinalTask = new Set<string>();
  const visitDependencies = (taskKey: string): void => {
    if (ancestorsOfFinalTask.has(taskKey)) return;
    ancestorsOfFinalTask.add(taskKey);
    const task = tasksByKey.get(taskKey);
    if (!task) return;
    for (const dependencyKey of task.dependsOn) {
      visitDependencies(dependencyKey);
    }
  };

  visitDependencies(finalTaskKey);
  if (ancestorsOfFinalTask.size !== tasksByKey.size) {
    throw new PlannerOutputValidationError(
      "Every Planner task must be on a path leading to finalTaskKey",
    );
  }
}
